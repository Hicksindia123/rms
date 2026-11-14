"""Custody segregation, functional inventory & spare-parts ledger (prompt P3-04).

Master plan §2.2 Stage-5 (Step-6), DD r63-r66, BR-30, G-04, G-05, G-08, G-09, G-12, G-16.

* **Segregated stock views**: functional stock (Sahil), non-functional stock and the salvaged spare
  parts ledger (Spare Parts Manager), batteries, rejected hold, hazard quarantine, pending hold and
  in-transit; paginated, filterable, CSV-exportable. Salvaged parts are visible only to the roles in
  `spare_parts_ledger_view_roles` (+ Super Admin), BR-30.
* **Stock card**: a lot's movements plus those of the lots it was reclassified / dismantled from,
  so the path from GS inward to the current location is complete.
* **Custody assignment** (DD r63-66): validates the lot's condition against the assignment
  (contradictions → G-04 / G-05 / G-12) and, when the lot is not already with the right custodian,
  starts a two-phase custody transfer (G-09) to the configured destination
  (`custody_assignment_targets`; its location class is locked to the assignment, G-12).
* **Segregation check**: `rms_private.inventory_segregation_violations()` on demand and nightly.
* **Stock adjustments**: count differences requested by the location's custodian, approved by a
  role in `stock_adjustment_approver_roles` (never the requester); ADJUST movement via
  rms_move_stock with an idempotency key (G-16).
"""

from __future__ import annotations

import csv
import io
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy.orm import Session

from app.core.db import UnitOfWork
from app.core.errors import (
    Conflict,
    NotFound,
    PermissionDenied,
    ServiceUnavailable,
    SystemGuardUnmet,
    SystemGuardViolation,
    ValidationFailed,
)
from app.core.idempotency import IdempotencyKey, IdempotentResult, run_idempotent
from app.core.permissions import EffectivePermissions
from app.core.security import CurrentUser
from app.modules.custody import service as custody_service
from app.modules.custody.schemas import TransferLineIn
from app.modules.inventory import ledger_service
from app.modules.inventory import repository as repo
from app.modules.inventory.schemas import (
    AdjustmentDecisionIn,
    AdjustmentIn,
    AdjustmentOut,
    AdjustmentPage,
    AdjustmentRejectIn,
    AssignmentIn,
    AssignmentOut,
    BalanceOut,
    InventoryLookupsOut,
    MovementOut,
    OptionOut,
    RefOut,
    SegregationCheckOut,
    SegregationRunOut,
    StockCardOut,
    StockPage,
    StockRowOut,
    StockView,
    ViolationOut,
)
from app.modules.notifications import service as notifications
from app.shared.guards import guard_g04, guard_g05, guard_g12

log = structlog.get_logger(__name__)

SEGREGATE_FORM, ASSIGNMENT_FIELD = "S5_SEGREGATE", "custody_assignment"  # DD r63-66
SEGREGATE_STEP = "S5_SEGREGATE"
ASSIGNMENT_PURPOSE = "CUSTODY_ASSIGNMENT"
ADJUSTMENT_ENTITY = "stock_adjustment"
EXPORT_ROW_LIMIT = 10_000

