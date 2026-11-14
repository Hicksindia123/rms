"""Service for Step-3 a) RM item-wise actions and Replacement Slip.

Master plan references: WF r6, BR-19, BR-20, G-08, DEC-12, DEC-13, DEC-33.
"""

from datetime import datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import UnitOfWork
from app.core.errors import (
    Conflict,
    NotFound,
    PermissionDenied,
    SystemGuardViolation,
    ValidationFailed,
)
from app.core.permissions import EffectivePermissions
from app.core.security import CurrentUser
from app.modules.inventory import ledger_service
from app.modules.notifications import service as notifications
from app.modules.rm_actions import repository as repo
from app.modules.rm_actions.schemas import (
    LineDispatchedDetail,
    LineOutcomeDetail,
    PendencyDetailInput,
    ReplacementSlipLine,
    ReplacementSlipResponse,
    ResolutionBoardLineOut,
    ResolutionBoardResponse,
    RmActionAllocationOut,
    RmActionLineOut,
    RmActionOptionOut,
    RmActionRevisionOut,
    RmActionsResponse,
    SaveRmActionsRequest,
)

EARLY_STATUSES = {
    "DRAFT",
    "GATE_INWARD",
    "UNBOXING",
    "ITEMIZATION",
    "CATEGORISATION",  # AMD-08
    "CSR_PENDING",
    "CSR_REJECTED",
    "UNDER_INSPECTION",
    "RM_REVIEW",
}


