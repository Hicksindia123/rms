"""E-Commerce settlement after the E-Commerce Executive (DEC-76; user spec 2026-11-26).

Enforced here AND by the DB (migration 20261126000100, `rms_private.ecommerce_*_guard`):

* unboxing  The unboxing / verifier user (ecommerce_unboxing.create) takes a batch of
            PENDING_UNBOXING returns of ONE platform and splits each into To Store / To Repair /
            Wastage (sum = received qty; a "Different Product" is all wastage, nothing stocked).
            The batch becomes one E-Commerce Action Sheet (series ECOM_ACTION_SHEET) with every
            order id, Qty Received and Qty Issue CN (= the executive's qty for REFUND, 0 for a free
            replacement). Stock (rms_move_stock, same transaction, rule f): good → receipt location
            + a pending store receipt; repair → the chosen department location + a repair record;
            wastage → wastage location. A sheet without CN qty completes at once.
* repair    The unboxing user records the pieces back from the department: ok → a pending store
            receipt (stock stays at the department until the store acknowledges), scrap → wastage.
* store     A user of the product's Intermediate Store acknowledges the receipt → stock moves into
            the store location.
* accounts  E-Commerce Accounts (ecommerce_accounts.edit) completes a sheet with one credit note
            (number, date, value; the offline Accounts data, DEC-71) when its Qty Issue CN > 0.
* close     A return is CLOSED as soon as it is settled (sheet completed, every good / repaired
            piece acknowledged, repair back).

DEC-51: no ownership lock between steps. Commands are idempotent on `Idempotency-Key` (G-16).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

import structlog
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.db import UnitOfWork
from app.core.errors import (
    Conflict,
    NotFound,
    PermissionDenied,
    ServiceUnavailable,
    ValidationFailed,
)
from app.core.idempotency import IdempotencyKey, IdempotentResult, run_idempotent
from app.core.security import CurrentUser
from app.modules.ecommerce_settlement import repository as repo
from app.modules.ecommerce_settlement.schemas import (
    AcknowledgeIn,
    ActionSheetLineOut,
    ActionSheetListOut,
    ActionSheetOut,
    ActionSheetRowOut,
    CompleteSheetIn,
    LocationOut,
    RepairReturnIn,
    RepairRowOut,
    ReturnReceiptOut,
    ReturnRepairOut,
    ReturnSettlementOut,
    SOptionOut,
    StoreReceiptRowOut,
    StoreReceiptsOut,
    UnboxBatchIn,
    UnboxingQueueOut,
    UnboxingRowOut,
    UnboxLineIn,
)
from app.modules.inventory import ledger_service

log = structlog.get_logger(__name__)

SET_PLATFORM = "ECOM_PLATFORM"
SET_BUCKET = "ECOM_UNBOX_BUCKET"
SET_SHEET_STATUS = "ECOM_ACTION_SHEET_STATUS"
SET_RETURN_STATUS = "ECOM_RETURN_STATUS"
REFUND = "REFUND"  # the only resolution that needs a credit note (user spec 2026-11-26)

DEFAULT_RECEIPT_LOCATION = "INWARD_STAGING"
DEFAULT_WASTAGE_LOCATION = "REJECTED_HOLD"
DEFAULT_REPAIR_LOCATIONS = ("DEPT_TECHNICIAN_REPAIR", "DEPT_REPACKAGING")
WASTAGE_CLASSES = frozenset({"REJECTED_HOLD", "NON_FUNCTIONAL", "SCRAP_DISPOSED"})
REF_TYPE = "ECOM_RETURN"
LIST_LIMIT = 300


def cn_qty_for(resolution_code: str, resolution_qty: int) -> int:
    """Qty Issue CN: a refund gets a credit note for the executive's qty; a free replacement
    none."""
    return resolution_qty if resolution_code == REFUND else 0


def _labels(session: Session, set_code: str) -> dict[str, str]:
    return {o["code"]: o["label"] for o in repo.options(session, set_code, include_inactive=True)}


class EcommerceSettlementService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    # ================================================================ configuration ==========
    def _location(
        self, session: Session, key: str, default: str, classes: frozenset[str]
    ) -> dict[str, Any]:
        value = repo.get_setting(session, key)
        code = value if isinstance(value, str) and value else default
        rows = repo.locations_by_codes(session, [code])
        if not rows or not rows[0]["is_active"] or rows[0]["location_class"] not in classes:
            log.error("ecommerce_setting_location_invalid", key=key, code=code)
            raise ServiceUnavailable(
                f"System setting {key} does not name an active "
                f"{'/'.join(sorted(classes))} location",
                code="SETTING_INVALID",
                details={"key": key, "code": code},
            )
        return rows[0]

    def _repair_locations(self, session: Session) -> list[dict[str, Any]]:
        value = repo.get_setting(session, "ecommerce_repair_location_codes")
        codes = (
            [c for c in value if isinstance(c, str)]
            if isinstance(value, list)
            else list(DEFAULT_REPAIR_LOCATIONS)
        )
        rows = {r["code"]: r for r in repo.locations_by_codes(session, codes)}
        # Configuration order; only active department (TECHNICIAN) locations are offered.
        return [
            rows[c]
            for c in codes
            if c in rows and rows[c]["is_active"] and rows[c]["location_class"] == "TECHNICIAN"
        ]

    # ================================================================ reads ==================
    def unboxing_queue(self, actor: CurrentUser) -> UnboxingQueueOut:
        with self._uow.transaction(actor.id) as session:
            rows = repo.unboxing_rows(session, limit=LIST_LIMIT)
            return UnboxingQueueOut(
                platforms=[
                    SOptionOut(**o)
                    for o in repo.options(session, SET_PLATFORM, include_inactive=True)
                ],
                buckets=[SOptionOut(**o) for o in repo.options(session, SET_BUCKET)],
                repair_locations=[
                    LocationOut(id=r["id"], code=r["code"], name=r["name"])
                    for r in self._repair_locations(session)
                ],
                rows=[
                    UnboxingRowOut(
                        **r, cn_qty=cn_qty_for(r["resolution_code"], r["resolution_qty"])
                    )
                    for r in rows
                ],
                repairs=[RepairRowOut(**r) for r in repo.open_repairs(session, limit=LIST_LIMIT)],
            )

    def store_receipts(self, actor: CurrentUser, state: str, *, can_ack: bool) -> StoreReceiptsOut:
        with self._uow.transaction(actor.id) as session:
            stores = repo.user_store_ids(session, actor.id)
            # Store users see their stores; read-only roles (no store) see every store.
            scope: set[UUID] | None = stores if stores else None
            rows = repo.list_receipts(session, state=state, store_ids=scope, limit=LIST_LIMIT)
            labels = _labels(session, SET_BUCKET)
            acts = {
                sid: repo.user_acts_for_store(session, actor.id, sid)
                for sid in {r["store_id"] for r in rows}
            }
        return StoreReceiptsOut(
            rows=[self._receipt_out(r, labels, can_ack and acts[r["store_id"]]) for r in rows]
        )

    @staticmethod
    def _receipt_out(
        r: dict[str, Any], labels: dict[str, str], can_ack: bool
    ) -> StoreReceiptRowOut:
        bucket = "TO_STORE" if r["source"] == "UNBOXING" else "TO_REPAIR"
        return StoreReceiptRowOut(
            id=r["id"],
            return_id=r["return_id"],
            return_no=r["return_no"],
            platform_label=r["platform_label"],
            order_id=r["order_id"],
            product_code=r["product_code"],
            product_name=r["product_name"],
            source=r["source"],
            source_label=labels.get(bucket, bucket),
            store_id=r["store_id"],
            store_name=r["store_name"],
            from_location_name=r["from_location_name"],
            qty=r["qty"],
            status=r["status"],
            created_at=r["created_at"],
            acknowledged_at=r["acknowledged_at"],
            acknowledged_by_name=r["acknowledged_by_name"],
            can_acknowledge=can_ack and r["status"] == "PENDING",
        )

    def sheets(self, actor: CurrentUser, status: str | None) -> ActionSheetListOut:
        with self._uow.transaction(actor.id) as session:
            options = repo.options(session, SET_SHEET_STATUS, include_inactive=True)
            labels = {o["code"]: o["label"] for o in options}
            rows = repo.list_sheets(session, status=status, limit=LIST_LIMIT)
        return ActionSheetListOut(
            status_options=[SOptionOut(**o) for o in options],
            rows=[
                ActionSheetRowOut(
                    id=r["id"],
                    sheet_no=r["sheet_no"],
                    platform_label=r["platform_label"],
                    status=r["status"],
                    status_label=labels.get(r["status"], r["status"]),
                    created_at=r["created_at"],
                    orders=int(r["orders"]),
                    total_received=int(r["total_received"]),
                    total_cn_qty=int(r["total_cn_qty"]),
                    cn_no=r["cn_no"],
                )
                for r in rows
            ],
        )

    def sheet(self, actor: CurrentUser, sheet_id: UUID) -> ActionSheetOut:
        with self._uow.transaction(actor.id) as session:
            return self._sheet_out(session, sheet_id)

    @staticmethod
    def settlement_for_return(session: Session, return_id: UUID) -> ReturnSettlementOut | None:
        """Read model for the E-Commerce Return detail (called by EcommerceReturnService)."""
        row = repo.return_settlement(session, return_id)
        if row is None:
            return None
        repair = repo.repair_for_return(session, return_id)
        return ReturnSettlementOut(
            **row,
            repair=ReturnRepairOut(**repair) if repair else None,
            receipts=[ReturnReceiptOut(**x) for x in repo.receipts_for_return(session, return_id)],
        )

    # ================================================================ unboxing ===============
    def unbox(
        self, actor: CurrentUser, payload: UnboxBatchIn, idem: IdempotencyKey
    ) -> IdempotentResult:
        return self._command(actor, idem, 201, lambda s: self._unbox(s, actor, payload))

    def _unbox(self, session: Session, actor: CurrentUser, payload: UnboxBatchIn) -> ActionSheetOut:
        errors: dict[str, list[str]] = {}

        def fail(field: str, message: str) -> None:
            errors.setdefault(field, []).append(message)

        platforms = _labels(session, SET_PLATFORM)
        if payload.platform_code not in platforms:
            raise ValidationFailed(
                "Choose a platform", details={"platform_code": ["Not an ECOM_PLATFORM option"]}
            )
        ids = [line.return_id for line in payload.lines]
        if len(set(ids)) != len(ids):
            raise ValidationFailed(
                "A return is listed twice", details={"lines": ["Each return once per batch"]}
            )
        locked = {r["id"]: r for r in repo.lock_returns(session, ids)}
        repair_locs = {r["id"]: r for r in self._repair_locations(session)}
        stores: dict[UUID, dict[str, Any]] = {}

        for i, line in enumerate(payload.lines):
            ret = locked.get(line.return_id)
            if ret is None:
                fail(f"lines.{i}.return_id", "E-Commerce Return not found")
                continue
            if ret["status"] != "PENDING_UNBOXING":
                fail(f"lines.{i}.return_id", f"{ret['return_no']} is not waiting for unboxing")
                continue
            if ret["platform_code"] != payload.platform_code:
                fail(
                    f"lines.{i}.return_id",
                    f"{ret['return_no']} is from another platform; one action sheet per platform",
                )
            total = line.good_qty + line.repair_qty + line.wastage_qty
            if total != ret["qty"]:
                fail(
                    f"lines.{i}.qty",
                    f"{ret['return_no']}: store + repair + wastage = {total}, "
                    f"received {ret['qty']}",
                )
            if ret["product_id"] is None and (line.good_qty or line.repair_qty):
                fail(
                    f"lines.{i}.good_qty",
                    f"{ret['return_no']} is not our product: all pieces are wastage",
                )
            if line.repair_qty > 0:
                if line.repair_location_id is None:
                    fail(f"lines.{i}.repair_location_id", "Choose the repair department")
                elif line.repair_location_id not in repair_locs:
                    fail(f"lines.{i}.repair_location_id", "This department is not offered")
            elif line.repair_location_id is not None:
                fail(
                    f"lines.{i}.repair_location_id", "No repair pieces: leave the department empty"
                )
            if line.good_qty > 0 and ret["product_id"] is not None:
                store = repo.store_for_product(session, ret["product_id"])
                if store is None:
                    fail(
                        f"lines.{i}.good_qty",
                        "STORE_MAPPING_MISSING: the product has no Intermediate Store",
                    )
                else:
                    stores[ret["id"]] = store
            if line.repair_qty > 0 and ret["product_id"] is not None:
                store = repo.store_for_product(session, ret["product_id"])
                if store is None:
                    fail(
                        f"lines.{i}.repair_qty",
                        "STORE_MAPPING_MISSING: the product has no Intermediate Store",
                    )
        if errors:
            raise ValidationFailed("Some lines need attention", details=errors)

        receipt_loc = self._location(
            session,
            "ecommerce_receipt_location_code",
            DEFAULT_RECEIPT_LOCATION,
            frozenset({"INWARD"}),
        )
        wastage_loc = self._location(
            session, "ecommerce_wastage_location_code", DEFAULT_WASTAGE_LOCATION, WASTAGE_CLASSES
        )

        sheet_no = repo.next_sheet_no(session, repo.business_today(session))
        sheet_id = repo.insert_sheet(
            session,
            sheet_no=sheet_no,
            platform_code=payload.platform_code,
            platform_label=platforms[payload.platform_code],
        )
        total_cn = 0
        for line in payload.lines:
            ret = locked[line.return_id]
            rid: UUID = ret["id"]
            cn_qty = cn_qty_for(ret["resolution_code"], ret["resolution_qty"])
            total_cn += cn_qty
            repo.set_return_unboxed(
                session,
                rid,
                {
                    "sheet_id": sheet_id,
                    "good_qty": line.good_qty,
                    "repair_qty": line.repair_qty,
                    "wastage_qty": line.wastage_qty,
                    "cn_qty": cn_qty,
                    "repair_location_id": line.repair_location_id if line.repair_qty else None,
                    "note": (line.note or "").strip() or None,
                    "by": actor.id,
                },
            )
            if ret["product_id"] is not None:
                self._stock_in(
                    session, actor, ret, line, sheet_no, receipt_loc, wastage_loc, stores
                )
            repo.insert_event(
                session,
                rid,
                "UNBOXED",
                from_status="PENDING_UNBOXING",
                to_status="UNBOXED",
                details={
                    "sheet_no": sheet_no,
                    "good_qty": line.good_qty,
                    "repair_qty": line.repair_qty,
                    "wastage_qty": line.wastage_qty,
                    "cn_qty": cn_qty,
                },
            )
        if total_cn == 0:
            # Nothing for Accounts (free replacements only): the sheet completes at once.
            repo.complete_sheet(
                session,
                sheet_id,
                cn_no=None,
                cn_date=None,
                cn_value=None,
                remarks=None,
                by=actor.id,
            )
            for rid in repo.sheet_return_ids(session, sheet_id):
                self._close_if_settled(session, rid)
        log.info(
            "ecommerce_unboxed",
            sheet_no=sheet_no,
            returns=len(payload.lines),
            cn_qty=total_cn,
        )
        return self._sheet_out(session, sheet_id)

    def _stock_in(
        self,
        session: Session,
        actor: CurrentUser,
        ret: dict[str, Any],
        line: UnboxLineIn,
        sheet_no: str,
        receipt_loc: dict[str, Any],
        wastage_loc: dict[str, Any],
        stores: dict[UUID, dict[str, Any]],
    ) -> None:
        """Receive the pieces of one return into stock, one lot per destination (rule f)."""
        rid: UUID = ret["id"]
        item_id = ledger_service.create_stock_item(
            session, item_kind="FINISHED_GOOD", product_id=ret["product_id"], created_by=actor.id
        )
        reason = f"E-Commerce Return {ret['return_no']} (action sheet {sheet_no})"

        def receive(qty: int, condition: str, bucket: str, to_loc: UUID) -> UUID:
            lot = ledger_service.create_stock_lot(
                session,
                stock_item_id=item_id,
                condition_class=condition,
                source_condition_code=bucket,
                created_by=actor.id,
                ecommerce_return_id=rid,
            )
            ledger_service.move_stock(
                session,
                lot_id=lot,
                from_location_id=None,
                to_location_id=to_loc,
                qty=qty,
                movement_type="RECEIPT",
                reference_type=REF_TYPE,
                reference_id=rid,
                idempotency_key=f"ecom-unbox:{rid}:{bucket}",
                actor_id=actor.id,
                reason=reason,
            )
            return lot

        if line.good_qty > 0:
            lot = receive(line.good_qty, "FUNCTIONAL_GOOD", "TO_STORE", receipt_loc["id"])
            store = stores[rid]
            repo.insert_receipt(
                session,
                return_id=rid,
                source="UNBOXING",
                store_id=store["id"],
                lot_id=lot,
                from_location_id=receipt_loc["id"],
                qty=line.good_qty,
            )
        if line.repair_qty > 0 and line.repair_location_id is not None:  # validated above
            lot = receive(line.repair_qty, "AS_RECEIVED", "TO_REPAIR", line.repair_location_id)
            repo.insert_repair(
                session,
                return_id=rid,
                location_id=line.repair_location_id,
                lot_id=lot,
                qty=line.repair_qty,
            )
        if line.wastage_qty > 0:
            receive(line.wastage_qty, "NON_GOOD", "WASTAGE", wastage_loc["id"])

    # ================================================================ repair =================
    def repair_return(
        self, actor: CurrentUser, repair_id: UUID, payload: RepairReturnIn, idem: IdempotencyKey
    ) -> IdempotentResult:
        def run(session: Session) -> BaseModel:
            repair = repo.get_repair(session, repair_id, for_update=True)
            if repair is None:
                raise NotFound("Repair record not found")
            if repair["status"] != "AT_DEPARTMENT":
                raise Conflict("These repair pieces already came back", code="ECOM_REPAIR_RETURNED")
            if payload.qty_ok + payload.qty_scrap != repair["qty_sent"]:
                raise ValidationFailed(
                    f"OK + scrap must equal the {repair['qty_sent']} pieces sent",
                    details={"qty_ok": [f"OK + scrap = {repair['qty_sent']}"]},
                )
            ret = repo.get_return_brief(session, repair["return_id"], for_update=True)
            assert ret is not None  # noqa: S101 - FK
            store = repo.store_for_product(session, ret["product_id"]) if payload.qty_ok else None
            if payload.qty_ok and store is None:
                raise Conflict(
                    "The product has no Intermediate Store", code="STORE_MAPPING_MISSING"
                )
            if payload.qty_scrap:
                wastage_loc = self._location(
                    session,
                    "ecommerce_wastage_location_code",
                    DEFAULT_WASTAGE_LOCATION,
                    WASTAGE_CLASSES,
                )
                ledger_service.move_stock(
                    session,
                    lot_id=repair["lot_id"],
                    from_location_id=repair["location_id"],
                    to_location_id=wastage_loc["id"],
                    qty=payload.qty_scrap,
                    movement_type="TRANSFER_IN",
                    reference_type=REF_TYPE,
                    reference_id=ret["id"],
                    idempotency_key=f"ecom-repair:{repair_id}:scrap",
                    actor_id=actor.id,
                    reason=f"E-Commerce Return {ret['return_no']}: scrap after repair",
                )
            note = (payload.note or "").strip() or None
            repo.set_repair_returned(
                session,
                repair_id,
                qty_ok=payload.qty_ok,
                qty_scrap=payload.qty_scrap,
                note=note,
                by=actor.id,
            )
            if payload.qty_ok and store is not None:
                repo.insert_receipt(
                    session,
                    return_id=ret["id"],
                    source="REPAIR",
                    store_id=store["id"],
                    lot_id=repair["lot_id"],
                    from_location_id=repair["location_id"],
                    qty=payload.qty_ok,
                )
            repo.insert_event(
                session,
                ret["id"],
                "REPAIR_RETURNED",
                from_status=ret["status"],
                to_status=ret["status"],
                details={"qty_ok": payload.qty_ok, "qty_scrap": payload.qty_scrap, "note": note},
            )
            self._close_if_settled(session, ret["id"])
            out = self.settlement_for_return(session, ret["id"])
            assert out is not None  # noqa: S101 - the return is unboxed
            return out

        return self._command(actor, idem, 200, run)

    # ================================================================ store ==================
    def acknowledge(
        self, actor: CurrentUser, payload: AcknowledgeIn, idem: IdempotencyKey
    ) -> IdempotentResult:
        def run(session: Session) -> BaseModel:
            ids = list(dict.fromkeys(payload.receipt_ids))
            rows = repo.lock_receipts(session, ids)
            found = {r["id"] for r in rows}
            missing = [str(i) for i in ids if i not in found]
            if missing:
                raise NotFound("Store receipt not found", details={"receipt_ids": missing})
            for r in rows:
                if r["status"] != "PENDING":
                    raise Conflict(
                        f"{r['return_no']} was already acknowledged",
                        code="ECOM_RECEIPT_ACKNOWLEDGED",
                        details={"receipt_id": str(r["id"])},
                    )
                if not repo.user_acts_for_store(session, actor.id, r["store_id"]):
                    raise PermissionDenied(
                        f"Only a user of {r['store_name']} acknowledges its receipts",
                        details={"receipt_id": str(r["id"])},
                    )
            labels = _labels(session, SET_BUCKET)
            for r in rows:
                movement = ledger_service.move_stock(
                    session,
                    lot_id=r["lot_id"],
                    from_location_id=r["from_location_id"],
                    to_location_id=r["store_location_id"],
                    qty=r["qty"],
                    movement_type="TRANSFER_IN",
                    reference_type=REF_TYPE,
                    reference_id=r["return_id"],
                    idempotency_key=f"ecom-receipt:{r['id']}",
                    actor_id=actor.id,
                    reason=f"E-Commerce Return {r['return_no']}: received in {r['store_name']}",
                )
                repo.acknowledge_receipt(session, r["id"], movement_id=movement, by=actor.id)
                ret = repo.get_return_brief(session, r["return_id"], for_update=True)
                assert ret is not None  # noqa: S101 - FK
                repo.insert_event(
                    session,
                    r["return_id"],
                    "STORE_RECEIVED",
                    from_status=ret["status"],
                    to_status=ret["status"],
                    details={"store": r["store_name"], "qty": r["qty"], "source": r["source"]},
                )
                self._close_if_settled(session, r["return_id"])
            done = repo.lock_receipts(session, ids)
            log.info("ecommerce_store_receipts_acknowledged", receipts=len(done))
            return StoreReceiptsOut(rows=[self._receipt_out(r, labels, False) for r in done])

        return self._command(actor, idem, 200, run)

    # ================================================================ accounts ===============
    def complete_sheet(
        self, actor: CurrentUser, sheet_id: UUID, payload: CompleteSheetIn, idem: IdempotencyKey
    ) -> IdempotentResult:
        def run(session: Session) -> BaseModel:
            sheet = repo.get_sheet(session, sheet_id, for_update=True)
            if sheet is None:
                raise NotFound("Action sheet not found")
            if sheet["status"] != "PENDING_ACCOUNTS":
                raise Conflict(
                    "This action sheet is already completed", code="ECOM_SHEET_COMPLETED"
                )
            total_cn = int(sheet["total_cn_qty"])
            cn_no = (payload.cn_no or "").strip() or None
            remarks = (payload.remarks or "").strip() or None
            if total_cn > 0:
                errors: dict[str, list[str]] = {}
                if not cn_no:
                    errors["cn_no"] = ["Required: Qty Issue CN is " + str(total_cn)]
                if payload.cn_date is None:
                    errors["cn_date"] = ["Required"]
                elif payload.cn_date > repo.business_today(session):
                    errors["cn_date"] = ["Cannot be later than today"]
                if payload.cn_value is None:
                    errors["cn_value"] = ["Required"]
                if errors:
                    raise ValidationFailed(
                        "Enter the credit note", code="ECOM_CN_REQUIRED", details=errors
                    )
                cn_date, cn_value = payload.cn_date, payload.cn_value
            else:
                if cn_no or payload.cn_date or payload.cn_value:
                    raise ValidationFailed(
                        "This sheet has no qty for a credit note",
                        code="ECOM_CN_NOT_NEEDED",
                        details={"cn_no": ["Leave empty"]},
                    )
                cn_no, cn_date, cn_value = None, None, None
            repo.complete_sheet(
                session,
                sheet_id,
                cn_no=cn_no,
                cn_date=cn_date,
                cn_value=cn_value,
                remarks=remarks,
                by=actor.id,
            )
            for rid in repo.sheet_return_ids(session, sheet_id):
                ret = repo.get_return_brief(session, rid, for_update=True)
                assert ret is not None  # noqa: S101
                repo.insert_event(
                    session,
                    rid,
                    "CN_ISSUED" if cn_no else "SHEET_COMPLETED",
                    from_status=ret["status"],
                    to_status=ret["status"],
                    details={"sheet_no": sheet["sheet_no"], "cn_no": cn_no},
                )
                self._close_if_settled(session, rid)
            log.info("ecommerce_sheet_completed", sheet_no=sheet["sheet_no"], cn_no=cn_no)
            return self._sheet_out(session, sheet_id)

        return self._command(actor, idem, 200, run)

    # ================================================================ internals ==============
    def _close_if_settled(self, session: Session, return_id: UUID) -> None:
        ret = repo.get_return_brief(session, return_id, for_update=True)
        if ret is None or ret["status"] != "UNBOXED" or not repo.return_settled(session, return_id):
            return
        repo.close_return(session, return_id)
        repo.insert_event(session, return_id, "CLOSED", from_status="UNBOXED", to_status="CLOSED")
        log.info("ecommerce_return_closed", return_id=str(return_id))

    def _sheet_out(self, session: Session, sheet_id: UUID) -> ActionSheetOut:
        sheet = repo.get_sheet(session, sheet_id)
        if sheet is None:
            raise NotFound("Action sheet not found")
        sheet_labels = _labels(session, SET_SHEET_STATUS)
        status_labels = _labels(session, SET_RETURN_STATUS)
        company = repo.get_setting(session, "company_name")
        return ActionSheetOut(
            id=sheet["id"],
            sheet_no=sheet["sheet_no"],
            platform_code=sheet["platform_code"],
            platform_label=sheet["platform_label"],
            status=sheet["status"],
            status_label=sheet_labels.get(sheet["status"], sheet["status"]),
            created_at=sheet["created_at"],
            created_by_name=sheet["created_by_name"],
            total_received=int(sheet["total_received"]),
            total_cn_qty=int(sheet["total_cn_qty"]),
            cn_no=sheet["cn_no"],
            cn_date=sheet["cn_date"],
            cn_value=sheet["cn_value"],
            remarks=sheet["remarks"],
            completed_at=sheet["completed_at"],
            completed_by_name=sheet["completed_by_name"],
            company_name=company if isinstance(company, str) and company.strip() else None,
            business_today=repo.business_today(session),
            lines=[
                ActionSheetLineOut(**ln, status_label=status_labels.get(ln["status"], ln["status"]))
                for ln in repo.sheet_lines(session, sheet_id)
            ],
        )

    def _command(
        self,
        actor: CurrentUser,
        idem: IdempotencyKey,
        status: int,
        work: Callable[[Session], BaseModel],
    ) -> IdempotentResult:
        with self._uow.transaction(actor.id) as session:
            return run_idempotent(
                session, idem, actor.id, lambda: (status, work(session).model_dump(mode="json"))
            )