# Stable codes (DD r63-66). The condition classes each assignment accepts follow the row text:
# r63 Good / Fresh, r64 Repaired, r65 Non-Functional / Scratched / Non-Sellable, r66 Salvaged parts.
ASSIGNMENT_CONDITIONS: Mapping[str, frozenset[str]] = {
    "CUST_FUNCTIONAL_GOOD": frozenset({"FUNCTIONAL_GOOD"}),
    "CUST_FUNCTIONAL_REPAIRED": frozenset({"FUNCTIONAL_REPAIRED"}),
    "CUST_NON_FUNCTIONAL": frozenset({"NON_GOOD", "NON_SELLABLE", "NOT_ALLOWED"}),
    "CUST_SALVAGED_PARTS": frozenset({"SALVAGED"}),
}
# Locked destination class per assignment (G-12 / BR-30); the location itself is configuration.
ASSIGNMENT_TARGET_CLASS: Mapping[str, str] = {
    "CUST_FUNCTIONAL_GOOD": "FUNCTIONAL",
    "CUST_FUNCTIONAL_REPAIRED": "FUNCTIONAL",
    "CUST_NON_FUNCTIONAL": "NON_FUNCTIONAL",
    "CUST_SALVAGED_PARTS": "SPARE_PARTS",
}
FUNCTIONAL_ASSIGNMENTS = frozenset({"CUST_FUNCTIONAL_GOOD", "CUST_FUNCTIONAL_REPAIRED"})
G04_CONDITIONS = frozenset({"NOT_ALLOWED", "HAZARD", "NON_GOOD", "NON_SELLABLE", "SCRAP"})
# Step-6 segregates working custody. Holds (rejected / pending / hazard), transit and the
# downstream locations are settled by their own flows (DEC-10, DEC-12, G-05, G-09, P3-05).
ASSIGNABLE_SOURCE_CLASSES = frozenset(
    {"INWARD", "FUNCTIONAL", "TECHNICIAN", "NON_FUNCTIONAL", "SPARE_PARTS"}
)
ASSIGNABLE_ITEM_KINDS = frozenset({"FINISHED_GOOD", "SPARE_PART"})

VIEWS: tuple[StockView, ...] = (
    "FUNCTIONAL",
    "NON_FUNCTIONAL",
    "SPARE_PARTS",
    "BATTERIES",
    "REJECTED_HOLD",
    "HAZARD_QUARANTINE",
    "PENDING_HOLD",
    "IN_TRANSIT",
)

CSV_COLUMNS: tuple[tuple[str, str], ...] = (
    ("gs_no", "GS No."),
    ("line_no", "Line"),
    ("product_code", "Product code"),
    ("product_name", "Product"),
    ("part_type", "Part type"),
    ("pcb_model_name", "PCB model"),
    ("pcb_supplier_name", "PCB supplier"),
    ("battery_type_name", "Battery type"),
    ("container_code", "Container"),
    ("partition_code", "Partition"),
    ("condition_class", "Condition"),
    ("location_name", "Location"),
    ("qty", "Qty"),
    ("received_at", "Received at"),
    ("age_days", "Age (days)"),
    ("next_action_text", "Next action"),
    ("transfer_no", "Transfer"),
)


# =============================================================================================
# Pure rules (unit-tested)
# =============================================================================================
def assignment_codes_for(condition_class: str, item_kind: str) -> list[str]:
    """Assignment codes valid for a lot (DD r63-66); empty when none applies."""
    if item_kind not in ASSIGNABLE_ITEM_KINDS:
        return []
    return [code for code, conds in ASSIGNMENT_CONDITIONS.items() if condition_class in conds]


def check_assignment(condition_class: str, item_kind: str, code: str) -> None:
    """Reject an assignment that contradicts the lot (BR-30; G-04 / G-05 / G-12 are guards)."""
    if code not in ASSIGNMENT_CONDITIONS:
        raise ValidationFailed(f"Unknown assignment {code!r}", code="CUSTODY_ASSIGNMENT_INVALID")
    if item_kind not in ASSIGNABLE_ITEM_KINDS:
        raise ValidationFailed(
            f"{item_kind} stock is not custody-assigned",
            code="CUSTODY_ASSIGNMENT_NOT_APPLICABLE",
        )
    if condition_class == "HAZARD":
        raise SystemGuardUnmet(
            "G-05", "Hazard lots stay in hazard quarantine; they are never custody-assigned"
        )
    if code in FUNCTIONAL_ASSIGNMENTS and condition_class in G04_CONDITIONS:
        raise SystemGuardUnmet(
            "G-04",
            f"A {condition_class} lot can never be assigned to functional custody",
            details={"condition_class": condition_class, "assignment_code": code},
        )
    if code in FUNCTIONAL_ASSIGNMENTS and condition_class == "SALVAGED":
        raise SystemGuardUnmet(
            "G-12",
            "Salvaged parts can never be assigned to functional custody",
            details={"condition_class": condition_class, "assignment_code": code},
        )
    if condition_class == "AS_RECEIVED":
        raise ValidationFailed(
            "This lot is not classified yet: classify it (direct classification or technician) "
            "before assigning custody",
            code="CUSTODY_ASSIGNMENT_NEEDS_CLASSIFICATION",
        )
    if condition_class not in ASSIGNMENT_CONDITIONS[code]:
        raise ValidationFailed(
            f"Assignment {code} does not match the lot's condition {condition_class}",
            code="CUSTODY_ASSIGNMENT_MISMATCH",
            details={
                "condition_class": condition_class,
                "valid_codes": assignment_codes_for(condition_class, item_kind),
            },
        )


