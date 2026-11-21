"""RM Review business logic (AMD-12, AMD-13, G-19)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog
from sqlalchemy.orm import Session

from app.core.db import UnitOfWork
from app.core.errors import (
    Conflict,
    NotFound,
    PermissionDenied,
    SystemGuardViolation,
    ValidationFailed,
)
from app.core.idempotency import IdempotencyKey, IdempotentResult, run_idempotent
from app.core.permissions import EffectivePermissions
from app.core.security import CurrentUser
from app.modules.custody import service as custody_service
from app.modules.custody.schemas import TransferLineIn
from app.modules.goods_slips import service as gs_service
from app.modules.inventory import ledger_service
from app.modules.itemization import repository as item_repo
from app.modules.itemization import service as item_service
from app.modules.itemization.schemas import (
    ItemBucketOut,
    ItemCountOut,
)
from app.modules.notifications import service as notifications
from app.modules.rm_review import repository as repo
from app.modules.rm_review.schemas import (
    RmApproveIn,
    RmApproveOut,
    RmReviewCartonVideoOut,
    RmReviewDataOut,
    RmReviewDocumentOut,
    RmReviewHeaderOut,
    RmReviewItemOut,
    RmReviewRevisionOut,
    RmSendBackIn,
    TransferSlipSummaryOut,
)

log = structlog.get_logger("rms.rm_review")

RM_ROLE = "REPLACEMENT_MANAGER"
INWARD_LOCATION = "INWARD_STAGING"
INTERMEDIATE_LOCATION = "INTERMEDIATE_STORE"
RM_REVIEW_STATUS = "RM_REVIEW"
CATEGORISATION_STATUS = "CATEGORISATION"


class RmReviewService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    def _assert_rm_or_admin(self, user: CurrentUser, perms: EffectivePermissions) -> None:
        if user.is_super_admin:
            return
        if RM_ROLE in user.role_codes:
            return
        if perms.allows("itemization", "approve"):
            return
        raise PermissionDenied("Only a Replacement Manager may review goods slips (AMD-12)")

    def get_review_data(
        self,
        user: CurrentUser,
        perms: EffectivePermissions,
        gs_id: UUID,
    ) -> RmReviewDataOut:
        with self._uow.transaction(user.id) as session:
            gs_service.get_visible_goods_slip(session, user, perms, gs_id)
            header_dict = repo.get_rm_review_header(session, gs_id)
            if not header_dict:
                raise NotFound(f"Goods slip {gs_id} not found", code="GS_NOT_FOUND")

            header = RmReviewHeaderOut.model_validate(header_dict)
            docs = [
                RmReviewDocumentOut.model_validate(d)
                for d in repo.get_rm_review_documents(session, gs_id)
            ]
            videos = [
                RmReviewCartonVideoOut.model_validate(v)
                for v in repo.get_carton_videos(session, gs_id)
            ]

            items_raw = item_repo.list_items(session, gs_id)
            item_ids = [i["id"] for i in items_raw]
            buckets_raw = item_repo.get_buckets_for_items(session, item_ids)
            counts_raw = item_repo.get_counts_for_items(session, item_ids)

            b_by_item: dict[UUID, list[ItemBucketOut]] = {iid: [] for iid in item_ids}
            for b in buckets_raw:
                b_by_item.setdefault(b["gs_item_id"], []).append(
                    ItemBucketOut(
                        id=b["id"],
                        item_id=b["gs_item_id"],
                        field_code=b["field_code"],
                        field_label=b.get("label_snapshot") or b["field_code"],
                        qty=b["qty"],
                    )
                )

            c_by_item: dict[UUID, list[ItemCountOut]] = {iid: [] for iid in item_ids}
            for c in counts_raw:
                c_by_item.setdefault(c["gs_item_id"], []).append(
                    ItemCountOut(
                        id=c["id"],
                        item_id=c["gs_item_id"],
                        count_type=c["field_code"],
                        field_label=c.get("label_snapshot") or c["field_code"],
                        count_value=c["qty"],
                    )
                )

            items_out: list[RmReviewItemOut] = []
            all_conserved = bool(items_raw)
            version_id = item_repo.get_profile_version_id(session, gs_id)
            for it in items_raw:
                fields = item_service.resolve_item_fields(session, it["product_id"], version_id)
                sku_code, sku_name = item_service.item_display(it)

                b_list = b_by_item.get(it["id"], [])
                tot_b = sum(b.qty for b in b_list)
                is_cons = tot_b == it["received_qty"]
                if not is_cons:
                    all_conserved = False

                items_out.append(
                    RmReviewItemOut(
                        item_id=it["id"],
                        product_id=it["product_id"],
                        sku_code=sku_code,
                        sku_name=sku_name,
                        documented_qty=it["documented_qty"],
                        received_qty=it["received_qty"],
                        short_qty=it.get(
                            "short_qty", max(0, it["documented_qty"] - it["received_qty"])
                        ),
                        excess_qty=it.get(
                            "excess_qty", max(0, it["received_qty"] - it["documented_qty"])
                        ),
                        allowed_buckets=fields.buckets,
                        allowed_counts=fields.counts,
                        buckets=b_list,
                        total_bucket_qty=tot_b,
                        is_conserved=is_cons,
                        counts=c_by_item.get(it["id"], []),
                    )
                )

            revisions = [
                RmReviewRevisionOut.model_validate(r) for r in repo.get_revisions(session, gs_id)
            ]

            transfer_slip = None
            if header_dict.get("transfer_slip_id"):
                ts = repo.get_transfer_slip_summary(session, header_dict["transfer_slip_id"])
                if ts:
                    transfer_slip = TransferSlipSummaryOut.model_validate(ts)

            can_rev = (
                (
                    user.is_super_admin
                    or RM_ROLE in user.role_codes
                    or perms.allows("itemization", "approve")
                )
                and header_dict["status"] == RM_REVIEW_STATUS
                and not header_dict.get("transfer_slip_id")
            )

            return RmReviewDataOut(
                goods_slip=header,
                documents=docs,
                carton_videos=videos,
                items=items_out,
                revisions=revisions,
                transfer_slip=transfer_slip,
                all_conserved=all_conserved,
                can_review=can_rev,
            )

    def send_back(
        self,
        user: CurrentUser,
        perms: EffectivePermissions,
        gs_id: UUID,
        payload: RmSendBackIn,
        idem: IdempotencyKey,
    ) -> IdempotentResult:
        with self._uow.transaction(user.id) as session:
            return run_idempotent(
                session,
                idem,
                user.id,
                lambda: (200, self._send_back(session, user, perms, gs_id, payload)),
            )

    def _send_back(
        self,
        session: Session,
        user: CurrentUser,
        perms: EffectivePermissions,
        gs_id: UUID,
        payload: RmSendBackIn,
    ) -> dict[str, Any]:
        self._assert_rm_or_admin(user, perms)
        gs = gs_service.lock_goods_slip(session, gs_id)
        if gs["status"] != RM_REVIEW_STATUS:
            raise Conflict("Goods slip must be in RM_REVIEW to send back", code="INVALID_STATUS")
        if gs.get("transfer_slip_id"):
            raise Conflict(
                "Goods slip cannot be sent back once transfer slip is generated",
                code="TRANSFER_SLIP_EXISTS",
            )

        rev_no = repo.get_next_revision_no(session, gs_id)
        all_items = item_repo.list_items(session, gs_id)
        all_buckets = item_repo.get_buckets_for_items(session, [i["id"] for i in all_items])
        snapshot = [
            {
                "item_id": str(i["id"]),
                "sku_code": item_service.item_display(i)[0],
                "sku_name": item_service.item_display(i)[1],
                "documented_qty": i["documented_qty"],
                "received_qty": i["received_qty"],
                "buckets": [
                    {"code": b["field_code"], "label": b["label_snapshot"], "qty": b["qty"]}
                    for b in all_buckets
                    if b["gs_item_id"] == i["id"]
                ],
            }
            for i in all_items
        ]
        repo.insert_revision(
            session,
            gs_id=gs_id,
            revision_no=rev_no,
            action="RM_SENT_BACK",
            items_snapshot=snapshot,
            remarks=payload.remarks,
            created_by=user.id,
        )

        gs_service.change_status_within_step(
            session,
            gs_id=gs_id,
            from_status=RM_REVIEW_STATUS,
            to_status=CATEGORISATION_STATUS,
            step_code="S1_ITEMIZE",
            reason=f"RM sent back to categorisation: {payload.remarks} (AMD-12)",
            by=user.id,
        )

        # Notify Inward Verifier
        verifier_ids = [gs["counted_by"]] if gs.get("counted_by") else []
        notifications.publish(
            session,
            "CATEGORISATION_SENT_BACK",
            user_ids=verifier_ids,
            role_codes=["INWARD_VERIFIER"] if not verifier_ids else [],
            notification_type="CATEGORISATION_SENT_BACK",
            title=f"{gs['gs_no']}: Sent back by Replacement Manager",
            body=payload.remarks,
            entity_type="goods_slips",
            entity_id=gs_id,
            gs_id=gs_id,
            priority="HIGH",
        )

        log.info("rm_review_sent_back", gs_id=str(gs_id), revision_no=rev_no)
        return {
            "goods_slip_id": str(gs_id),
            "status": CATEGORISATION_STATUS,
            "message": "Sent back to categorisation",
        }

    def approve(
        self,
        user: CurrentUser,
        perms: EffectivePermissions,
        gs_id: UUID,
        payload: RmApproveIn,
        idem: IdempotencyKey,
    ) -> IdempotentResult:
        with self._uow.transaction(user.id) as session:
            return run_idempotent(
                session,
                idem,
                user.id,
                lambda: (200, self._approve(session, user, perms, gs_id, payload)),
            )

    def _approve(
        self,
        session: Session,
        user: CurrentUser,
        perms: EffectivePermissions,
        gs_id: UUID,
        payload: RmApproveIn,
    ) -> RmApproveOut:
        self._assert_rm_or_admin(user, perms)
        gs = gs_service.lock_goods_slip(session, gs_id)
        if gs["status"] != RM_REVIEW_STATUS:
            raise Conflict("Goods slip must be in RM_REVIEW to approve", code="INVALID_STATUS")
        if gs.get("transfer_slip_id"):
            raise Conflict(
                "Goods slip has already been approved (transfer slip generated)",
                code="ALREADY_APPROVED",
            )

        items = item_repo.list_items(session, gs_id)
        if not items:
            raise ValidationFailed("At least one item line is required", code="ITEMS_REQUIRED")

        item_ids = [i["id"] for i in items]
        buckets = item_repo.get_buckets_for_items(session, item_ids)
        b_sum_by_item: dict[UUID, int] = {iid: 0 for iid in item_ids}
        for b in buckets:
            b_sum_by_item[b["gs_item_id"]] = b_sum_by_item.get(b["gs_item_id"], 0) + b["qty"]

        # Validate G-19 bucket conservation
        transfer_lines: list[TransferLineIn] = []
        for it in items:
            recv = it["received_qty"]
            b_sum = b_sum_by_item.get(it["id"], 0)
            if b_sum != recv:
                raise SystemGuardViolation(
                    "G-19",
                    f"Item {item_service.item_display(it)[0]} bucket total ({b_sum}) does not "
                    f"match counted quantity ({recv}) (G-19)",
                    details={"item_id": str(it["id"]), "received_qty": recv, "bucket_total": b_sum},
                )
            if recv > 0:
                lot_id = ledger_service.find_inward_lot(session, it["id"])
                inward_loc = ledger_service.get_location_by_code(session, INWARD_LOCATION)
                if not inward_loc:
                    raise NotFound(
                        f"Location {INWARD_LOCATION} not found", code="LOCATION_NOT_FOUND"
                    )
                if not lot_id:
                    # Inward lot if not yet created (DEC-54: stock booked at RM approval)
                    stock_item = ledger_service.finished_good_item(
                        session, it["product_id"], user.id
                    )
                    lot_id = ledger_service.create_stock_lot(
                        session,
                        stock_item_id=stock_item,
                        gs_id=gs_id,
                        gs_item_id=it["id"],
                        condition_class="AS_RECEIVED",
                        created_by=user.id,
                    )
                    ledger_service.move_stock(
                        session,
                        lot_id=lot_id,
                        from_location_id=None,
                        to_location_id=inward_loc["id"],
                        movement_type="INWARD",
                        qty=recv,
                        reference_type="gs_items",
                        reference_id=it["id"],
                        idempotency_key=f"{it['id']}:inward",
                        actor_id=user.id,
                        reason="Inward staging",
                    )
                else:
                    # Legacy GS already in RM_REVIEW with stock keep working (existing lot reused)
                    balance = ledger_service.get_balance(session, lot_id, inward_loc["id"])
                    if balance != recv:
                        delta = recv - balance
                        ledger_service.move_stock(
                            session,
                            lot_id=lot_id,
                            from_location_id=inward_loc["id"] if delta < 0 else None,
                            to_location_id=None if delta < 0 else inward_loc["id"],
                            movement_type="ADJUST",
                            qty=abs(delta),
                            reference_type="gs_items",
                            reference_id=it["id"],
                            idempotency_key=f"{it['id']}:rm_approve_adjust:{recv}",
                            actor_id=user.id,
                            reason=f"Legacy lot balance adjusted to match received qty {recv}",
                        )
                transfer_lines.append(TransferLineIn(lot_id=lot_id, qty=recv))

        if not transfer_lines:
            raise ValidationFailed("No stock lots available to transfer", code="NO_TRANSFER_LINES")

        rem_s = f": {payload.remarks}" if payload.remarks else ""
        # Auto-generate custody transfer slip handing goods to INTERMEDIATE_STORE
        transfer_id = custody_service.initiate_transfer(
            session,
            actor=user,
            from_location_code=INWARD_LOCATION,
            to_location_code=INTERMEDIATE_LOCATION,
            lines=transfer_lines,
            gs_id=gs_id,
            purpose_code="HANDOVER_TO_INTERMEDIATE_STORE",
            notes=f"Auto-generated on RM Review approval (AMD-13){rem_s}",
            check_custodian=False,
        )

        repo.set_gs_transfer_slip_id(session, gs_id, transfer_id)
        transfer_row = repo.get_transfer_slip_summary(session, transfer_id)
        transfer_no = transfer_row["transfer_no"] if transfer_row else str(transfer_id)

        # Record revision in rm_review_revisions
        rev_no = repo.get_next_revision_no(session, gs_id)
        snapshot = [
            {
                "item_id": str(i["id"]),
                "sku_code": item_service.item_display(i)[0],
                "sku_name": item_service.item_display(i)[1],
                "documented_qty": i["documented_qty"],
                "received_qty": i["received_qty"],
                "buckets": [
                    {"code": b["field_code"], "label": b["label_snapshot"], "qty": b["qty"]}
                    for b in buckets
                    if b["gs_item_id"] == i["id"]
                ],
            }
            for i in items
        ]
        repo.insert_revision(
            session,
            gs_id=gs_id,
            revision_no=rev_no,
            action="RM_APPROVED",
            items_snapshot=snapshot,
            remarks=payload.remarks or f"RM Approved. Transfer slip {transfer_no} generated.",
            created_by=user.id,
        )

        # Notify Intermediate Store Manager
        notifications.publish(
            session,
            "TRANSFER_AWAITING_ACCEPTANCE",
            role_codes=["INTERMEDIATE_STORE_MANAGER"],
            notification_type="TRANSFER_AWAITING_ACCEPTANCE",
            title=f"Transfer {transfer_no} ready for acceptance",
            body=(
                f"Goods slip {gs['gs_no']} approved by RM. "
                f"Transfer slip {transfer_no} waiting for receipt count at Intermediate Store."
            ),
            entity_type="custody_transfers",
            entity_id=transfer_id,
            gs_id=gs_id,
            priority="HIGH",
        )

        log.info(
            "rm_review_approved",
            gs_id=str(gs_id),
            transfer_id=str(transfer_id),
            transfer_no=transfer_no,
        )
        return RmApproveOut(
            goods_slip_id=gs_id,
            status=gs["status"],
            transfer_id=transfer_id,
            transfer_no=transfer_no,
            message=(
                f"RM Review approved. Transfer slip {transfer_no} "
                "generated and sent to Intermediate Store."
            ),
        )
