"""Product-specific inspection, not-allowed/hazard handling & extraction reconciliation (P2-05).

(master plan §2.2 Step-3, §3.2 DD r21-r43, BR-11..BR-17, G-04..G-07, DEC-07, DEC-09..DEC-14).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import (
    Conflict,
    NotFound,
    PermissionDenied,
    SystemGuardViolation,
    ValidationFailed,
)
from app.core.permissions import EffectivePermissions, assert_step_actor, step_codes_for
from app.core.security import CurrentUser
from app.modules.goods_slips import repository as gs_repo
from app.modules.goods_slips import service as gs_service
from app.modules.inspection import repository as repo
from app.modules.inspection.schemas import (
    AllocationOut,
    ConditionOption,
    ExtractionOut,
    FinaliseLineOut,
    InspectionDraftIn,
    InspectionGsOut,
    InspectionLineOut,
    InspectionPermissions,
    InspectionTotals,
    RejectionOut,
    ReopenIn,
    ReopenOut,
)
from app.modules.inventory import ledger_service
from app.modules.notifications import service as notifications_service

log = structlog.get_logger("rms.inspection")

INSPECT_STEP = "S1_INSPECT"
RM_STEP = "S1A_RM_ACTION"
ENTITY_TYPE = "goods_slip"

DEFAULT_ROUTING_TABLE = {
    "DMT_OK_PACKED": "SELLABLE",
    "PRS_OK": "SELLABLE",
    "EO_OK": "SELLABLE",
    "DMT_OK_PKG_DAMAGED": "REPACK_OR_TECH",
    "EO_INNER_CAPILLARY_BROKEN": "EVALUATE",
    "DMT_SCRATCHED": "TO_TECHNICIAN",
    "DMT_DIRTY": "TO_TECHNICIAN",
    "DMT_DISPLAY_ISSUE": "TO_TECHNICIAN",
}


def _check_inspect_permission(
    session: Session, user: CurrentUser, gs: dict[str, Any], perms: EffectivePermissions
) -> None:
    if user.is_super_admin:
        return

    if not (
        perms.allows("inspection", "edit")
        or perms.allows("inspection", "create")
        or perms.allows("goods_slips", "edit")
    ):
        raise PermissionDenied("You do not hold permission to perform inspection")

    assert_step_actor(session, user, INSPECT_STEP, "PERFORM")


def _check_reopen_permission(
    session: Session, user: CurrentUser, gs: dict[str, Any], perms: EffectivePermissions
) -> None:
    if user.is_super_admin:
        return

    is_rm_role = "REPLACEMENT_MANAGER" in user.role_codes
    if not (
        perms.allows("inspection", "approve") or perms.allows("workflow", "admin") or is_rm_role
    ):
        raise PermissionDenied(
            "Only the Replacement Manager or an administrator can reopen an inspection"
        )


def _versioned_condition_options(
    session: Session, item: dict[str, Any], form_version_id: UUID | None
) -> list[dict[str, Any]]:
    """Condition options with labels from the form version the inspection is pinned to (G-18).

    Codes, allowed status and behaviour stay those of the option set (guards key off codes);
    only the display label is taken from the frozen snapshot, so a relabel published later does
    not change what an in-flight GS shows. Without a pin, the currently published version applies.
    """
    set_id = item["condition_option_set_id"]
    options = repo.get_condition_options(session, set_id)
    version_id = form_version_id or repo.get_published_inspection_form_version(session, set_id)
    if version_id is None:
        return options
    labels = repo.get_form_version_option_labels(session, version_id, set_id)
    return [{**o, "label": labels.get(o["code"], o["label"])} for o in options]


def get_gs_inspection(
    session: Session, gs_id: UUID, user: CurrentUser, perms: EffectivePermissions
) -> InspectionGsOut:
    gs = repo.get_goods_slip(session, gs_id)
    if not gs:
        raise NotFound(f"Goods slip '{gs_id}' not found")

    items = repo.get_gs_items(session, gs_id)
    lines_out: list[InspectionLineOut] = []

    total_received = 0
    total_graded = 0
    total_rejected = 0
    total_hazard = 0
    lines_finalised = 0

    for item in items:
        gs_item_id = item["gs_item_id"]
        total_received += int(item["received_qty"])

        insp = repo.get_inspection_details(session, gs_item_id)
        options = _versioned_condition_options(
            session, item, insp["form_version_id"] if insp else None
        )
        cond_opts = [
            ConditionOption(
                code=o["code"],
                label=o["label"],
                allowed_status=o["allowed_status"],
                system_behavior=o["system_behavior"],
                rule_text=o["rule_text"],
                next_action_text=o["next_action_text"],
                remarks=o["remarks"],
                sort_order=o["sort_order"],
            )
            for o in options
        ]

        allocations: list[AllocationOut] = []
        if insp:
            raw_allocs = repo.get_allocations_for_inspection(session, insp["inspection_id"])
            for a in raw_allocs:
                allocations.append(
                    AllocationOut(
                        id=a["id"],
                        condition_code=a["condition_code"],
                        qty=a["qty"],
                        allowed_status=a["allowed_status"],
                        system_behavior=a["system_behavior"],
                        label=a["label"],
                    )
                )
                if a["system_behavior"] != "SHORT_QTY" and a["condition_code"] != "DMT_SHORT_QTY":
                    total_graded += int(a["qty"])

        raw_ext = repo.get_extraction_for_item(session, gs_item_id)
        ext_out = (
            ExtractionOut(
                id=raw_ext["id"],
                primary_type=raw_ext["primary_type"],
                packaging_qty=raw_ext["packaging_qty"],
                container_qty=raw_ext["container_qty"],
                reconciled=raw_ext["reconciled"],
            )
            if raw_ext
            else None
        )

        raw_rejs = repo.get_rejections_for_item(session, gs_item_id)
        rejs_out = [
            RejectionOut(
                id=r["id"],
                condition_code=r["condition_code"],
                qty=r["qty"],
                disposition=r["disposition"],
                hazard=r["hazard"],
                stock_movement_id=r["stock_movement_id"],
            )
            for r in raw_rejs
        ]
        for r in raw_rejs:
            total_rejected += int(r["qty"])
            if r["hazard"]:
                total_hazard += int(r["qty"])

        is_final = insp and insp["inspection_status"] == "FINAL"
        if is_final:
            lines_finalised += 1

        lines_out.append(
            InspectionLineOut(
                gs_item_id=gs_item_id,
                line_no=item["line_no"],
                product_id=item["product_id"],
                product_code=item["product_code"],
                product_name=item["product_name"],
                category_id=item["category_id"],
                category_code=item["category_code"],
                category_name=item["category_name"],
                documented_qty=item["documented_qty"],
                received_qty=item["received_qty"],
                short_qty=item["short_qty"],
                excess_qty=item["excess_qty"],
                requires_full_opening=bool(item["requires_full_opening"]),
                full_opening_confirmed=bool(insp["full_opening_confirmed"]) if insp else False,
                inspection_id=insp["inspection_id"] if insp else None,
                inspection_status=insp["inspection_status"] if insp else "PENDING",
                inspected_by=insp["inspected_by"] if insp else None,
                inspected_by_name=insp["inspected_by_name"] if insp else None,
                inspected_at=insp["inspected_at"] if insp else None,
                reopened_at=insp["reopened_at"] if insp else None,
                reopened_by_name=insp["reopened_by_name"] if insp else None,
                reopen_reason=insp["reopen_reason"] if insp else None,
                condition_options=cond_opts,
                allocations=allocations,
                extraction=ext_out,
                rejections=rejs_out,
            )
        )

    can_inspect = user.is_super_admin or (
        perms.allows("inspection", "edit")
        and INSPECT_STEP in step_codes_for(session, user, "PERFORM")
        and gs["status"] == "INSPECTION"
    )
    can_finalise = can_inspect
    is_rm = (
        user.is_super_admin
        or "REPLACEMENT_MANAGER" in user.role_codes
        or perms.allows("inspection", "approve")
    )
    can_reopen = is_rm and not repo.has_downstream_custody_transfer(session, gs_id)

    return InspectionGsOut(
        gs_id=gs["id"],
        gs_no=gs["gs_no"],
        status=gs["status"],
        category_code=gs.get("category_code"),
        has_hazard=bool(gs.get("has_hazard")),
        has_rejections=bool(gs.get("has_rejections")),
        lines=lines_out,
        totals=InspectionTotals(
            lines_count=len(items),
            lines_finalised=lines_finalised,
            total_received_qty=total_received,
            total_graded_qty=total_graded,
            total_rejected_qty=total_rejected,
            total_hazard_qty=total_hazard,
        ),
        permissions=InspectionPermissions(
            can_inspect=can_inspect,
            can_finalise=can_finalise,
            can_reopen=can_reopen,
        ),
    )


def save_draft_inspection(
    session: Session,
    gs_item_id: UUID,
    payload: InspectionDraftIn,
    user: CurrentUser,
    perms: EffectivePermissions,
) -> InspectionLineOut:
    item = repo.get_gs_item(session, gs_item_id)
    if not item:
        raise NotFound(f"Goods slip item '{gs_item_id}' not found")

    gs = repo.get_goods_slip(session, item["gs_id"])
    if not gs:
        raise NotFound(f"Goods slip for item '{gs_item_id}' not found")

    _check_inspect_permission(session, user, gs, perms)

    # Grading is recorded only while the GS is in INSPECTION (a CSR awaiting the RM decision
    # cannot be graded, G-03), and a finalised line changes only through an RM reopen (P2-08 fix).
    if gs["status"] != "INSPECTION":
        raise Conflict(
            f"Goods slip is in status '{gs['status']}', must be 'INSPECTION' to record grading"
        )
    current = repo.get_inspection_details(session, gs_item_id)
    if current and current["inspection_status"] == "FINAL":
        raise Conflict("This line is finalised; the Replacement Manager must reopen it first")

    # G-06 / BR-14: Enclosed Oval requires full opening confirmation
    has_allocations = any(a.qty > 0 for a in payload.allocations)
    is_eo = item["requires_full_opening"] or item["category_code"] == "ENCLOSED_OVAL"
    if is_eo and has_allocations and not payload.full_opening_confirmed:
        raise SystemGuardViolation(
            guard="G-06",
            message=(
                "Enclosed Oval grading cannot be submitted unless full_opening_confirmed = true"
            ),
        )

    # Upsert inspection in DRAFT, pinned to the published inspection form version (G-18)
    inspection_id = repo.upsert_inspection(
        session,
        gs_item_id=gs_item_id,
        full_opening_confirmed=payload.full_opening_confirmed,
        form_version_id=repo.get_published_inspection_form_version(
            session, item["condition_option_set_id"]
        ),
        inspected_by=user.id,
    )
    pinned = repo.get_inspection_details(session, gs_item_id)

    options = {
        o["code"]: o
        for o in _versioned_condition_options(
            session, item, pinned["form_version_id"] if pinned else None
        )
    }

    alloc_data: list[dict[str, Any]] = []
    for a in payload.allocations:
        if a.qty > 0:
            opt = options.get(a.condition_code)
            if not opt:
                raise ValidationFailed(
                    f"Unknown condition code '{a.condition_code}' for this product category"
                )
            alloc_data.append(
                {
                    "condition_code": a.condition_code,
                    "option_item_id": opt["id"],
                    "qty": a.qty,
                    "allowed_status_snapshot": opt["allowed_status"],
                    "system_behavior_snapshot": opt["system_behavior"],
                    "label_snapshot": opt["label"],
                }
            )

    repo.replace_allocations(session, inspection_id=inspection_id, allocations_data=alloc_data)

    if payload.extraction:
        repo.upsert_extraction_record(
            session,
            gs_item_id=gs_item_id,
            primary_type=payload.extraction.primary_type,
            packaging_qty=payload.extraction.packaging_qty,
            container_qty=payload.extraction.container_qty,
            reconciled=False,
            created_by=user.id,
        )

    insp = repo.get_inspection_details(session, gs_item_id)
    allocations = [
        AllocationOut(
            id=al["id"],
            condition_code=al["condition_code"],
            qty=al["qty"],
            allowed_status=al["allowed_status"],
            system_behavior=al["system_behavior"],
            label=al["label"],
        )
        for al in repo.get_allocations_for_inspection(session, inspection_id)
    ]
    raw_ext = repo.get_extraction_for_item(session, gs_item_id)
    ext_out = (
        ExtractionOut(
            id=raw_ext["id"],
            primary_type=raw_ext["primary_type"],
            packaging_qty=raw_ext["packaging_qty"],
            container_qty=raw_ext["container_qty"],
            reconciled=raw_ext["reconciled"],
        )
        if raw_ext
        else None
    )

    cond_opts = [
        ConditionOption(
            code=o["code"],
            label=o["label"],
            allowed_status=o["allowed_status"],
            system_behavior=o["system_behavior"],
            rule_text=o["rule_text"],
            next_action_text=o["next_action_text"],
            remarks=o["remarks"],
            sort_order=o["sort_order"],
        )
        for o in options.values()
    ]

    return InspectionLineOut(
        gs_item_id=gs_item_id,
        line_no=item["line_no"],
        product_id=item["product_id"],
        product_code=item["product_code"],
        product_name=item["product_name"],
        category_id=item["category_id"],
        category_code=item["category_code"],
        category_name=item["category_name"],
        documented_qty=item["documented_qty"],
        received_qty=item["received_qty"],
        short_qty=item["short_qty"],
        excess_qty=item["excess_qty"],
        requires_full_opening=bool(item["requires_full_opening"]),
        full_opening_confirmed=bool(insp["full_opening_confirmed"]) if insp else False,
        inspection_id=inspection_id,
        inspection_status=insp["inspection_status"] if insp else "DRAFT",
        inspected_by=insp["inspected_by"] if insp else None,
        inspected_by_name=insp["inspected_by_name"] if insp else None,
        inspected_at=insp["inspected_at"] if insp else None,
        condition_options=cond_opts,
        allocations=allocations,
        extraction=ext_out,
        rejections=[],
    )


def finalise_line_inspection(
    session: Session,
    gs_item_id: UUID,
    user: CurrentUser,
    perms: EffectivePermissions,
    idempotency_key: str | None = None,
) -> FinaliseLineOut:
    item = repo.get_gs_item(session, gs_item_id)
    if not item:
        raise NotFound(f"Goods slip item '{gs_item_id}' not found")

    gs = repo.get_goods_slip(session, item["gs_id"], for_update=True)
    if not gs:
        raise NotFound(f"Goods slip for item '{gs_item_id}' not found")

    _check_inspect_permission(session, user, gs, perms)

    if gs["status"] != "INSPECTION":
        raise Conflict(
            f"Goods slip is in status '{gs['status']}', must be 'INSPECTION' to finalise grading"
        )

    # Business rule toggle (DEC-08): if enabled, DMT lines cannot be finalised
    # unless today's container audit is confirmed
    is_dmt = item["category_code"] == "DMT"
    if is_dmt:
        setting_val = session.execute(
            text(
                "select value from public.system_settings "
                "where key = 'daily_audit_blocks_inspection'"
            )
        ).scalar_one_or_none()
        blocks = False
        if setting_val is not None:
            if isinstance(setting_val, bool):
                blocks = setting_val
            elif isinstance(setting_val, str):
                blocks = setting_val.lower() in ("true", "1")
            elif isinstance(setting_val, dict):
                blocks = bool(setting_val.get("value", False))
        if blocks:
            today_ist = datetime.now(ZoneInfo("Asia/Kolkata")).date()
            confirmed = session.execute(
                text("select confirmed from public.container_audit_days where audit_date = :dt"),
                {"dt": today_ist},
            ).scalar_one_or_none()
            if not confirmed:
                raise ValidationFailed(f"Daily container audit pending for {today_ist.isoformat()}")

    insp = repo.get_inspection_details(session, gs_item_id)
    if not insp:
        raise ValidationFailed(
            "No inspection draft found for this line. Save draft before finalising."
        )

    if insp["inspection_status"] == "FINAL":
        rejections = [
            RejectionOut(
                id=r["id"],
                condition_code=r["condition_code"],
                qty=r["qty"],
                disposition=r["disposition"],
                hazard=r["hazard"],
                stock_movement_id=r["stock_movement_id"],
            )
            for r in repo.get_rejections_for_item(session, gs_item_id)
        ]
        return FinaliseLineOut(
            gs_item_id=gs_item_id,
            status="FINAL",
            is_gs_finalised=(gs["status"] == "RM_REVIEW"),
            next_status=gs["status"],
            rejections=rejections,
        )

    # Guard G-06: EO full opening
    is_eo = item["requires_full_opening"] or item["category_code"] == "ENCLOSED_OVAL"
    if is_eo and not insp["full_opening_confirmed"]:
        raise SystemGuardViolation(
            guard="G-06",
            message=(
                "Enclosed Oval grading cannot be submitted unless full_opening_confirmed = true"
            ),
        )

    allocations = repo.get_allocations_for_inspection(session, insp["inspection_id"])
    if not allocations and item["received_qty"] > 0:
        raise ValidationFailed("No condition allocations entered for this line")

    # Guard G-07: Σ condition quantities = received quantity (excluding DMT_SHORT_QTY / SHORT_QTY)
    graded_sum = sum(
        int(a["qty"])
        for a in allocations
        if a["system_behavior"] != "SHORT_QTY" and a["condition_code"] != "DMT_SHORT_QTY"
    )
    if graded_sum != item["received_qty"]:
        raise SystemGuardViolation(
            guard="G-07",
            message=(
                f"Inspection finalisation requires sum of condition quantities ({graded_sum}) "
                f"to equal received quantity ({item['received_qty']})"
            ),
        )

    # Guard G-07: extraction reconciliation
    raw_ext = repo.get_extraction_for_item(session, gs_item_id)
    if not raw_ext:
        raise SystemGuardViolation(
            guard="G-07",
            message="Inspection finalisation requires an extraction record",
        )

    ext_sum = int(raw_ext["packaging_qty"]) + int(raw_ext["container_qty"])
    if ext_sum != item["received_qty"]:
        raise SystemGuardViolation(
            guard="G-07",
            message=(
                f"Inspection finalisation requires extraction total ({ext_sum}) "
                f"to equal received quantity ({item['received_qty']})"
            ),
        )

    # Mark extraction reconciled
    repo.upsert_extraction_record(
        session,
        gs_item_id=gs_item_id,
        primary_type=raw_ext["primary_type"],
        packaging_qty=raw_ext["packaging_qty"],
        container_qty=raw_ext["container_qty"],
        reconciled=True,
        created_by=user.id,
    )

    inward_loc = repo.get_location_by_code(session, "INWARD_STAGING")
    rejected_loc = repo.get_location_by_code(session, "REJECTED_HOLD")
    non_func_loc = repo.get_location_by_code(session, "NON_FUNCTIONAL_STORE")
    hazard_loc = repo.get_location_by_code(session, "HAZARD_QUARANTINE")

    if not inward_loc or not rejected_loc or not non_func_loc or not hazard_loc:
        raise ValidationFailed("Missing required warehouse inventory locations")

    initial_lot = repo.get_initial_lot_for_item(session, gs_item_id)
    if not initial_lot:
        lots = repo.get_lots_for_item(session, gs_item_id)
        if lots:
            initial_lot = lots[0]
        else:
            stock_item_id = ledger_service.create_stock_item(
                session,
                item_kind="FINISHED_GOOD",
                product_id=item["product_id"],
                created_by=user.id,
            )
            initial_lot_id = ledger_service.create_stock_lot(
                session,
                stock_item_id=stock_item_id,
                gs_id=gs["id"],
                gs_item_id=gs_item_id,
                condition_class="AS_RECEIVED",
                created_by=user.id,
            )
            ledger_service.move_stock(
                session,
                lot_id=initial_lot_id,
                from_location_id=None,
                to_location_id=inward_loc["id"],
                qty=item["received_qty"],
                movement_type="INWARD",
                reference_type=ENTITY_TYPE,
                reference_id=gs["id"],
                idempotency_key=f"{gs_item_id}:inward_fallback",
                actor_id=user.id,
                reason=f"Initial receipt for GS {gs['gs_no']} line {item['line_no']}",
            )
            initial_lot = {
                "id": initial_lot_id,
                "stock_item_id": stock_item_id,
                "gs_id": gs["id"],
                "gs_item_id": gs_item_id,
                "condition_class": "AS_RECEIVED",
            }

    routing_setting = repo.get_system_setting(session, "condition_routing_table")
    routing_table: dict[str, str] = DEFAULT_ROUTING_TABLE.copy()
    if routing_setting and isinstance(routing_setting, dict):
        routing_table.update(routing_setting)
    elif routing_setting and isinstance(routing_setting, str):
        try:
            parsed = json.loads(routing_setting)
            if isinstance(parsed, dict):
                routing_table.update(parsed)
        except json.JSONDecodeError:
            pass

    has_hazard_line = False
    has_rejection_line = False
    created_rejections: list[RejectionOut] = []
    lots_created: list[dict[str, Any]] = []

    for a in allocations:
        qty = int(a["qty"])
        if qty <= 0:
            continue

        cond_code = a["condition_code"]
        behavior = a.get("system_behavior") or ""

        # DEC-09: SHORT_QTY does not consume received pieces
        if behavior == "SHORT_QTY" or cond_code == "DMT_SHORT_QTY":
            continue

        # Disposition 1: HAZARD (PRS_BROKEN_WITH_HG, EO_BODY_BROKEN_HG)
        if behavior == "HAZARD" or cond_code in ("PRS_BROKEN_WITH_HG", "EO_BODY_BROKEN_HG"):
            has_hazard_line = True
            has_rejection_line = True

            hazard_lot_id = ledger_service.create_stock_lot(
                session,
                stock_item_id=initial_lot["stock_item_id"],
                gs_id=gs["id"],
                gs_item_id=gs_item_id,
                condition_class="HAZARD",
                source_condition_code=cond_code,
                routing_hint="EVALUATE",
                created_by=user.id,
            )
            lots_created.append({"lot_id": hazard_lot_id, "condition_class": "HAZARD", "qty": qty})

            m1 = ledger_service.move_stock(
                session,
                lot_id=initial_lot["id"],
                from_location_id=inward_loc["id"],
                to_location_id=hazard_loc["id"],
                qty=qty,
                movement_type="TRANSFER_OUT",
                reference_type="inspection",
                reference_id=gs_item_id,
                idempotency_key=f"{gs_item_id}:{cond_code}:hazard_trf",
                actor_id=user.id,
                reason=(
                    f"Hazardous mercury material quarantined for GS {gs['gs_no']} "
                    f"line {item['line_no']}"
                ),
            )
            ledger_service.reclassify_lot(
                session,
                source_lot_id=initial_lot["id"],
                target_lot_id=hazard_lot_id,
                location_id=hazard_loc["id"],
                qty=qty,
                reference_type="inspection",
                reference_id=gs_item_id,
                idempotency_key=f"{gs_item_id}:{cond_code}:hazard_reclass",
                actor_id=user.id,
                reason=f"Reclassified to HAZARD for GS {gs['gs_no']} line {item['line_no']}",
            )

            rej_id = repo.create_rejection(
                session,
                gs_item_id=gs_item_id,
                condition_code=cond_code,
                qty=qty,
                disposition="HAZARD_QUARANTINE",
                hazard=True,
                stock_movement_id=m1,
                created_by=user.id,
            )
            created_rejections.append(
                RejectionOut(
                    id=rej_id,
                    condition_code=cond_code,
                    qty=qty,
                    disposition="HAZARD_QUARANTINE",
                    hazard=True,
                    stock_movement_id=m1,
                )
            )

            # High-priority alert to RM, Spare Parts Manager, and safety recipients (DEC-11)
            notifications_service.publish(
                session,
                "HAZARD_DETECTED",
                role_codes=["REPLACEMENT_MANAGER", "SPARE_PARTS_MANAGER", "SUPER_ADMIN"],
                notification_type="MERCURY_HAZARD_ALERT",
                title="MERCURY HAZARD ALERT",
                body=(
                    f"Hazardous material ({a.get('label', cond_code)}) detected on GS "
                    f"{gs['gs_no']} line {item['line_no']} "
                    f"({qty} pcs quarantined in {hazard_loc['name']})"
                ),
                entity_type=ENTITY_TYPE,
                entity_id=gs["id"],
                gs_id=gs["id"],
                data={"gs_no": gs["gs_no"]},
                priority="HIGH",
            )

        # Disposition 2: REJECT_HOLD (DMT_OTHER_BRANDS) -> HOLD_PARTY_RETURN
        elif behavior == "REJECT_HOLD" or cond_code == "DMT_OTHER_BRANDS":
            has_rejection_line = True
            target_lot_id = ledger_service.create_stock_lot(
                session,
                stock_item_id=initial_lot["stock_item_id"],
                gs_id=gs["id"],
                gs_item_id=gs_item_id,
                condition_class="NOT_ALLOWED",
                source_condition_code=cond_code,
                created_by=user.id,
            )
            lots_created.append(
                {"lot_id": target_lot_id, "condition_class": "NOT_ALLOWED", "qty": qty}
            )

            ledger_service.reclassify_lot(
                session,
                source_lot_id=initial_lot["id"],
                target_lot_id=target_lot_id,
                location_id=inward_loc["id"],
                qty=qty,
                reference_type="inspection",
                reference_id=gs_item_id,
                idempotency_key=f"{gs_item_id}:{cond_code}:reclass",
                actor_id=user.id,
                reason=(
                    f"Reclassified not-allowed {cond_code} for GS {gs['gs_no']} "
                    f"line {item['line_no']}"
                ),
            )
            m_mov = ledger_service.move_stock(
                session,
                lot_id=target_lot_id,
                from_location_id=inward_loc["id"],
                to_location_id=rejected_loc["id"],
                qty=qty,
                movement_type="TRANSFER_OUT",
                reference_type="inspection",
                reference_id=gs_item_id,
                idempotency_key=f"{gs_item_id}:{cond_code}:relocate",
                actor_id=user.id,
                reason=(
                    f"Moved to REJECTED_HOLD for party return for GS {gs['gs_no']} "
                    f"line {item['line_no']}"
                ),
            )
            rej_id = repo.create_rejection(
                session,
                gs_item_id=gs_item_id,
                condition_code=cond_code,
                qty=qty,
                disposition="HOLD_PARTY_RETURN",
                hazard=False,
                stock_movement_id=m_mov,
                created_by=user.id,
            )
            created_rejections.append(
                RejectionOut(
                    id=rej_id,
                    condition_code=cond_code,
                    qty=qty,
                    disposition="HOLD_PARTY_RETURN",
                    hazard=False,
                    stock_movement_id=m_mov,
                )
            )

        # Disposition 3: TO_SPARE_PARTS (DMT_BROKEN_BODY) -> NON_FUNCTIONAL_STORE
        elif behavior == "TO_SPARE_PARTS" or cond_code == "DMT_BROKEN_BODY":
            has_rejection_line = True
            target_lot_id = ledger_service.create_stock_lot(
                session,
                stock_item_id=initial_lot["stock_item_id"],
                gs_id=gs["id"],
                gs_item_id=gs_item_id,
                condition_class="NOT_ALLOWED",
                source_condition_code=cond_code,
                created_by=user.id,
            )
            lots_created.append(
                {"lot_id": target_lot_id, "condition_class": "NOT_ALLOWED", "qty": qty}
            )

            ledger_service.reclassify_lot(
                session,
                source_lot_id=initial_lot["id"],
                target_lot_id=target_lot_id,
                location_id=inward_loc["id"],
                qty=qty,
                reference_type="inspection",
                reference_id=gs_item_id,
                idempotency_key=f"{gs_item_id}:{cond_code}:sp_reclass",
                actor_id=user.id,
                reason=(
                    f"Reclassified broken body {cond_code} for GS {gs['gs_no']} "
                    f"line {item['line_no']}"
                ),
            )
            m_mov = ledger_service.move_stock(
                session,
                lot_id=target_lot_id,
                from_location_id=inward_loc["id"],
                to_location_id=non_func_loc["id"],
                qty=qty,
                movement_type="TRANSFER_OUT",
                reference_type="inspection",
                reference_id=gs_item_id,
                idempotency_key=f"{gs_item_id}:{cond_code}:sp_relocate",
                actor_id=user.id,
                reason=(
                    f"Transferred broken body to NON_FUNCTIONAL_STORE for GS {gs['gs_no']} "
                    f"line {item['line_no']}"
                ),
            )
            rej_id = repo.create_rejection(
                session,
                gs_item_id=gs_item_id,
                condition_code=cond_code,
                qty=qty,
                disposition="TO_SPARE_PARTS",
                hazard=False,
                stock_movement_id=m_mov,
                created_by=user.id,
            )
            created_rejections.append(
                RejectionOut(
                    id=rej_id,
                    condition_code=cond_code,
                    qty=qty,
                    disposition="TO_SPARE_PARTS",
                    hazard=False,
                    stock_movement_id=m_mov,
                )
            )

        # Disposition 4: RECORDED_REJECT (PRS_BULB_BROKEN_NO_HG, EO_BULB_BROKEN_NO_HG)
        elif behavior == "REJECT_RECORD" or cond_code in (
            "PRS_BULB_BROKEN_NO_HG",
            "EO_BULB_BROKEN_NO_HG",
        ):
            has_rejection_line = True
            target_lot_id = ledger_service.create_stock_lot(
                session,
                stock_item_id=initial_lot["stock_item_id"],
                gs_id=gs["id"],
                gs_item_id=gs_item_id,
                condition_class="NOT_ALLOWED",
                source_condition_code=cond_code,
                created_by=user.id,
            )
            lots_created.append(
                {"lot_id": target_lot_id, "condition_class": "NOT_ALLOWED", "qty": qty}
            )

            ledger_service.reclassify_lot(
                session,
                source_lot_id=initial_lot["id"],
                target_lot_id=target_lot_id,
                location_id=inward_loc["id"],
                qty=qty,
                reference_type="inspection",
                reference_id=gs_item_id,
                idempotency_key=f"{gs_item_id}:{cond_code}:rr_reclass",
                actor_id=user.id,
                reason=(
                    f"Reclassified recorded reject {cond_code} for GS {gs['gs_no']} "
                    f"line {item['line_no']}"
                ),
            )
            m_mov = ledger_service.move_stock(
                session,
                lot_id=target_lot_id,
                from_location_id=inward_loc["id"],
                to_location_id=rejected_loc["id"],
                qty=qty,
                movement_type="TRANSFER_OUT",
                reference_type="inspection",
                reference_id=gs_item_id,
                idempotency_key=f"{gs_item_id}:{cond_code}:rr_relocate",
                actor_id=user.id,
                reason=(
                    f"Moved to REJECTED_HOLD as recorded reject for GS {gs['gs_no']} "
                    f"line {item['line_no']}"
                ),
            )
            rej_id = repo.create_rejection(
                session,
                gs_item_id=gs_item_id,
                condition_code=cond_code,
                qty=qty,
                disposition="RECORDED_REJECT",
                hazard=False,
                stock_movement_id=m_mov,
                created_by=user.id,
            )
            created_rejections.append(
                RejectionOut(
                    id=rej_id,
                    condition_code=cond_code,
                    qty=qty,
                    disposition="RECORDED_REJECT",
                    hazard=False,
                    stock_movement_id=m_mov,
                )
            )

        # Disposition 5: Allowed conditions (YES / CONDITIONAL)
        else:
            req_eval = cond_code == "EO_INNER_CAPILLARY_BROKEN"
            r_hint = (
                "EVALUATE"
                if req_eval
                else routing_table.get(
                    cond_code,
                    "TO_TECHNICIAN" if behavior == "TO_TECHNICIAN" else "SELLABLE",
                )
            )

            target_lot_id = ledger_service.create_stock_lot(
                session,
                stock_item_id=initial_lot["stock_item_id"],
                gs_id=gs["id"],
                gs_item_id=gs_item_id,
                condition_class="AS_RECEIVED",
                source_condition_code=cond_code,
                requires_evaluation=req_eval,
                routing_hint=r_hint,
                created_by=user.id,
            )
            lots_created.append(
                {"lot_id": target_lot_id, "condition_class": "AS_RECEIVED", "qty": qty}
            )

            ledger_service.reclassify_lot(
                session,
                source_lot_id=initial_lot["id"],
                target_lot_id=target_lot_id,
                location_id=inward_loc["id"],
                qty=qty,
                reference_type="inspection",
                reference_id=gs_item_id,
                idempotency_key=f"{gs_item_id}:{cond_code}:graded_reclass",
                actor_id=user.id,
                reason=f"Graded as {cond_code} for GS {gs['gs_no']} line {item['line_no']}",
            )

    repo.set_inspection_status_final(
        session, inspection_id=insp["inspection_id"], inspected_by=user.id
    )

    if created_rejections:
        # P4-03: REJECTION_RECORDED (rule seeded inactive). Context recipients: the roles that
        # perform the RM action step of the GS's pinned workflow (they decide the disposition).
        total_rejected = sum(r.qty for r in created_rejections)
        notifications_service.publish(
            session,
            "REJECTION_RECORDED",
            role_codes=gs_service.step_role_codes(session, gs, RM_STEP, "PERFORM"),
            title=f"{gs['gs_no']} line {item['line_no']}: {total_rejected} pc(s) rejected",
            body=", ".join(
                f"{r.condition_code} x{r.qty} -> {r.disposition}" for r in created_rejections
            ),
            entity_type=ENTITY_TYPE,
            entity_id=gs["id"],
            gs_id=gs["id"],
            data={"gs_no": gs["gs_no"]},
            dedupe_key=f"rejection:{created_rejections[0].id}",
        )

    new_hazard = bool(gs.get("has_hazard")) or has_hazard_line
    new_rejections = bool(gs.get("has_rejections")) or has_rejection_line
    repo.update_gs_flags(
        session, gs_id=gs["id"], has_hazard=new_hazard, has_rejections=new_rejections
    )

    all_items = repo.get_gs_items(session, gs["id"])
    all_final = True
    for it in all_items:
        it_insp = repo.get_inspection_details(session, it["gs_item_id"])
        if not it_insp or it_insp["inspection_status"] != "FINAL":
            all_final = False
            break

    next_status = gs["status"]
    if all_final:
        gs_service.transition_gs(
            session,
            gs_id=gs["id"],
            to_status="RM_REVIEW",
            step_code=RM_STEP,
            user=user,
            reason="All lines finalised in Step-3 visual inspection & extraction reconciliation",
            actor_step_code=INSPECT_STEP,
            context_overrides={
                "eo_full_opening_confirmed": True,
                "inspection_reconciled": True,
            },
        )
        next_status = "RM_REVIEW"

    return FinaliseLineOut(
        gs_item_id=gs_item_id,
        status="FINAL",
        is_gs_finalised=all_final,
        next_status=next_status,
        rejections=created_rejections,
        lots_created=lots_created,
    )


def finalise_all(
    session: Session,
    gs_id: UUID,
    user: CurrentUser,
    perms: EffectivePermissions,
    idempotency_key: str | None = None,
) -> InspectionGsOut:
    gs = repo.get_goods_slip(session, gs_id, for_update=True)
    if not gs:
        raise NotFound(f"Goods slip '{gs_id}' not found")

    items = repo.get_gs_items(session, gs_id)
    for it in items:
        finalise_line_inspection(session, it["gs_item_id"], user, perms)

    return get_gs_inspection(session, gs_id, user, perms)


def reopen_inspection(
    session: Session,
    gs_item_id: UUID,
    payload: ReopenIn,
    user: CurrentUser,
    perms: EffectivePermissions,
) -> ReopenOut:
    item = repo.get_gs_item(session, gs_item_id)
    if not item:
        raise NotFound(f"Goods slip item '{gs_item_id}' not found")

    gs = repo.get_goods_slip(session, item["gs_id"], for_update=True)
    if not gs:
        raise NotFound(f"Goods slip for item '{gs_item_id}' not found")

    _check_reopen_permission(session, user, gs, perms)

    insp = repo.get_inspection_details(session, gs_item_id)
    if not insp:
        raise NotFound(f"No inspection found for line '{gs_item_id}'")

    if insp["inspection_status"] != "FINAL":
        raise Conflict("Cannot reopen an inspection that is not finalised")

    if repo.has_downstream_custody_transfer(session, gs["id"]):
        raise Conflict(
            "Cannot reopen inspection: custody transfer already exists for this goods slip"
        )

    initial_lot = repo.get_initial_lot_for_item(session, gs_item_id)
    if initial_lot:
        inward_loc = repo.get_location_by_code(session, "INWARD_STAGING")
        rejected_loc = repo.get_location_by_code(session, "REJECTED_HOLD")
        non_func_loc = repo.get_location_by_code(session, "NON_FUNCTIONAL_STORE")
        hazard_loc = repo.get_location_by_code(session, "HAZARD_QUARANTINE")

        rejections = repo.get_rejections_for_item(session, gs_item_id)
        for r in rejections:
            if r["hazard"] and hazard_loc and inward_loc:
                hazard_lots = [
                    lot
                    for lot in repo.get_lots_for_item(session, gs_item_id)
                    if lot["condition_class"] == "HAZARD"
                    and lot["source_condition_code"] == r["condition_code"]
                ]
                for hl in hazard_lots:
                    bal = ledger_service.get_balance(session, hl["id"], hazard_loc["id"])
                    if bal > 0:
                        reopen_idem = f"{gs_item_id}:{r['condition_code']}:reopen_hazard_reclass"
                        ledger_service.reclassify_lot(
                            session,
                            source_lot_id=hl["id"],
                            target_lot_id=initial_lot["id"],
                            location_id=hazard_loc["id"],
                            qty=bal,
                            reference_type="inspection_reversal",
                            reference_id=gs_item_id,
                            idempotency_key=reopen_idem,
                            actor_id=user.id,
                            reason=f"Compensating reclassify: {payload.reason}",
                        )
                        ledger_service.move_stock(
                            session,
                            lot_id=initial_lot["id"],
                            from_location_id=hazard_loc["id"],
                            to_location_id=inward_loc["id"],
                            qty=bal,
                            movement_type="TRANSFER_OUT",
                            reference_type="inspection_reversal",
                            reference_id=gs_item_id,
                            idempotency_key=f"{gs_item_id}:{r['condition_code']}:reopen_hazard_move",
                            actor_id=user.id,
                            reason=f"Compensating move on inspection reopen: {payload.reason}",
                        )

            elif r["disposition"] == "HOLD_PARTY_RETURN" and rejected_loc and inward_loc:
                rej_lots = [
                    lot
                    for lot in repo.get_lots_for_item(session, gs_item_id)
                    if lot["condition_class"] == "NOT_ALLOWED"
                    and lot["source_condition_code"] == r["condition_code"]
                ]
                for rl in rej_lots:
                    bal = ledger_service.get_balance(session, rl["id"], rejected_loc["id"])
                    if bal > 0:
                        ledger_service.move_stock(
                            session,
                            lot_id=rl["id"],
                            from_location_id=rejected_loc["id"],
                            to_location_id=inward_loc["id"],
                            qty=bal,
                            movement_type="TRANSFER_OUT",
                            reference_type="inspection_reversal",
                            reference_id=gs_item_id,
                            idempotency_key=f"{gs_item_id}:{r['condition_code']}:reopen_rej_move",
                            actor_id=user.id,
                            reason=f"Compensating move on inspection reopen: {payload.reason}",
                        )
                        reopen_rej_idem = f"{gs_item_id}:{r['condition_code']}:reopen_rej_reclass"
                        ledger_service.reclassify_lot(
                            session,
                            source_lot_id=rl["id"],
                            target_lot_id=initial_lot["id"],
                            location_id=inward_loc["id"],
                            qty=bal,
                            reference_type="inspection_reversal",
                            reference_id=gs_item_id,
                            idempotency_key=reopen_rej_idem,
                            actor_id=user.id,
                            reason=f"Compensating reclassify: {payload.reason}",
                        )

            elif r["disposition"] == "TO_SPARE_PARTS" and non_func_loc and inward_loc:
                sp_lots = [
                    lot
                    for lot in repo.get_lots_for_item(session, gs_item_id)
                    if lot["condition_class"] == "NOT_ALLOWED"
                    and lot["source_condition_code"] == r["condition_code"]
                ]
                for sl in sp_lots:
                    bal = ledger_service.get_balance(session, sl["id"], non_func_loc["id"])
                    if bal > 0:
                        ledger_service.move_stock(
                            session,
                            lot_id=sl["id"],
                            from_location_id=non_func_loc["id"],
                            to_location_id=inward_loc["id"],
                            qty=bal,
                            movement_type="TRANSFER_OUT",
                            reference_type="inspection_reversal",
                            reference_id=gs_item_id,
                            idempotency_key=f"{gs_item_id}:{r['condition_code']}:reopen_sp_move",
                            actor_id=user.id,
                            reason=f"Compensating move on inspection reopen: {payload.reason}",
                        )
                        reopen_sp_idem = f"{gs_item_id}:{r['condition_code']}:reopen_sp_reclass"
                        ledger_service.reclassify_lot(
                            session,
                            source_lot_id=sl["id"],
                            target_lot_id=initial_lot["id"],
                            location_id=inward_loc["id"],
                            qty=bal,
                            reference_type="inspection_reversal",
                            reference_id=gs_item_id,
                            idempotency_key=reopen_sp_idem,
                            actor_id=user.id,
                            reason=f"Compensating reclassify: {payload.reason}",
                        )

        if inward_loc:
            graded_lots = [
                lot
                for lot in repo.get_lots_for_item(session, gs_item_id)
                if lot["condition_class"] == "AS_RECEIVED"
                and lot["source_condition_code"] is not None
            ]
            for gl in graded_lots:
                bal = ledger_service.get_balance(session, gl["id"], inward_loc["id"])
                if bal > 0:
                    ledger_service.reclassify_lot(
                        session,
                        source_lot_id=gl["id"],
                        target_lot_id=initial_lot["id"],
                        location_id=inward_loc["id"],
                        qty=bal,
                        reference_type="inspection_reversal",
                        reference_id=gs_item_id,
                        idempotency_key=f"{gs_item_id}:{gl['id']}:reopen_graded_reclass",
                        actor_id=user.id,
                        reason=f"Compensating reclassify on inspection reopen: {payload.reason}",
                    )

    repo.delete_rejections_for_item(session, gs_item_id)

    repo.reopen_inspection_db(
        session,
        inspection_id=insp["inspection_id"],
        reopened_by=user.id,
        reopen_reason=payload.reason,
    )

    if gs["status"] == "RM_REVIEW":
        gs_repo.update_gs_status(session, gs["id"], "INSPECTION")
        gs_repo.record_status_history(
            session,
            gs_id=gs["id"],
            from_status="RM_REVIEW",
            to_status="INSPECTION",
            step_code=INSPECT_STEP,
            reason=f"Inspection reopened by RM: {payload.reason}",
            by_user_id=user.id,
        )
        gs_repo.complete_open_tasks(session, gs["id"])
        wf = gs_service.pinned_workflow_snapshot(session, gs)
        step_meta = next((s for s in wf.get("steps", []) if s.get("code") == INSPECT_STEP), None)
        if step_meta:
            for assignment in step_meta.get("assignments", []):
                if assignment.get("assignment_type", "PERFORM") == "PERFORM":
                    gs_repo.create_workflow_task(
                        session,
                        gs_id=gs["id"],
                        step_code=INSPECT_STEP,
                        assigned_role_id=UUID(assignment["role_id"])
                        if assignment.get("role_id")
                        else None,
                        assigned_user_id=UUID(assignment["user_id"])
                        if assignment.get("user_id")
                        else None,
                    )

    has_any_hazard = False
    has_any_rejections = False
    for it in repo.get_gs_items(session, gs["id"]):
        it_rejs = repo.get_rejections_for_item(session, it["gs_item_id"])
        if it_rejs:
            has_any_rejections = True
            if any(r["hazard"] for r in it_rejs):
                has_any_hazard = True
    repo.update_gs_flags(
        session, gs_id=gs["id"], has_hazard=has_any_hazard, has_rejections=has_any_rejections
    )

    insp_after = repo.get_inspection_details(session, gs_item_id)
    reopened_at = datetime.now(UTC)
    if insp_after and insp_after.get("reopened_at"):
        reopened_at = insp_after["reopened_at"]
    return ReopenOut(
        gs_item_id=gs_item_id,
        status="DRAFT",
        reopened_at=reopened_at,
    )