def adjustment_movement(location_id: UUID, delta: int) -> tuple[UUID | None, UUID | None, int]:
    """(from, to, qty) of the ADJUST movement for a count difference."""
    if delta == 0:
        raise ValidationFailed("No difference to adjust", code="ADJUSTMENT_NO_DIFFERENCE")
    return (location_id, None, -delta) if delta < 0 else (None, location_id, delta)


def to_csv(rows: list[dict[str, Any]]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow([header for _, header in CSV_COLUMNS])
    for row in rows:
        writer.writerow(
            ["" if row.get(k) is None else _csv_cell(row.get(k)) for k, _ in CSV_COLUMNS]
        )
    return buf.getvalue()


def _csv_cell(value: Any) -> str:
    out = value.isoformat() if isinstance(value, datetime) else str(value)
    # CSV formula injection: a leading = + - @ \t \r is neutralised for spreadsheet apps.
    return f"'{out}" if out[:1] in ("=", "+", "-", "@", "\t", "\r") else out


@dataclass(frozen=True, slots=True)
class StockFilters:
    product_id: UUID | None = None
    condition_class: str | None = None
    gs_id: UUID | None = None
    location_id: UUID | None = None
    part_type: str | None = None
    pcb_model_id: UUID | None = None
    pcb_supplier_id: UUID | None = None
    container_id: UUID | None = None
    partition_id: UUID | None = None
    battery_type_id: UUID | None = None
    q: str | None = None
    min_age_days: int | None = None
    max_age_days: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__slots__}


