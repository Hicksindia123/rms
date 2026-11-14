"""Service for Pendency register and clearance.

Master plan references: WF r7 col K, BR-20, DEC-12, G-08.
"""

from datetime import date, datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import UnitOfWork
from app.core.errors import NotFound, PermissionDenied, ValidationFailed
from app.core.permissions import EffectivePermissions
from app.core.security import CurrentUser
from app.modules.inventory import ledger_service
from app.modules.notifications import service as notifications
from app.modules.pendency import repository as repo
from app.modules.pendency.schemas import ClearPendencyRequest, PendencyOut
from app.modules.rm_actions import repository as rm_repo

ALLOWED_RESOLUTIONS = {"SEND_NEW", "SEND_REPAIRED", "ISSUE_CN", "NOT_ALLOWED"}


class PendencyService:
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

    def list_pendencies(
        self,
        status: str | None,
        gs_id: UUID | None,
        from_date: date | None,
        to_date: date | None,
        user: CurrentUser,
        perms: EffectivePermissions,
    ) -> list[PendencyOut]:
        with self._uow.transaction(user.id) as session:
            rows = repo.list_pendencies(
                session,
                status=status,
                gs_id=gs_id,
                from_date=from_date,
                to_date=to_date,
            )
            tz = ZoneInfo("Asia/Kolkata")
            now = datetime.now(tz)

            out: list[PendencyOut] = []
            for r in rows:
                opened_dt = r["opened_at"].astimezone(tz)
                end_dt = r["cleared_at"].astimezone(tz) if r["cleared_at"] else now
                delta = end_dt - opened_dt
                age_days = max(0, delta.days)
                age_hours = max(0, int(delta.total_seconds() // 3600))

                out.append(
                    PendencyOut(
                        id=r["id"],
                        gs_id=r["gs_id"],
                        gs_no=r["gs_no"],
                        party_name=r["party_name"] or "Unknown",
                        gs_item_id=r["gs_item_id"],
                        line_no=r["line_no"],
                        product_name=r["product_name"] or "Unknown",
                        qty=r["qty"],
                        reason=r["reason"],
                        sent_to=r["sent_to"],
                        blocks_gs=bool(r["blocks_gs"]),
                        status=r["status"],
                        opened_by=r["opened_by"],
                        opened_by_name=r["opened_by_name"] or "User",
                        opened_at=r["opened_at"],
                        cleared_by=r["cleared_by"],
                        cleared_by_name=r["cleared_by_name"],
                        cleared_at=r["cleared_at"],
                        clearance_notes=r["clearance_notes"],
                        resolution_action=r["resolution_action"],
                        age_days=age_days,
                        age_hours=age_hours,
                    )
                )
            return out

    def clear_pendency(
        self,
        pendency_id: UUID,
        payload: ClearPendencyRequest,
        user: CurrentUser,
        perms: EffectivePermissions,
    ) -> PendencyOut:
        if payload.resolution_action not in ALLOWED_RESOLUTIONS:
            allowed_str = ", ".join(sorted(ALLOWED_RESOLUTIONS))
            raise ValidationFailed(
                f"Invalid resolution action: {payload.resolution_action}. Must be: {allowed_str}"
            )

        with self._uow.transaction(user.id) as session:
            p = repo.get_pendency(session, pendency_id)
            if not p:
                raise NotFound("Pendency not found")

            if p["status"] != "OPEN":
                raise ValidationFailed("Only OPEN pendencies can be cleared")

            # DEC-12: Pendency cleared by RM or the user who raised it
            is_rm = "REPLACEMENT_MANAGER" in user.role_codes or "SUPER_ADMIN" in user.role_codes
            is_opener = str(p["opened_by"]) == str(user.id)
            if not (is_rm or is_opener):
                raise PermissionDenied(
                    "Only the RM or the user who opened the pendency may clear it (DEC-12)"
                )

            gs_id = p["gs_id"]
            item_id = p["gs_item_id"]
            qty = p["qty"]

            # Move stock back from PENDING_HOLD to INWARD_STAGING
            inward_loc = self._get_inventory_location(session, "INWARD_STAGING")
            pending_hold_loc = self._get_inventory_location(session, "PENDING_HOLD")

            lot_id = p.get("lot_id")
            if lot_id:
                # Move stock from PENDING_HOLD back to INWARD_STAGING
                move_idem = f"clear:{pendency_id}:move"
                ledger_service.move_stock(
                    session,
                    lot_id=lot_id,
                    from_location_id=pending_hold_loc["id"],
                    to_location_id=inward_loc["id"],
                    qty=qty,
                    movement_type="TRANSFER_IN",
                    reference_type="pendency_clear",
                    reference_id=pendency_id,
                    idempotency_key=move_idem,
                    actor_id=user.id,
                    reason=f"Pendency cleared: {payload.notes}",
                )

                # Return the pieces to a non-pending lot with the same inspected condition and
                # routing (DEC-28 lineage, DEC-14); create it from the pending lot if none exists.
                pending_lot = (
                    session.execute(
                        text(
                            """
                            select stock_item_id, source_condition_code, routing_hint,
                                   requires_evaluation
                              from public.stock_lots where id = :lot_id
                            """
                        ),
                        {"lot_id": lot_id},
                    )
                    .mappings()
                    .one()
                )
                normal_lot = (
                    session.execute(
                        text(
                            """
                            select id
                              from public.stock_lots
                             where gs_item_id = :item_id
                               and condition_class = 'AS_RECEIVED'
                               and is_pending = false
                               and source_condition_code is not distinct from :src
                               and routing_hint is not distinct from :routing
                             order by created_at, id
                             limit 1
                            """
                        ),
                        {
                            "item_id": item_id,
                            "src": pending_lot["source_condition_code"],
                            "routing": pending_lot["routing_hint"],
                        },
                    )
                    .mappings()
                    .first()
                )
                if normal_lot:
                    target_lot_id = normal_lot["id"]
                else:
                    target_lot_id = ledger_service.create_stock_lot(
                        session,
                        stock_item_id=pending_lot["stock_item_id"],
                        gs_id=gs_id,
                        gs_item_id=item_id,
                        condition_class="AS_RECEIVED",
                        source_condition_code=pending_lot["source_condition_code"],
                        routing_hint=pending_lot["routing_hint"],
                        requires_evaluation=bool(pending_lot["requires_evaluation"]),
                        is_pending=False,
                        created_by=user.id,
                    )

                # Reclassify from pending lot back to normal lot in INWARD_STAGING
                reclass_idem = f"clear:{pendency_id}:reclass"
                ledger_service.reclassify_lot(
                    session,
                    source_lot_id=lot_id,
                    target_lot_id=target_lot_id,
                    location_id=inward_loc["id"],
                    qty=qty,
                    reference_type="pendency_clear",
                    reference_id=pendency_id,
                    idempotency_key=reclass_idem,
                    actor_id=user.id,
                    reason=f"Pendency resolved to {payload.resolution_action}",
                )

            # Update pendency in database
            repo.clear_pendency_db(
                session, pendency_id, payload.resolution_action, payload.notes, user.id
            )

            # Recompute GS open pendency flag
            open_count = rm_repo.count_open_pendencies_for_gs(session, gs_id)
            rm_repo.update_gs_pendency_flag(session, gs_id, open_count > 0)

            # Create a new RM action revision reflecting the clearance
            current_actions = rm_repo.get_current_rm_actions_for_gs(session, gs_id)
            if current_actions:
                max_rev = rm_repo.get_max_revision_no(session, gs_id)
                new_rev = max_rev + 1
                rm_repo.retire_current_rm_actions(session, gs_id)

                for ca in current_actions:
                    act_item_id = ca["gs_item_id"]
                    act_code = ca["action_code"]
                    act_qty = ca["qty"]

                    if act_item_id == item_id:
                        if act_code == "PENDING_BP":
                            act_qty -= qty
                        elif act_code == payload.resolution_action:
                            act_qty += qty

                    if act_qty > 0:
                        rm_repo.insert_rm_item_action(
                            session,
                            gs_item_id=act_item_id,
                            revision_no=new_rev,
                            action_code=act_code,
                            qty=act_qty,
                            is_current=True,
                            reason=f"Pendency cleared ({payload.notes})",
                            decided_by=user.id,
                        )

                # In case resolution_action was not previously in the line's actions
                item_has_resolution = any(
                    ca["gs_item_id"] == item_id and ca["action_code"] == payload.resolution_action
                    for ca in current_actions
                )
                if not item_has_resolution:
                    rm_repo.insert_rm_item_action(
                        session,
                        gs_item_id=item_id,
                        revision_no=new_rev,
                        action_code=payload.resolution_action,
                        qty=qty,
                        is_current=True,
                        reason=f"Pendency cleared ({payload.notes})",
                        decided_by=user.id,
                    )

            cleared_p = repo.get_pendency(session, pendency_id)
            if not cleared_p:
                raise NotFound("Pendency not found")
            # P4-03: PENDENCY_CLEARED (BR-20; rule seeded inactive). Context: who opened it.
            notifications.publish(
                session,
                "PENDENCY_CLEARED",
                user_ids=[p["opened_by"]],
                title=f"{cleared_p['gs_no']}: pendency of {qty} pc(s) cleared",
                body=f"Resolved as {payload.resolution_action} by {user.full_name}.",
                entity_type="goods_slip",
                entity_id=gs_id,
                gs_id=gs_id,
                data={"gs_no": str(cleared_p["gs_no"])},
                dedupe_key=f"pendency-cleared:{pendency_id}",
            )
            tz = ZoneInfo("Asia/Kolkata")
            opened_dt = cleared_p["opened_at"].astimezone(tz)
            cleared_dt = (
                cleared_p["cleared_at"].astimezone(tz)
                if cleared_p["cleared_at"]
                else datetime.now(tz)
            )
            delta = cleared_dt - opened_dt

            return PendencyOut(
                id=cleared_p["id"],
                gs_id=cleared_p["gs_id"],
                gs_no=cleared_p["gs_no"],
                party_name=cleared_p["party_name"] or "Unknown",
                gs_item_id=cleared_p["gs_item_id"],
                line_no=cleared_p["line_no"],
                product_name=cleared_p["product_name"] or "Unknown",
                qty=cleared_p["qty"],
                reason=cleared_p["reason"],
                sent_to=cleared_p["sent_to"],
                blocks_gs=bool(cleared_p["blocks_gs"]),
                status=cleared_p["status"],
                opened_by=cleared_p["opened_by"],
                opened_by_name=cleared_p["opened_by_name"] or "User",
                opened_at=cleared_p["opened_at"],
                cleared_by=cleared_p["cleared_by"],
                cleared_by_name=cleared_p["cleared_by_name"],
                cleared_at=cleared_p["cleared_at"],
                clearance_notes=cleared_p["clearance_notes"],
                resolution_action=cleared_p["resolution_action"],
                age_days=max(0, delta.days),
                age_hours=max(0, int(delta.total_seconds() // 3600)),
            )