class RmActionsService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    def _get_inventory_location(self, session: Session, code: str) -> dict[str, Any]:
        stmt = text(
            "select id, code, name, location_class "
            "from public.inventory_locations where code = :code"
        )
        row = session.execute(stmt, {"code": code}).mappings().first()
        if not row:
            raise NotFound(f"Location {code} not found")
        return dict(row)

    def _assert_gs_access(
        self, gs: dict[str, Any] | None, user: CurrentUser, perms: EffectivePermissions
    ) -> None:
        if not gs:
            raise NotFound("Goods slip not found")
        if "SUPER_ADMIN" in user.role_codes:
            return
        if not (perms.allows("goods_slips", "view") or perms.allows("inspection", "view")):
            raise PermissionDenied("You do not have permission to view this goods slip")

    def _assert_rm_action_permission(
        self, gs: dict[str, Any], user: CurrentUser, perms: EffectivePermissions
    ) -> None:
        if "SUPER_ADMIN" in user.role_codes or "REPLACEMENT_MANAGER" in user.role_codes:
            return
        if not (perms.allows("goods_slips", "edit") or perms.allows("goods_slips", "approve")):
            raise PermissionDenied(
                "Only the Replacement Manager or authorized users may edit item actions"
            )

    def _assert_not_final_action_flow(self, session: Session, gs: dict[str, Any]) -> None:
        """Change plan Phase 7 (AMD-16, G-21): a GS on the AMD-13 flow (transfer slip / held at the
        intermediate store) takes its actions on the Final Actions screen, which applies the
        resolved action profile and the qty-available rule. The DB rejects these writes too."""
        if repo.is_on_final_action_flow(session, gs["id"]):
            raise Conflict(
                f"Goods slip {gs['gs_no']} takes its RM actions on the Final Actions screen",
                code="USE_FINAL_ACTIONS",
            )

    def get_rm_actions_data(
        self,
        gs_id: UUID,
        user: CurrentUser,
        perms: EffectivePermissions,
    ) -> RmActionsResponse:
        with self._uow.transaction(user.id) as session:
            gs = repo.get_goods_slip(session, gs_id)
            self._assert_gs_access(gs, user, perms)
            if not gs:
                raise NotFound("Goods slip not found")

            items = repo.get_gs_items(session, gs_id)
            allocations = repo.get_inspection_allocations_for_gs(session, gs_id)
            rejections = repo.get_rejections_for_gs(session, gs_id)
            options = repo.get_rm_action_options(session)
            current_actions = repo.get_current_rm_actions_for_gs(session, gs_id)
            current_rev = repo.get_max_revision_no(session, gs_id)
            revision_history = repo.get_all_rm_action_revisions_for_gs(session, gs_id)

            # Map allocations by item
            alloc_by_item: dict[UUID, list[dict[str, Any]]] = {}
            for a in allocations:
                alloc_by_item.setdefault(a["gs_item_id"], []).append(a)

            # Map rejections by item
            rej_by_item: dict[UUID, list[dict[str, Any]]] = {}
            for r in rejections:
                rej_by_item.setdefault(r["gs_item_id"], []).append(r)

            # Map current actions by item
            act_by_item: dict[UUID, list[dict[str, Any]]] = {}
            for ca in current_actions:
                act_by_item.setdefault(ca["gs_item_id"], []).append(ca)

            # Map options by code
            opt_map = {opt["code"]: opt["label"] for opt in options}

            lines_out: list[RmActionLineOut] = []
            for item in items:
                item_id = item["id"]
                item_allocs = alloc_by_item.get(item_id, [])
                item_rejs = rej_by_item.get(item_id, [])
                item_cur_acts = act_by_item.get(item_id, [])

                not_allowed_qty = sum(r["qty"] for r in item_rejs)
                allowed_qty = max(0, item["received_qty"] - not_allowed_qty)

                # Fetch open pendencies for this item
                open_pends = repo.get_open_pendencies_for_item(session, item_id)
                pending_qty = sum(p["qty"] for p in open_pends)

                cur_acts_out: list[RmActionAllocationOut] = []
                if item_cur_acts:
                    for ca in item_cur_acts:
                        cur_acts_out.append(
                            RmActionAllocationOut(
                                action_code=ca["action_code"],
                                label=ca["action_label"]
                                or opt_map.get(ca["action_code"], ca["action_code"]),
                                qty=ca["qty"],
                                reason=ca["reason"],
                            )
                        )
                else:
                    # Pre-fill default actions if no revision yet
                    if not_allowed_qty > 0:
                        cur_acts_out.append(
                            RmActionAllocationOut(
                                action_code="NOT_ALLOWED",
                                label=opt_map.get("NOT_ALLOWED", "Not Allowed"),
                                qty=not_allowed_qty,
                            )
                        )
                    # Remaining actions initially 0
                    for opt in options:
                        if opt["code"] != "NOT_ALLOWED":
                            cur_acts_out.append(
                                RmActionAllocationOut(
                                    action_code=opt["code"],
                                    label=opt["label"],
                                    qty=0,
                                )
                            )

                lines_out.append(
                    RmActionLineOut(
                        gs_item_id=item_id,
                        line_no=item["line_no"],
                        product_id=item["product_id"],
                        product_code=item["product_code"],
                        product_name=item["product_name"],
                        received_qty=item["received_qty"],
                        allowed_qty=allowed_qty,
                        not_allowed_qty=not_allowed_qty,
                        allocations=item_allocs,
                        rejections=item_rejs,
                        current_actions=cur_acts_out,
                        pending_qty=pending_qty,
                    )
                )

            requires_reason = gs["status"] not in EARLY_STATUSES
            can_revise = gs["status"] != "CLOSED"

            return RmActionsResponse(
                gs_id=gs["id"],
                gs_no=gs["gs_no"],
                status=gs["status"],
                current_step_code="S1A_RM_ACTION",
                current_revision_no=current_rev,
                has_open_pendency=bool(gs["has_open_pendency"]),
                can_revise=can_revise,
                requires_reason_for_revision=requires_reason,
                lines=lines_out,
                revision_history=[
                    RmActionRevisionOut(
                        revision_no=rh["revision_no"],
                        decided_by=rh["decided_by"],
                        decided_by_name=rh["decided_by_name"],
                        decided_at=rh["decided_at"],
                        reason=rh["reason"],
                        lines=rh["lines"],
                    )
                    for rh in revision_history
                ],
                options=[
                    RmActionOptionOut(
                        code=o["code"],
                        label=o["label"],
                        allowed_status=o["allowed_status"],
                        rule_text=o["rule_text"],
                        next_action_text=o["next_action_text"],
                        sort_order=o["sort_order"],
                    )
                    for o in options
                ],
            )

    def save_rm_actions(
        self,
        gs_id: UUID,
        payload: SaveRmActionsRequest,
        user: CurrentUser,
        perms: EffectivePermissions,
    ) -> RmActionsResponse:
        with self._uow.transaction(user.id) as session:
            gs = repo.get_goods_slip(session, gs_id)
            self._assert_gs_access(gs, user, perms)
            if not gs:
                raise NotFound("Goods slip not found")
            self._assert_rm_action_permission(gs, user, perms)
            self._assert_not_final_action_flow(session, gs)

            if gs["status"] == "CLOSED":
                raise ValidationFailed("Cannot revise RM actions on a CLOSED goods slip")

            requires_reason = gs["status"] not in EARLY_STATUSES
            if requires_reason and (not payload.reason or not payload.reason.strip()):
                raise ValidationFailed(
                    "A non-empty reason is required when revising RM actions after handover (WF r6)"
                )

            items = {item["id"]: item for item in repo.get_gs_items(session, gs_id)}
            # AMD-16: valid codes = active ACTION entries of the item field library (DB FK + trigger
            # re-check this; the hard-coded list is gone).
            valid_action_codes = {o["code"] for o in repo.get_rm_action_options(session)}
            rejections = repo.get_rejections_for_gs(session, gs_id)
            rej_by_item: dict[UUID, int] = {}
            for r in rejections:
                rej_by_item[r["gs_item_id"]] = rej_by_item.get(r["gs_item_id"], 0) + r["qty"]

            # Validate each input line
            input_items: set[UUID] = set()
            for line_input in payload.lines:
                item_id = line_input.gs_item_id
                if item_id not in items:
                    raise ValidationFailed(f"Item {item_id} does not belong to goods slip {gs_id}")
                input_items.add(item_id)

                item = items[item_id]
                action_sum = sum(a.qty for a in line_input.actions)
                if action_sum != item["received_qty"]:
                    rec_qty = item["received_qty"]
                    raise ValidationFailed(
                        f"Line {item['line_no']} actions sum ({action_sum}) "
                        f"must equal received quantity ({rec_qty})"
                    )

                for act in line_input.actions:
                    if act.action_code not in valid_action_codes:
                        raise ValidationFailed(f"Invalid action code: {act.action_code}")

                # DEC-33 validation: NOT_ALLOWED must cover at least inspection rejected qty
                rej_qty = rej_by_item.get(item_id, 0)
                not_allowed_act = next(
                    (a.qty for a in line_input.actions if a.action_code == "NOT_ALLOWED"), 0
                )
                if not_allowed_act < rej_qty and not (
                    payload.override_reason and payload.override_reason.strip()
                ):
                    raise ValidationFailed(
                        f"Line {item['line_no']} has {rej_qty} rejected piece(s) at inspection; "
                        f"allocating below that requires an RM override reason (DEC-33)."
                    )

            if len(input_items) != len(items):
                raise ValidationFailed(
                    "All lines in the goods slip must be included in the RM action segregation"
                )

            # Check previous actions for notifications comparison
            prev_actions = repo.get_current_rm_actions_for_gs(session, gs_id)
            prev_has_cn_or_send = any(
                pa["action_code"] in ("ISSUE_CN", "SEND_NEW", "SEND_REPAIRED") and pa["qty"] > 0
                for pa in prev_actions
            )

            # Handle PENDING_BP quantities
            inward_loc = self._get_inventory_location(session, "INWARD_STAGING")
            pending_hold_loc = self._get_inventory_location(session, "PENDING_HOLD")
            pending_blocks_entire_gs = repo.get_system_setting_value(
                session, "pending_blocks_entire_gs", False
            )

            max_rev = repo.get_max_revision_no(session, gs_id)
            new_rev = max_rev + 1

            for line_input in payload.lines:
                item_id = line_input.gs_item_id
                pending_act = next(
                    (a.qty for a in line_input.actions if a.action_code == "PENDING_BP"), 0
                )
                open_pends = repo.get_open_pendencies_for_item(session, item_id)
                current_open_qty = sum(p["qty"] for p in open_pends)

                if pending_act > current_open_qty:
                    delta = pending_act - current_open_qty
                    # Extract detail
                    pend_detail: PendencyDetailInput | None = None
                    if payload.pendency_details and str(item_id) in payload.pendency_details:
                        pend_detail = payload.pendency_details[str(item_id)]
                    reason_text = (
                        pend_detail.reason if pend_detail else "Sent to Repair Team for checking"
                    )
                    sent_to_text = pend_detail.sent_to if pend_detail else "Repair Team"

                    # Find source lot in INWARD_STAGING for this item
                    find_lot_stmt = text(
                        """
                        select sl.id, sl.stock_item_id, sb.qty, sl.source_condition_code,
                               sl.routing_hint, sl.requires_evaluation
                          from public.stock_balances sb
                          join public.stock_lots sl on sl.id = sb.lot_id
                         where sl.gs_item_id = :item_id
                           and sb.location_id = :loc_id
                           and sl.condition_class = 'AS_RECEIVED'
                           and sl.is_pending = false
                           and sb.qty >= :needed_qty
                         order by sl.created_at, sl.id
                         limit 1
                        """
                    )
                    source_lot = (
                        session.execute(
                            find_lot_stmt,
                            {
                                "item_id": item_id,
                                "loc_id": inward_loc["id"],
                                "needed_qty": delta,
                            },
                        )
                        .mappings()
                        .first()
                    )

                    if not source_lot:
                        # Fallback: any lot for this item in INWARD_STAGING with enough qty
                        fallback_stmt = text(
                            """
                            select sl.id, sl.stock_item_id, sb.qty, sl.source_condition_code,
                                   sl.routing_hint, sl.requires_evaluation
                              from public.stock_balances sb
                              join public.stock_lots sl on sl.id = sb.lot_id
                             where sl.gs_item_id = :item_id
                               and sb.location_id = :loc_id
                               and sl.is_pending = false
                               and sb.qty >= :needed_qty
                             order by sl.created_at, sl.id
                             limit 1
                            """
                        )
                        source_lot = (
                            session.execute(
                                fallback_stmt,
                                {
                                    "item_id": item_id,
                                    "loc_id": inward_loc["id"],
                                    "needed_qty": delta,
                                },
                            )
                            .mappings()
                            .first()
                        )

                    if not source_lot:
                        l_no = items[item_id]["line_no"]
                        raise ValidationFailed(
                            f"Insufficient available stock balance in Inward Staging "
                            f"for item {l_no} to mark {delta} pending"
                        )

                    # Create a lot marked is_pending = true. It keeps the inspected condition and
                    # routing of the pieces it holds (DEC-28 lot lineage; DEC-14 routing).
                    pending_lot_id = ledger_service.create_stock_lot(
                        session,
                        stock_item_id=source_lot["stock_item_id"],
                        gs_id=gs_id,
                        gs_item_id=item_id,
                        condition_class="AS_RECEIVED",
                        source_condition_code=source_lot["source_condition_code"],
                        routing_hint=source_lot["routing_hint"],
                        requires_evaluation=bool(source_lot["requires_evaluation"]),
                        is_pending=True,
                        created_by=user.id,
                    )

                    # Reclassify delta from source lot to pending lot in INWARD_STAGING
                    reclass_idem = f"{item_id}:pend:{new_rev}:reclass"
                    ledger_service.reclassify_lot(
                        session,
                        source_lot_id=source_lot["id"],
                        target_lot_id=pending_lot_id,
                        location_id=inward_loc["id"],
                        qty=delta,
                        reference_type="pendency",
                        reference_id=item_id,
                        idempotency_key=reclass_idem,
                        actor_id=user.id,
                        reason=f"Hold for pendency: {reason_text}",
                    )

                    # Move pending lot from INWARD_STAGING to PENDING_HOLD
                    move_idem = f"{item_id}:pend:{new_rev}:move"
                    mov_id = ledger_service.move_stock(
                        session,
                        lot_id=pending_lot_id,
                        from_location_id=inward_loc["id"],
                        to_location_id=pending_hold_loc["id"],
                        qty=delta,
                        movement_type="TRANSFER_OUT",
                        reference_type="pendency",
                        reference_id=item_id,
                        idempotency_key=move_idem,
                        actor_id=user.id,
                        reason=f"Moved to PENDING_HOLD for {sent_to_text}",
                    )

                    pendency_id = repo.create_pendency(
                        session,
                        gs_id=gs_id,
                        gs_item_id=item_id,
                        qty=delta,
                        reason=reason_text,
                        sent_to=sent_to_text,
                        blocks_gs=bool(pending_blocks_entire_gs),
                        lot_id=pending_lot_id,
                        stock_movement_id=mov_id,
                        opened_by=user.id,
                    )
                    # P4-03: PENDENCY_OPENED (BR-20; rule seeded inactive, addresses the
                    # assignees of the GS's open step).
                    notifications.publish(
                        session,
                        "PENDENCY_OPENED",
                        title=f"{gs['gs_no']} line {items[item_id]['line_no']}: "
                        f"{delta} pc(s) pending (BP)",
                        body=f"Sent to {sent_to_text}. {reason_text}",
                        entity_type="goods_slip",
                        entity_id=gs_id,
                        gs_id=gs_id,
                        data={"gs_no": gs["gs_no"]},
                        dedupe_key=f"pendency-opened:{pendency_id}",
                    )

                elif pending_act < current_open_qty:
                    l_no = items[item_id]["line_no"]
                    raise ValidationFailed(
                        f"Cannot decrease Pending (BP) quantity directly on line {l_no}. "
                        "Please clear the open pendency using the Pendency Register."
                    )

            # Retire current actions and insert new revision
            repo.retire_current_rm_actions(session, gs_id)
            for line_input in payload.lines:
                for act in line_input.actions:
                    if act.qty > 0:
                        repo.insert_rm_item_action(
                            session,
                            gs_item_id=line_input.gs_item_id,
                            revision_no=new_rev,
                            action_code=act.action_code,
                            qty=act.qty,
                            is_current=True,
                            reason=payload.reason,
                            decided_by=user.id,
                        )

            # Update GS open pendency flag
            open_count = repo.count_open_pendencies_for_gs(session, gs_id)
            repo.update_gs_pendency_flag(session, gs_id, open_count > 0)

            # If revising post-handover and actions changed to/from ISSUE_CN or SEND_*,
            # notify Accounts and Store
            if requires_reason:
                new_actions = repo.get_current_rm_actions_for_gs(session, gs_id)
                new_has_cn_or_send = any(
                    na["action_code"] in ("ISSUE_CN", "SEND_NEW", "SEND_REPAIRED") and na["qty"] > 0
                    for na in new_actions
                )
                if prev_has_cn_or_send != new_has_cn_or_send or any(
                    pa["action_code"] != na["action_code"] or pa["qty"] != na["qty"]
                    for pa, na in zip(prev_actions, new_actions, strict=False)
                    if pa.get("action_code") in ("ISSUE_CN", "SEND_NEW", "SEND_REPAIRED")
                    or na.get("action_code") in ("ISSUE_CN", "SEND_NEW", "SEND_REPAIRED")
                ):
                    # Pre-P4-03 recipients kept unchanged; note "ACCOUNTS_USER" is not a seeded
                    # role code (the Accounts role is ACCOUNTS): see docs/DECISIONS.md (P4-03).
                    target_roles = ["ACCOUNTS_USER", "INTERMEDIATE_STORE_MANAGER"]
                    notifications.publish(
                        session,
                        "RM_ACTION_REVISED",
                        role_codes=target_roles,
                        notification_type="RM_ACTION_REVISED",
                        title=f"RM Actions Revised for GS {gs['gs_no']}",
                        body=f"Revision {new_rev} by {user.full_name}: {payload.reason}",
                        entity_type="goods_slips",
                        entity_id=gs_id,
                        gs_id=gs_id,
                        data={"gs_no": gs["gs_no"]},
                        priority="HIGH",
                    )

        return self.get_rm_actions_data(gs_id, user, perms)

    def finalise_rm_actions(
        self,
        gs_id: UUID,
        user: CurrentUser,
        perms: EffectivePermissions,
    ) -> RmActionsResponse:
        with self._uow.transaction(user.id) as session:
            gs = repo.get_goods_slip(session, gs_id)
            self._assert_gs_access(gs, user, perms)
            if not gs:
                raise NotFound("Goods slip not found")
            self._assert_rm_action_permission(gs, user, perms)
            self._assert_not_final_action_flow(session, gs)

            items = repo.get_gs_items(session, gs_id)
            current_actions = repo.get_current_rm_actions_for_gs(session, gs_id)

            # Check that every item has current actions and reconciles to received_qty
            actions_by_item: dict[UUID, int] = {}
            for ca in current_actions:
                actions_by_item[ca["gs_item_id"]] = (
                    actions_by_item.get(ca["gs_item_id"], 0) + ca["qty"]
                )

            for item in items:
                allocated = actions_by_item.get(item["id"], 0)
                if allocated != item["received_qty"]:
                    rec_qty = item["received_qty"]
                    p_name = item["product_name"]
                    raise ValidationFailed(
                        f"Line {item['line_no']} ({p_name}) has allocated {allocated} "
                        f"but received quantity is {rec_qty}. All lines must be reconciled."
                    )

            # Guard G-08: If pending_blocks_entire_gs=true, cannot advance beyond RM_REVIEW
            # while pendencies are open
            pending_blocks_entire_gs = repo.get_system_setting_value(
                session, "pending_blocks_entire_gs", False
            )
            if pending_blocks_entire_gs and gs["has_open_pendency"]:
                raise SystemGuardViolation(
                    guard="G-08",
                    message=(
                        "G-08: Goods Slip cannot advance status while open pendencies exist "
                        "(pending_blocks_entire_gs is enabled)."
                    ),
                )

            # Transition GS status to IN_PROCESS (for RO)
            repo.set_goods_slip_status(
                session, gs_id, "IN_PROCESS", user.id, "RM Actions finalised"
            )
            repo.complete_workflow_task(session, gs_id, "S1A_RM_ACTION")
            repo.create_workflow_task(session, gs_id, "S2_HANDOVER", "INWARD_VERIFIER")

        return self.get_rm_actions_data(gs_id, user, perms)

    def get_replacement_slip(
        self,
        gs_id: UUID,
        user: CurrentUser,
        perms: EffectivePermissions,
    ) -> ReplacementSlipResponse:
        with self._uow.transaction(user.id) as session:
            gs = repo.get_goods_slip(session, gs_id)
            self._assert_gs_access(gs, user, perms)
            if not gs:
                raise NotFound("Goods slip not found")

            template = repo.get_published_print_template(session, "REPLACEMENT_SLIP")
            if not template:
                raise NotFound("Published REPLACEMENT_SLIP print template not found")

            items = repo.get_gs_items(session, gs_id)
            rejections = repo.get_rejections_for_gs(session, gs_id)
            current_actions = repo.get_current_rm_actions_for_gs(session, gs_id)
            current_rev = repo.get_max_revision_no(session, gs_id)

            rej_by_item: dict[UUID, list[dict[str, Any]]] = {}
            for r in rejections:
                rej_by_item.setdefault(r["gs_item_id"], []).append(r)

            act_by_item: dict[UUID, dict[str, int]] = {}
            for ca in current_actions:
                act_by_item.setdefault(ca["gs_item_id"], {})[ca["action_code"]] = ca["qty"]

            # Log this print
            repo.insert_print_log(
                session,
                template_code="REPLACEMENT_SLIP",
                entity_id=gs_id,
                revision_no=max(1, current_rev),
                actor_id=user.id,
            )
            print_cnt = repo.get_print_logs_count(session, "REPLACEMENT_SLIP", gs_id)

            tz = ZoneInfo("Asia/Kolkata")
            created_dt = gs["created_at"].astimezone(tz) if gs["created_at"] else datetime.now(tz)
            date_str = created_dt.strftime("%d/%m/%Y")

            rm_name = user.full_name
            # If current actions were decided by someone else, look up their name
            if current_actions:
                decided_by_id = current_actions[0].get("decided_by")
                decider_name = repo.get_profile_name(session, decided_by_id)
                if decider_name:
                    rm_name = decider_name

            prepared_by_name = (
                repo.get_profile_name(session, gs["created_by"]) or "Unboxing Verifier"
            )

            slip_lines: list[ReplacementSlipLine] = []
            totals: dict[str, int] = {
                "received_qty": 0,
                "send_new_qty": 0,
                "send_repaired_qty": 0,
                "issue_cn_qty": 0,
                "not_allowed_qty": 0,
                "pending_bp_qty": 0,
                "rejected_qty": 0,
            }

            for item in items:
                item_id = item["id"]
                acts = act_by_item.get(item_id, {})
                rejs = rej_by_item.get(item_id, [])

                send_new = acts.get("SEND_NEW", 0)
                send_rep = acts.get("SEND_REPAIRED", 0)
                issue_cn = acts.get("ISSUE_CN", 0)
                not_allowed = acts.get("NOT_ALLOWED", 0)
                pending_bp = acts.get("PENDING_BP", 0)
                rej_qty = sum(r["qty"] for r in rejs)
                rej_reasons = [
                    f"{r['condition_label'] or r['condition_code']} ({r['qty']})" for r in rejs
                ]

                totals["received_qty"] += item["received_qty"]
                totals["send_new_qty"] += send_new
                totals["send_repaired_qty"] += send_rep
                totals["issue_cn_qty"] += issue_cn
                totals["not_allowed_qty"] += not_allowed
                totals["pending_bp_qty"] += pending_bp
                totals["rejected_qty"] += rej_qty

                slip_lines.append(
                    ReplacementSlipLine(
                        line_no=item["line_no"],
                        product_code=item["product_code"],
                        product_name=item["product_name"],
                        received_qty=item["received_qty"],
                        send_new_qty=send_new,
                        send_repaired_qty=send_rep,
                        issue_cn_qty=issue_cn,
                        not_allowed_qty=not_allowed,
                        pending_bp_qty=pending_bp,
                        rejected_qty=rej_qty,
                        rejection_reasons=rej_reasons,
                        pending_qty=pending_bp,
                    )
                )

            is_reprint = print_cnt > 1
            watermark = None
            if current_rev > 1:
                watermark = f"REVISION {current_rev}"
            elif is_reprint:
                watermark = "REPRINT"

            signature_blocks = [
                {"label": "Prepared By", "role": "Unboxing Verifier", "name": prepared_by_name},
                {"label": "Replacement Manager", "role": "Replacement Manager", "name": rm_name},
            ]

            return ReplacementSlipResponse(
                gs_id=gs["id"],
                gs_no=gs["gs_no"],
                party_name=gs["party_name"] or "Unknown Party",
                party_code=gs["party_code"],
                station_name=gs["station_name"],
                state_name=gs["state_name"],
                date=date_str,
                revision_no=max(1, current_rev),
                rm_name=rm_name,
                prepared_by=prepared_by_name,
                print_count=print_cnt,
                is_reprint=is_reprint,
                watermark=watermark,
                signature_blocks=signature_blocks,
                lines=slip_lines,
                totals=totals,
                layout=template["layout"],
            )

    def get_resolution_board(
        self,
        gs_id: UUID,
        user: CurrentUser,
        perms: EffectivePermissions,
    ) -> ResolutionBoardResponse:
        with self._uow.transaction(user.id) as session:
            gs = repo.get_goods_slip(session, gs_id)
            if not gs:
                raise NotFound(f"Goods slip {gs_id} not found")
            self._assert_gs_access(gs, user, perms)

            current_rev = repo.get_max_revision_no(session, gs_id)
            items = repo.get_gs_items(session, gs_id)
            current_actions = repo.get_current_rm_actions_for_gs(session, gs_id)
            board_data = repo.get_resolution_board_data(session, gs_id)

            tech_by_item = board_data["tech_by_item"]
            rej_by_item = board_data["rej_by_item"]
            issue_by_item = board_data["issue_by_item"]
            disp_rows = board_data["disp_rows"]
            lot_rows = board_data["lot_rows"]

            lots_by_item: dict[UUID, dict[str, int]] = {}
            for lr in lot_rows:
                item_id = lr["gs_item_id"]
                c_class = lr["condition_class"]
                lots_by_item.setdefault(item_id, {})
                lots_by_item[item_id][c_class] = (
                    lots_by_item[item_id].get(c_class, 0) + lr["balance_qty"]
                )

            disp_by_item: dict[UUID, dict[str, int]] = {}
            for dr in disp_rows:
                item_id = dr["gs_item_id"]
                dtype = dr["dispatch_type"]
                disp_by_item.setdefault(item_id, {})
                disp_by_item[item_id][dtype] = disp_by_item[item_id].get(dtype, 0) + dr["qty"]

            actions_by_item: dict[UUID, list[RmActionAllocationOut]] = {}
            for act in current_actions:
                item_id = act["gs_item_id"]
                actions_by_item.setdefault(item_id, []).append(
                    RmActionAllocationOut(
                        action_code=act["action_code"],
                        label=act.get("action_label") or act["action_code"],
                        qty=act["qty"],
                        reason=act.get("reason"),
                    )
                )

            board_lines: list[ResolutionBoardLineOut] = []
            overall_summary: list[str] = []

            for item in items:
                item_id = item["id"]
                tech_info = tech_by_item.get(item_id, {})
                lot_info = lots_by_item.get(item_id, {})
                rej_qty = rej_by_item.get(item_id, 0)
                disp_info = disp_by_item.get(item_id, {})
                issued_main = issue_by_item.get(item_id, 0)

                tech_good = tech_info.get("tech_good", 0)
                tech_repaired = tech_info.get("tech_repaired", 0)
                tech_non_good = tech_info.get("tech_non_good", 0)
                tech_non_sellable = tech_info.get("tech_non_sellable", 0)

                if tech_info:
                    f_good = tech_good
                    f_repaired = tech_repaired
                    non_good = tech_non_good
                    non_sellable = tech_non_sellable
                else:
                    f_good = lot_info.get("FUNCTIONAL_GOOD", 0)
                    f_repaired = lot_info.get("FUNCTIONAL_REPAIRED", 0)
                    non_good = lot_info.get("NON_GOOD", 0)
                    non_sellable = lot_info.get("NON_SELLABLE", 0)

                outcomes = LineOutcomeDetail(
                    functional_good_qty=f_good,
                    functional_repaired_qty=f_repaired,
                    non_good_qty=non_good,
                    non_sellable_qty=non_sellable,
                    rejected_qty=rej_qty,
                )

                dispatched = LineDispatchedDetail(
                    dispatched_new_qty=disp_info.get("SEND_NEW", 0),
                    dispatched_repaired_qty=disp_info.get("SEND_REPAIRED", 0),
                    issued_main_store_qty=issued_main,
                )

                item_actions = actions_by_item.get(item_id, [])
                action_dict = {a.action_code: a.qty for a in item_actions}
                planned_repaired = action_dict.get("SEND_REPAIRED", 0)
                planned_new = action_dict.get("SEND_NEW", 0)
                planned_not_allowed = action_dict.get("NOT_ALLOWED", 0)

                suggestions: list[str] = []
                mismatch = False

                if planned_repaired > f_repaired:
                    deficit = planned_repaired - f_repaired
                    suggestions.append(
                        f"Planned {planned_repaired} SEND_REPAIRED but only {f_repaired} unit(s) "
                        "repaired. "
                        f"Suggest revising {deficit} to SEND_NEW, ISSUE_CN, or NOT_ALLOWED."
                    )
                    mismatch = True

                if f_repaired > planned_repaired and planned_new > 0:
                    shiftable = min(f_repaired - planned_repaired, planned_new)
                    suggestions.append(
                        f"{f_repaired} unit(s) repaired successfully. Consider revising "
                        f"{shiftable} from SEND_NEW to SEND_REPAIRED."
                    )
                    mismatch = True

                if non_sellable > 0 and planned_not_allowed < non_sellable:
                    suggestions.append(
                        f"{non_sellable} unit(s) marked NON_SELLABLE due to scratches/damage. "
                        "Consider revising to NOT_ALLOWED."
                    )
                    mismatch = True

                if rej_qty > 0 and planned_not_allowed < rej_qty:
                    suggestions.append(
                        f"{rej_qty} unit(s) rejected at inspection. "
                        "Allocation to NOT_ALLOWED recommended (DEC-33)."
                    )
                    mismatch = True

                if not suggestions:
                    suggestions.append("Allocations align with technical and inspection outcomes.")

                board_lines.append(
                    ResolutionBoardLineOut(
                        gs_item_id=item_id,
                        line_no=item["line_no"],
                        product_id=item["product_id"],
                        product_code=item["product_code"],
                        product_name=item["product_name"],
                        received_qty=item["received_qty"],
                        current_actions=item_actions,
                        outcomes=outcomes,
                        dispatched=dispatched,
                        suggested_adjustments=suggestions,
                        has_mismatch=mismatch,
                    )
                )

            total_mismatches = sum(1 for line in board_lines if line.has_mismatch)
            if total_mismatches > 0:
                overall_summary.append(
                    f"{total_mismatches} line(s) have discrepancy between planned RM actions "
                    "and actual technical outcomes. "
                    "Revision recommended before final dispatch."
                )
            else:
                overall_summary.append(
                    "All line allocations are aligned with actual technical outcomes."
                )

            return ResolutionBoardResponse(
                gs_id=gs["id"],
                gs_no=gs["gs_no"],
                status=gs["status"],
                current_step_code=None,
                current_revision_no=max(1, current_rev),
                lines=board_lines,
                summary_notes=overall_summary,
            )