# =============================================================================================
# Service
# =============================================================================================
class InventoryService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    # --- lookups ---------------------------------------------------------------------------
    def lookups(self, user: CurrentUser, perms: EffectivePermissions) -> InventoryLookupsOut:
        with self._uow.transaction(user.id) as session:
            parts = _can_see_parts(session, user)
            return InventoryLookupsOut(
                assignment_options=_assignment_options(session),
                views=[v for v in VIEWS if parts or v != "SPARE_PARTS"],
                products=[RefOut(**r) for r in repo.stocked_products(session)],
                part_types=[
                    OptionOut(code=o["code"], label=o["label"])
                    for o in repo.option_items(session, "RECOVERABLE_PART_TYPE")
                ],
                pcb_models=_refs(session, "pcb_models") if parts else [],
                pcb_suppliers=_refs(session, "pcb_suppliers") if parts else [],
                containers=_refs(session, "containers") if parts else [],
                partitions=_refs(session, "partitions") if parts else [],
                battery_types=_refs(session, "battery_types"),
                can_export=perms.allows("inventory", "export"),
                can_assign=perms.allows("inventory", "edit"),
                can_request_adjustment=perms.allows("inventory", "edit"),
                can_approve_adjustment=_may_approve(session, user, perms),
            )

    # --- stock views -----------------------------------------------------------------------
    def stock(
        self,
        user: CurrentUser,
        view: StockView,
        filters: StockFilters,
        *,
        page: int,
        page_size: int,
    ) -> StockPage:
        with self._uow.transaction(user.id) as session:
            rows, total, total_qty = self._stock_rows(
                session, user, view, filters, limit=page_size, offset=(page - 1) * page_size
            )
            return StockPage(
                view=view,
                items=[StockRowOut(**r) for r in rows],
                total=total,
                total_qty=total_qty,
                page=page,
                page_size=page_size,
            )

    def export_csv(self, user: CurrentUser, view: StockView, filters: StockFilters) -> str:
        with self._uow.transaction(user.id) as session:
            rows, total, _ = self._stock_rows(
                session, user, view, filters, limit=EXPORT_ROW_LIMIT, offset=0
            )
            if total > EXPORT_ROW_LIMIT:
                raise ValidationFailed(
                    f"The export is limited to {EXPORT_ROW_LIMIT} rows; narrow the filters",
                    code="EXPORT_TOO_LARGE",
                    details={"total": total},
                )
            log.info("inventory_exported", view=view, rows=len(rows))
            return to_csv(rows)

    def _stock_rows(
        self,
        session: Session,
        user: CurrentUser,
        view: StockView,
        filters: StockFilters,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, Any]], int, int]:
        parts = _can_see_parts(session, user)
        if view == "SPARE_PARTS" and not parts:
            raise PermissionDenied(
                "The spare parts ledger is visible only to the Spare Parts Manager and "
                "management (BR-30)",
                code="SPARE_PARTS_LEDGER_RESTRICTED",
            )
        rows, total, total_qty = repo.stock_page(
            session, view, filters.as_dict(), include_salvaged=parts, limit=limit, offset=offset
        )
        options = {o.code: o for o in _assignment_options(session)}
        for row in rows:
            codes = assignment_codes_for(row["condition_class"], row["item_kind"])
            row["assignment_codes"] = (
                [c for c in codes if c in options]
                if row["location_class"] in ASSIGNABLE_SOURCE_CLASSES
                else []
            )
            # DD r63-64 routing ("Store Issue or Customer Dispatch" / "… or General CN") is the
            # next-action text of the matching assignment option (configuration, rule e).
            match = codes[0] if len(codes) == 1 and codes[0] in options else None
            row["next_action_code"] = match
            row["next_action_text"] = options[match].description if match else None
        return rows, total, total_qty

    # --- stock card ------------------------------------------------------------------------
    def stock_card(self, user: CurrentUser, lot_id: UUID) -> StockCardOut:
        with self._uow.transaction(user.id) as session:
            header = repo.lot_header(session, lot_id)
            if not header:
                raise NotFound("Lot not found", code="LOT_NOT_FOUND")
            if header["condition_class"] == "SALVAGED" and not _can_see_parts(session, user):
                raise PermissionDenied(
                    "Salvaged parts are visible only in the spare parts ledger (BR-30)",
                    code="SPARE_PARTS_LEDGER_RESTRICTED",
                )
            lineage = repo.lot_lineage(session, lot_id)
            ancestors = [a for a in lineage if a["lot_id"] != lot_id]
            movements = repo.movements_for_lineage(session, lot_id, ancestors)
            lot_ids = [a["lot_id"] for a in lineage]
            return StockCardOut(
                **header,
                lineage=lot_ids,
                balances=[BalanceOut(**b) for b in repo.lot_positions(session, lot_id)],
                movements=[MovementOut(**m) for m in movements],
                assignments=[
                    AssignmentOut(**a) for a in repo.assignments_for_lots(session, lot_ids)
                ],
            )

    # --- custody assignment (DD r63-66) -----------------------------------------------------
    def assign(
        self,
        user: CurrentUser,
        perms: EffectivePermissions,
        payload: AssignmentIn,
        idem: IdempotencyKey,
    ) -> IdempotentResult:
        with self._uow.transaction(user.id) as session:

            def command() -> tuple[int, Any]:
                return 201, self._assign(session, user, perms, payload)

            return run_idempotent(session, idem, user.id, command)

    def _assign(
        self,
        session: Session,
        user: CurrentUser,
        perms: EffectivePermissions,
        payload: AssignmentIn,
    ) -> AssignmentOut:
        lot = repo.lot_for_update(session, payload.lot_id)
        if not lot:
            raise NotFound("Lot not found", code="LOT_NOT_FOUND")
        if lot["condition_class"] == "SALVAGED" and not _can_see_parts(session, user):
            raise PermissionDenied(
                "Salvaged parts are managed only in the spare parts ledger (BR-30)",
                code="SPARE_PARTS_LEDGER_RESTRICTED",
            )
        code = payload.assignment_code
        check_assignment(lot["condition_class"], lot["item_kind"], code)
        option = custody_service.form_option(session, SEGREGATE_FORM, ASSIGNMENT_FIELD, code)
        target = _assignment_target(session, code)
        source, available = _assignment_source(session, lot, target, payload)
        if payload.qty > available:
            raise ValidationFailed(
                f"The lot holds {available} at {source['name']}; cannot assign {payload.qty}",
                code="CUSTODY_ASSIGNMENT_QTY_INVALID",
                details={"available": available, "qty": payload.qty},
            )
        if not (
            custody_service.is_custodian(session, user, source)
            or custody_service.may_override(session, user, perms)
        ):
            raise PermissionDenied(
                f"Only the custodian of {source['name']} (or a custody override role) may "
                "assign this stock",
                code="NOT_LOCATION_CUSTODIAN",
                details={"location_code": source["code"]},
            )
        notes = _clean(payload.notes)
        transfer_id: UUID | None = None
        if source["id"] != target["id"]:
            # G-09: custody moves only through the two-phase engine; the receiver accepts.
            transfer_id = custody_service.initiate_transfer(
                session,
                actor=user,
                from_location_code=source["code"],
                to_location_code=target["code"],
                lines=[TransferLineIn(lot_id=payload.lot_id, qty=payload.qty)],
                gs_id=lot["gs_id"],
                purpose_code=ASSIGNMENT_PURPOSE,
                notes=notes or f"Custody assignment {code}",
                check_custodian=False,
                task_step_code=SEGREGATE_STEP,
            )
        assignment_id = repo.insert_assignment(
            session,
            lot_id=payload.lot_id,
            qty=payload.qty,
            assignment_code=code,
            condition_class=lot["condition_class"],
            from_location_id=source["id"],
            to_location_id=target["id"],
            outcome="TRANSFER_INITIATED" if transfer_id else "ALREADY_IN_PLACE",
            transfer_id=transfer_id,
            form_version_id=option["form_version_id"],
            labels_snapshot={ASSIGNMENT_FIELD: option["snapshot"]},
            notes=notes,
            by=user.id,
        )
        log.info(
            "custody_assignment_recorded",
            assignment_id=str(assignment_id),
            code=code,
            transfer_id=str(transfer_id) if transfer_id else None,
        )
        return AssignmentOut(**repo.get_assignment(session, assignment_id))

    # --- segregation check -----------------------------------------------------------------
    def segregation_check(self, user: CurrentUser) -> SegregationCheckOut:
        with self._uow.transaction(user.id) as session:
            violations = repo.segregation_violations(session)
            last = repo.last_segregation_run(session, "NIGHTLY")
            return SegregationCheckOut(
                checked_at=datetime.now(UTC),
                violation_count=len(violations),
                violations=[ViolationOut(**v) for v in violations],
                last_nightly_run=SegregationRunOut(**last) if last else None,
            )

    # --- stock adjustments -----------------------------------------------------------------
    def list_adjustments(
        self,
        user: CurrentUser,
        perms: EffectivePermissions,
        *,
        status: str | None,
        page: int,
        page_size: int,
    ) -> AdjustmentPage:
        with self._uow.transaction(user.id) as session:
            rows, total = repo.list_adjustments(
                session,
                status=status,
                include_salvaged=_can_see_parts(session, user),
                limit=page_size,
                offset=(page - 1) * page_size,
            )
            approver = _may_approve(session, user, perms)
            return AdjustmentPage(
                items=[_adjustment_out(r, user, approver) for r in rows],
                total=total,
                page=page,
                page_size=page_size,
            )

    def request_adjustment(
        self, user: CurrentUser, perms: EffectivePermissions, payload: AdjustmentIn
    ) -> AdjustmentOut:
        with self._uow.transaction(user.id) as session:
            location = repo.location_by_id(session, payload.location_id)
            if not location:
                raise NotFound("Location not found", code="LOCATION_NOT_FOUND")
            lot = repo.lot_for_update(session, payload.lot_id)
            if not lot:
                raise NotFound("Lot not found", code="LOT_NOT_FOUND")
            if lot["item_kind"] == "BATTERY":
                raise ValidationFailed(
                    "Battery stock is adjusted from the battery store (battery adjustments)",
                    code="ADJUSTMENT_USE_BATTERY_FLOW",
                )
            if lot["condition_class"] == "SALVAGED" and not _can_see_parts(session, user):
                raise PermissionDenied(
                    "Salvaged parts are managed only in the spare parts ledger (BR-30)",
                    code="SPARE_PARTS_LEDGER_RESTRICTED",
                )
            if location["location_class"] == "TRANSIT":
                raise SystemGuardUnmet(
                    "G-09", "Stock in transit is settled through its custody transfer"
                )
            if not custody_service.is_custodian(session, user, location):
                raise PermissionDenied(
                    f"Only the custodian of {location['name']} may request a count adjustment",
                    code="NOT_LOCATION_CUSTODIAN",
                    details={"location_code": location["code"]},
                )
            reason = _clean(payload.reason)
            if not reason:
                raise ValidationFailed(
                    "A reason is required", code="FORM_VALIDATION_FAILED", details={"reason": []}
                )
            system_qty = repo.balance_for_update(session, payload.lot_id, payload.location_id)
            if payload.counted_qty == system_qty:
                raise ValidationFailed(
                    "The counted quantity equals the system quantity; nothing to adjust",
                    code="ADJUSTMENT_NO_DIFFERENCE",
                )
            if payload.counted_qty > system_qty:
                _assert_may_hold(lot, location)
            if repo.open_adjustment_exists(session, payload.lot_id, payload.location_id):
                raise Conflict(
                    "An adjustment for this lot and location is already awaiting approval",
                    code="ADJUSTMENT_ALREADY_OPEN",
                )
            adjustment_id = repo.insert_adjustment(
                session,
                lot_id=payload.lot_id,
                location_id=payload.location_id,
                system_qty=system_qty,
                counted_qty=payload.counted_qty,
                reason=reason,
                by=user.id,
            )
            roles = _setting_list(session, "stock_adjustment_approver_roles")
            notifications.publish(
                session,
                "STOCK_ADJUSTMENT_REQUESTED",
                role_codes=roles,
                notification_type="STOCK_ADJUSTMENT_REQUESTED",
                title=f"Stock count difference at {location['name']}",
                body=f"System {system_qty}, counted {payload.counted_qty}: {reason}",
                entity_type=ADJUSTMENT_ENTITY,
                entity_id=adjustment_id,
            )
            return _adjustment_out(
                _reload_adjustment(session, adjustment_id), user, _may_approve(session, user, perms)
            )

    def approve_adjustment(
        self,
        user: CurrentUser,
        perms: EffectivePermissions,
        adjustment_id: UUID,
        payload: AdjustmentDecisionIn,
        idem: IdempotencyKey,
    ) -> IdempotentResult:
        with self._uow.transaction(user.id) as session:

            def command() -> tuple[int, Any]:
                adj = _open_adjustment_for_decision(session, user, perms, adjustment_id)
                current = repo.balance_for_update(session, adj["lot_id"], adj["location_id"])
                if current != adj["system_qty"]:
                    raise Conflict(
                        "The stock changed since the count; reject this request and recount",
                        code="STOCK_CHANGED_SINCE_COUNT",
                        details={"system_qty": adj["system_qty"], "current_qty": current},
                    )
                from_loc, to_loc, qty = adjustment_movement(adj["location_id"], adj["delta"])
                movement_id = ledger_service.move_stock(
                    session,
                    lot_id=adj["lot_id"],
                    from_location_id=from_loc,
                    to_location_id=to_loc,
                    qty=qty,
                    movement_type="ADJUST",
                    reference_type=ADJUSTMENT_ENTITY,
                    reference_id=adjustment_id,
                    idempotency_key=f"stock-adjustment:{adjustment_id}",
                    actor_id=user.id,
                    reason=f"Count adjustment: {adj['reason']}",
                )
                repo.decide_adjustment(
                    session,
                    adjustment_id,
                    status="APPROVED",
                    by=user.id,
                    remarks=_clean(payload.remarks),
                    movement_id=movement_id,
                )
                _notify_requester(session, adj, "approved")
                row = _reload_adjustment(session, adjustment_id)
                return 200, _adjustment_out(row, user, approver=True)

            return run_idempotent(session, idem, user.id, command)

    def reject_adjustment(
        self,
        user: CurrentUser,
        perms: EffectivePermissions,
        adjustment_id: UUID,
        payload: AdjustmentRejectIn,
    ) -> AdjustmentOut:
        with self._uow.transaction(user.id) as session:
            adj = _open_adjustment_for_decision(session, user, perms, adjustment_id)
            remarks = _clean(payload.remarks)
            if not remarks:
                raise ValidationFailed(
                    "Remarks are required to reject",
                    code="FORM_VALIDATION_FAILED",
                    details={"remarks": []},
                )
            repo.decide_adjustment(
                session,
                adjustment_id,
                status="REJECTED",
                by=user.id,
                remarks=remarks,
                movement_id=None,
            )
            _notify_requester(session, adj, "rejected")
            return _adjustment_out(_reload_adjustment(session, adjustment_id), user, approver=True)


# =============================================================================================
# Nightly job (app.worker)
# =============================================================================================
def run_nightly_segregation_check(session: Session) -> int:
    """Record a NIGHTLY run; alert Super Admins + `segregation_alert_roles` on any violation."""
    violations = repo.segregation_violations(session)
    run_id = repo.insert_segregation_run(
        session, trigger_code="NIGHTLY", by=None, violations=violations
    )
    if violations:
        user_ids = set(
            notifications.active_user_ids_with_roles(
                session, _setting_list(session, "segregation_alert_roles")
            )
        )
        user_ids.update(repo.super_admin_ids(session))
        notifications.publish(
            session,
            "SEGREGATION_VIOLATION",
            user_ids=sorted(user_ids, key=str),
            notification_type="SEGREGATION_VIOLATION",
            title=f"Inventory segregation check: {len(violations)} violation(s)",
            body="; ".join(sorted({str(v["rule_code"]) for v in violations})),
            entity_type="segregation_check_run",
            entity_id=run_id,
            priority="HIGH",
        )
        log.warning("segregation_violations_found", count=len(violations), run_id=str(run_id))
    else:
        log.info("segregation_check_clean", run_id=str(run_id))
    return len(violations)


# =============================================================================================
# Helpers
# =============================================================================================
def _assignment_options(session: Session) -> list[OptionOut]:
    return [
        OptionOut(code=o.code, label=o.label, description=o.description)
        for o in custody_service.form_options(session, SEGREGATE_FORM, ASSIGNMENT_FIELD)
    ]


def _assignment_target(session: Session, code: str) -> dict[str, Any]:
    targets = repo.get_setting(session, "custody_assignment_targets")
    target_code = targets.get(code) if isinstance(targets, dict) else None
    target = repo.location_by_code(session, str(target_code)) if target_code else None
    if not target or not target["is_active"]:
        raise ServiceUnavailable(
            f"No active destination is configured for {code} (custody_assignment_targets)",
            code="CUSTODY_ASSIGNMENT_TARGET_MISSING",
        )
    if target["location_class"] != ASSIGNMENT_TARGET_CLASS[code]:
        # Configuration can relocate custody but never cross the functional boundary.
        raise SystemGuardViolation(
            "G-12",
            f"{code} cannot target {target['code']} ({target['location_class']})",
            details={"location_code": target["code"]},
        )
    return target


def _assignment_source(
    session: Session, lot: dict[str, Any], target: dict[str, Any], payload: AssignmentIn
) -> tuple[dict[str, Any], int]:
    positions = repo.lot_positions(session, payload.lot_id)
    by_id = {p["location_id"]: p for p in positions}
    if payload.from_location_id is not None:
        chosen = by_id.get(payload.from_location_id)
        if chosen is None:
            raise ValidationFailed(
                "The lot holds no stock at that location",
                code="CUSTODY_ASSIGNMENT_SOURCE_INVALID",
            )
    elif target["id"] in by_id and by_id[target["id"]]["qty"] >= payload.qty:
        chosen = by_id[target["id"]]
    else:
        candidates = [p for p in positions if p["location_class"] in ASSIGNABLE_SOURCE_CLASSES]
        if len(candidates) != 1:
            raise ValidationFailed(
                "Choose the location the stock is assigned from",
                code="CUSTODY_ASSIGNMENT_SOURCE_REQUIRED",
                details={"positions": [p["location_code"] for p in positions]},
            )
        chosen = candidates[0]
    if chosen["location_class"] not in ASSIGNABLE_SOURCE_CLASSES:
        raise ValidationFailed(
            f"Stock in {chosen['location_name']} is settled by its own flow (hold, transit or "
            "downstream), not by custody assignment",
            code="CUSTODY_ASSIGNMENT_SOURCE_INVALID",
            details={"location_code": chosen["location_code"]},
        )
    source = repo.location_by_id(session, chosen["location_id"])
    if source is None:
        raise NotFound("Location not found", code="LOCATION_NOT_FOUND")
    return source, int(chosen["qty"])


def _assert_may_hold(lot: dict[str, Any], location: dict[str, Any]) -> None:
    """Service half of G-04 / G-05 / G-12 for a positive adjustment (rms_move_stock repeats it)."""
    entity = SimpleNamespace(
        context={
            "condition_class": lot["condition_class"],
            "source_condition_code": lot["source_condition_code"],
            "target_location_class": location["location_class"],
        }
    )
    for guard_id, check in (("G-05", guard_g05), ("G-04", guard_g04), ("G-12", guard_g12)):
        if not check(entity, None):
            raise SystemGuardUnmet(
                guard_id,
                f"A {lot['condition_class']} lot cannot be held in {location['name']}",
                details={"location_code": location["code"]},
            )


def _open_adjustment_for_decision(
    session: Session, user: CurrentUser, perms: EffectivePermissions, adjustment_id: UUID
) -> dict[str, Any]:
    if not _may_approve(session, user, perms):
        raise PermissionDenied(
            "Only an adjustment approver (stock_adjustment_approver_roles) may decide",
            code="ADJUSTMENT_APPROVER_REQUIRED",
        )
    adj = repo.get_adjustment(session, adjustment_id, for_update=True)
    if not adj:
        raise NotFound("Stock adjustment not found", code="ADJUSTMENT_NOT_FOUND")
    if adj["condition_class"] == "SALVAGED" and not _can_see_parts(session, user):
        raise NotFound("Stock adjustment not found", code="ADJUSTMENT_NOT_FOUND")
    if adj["status"] != "REQUESTED":
        raise Conflict(
            f"This adjustment is already {adj['status']}",
            code="ADJUSTMENT_ALREADY_DECIDED",
            details={"status": adj["status"]},
        )
    if adj["requested_by"] == user.id:
        raise PermissionDenied(
            "Segregation of duties: the requester cannot decide their own adjustment",
            code="SEGREGATION_OF_DUTIES",
        )
    return adj


def _reload_adjustment(session: Session, adjustment_id: UUID) -> dict[str, Any]:
    row = repo.get_adjustment(session, adjustment_id)
    if row is None:
        raise NotFound("Stock adjustment not found", code="ADJUSTMENT_NOT_FOUND")
    return row


def _notify_requester(session: Session, adj: dict[str, Any], verb: str) -> None:
    notifications.publish(
        session,
        "STOCK_ADJUSTMENT_DECIDED",
        user_ids=[adj["requested_by"]],
        notification_type=f"STOCK_ADJUSTMENT_{verb.upper()}",
        title=f"Stock adjustment {verb} ({adj['location_name']})",
        body=f"Counted {adj['counted_qty']} vs system {adj['system_qty']}",
        entity_type=ADJUSTMENT_ENTITY,
        entity_id=adj["id"],
    )


def _adjustment_out(row: dict[str, Any], user: CurrentUser, approver: bool) -> AdjustmentOut:
    return AdjustmentOut(
        **row,
        can_decide=approver and row["status"] == "REQUESTED" and row["requested_by"] != user.id,
    )


def _can_see_parts(session: Session, user: CurrentUser) -> bool:
    """BR-30: salvaged parts only for `spare_parts_ledger_view_roles` (+ Super Admin)."""
    return user.is_super_admin or bool(
        set(_setting_list(session, "spare_parts_ledger_view_roles")) & user.role_codes
    )


def _may_approve(session: Session, user: CurrentUser, perms: EffectivePermissions) -> bool:
    if not perms.allows("inventory", "approve") and not user.is_super_admin:
        return False
    return user.is_super_admin or bool(
        set(_setting_list(session, "stock_adjustment_approver_roles")) & user.role_codes
    )


def _setting_list(session: Session, key: str) -> list[str]:
    value = repo.get_setting(session, key)
    return [str(v) for v in value] if isinstance(value, list) else []


def _refs(session: Session, table: str) -> list[RefOut]:
    return [RefOut(**r) for r in repo.simple_master(session, table)]


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None
