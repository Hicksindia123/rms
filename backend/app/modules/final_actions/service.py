"""RM Final Actions and the "Replacement Slip - A/c Actions" (change plan 2026-11-12 Phase 7;
AMD-16, AMD-17; DEC-41, DEC-45, DEC-46; G-18, G-20, G-21).

* Save: per item the RM splits the qty available for action (counted - at departments) across the
  actions allowed by the product's resolved ACTION profile. G-21: Σ action qty = available qty.
  Every save is a new revision (rm_item_actions, insert-only history; G-18 label snapshots).
  Revising finalised actions needs a reason and supersedes the current slip (Accounts notified).
* Finalise: nothing may remain at a department (so the actions cover the full counted qty); a
  server-side PDF is rendered from the published AC_ACTIONS_SLIP template (DEC-41), stored as a
  GENERATED_PDF attachment and recorded as a new slip version; ACCOUNTS is notified (rule-driven).
* Print: any version can be printed again at any time; every print is logged (print_logs).

Save and finalise run in one transaction each and are idempotent on `Idempotency-Key` (G-16).
The DB enforces G-21 / G-20 again (triggers + validate functions), so no path can bypass them.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable
from datetime import date, datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog
from sqlalchemy.orm import Session

from app.core.db import UnitOfWork
from app.core.errors import (
    Conflict,
    NotFound,
    ServiceUnavailable,
    SystemGuardViolation,
    ValidationFailed,
)
from app.core.idempotency import IdempotencyKey, IdempotentResult, run_idempotent
from app.core.permissions import EffectivePermissions
from app.core.security import CurrentUser
from app.modules.attachments.service import signed_url_ttl
from app.modules.department_routing.service import department_routing_service
from app.modules.final_actions import repository as repo
from app.modules.final_actions.schemas import (
    AcSlipActionTotal,
    AcSlipPrintOut,
    AcSlipVersion,
    FinalActionAllocation,
    FinalActionGroup,
    FinalActionLine,
    FinalActionOption,
    FinalActionRevision,
    FinalActionRevisionLine,
    FinalActionsState,
    FinaliseFinalActionsIn,
    ItemConditionQty,
    OutcomeQty,
    SaveFinalActionsIn,
)
from app.modules.notifications import service as notifications
from app.shared.branding import template_logo
from app.shared.pdf import (
    SlipColumn,
    SlipDocument,
    SlipField,
    SlipSection,
    SlipSignature,
    SlipTable,
    render_slip_pdf,
)
from app.shared.storage import Bucket, StorageService, build_object_path

log = structlog.get_logger("rms.final_actions")

HELD_STATUS = "HELD_AT_INTERMEDIATE_STORE"
# DEC-57: statuses in which a Pending re-action round (round >= 2) may change / finalise; the DB
# guards check the same list.
OPEN_AFTER_HOLD = frozenset({"IN_PROCESS", "COMMERCIAL_RESOLUTION", "AWAITING_NOTIFICATION"})
# DEC-57 (Q10): the stable ACTION code of "Pending" (rule e: logic keys off codes; the label is
# configuration). Its pieces go to the Pending Hold and are re-actioned in the next round.
PENDING_ACTION = "PENDING_BP"
PDF_MIME = "application/pdf"


# --- small helpers ------------------------------------------------------------------------------


def _tz(session: Session) -> ZoneInfo:
    name = repo.get_setting(session, "timezone")
    try:
        return ZoneInfo(str(name)) if name else ZoneInfo("Asia/Kolkata")
    except ZoneInfoNotFoundError:
        log.error("timezone_setting_invalid", value=name)
        raise Conflict(
            "System setting 'timezone' is not a valid time zone",
            code="SETTING_INVALID",
            details={"key": "timezone"},
        ) from None


def _date_fmt(session: Session) -> str:
    """`date_format` setting (e.g. DD-MM-YYYY) as a strftime pattern."""
    raw = str(repo.get_setting(session, "date_format") or "DD-MM-YYYY")
    return raw.replace("YYYY", "%Y").replace("MM", "%m").replace("DD", "%d")


def _fmt_date(value: date | datetime | None, fmt: str, tz: ZoneInfo) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.astimezone(tz).strftime(fmt)
    return value.strftime(fmt)


def _pending_qty(session: Session, gs_id: UUID, round_no: int) -> int:
    """Pieces a round left Pending (DEC-57)."""
    return sum(int(g["qty"]) for g in repo.action_groups(session, gs_id, round_no, PENDING_ACTION))


def _slip_out(row: dict[str, Any]) -> AcSlipVersion:
    totals = row.get("totals") or {}
    return AcSlipVersion(
        id=row["id"],
        slip_no=row["slip_no"],
        version_no=row["version_no"],
        revision_no=row["revision_no"],
        round_no=int(row.get("round_no") or 1),
        status=row["status"],
        is_completed=bool(row.get("is_completed")),
        finalised_at=row["finalised_at"],
        finalised_by_name=row.get("finalised_by_name"),
        superseded_at=row.get("superseded_at"),
        superseded_by_name=row.get("superseded_by_name"),
        supersede_reason=row.get("supersede_reason"),
        remarks=row.get("remarks"),
        total_qty=int(totals.get("total_qty", 0)),
        action_totals=[AcSlipActionTotal(**t) for t in totals.get("by_action", [])],
        print_count=int(row.get("print_count") or 0),
    )


class FinalActionsService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    # === rounds (DEC-57) ===

    @staticmethod
    def _working_round(session: Session, gs_id: UUID) -> int:
        """The round the RM works on: 1 until Accounts completed it; then, while the last completed
        round left pieces Pending, the next round (re-action, Q10)."""
        last = repo.max_round(session, gs_id)
        if last == 0:
            return 1
        slip = repo.current_slip(session, gs_id, last)
        if slip is not None and slip["is_completed"] and _pending_qty(session, gs_id, last) > 0:
            return last + 1
        return last

    @staticmethod
    def _groups(
        session: Session, gs_id: UUID, round_no: int
    ) -> dict[tuple[UUID, UUID | None], dict[str, Any]]:
        """The (item, condition) groups of a round with the qty each must allocate (G-21)."""
        out: dict[tuple[UUID, UUID | None], dict[str, Any]] = {}
        if round_no == 1:
            for g in repo.condition_quantities(session, gs_id):
                out[(g["gs_item_id"], g["condition_field_id"])] = g
            return out
        for g in repo.action_groups(session, gs_id, round_no - 1, PENDING_ACTION):
            out[(g["gs_item_id"], g["condition_field_id"])] = {
                **g,
                "current_qty": g["qty"],
                "at_dept_qty": 0,
                "available_qty": g["qty"],
            }
        return out

    def _round_blocker(self, session: Session, gs: dict[str, Any], round_no: int) -> str | None:
        """Why the round cannot change now (None = it can)."""
        if round_no == 1:
            if gs["status"] != HELD_STATUS:
                return "The goods slip is not held at the intermediate store."
            return None
        if gs["status"] not in OPEN_AFTER_HOLD:
            return f"The goods slip is {gs['status']}; Pending pieces can no longer be re-actioned."
        if not repo.round_settled(session, gs["id"], round_no - 1):
            return (
                f"Round {round_no - 1} is not settled yet: Accounts must complete it and its "
                "Dispatch Slip (if any) must be dispatched before the Pending pieces are "
                "re-actioned."
            )
        return None

    # === queries ===

    def get_state(
        self, gs_id: UUID, user: CurrentUser, perms: EffectivePermissions
    ) -> FinalActionsState:
        with self._uow.transaction(user.id) as session:
            return self._state(session, gs_id, perms)

    def _state(
        self, session: Session, gs_id: UUID, perms: EffectivePermissions
    ) -> FinalActionsState:
        gs = repo.get_gs_header(session, gs_id)
        if not gs:
            raise NotFound(f"Goods slip {gs_id} not found", code="GS_NOT_FOUND")
        on_flow = repo.is_on_final_action_flow(session, gs_id)
        version_id = gs["item_field_profile_version_id"]
        rnd = self._working_round(session, gs_id)

        outcomes: dict[UUID, list[OutcomeQty]] = {}
        for o in repo.outcome_breakdown(session, gs_id):
            outcomes.setdefault(o["gs_item_id"], []).append(
                OutcomeQty(
                    **{k: o[k] for k in ("outcome_code", "outcome_label", "is_wastage", "qty")}
                )
            )
        conditions: dict[UUID, list[ItemConditionQty]] = {}
        for c in repo.current_conditions(session, gs_id):
            conditions.setdefault(c["gs_item_id"], []).append(
                ItemConditionQty(
                    **{
                        k: c[k]
                        for k in ("field_code", "field_label", "original_qty", "current_qty")
                    }
                )
            )
        actions = repo.current_actions(session, gs_id, rnd)
        by_group: dict[tuple[UUID, UUID | None], list[FinalActionAllocation]] = {}
        by_item: dict[UUID, dict[str, FinalActionAllocation]] = {}
        for a in actions:
            by_group.setdefault((a["gs_item_id"], a["condition_field_id"]), []).append(
                FinalActionAllocation(action_code=a["action_code"], label=a["label"], qty=a["qty"])
            )
            agg = by_item.setdefault(a["gs_item_id"], {})
            if a["action_code"] in agg:
                agg[a["action_code"]].qty += a["qty"]
            else:
                agg[a["action_code"]] = FinalActionAllocation(
                    action_code=a["action_code"], label=a["label"], qty=a["qty"]
                )

        groups = self._groups(session, gs_id, rnd)
        group_out: dict[UUID, list[FinalActionGroup]] = {}
        for (item_id, cond_id), g in groups.items():
            current = by_group.get((item_id, cond_id), [])
            actioned = sum(a.qty for a in current)
            group_out.setdefault(item_id, []).append(
                FinalActionGroup(
                    condition_field_id=cond_id,
                    condition_code=g["condition_code"],
                    condition_label=g["condition_label"],
                    current_qty=g["current_qty"],
                    at_departments_qty=g["at_dept_qty"],
                    available_qty=g["available_qty"],
                    actioned_qty=actioned,
                    is_balanced=actioned == g["available_qty"],
                    current_actions=current,
                )
            )

        allowed_cache: dict[UUID, list[FinalActionOption]] = {}
        lines: list[FinalActionLine] = []
        for q in repo.item_quantities(session, gs_id):
            item_id = q["gs_item_id"]
            if rnd > 1 and item_id not in group_out:
                continue  # a re-action round shows only the items with Pending pieces
            if q["product_id"] not in allowed_cache:
                allowed_cache[q["product_id"]] = [
                    FinalActionOption(**a)
                    for a in repo.allowed_actions(session, q["product_id"], version_id)
                ]
            item_groups = group_out.get(item_id, [])
            if rnd == 1:
                at_dept, available = q["at_dept_qty"], q["available_qty"]
                actioned = q["actioned_qty"]
            else:
                at_dept = 0
                available = sum(g.available_qty for g in item_groups)
                actioned = sum(g.actioned_qty for g in item_groups)
            lines.append(
                FinalActionLine(
                    gs_item_id=item_id,
                    line_no=q["line_no"],
                    product_id=q["product_id"],
                    product_code=q["product_code"],
                    product_name=q["product_name"],
                    counted_qty=q["counted_qty"],
                    at_departments_qty=at_dept,
                    available_qty=available,
                    actioned_qty=actioned,
                    is_balanced=actioned == available and all(g.is_balanced for g in item_groups),
                    outcomes=outcomes.get(item_id, []),
                    current_conditions=conditions.get(item_id, []),
                    allowed_actions=allowed_cache[q["product_id"]],
                    current_actions=list(by_item.get(item_id, {}).values()),
                    groups=item_groups,
                )
            )

        revisions: dict[int, FinalActionRevision] = {}
        for r in repo.revision_rows(session, gs_id):
            rev = revisions.get(r["revision_no"])
            if rev is None:
                rev = revisions[r["revision_no"]] = FinalActionRevision(
                    revision_no=r["revision_no"],
                    round_no=r["round_no"],
                    decided_by_name=r["decided_by_name"],
                    decided_at=r["decided_at"],
                    reason=r["reason"],
                )
            rev.lines.append(
                FinalActionRevisionLine(
                    line_no=r["line_no"],
                    action_code=r["action_code"],
                    action_label=r["label"],
                    condition_label=r["condition_label"],
                    qty=r["qty"],
                )
            )

        slips = [_slip_out(s) for s in repo.list_slips(session, gs_id)]
        current_slip = next((s for s in slips if s.status == "CURRENT" and s.round_no == rnd), None)
        completed = current_slip is not None and current_slip.is_completed
        round_rev = max((a["revision_no"] for a in actions), default=0)
        round_block = self._round_blocker(session, gs, rnd)
        pending_prev = _pending_qty(session, gs_id, rnd - 1) if rnd > 1 else 0

        blockers: list[str] = []
        if not on_flow:
            blockers.append("This goods slip uses the earlier RM actions screen (P2-07).")
        elif round_block:
            blockers.append(round_block)
        if current_slip is not None:
            blockers.append(
                f"Already finalised on {current_slip.slip_no} v{current_slip.version_no}."
            )
        if round_rev == 0:
            blockers.append("No final actions have been saved yet.")
        # DEC-55 / G-21: pieces planned for a department wait for the Store issue first.
        planned = department_routing_service.planned_qty_by_item(session, gs_id) if rnd == 1 else {}
        for ln in lines:
            if planned.get(ln.gs_item_id, 0) > 0:
                blockers.append(
                    f"Line {ln.line_no}: {planned[ln.gs_item_id]} pc(s) planned for a department, "
                    "not issued by the store yet."
                )
            if ln.at_departments_qty > 0:
                blockers.append(
                    f"Line {ln.line_no}: {ln.at_departments_qty} pc(s) still at a department."
                )
                continue
            for grp in ln.groups:
                if not grp.is_balanced:
                    where = f" {grp.condition_label}" if grp.condition_label else ""
                    blockers.append(
                        f"Line {ln.line_no}{where}: actions total {grp.actioned_qty} of "
                        f"{grp.available_qty} pc(s) (G-21)."
                    )
            if ln.actioned_qty != ln.available_qty and all(x.is_balanced for x in ln.groups):
                blockers.append(
                    f"Line {ln.line_no}: actions total {ln.actioned_qty} of "
                    f"{ln.available_qty} pc(s) (G-21)."
                )

        return FinalActionsState(
            gs_id=gs["id"],
            gs_no=gs["gs_no"],
            status=gs["status"],
            party_name=gs["party_name"],
            on_final_action_flow=on_flow,
            can_edit=on_flow
            and round_block is None
            and not completed
            and perms.allows("final_actions", "edit"),
            can_finalise=not blockers and perms.allows("final_actions", "approve"),
            finalise_blockers=blockers,
            current_revision_no=repo.max_revision(session, gs_id),
            round_no=rnd,
            pending_from_previous_round=pending_prev,
            waiting_for_previous_round=rnd > 1 and round_block is not None,
            is_finalised=current_slip is not None,
            is_completed=completed,
            current_slip=current_slip,
            lines=lines,
            revisions=sorted(revisions.values(), key=lambda r: r.revision_no, reverse=True),
            slips=slips,
        )

    # === save (new revision) ===

    def save(
        self,
        gs_id: UUID,
        payload: SaveFinalActionsIn,
        user: CurrentUser,
        perms: EffectivePermissions,
        idem: IdempotencyKey,
    ) -> IdempotentResult:
        with self._uow.transaction(user.id) as session:
            return run_idempotent(
                session,
                idem,
                user.id,
                lambda: (200, self._save(session, gs_id, payload, user, perms)),
            )

    def _lock_round(self, session: Session, gs_id: UUID) -> tuple[dict[str, Any], int]:
        """Lock the goods slip and return it with the round that may change now (DEC-57)."""
        gs = repo.get_gs_header(session, gs_id, lock=True)
        if not gs:
            raise NotFound(f"Goods slip {gs_id} not found", code="GS_NOT_FOUND")
        if not repo.is_on_final_action_flow(session, gs_id):
            raise Conflict(
                f"Goods slip {gs['gs_no']} uses the earlier RM actions screen (P2-07)",
                code="NOT_ON_FINAL_ACTION_FLOW",
            )
        rnd = self._working_round(session, gs_id)
        if rnd == 1 and gs["status"] != HELD_STATUS:
            raise Conflict(
                f"Final actions need goods slip {gs['gs_no']} held at the intermediate store "
                f"(current status: {gs['status']})",
                code="INVALID_GS_STATUS",
            )
        if rnd > 1:
            if gs["status"] not in OPEN_AFTER_HOLD:
                raise Conflict(
                    f"Goods slip {gs['gs_no']} is {gs['status']}; Pending pieces can no longer be "
                    "re-actioned",
                    code="INVALID_GS_STATUS",
                )
            if not repo.round_settled(session, gs_id, rnd - 1):
                raise Conflict(
                    f"Round {rnd - 1} of {gs['gs_no']} is not settled yet (Accounts completion and "
                    "dispatch come first)",
                    code="ROUND_NOT_SETTLED",
                )
        slip = repo.current_slip(session, gs_id, rnd)
        if slip is not None and slip["is_completed"]:
            raise SystemGuardViolation(
                "G-22",
                f"G-22: Accounts completed {slip['slip_no']} v{slip['version_no']}; the actions "
                "of this round are frozen",
            )
        return gs, rnd

    def _save(
        self,
        session: Session,
        gs_id: UUID,
        payload: SaveFinalActionsIn,
        user: CurrentUser,
        perms: EffectivePermissions,
    ) -> FinalActionsState:
        gs, rnd = self._lock_round(session, gs_id)
        items = {q["gs_item_id"]: q for q in repo.item_quantities(session, gs_id)}
        groups = self._groups(session, gs_id, rnd)
        version_id = gs["item_field_profile_version_id"]

        def where(key: tuple[UUID, UUID | None]) -> str:
            g = groups.get(key)
            label = f" {g['condition_label']}" if g and g["condition_label"] else ""
            return f"line {items[key[0]]['line_no']}{label}"

        # Every (item, condition) group exactly once (the split is a whole-round decision).
        seen: set[tuple[UUID, UUID | None]] = set()
        for line in payload.lines:
            key = (line.gs_item_id, line.condition_field_id)
            if line.gs_item_id not in items:
                raise ValidationFailed(
                    f"Item {line.gs_item_id} does not belong to goods slip {gs['gs_no']}",
                    code="ITEM_NOT_IN_GS",
                )
            if key not in groups:
                raise ValidationFailed(
                    f"Line {items[line.gs_item_id]['line_no']}: "
                    + (
                        "this condition is not in the item's current condition split (DEC-57)"
                        if rnd == 1
                        else "no Pending pieces of this item / condition to re-action (DEC-57)"
                    ),
                    code="CONDITION_NOT_IN_ITEM" if rnd == 1 else "NOT_PENDING",
                    details={
                        "line_no": items[line.gs_item_id]["line_no"],
                        "condition_field_id": str(line.condition_field_id)
                        if line.condition_field_id
                        else None,
                    },
                )
            if key in seen:
                raise ValidationFailed(
                    f"{where(key).capitalize()} is listed more than once", code="DUPLICATE_LINE"
                )
            seen.add(key)
        missing = sorted(
            {
                items[k[0]]["line_no"]
                for k, g in groups.items()
                if k not in seen and g["available_qty"]
            }
        )
        if missing:
            raise ValidationFailed(
                f"Every line needs its final actions; missing line(s) {missing}",
                code="LINES_MISSING",
                details={"line_nos": missing},
            )

        allowed_cache: dict[UUID, set[str]] = {}
        new_alloc: dict[tuple[UUID, UUID | None], dict[str, int]] = {}
        for line in payload.lines:
            key = (line.gs_item_id, line.condition_field_id)
            item = items[line.gs_item_id]
            if item["product_id"] not in allowed_cache:
                allowed_cache[item["product_id"]] = {
                    a["code"] for a in repo.allowed_actions(session, item["product_id"], version_id)
                }
            allowed = allowed_cache[item["product_id"]]
            alloc: dict[str, int] = {}
            for act in line.actions:
                if act.action_code in alloc:
                    raise ValidationFailed(
                        f"{where(key).capitalize()}: action {act.action_code} is listed twice",
                        code="DUPLICATE_ACTION",
                    )
                if act.qty > 0 and act.action_code not in allowed:
                    raise SystemGuardViolation(
                        "G-21",
                        f"G-21: action {act.action_code} is not allowed by the resolved profile "
                        f"of line {item['line_no']} ({item['product_name']})",
                        details={"line_no": item["line_no"], "action_code": act.action_code},
                    )
                alloc[act.action_code] = act.qty
            total = sum(alloc.values())
            available = groups[key]["available_qty"]
            if total != available:
                raise SystemGuardViolation(
                    "G-21",
                    f"G-21: {where(key)} ({item['product_name']}): action qty total ({total}) "
                    f"must equal the qty available for action ({available})",
                    details={
                        "line_no": item["line_no"],
                        "condition_field_id": str(key[1]) if key[1] else None,
                        "action_total": total,
                        "available_qty": available,
                    },
                )
            new_alloc[key] = {c: q for c, q in alloc.items() if q > 0}

        if rnd == 1:
            # Per item too: legacy routings without a source condition are only counted per item.
            for item_id, item in items.items():
                total = sum(sum(a.values()) for k, a in new_alloc.items() if k[0] == item_id)
                if total != item["available_qty"]:
                    raise SystemGuardViolation(
                        "G-21",
                        f"G-21: line {item['line_no']} ({item['product_name']}): action qty total "
                        f"({total}) must equal the qty available for action "
                        f"({item['available_qty']} = counted {item['counted_qty']} - at "
                        f"departments {item['at_dept_qty']})",
                        details={
                            "line_no": item["line_no"],
                            "action_total": total,
                            "available_qty": item["available_qty"],
                        },
                    )

        old_alloc: dict[tuple[UUID, UUID | None], dict[str, int]] = {}
        for a in repo.current_actions(session, gs_id, rnd):
            old_alloc.setdefault((a["gs_item_id"], a["condition_field_id"]), {})[
                a["action_code"]
            ] = a["qty"]
        unchanged = bool(old_alloc) and {k: v for k, v in new_alloc.items() if v} == old_alloc

        slip = repo.current_slip(session, gs_id, rnd)
        reason = (payload.reason or "").strip() or None
        if slip is not None:
            # AMD-16: finalised actions are revised only with a reason; the slip is superseded.
            if unchanged:
                raise ValidationFailed(
                    f"No change to the finalised actions; {slip['slip_no']} "
                    f"v{slip['version_no']} stays current",
                    code="NO_CHANGE",
                )
            if reason is None:
                raise ValidationFailed(
                    f"A reason is required to revise actions finalised on {slip['slip_no']} "
                    f"v{slip['version_no']}",
                    code="REASON_REQUIRED",
                )
            repo.supersede_slip(session, slip["id"], by=user.id, reason=reason)
            notifications.publish(
                session,
                "AC_ACTIONS_SLIP_SUPERSEDED",
                title=f"{gs['gs_no']}: A/c Actions slip {slip['slip_no']} v{slip['version_no']} "
                "superseded",
                body=f"Revised by {user.full_name}: {reason}. A new version follows when the "
                "Replacement Manager finalises again.",
                entity_type=repo.AC_SLIP_ENTITY,
                entity_id=slip["id"],
                gs_id=gs_id,
                data={"gs_no": gs["gs_no"], "slip_no": slip["slip_no"]},
                dedupe_key=f"ac-slip-superseded:{slip['id']}",
            )
        elif unchanged:
            return self._state(session, gs_id, perms)  # nothing to record

        new_rev = repo.max_revision(session, gs_id) + 1
        repo.retire_current_actions(session, gs_id, rnd)
        for (item_id, cond_id), alloc in new_alloc.items():
            for code, qty in sorted(alloc.items()):
                repo.insert_action(
                    session,
                    gs_item_id=item_id,
                    revision_no=new_rev,
                    round_no=rnd,
                    condition_field_id=cond_id,
                    action_code=code,
                    qty=qty,
                    reason=reason,
                    decided_by=user.id,
                )
        # The DB checks the same now (and again at commit): G-21 split and G-20 conservation.
        repo.validate_split(session, gs_id, complete=False)
        repo.validate_reconciliation(session, gs_id)
        log.info("final_actions_saved", gs_id=str(gs_id), revision_no=new_rev, round_no=rnd)
        return self._state(session, gs_id, perms)

    # === finalise (slip version) ===

    def finalise(
        self,
        gs_id: UUID,
        payload: FinaliseFinalActionsIn,
        user: CurrentUser,
        perms: EffectivePermissions,
        idem: IdempotencyKey,
        storage: StorageService,
    ) -> IdempotentResult:
        uploaded: list[str] = []
        try:
            with self._uow.transaction(user.id) as session:
                return run_idempotent(
                    session,
                    idem,
                    user.id,
                    lambda: (
                        200,
                        self._finalise(
                            session, gs_id, payload, user, perms, storage, uploaded.append
                        ),
                    ),
                )
        except Exception:
            # The transaction rolled back, so the stored PDF has no row: remove it, then re-raise.
            for path in uploaded:
                try:
                    storage.delete(Bucket.DOCUMENTS, path)
                except ServiceUnavailable:
                    log.error("ac_slip_orphan_pdf_not_removed", gs_id=str(gs_id), path=path)
            raise

    def _finalise(
        self,
        session: Session,
        gs_id: UUID,
        payload: FinaliseFinalActionsIn,
        user: CurrentUser,
        perms: EffectivePermissions,
        storage: StorageService,
        on_uploaded: Callable[[str], None],
    ) -> FinalActionsState:
        gs, rnd = self._lock_round(session, gs_id)
        existing = repo.current_slip(session, gs_id, rnd)
        if existing is not None:
            raise Conflict(
                f"Already finalised on {existing['slip_no']} v{existing['version_no']}",
                code="ALREADY_FINALISED",
            )
        items = repo.item_quantities(session, gs_id)
        revision_no = repo.max_revision(session, gs_id)
        if not repo.current_actions(session, gs_id, rnd):
            raise SystemGuardViolation(
                "G-21",
                "G-21: no RM final actions have been saved for this goods slip"
                + (f" (re-action round {rnd})" if rnd > 1 else ""),
            )
        if rnd == 1:
            planned = department_routing_service.planned_qty_by_item(session, gs_id)
            for q in items:
                if planned.get(q["gs_item_id"], 0) > 0:
                    raise SystemGuardViolation(
                        "G-21",
                        f"G-21: line {q['line_no']} ({q['product_name']}) has "
                        f"{planned[q['gs_item_id']]} pc(s) planned for a department but not "
                        "issued by the store; issue or cancel them before finalising",
                    )
                if q["at_dept_qty"] > 0:
                    raise SystemGuardViolation(
                        "G-21",
                        f"G-21: line {q['line_no']} ({q['product_name']}) still has "
                        f"{q['at_dept_qty']} pc(s) at a department; receive them back first",
                    )
                if q["actioned_qty"] != q["counted_qty"]:
                    raise SystemGuardViolation(
                        "G-21",
                        f"G-21: line {q['line_no']} ({q['product_name']}): action qty total "
                        f"({q['actioned_qty']}) must equal the counted qty ({q['counted_qty']})",
                    )
        # DEC-57: every item + condition group of the round is exactly allocated.
        actioned: dict[tuple[UUID, UUID | None], int] = {}
        for a in repo.current_actions(session, gs_id, rnd):
            key = (a["gs_item_id"], a["condition_field_id"])
            actioned[key] = actioned.get(key, 0) + int(a["qty"])
        line_nos = {q["gs_item_id"]: q["line_no"] for q in items}
        for key, g in self._groups(session, gs_id, rnd).items():
            if actioned.get(key, 0) != g["available_qty"]:
                where = f" {g['condition_label']}" if g["condition_label"] else ""
                raise SystemGuardViolation(
                    "G-21",
                    f"G-21: line {line_nos[key[0]]}{where}: action qty total "
                    f"({actioned.get(key, 0)}) must equal the qty to action ({g['available_qty']})",
                )
        repo.validate_split(session, gs_id, complete=True)
        if rnd > 1:
            items = [q for q in items if any(k[0] == q["gs_item_id"] for k in actioned)]

        template = repo.published_template(session, repo.AC_SLIP_TEMPLATE)
        if not template:
            raise Conflict(
                "No published AC_ACTIONS_SLIP print template", code="TEMPLATE_NOT_PUBLISHED"
            )

        prev = repo.latest_slip_identity(session, gs_id)
        slip_no = prev["slip_no"] if prev else repo.next_number(session, repo.AC_SLIP_SERIES)
        version_no = (prev["version_no"] + 1) if prev else 1
        slip_id = uuid.uuid4()
        remarks = (payload.remarks or "").strip() or None

        content, totals = self._slip_content(
            session,
            gs,
            items,
            slip_no=slip_no,
            version_no=version_no,
            revision_no=revision_no,
            round_no=rnd,
            user=user,
            remarks=remarks,
        )
        pdf = render_slip_pdf(self._slip_document(session, template, content))
        digest = hashlib.sha256(pdf).hexdigest()

        path = build_object_path(gs_id, "generated_pdf", "pdf")
        storage.upload(Bucket.DOCUMENTS, path, pdf, PDF_MIME)
        on_uploaded(path)

        attachment_id = repo.insert_generated_pdf(
            session,
            gs_id=gs_id,
            entity_id=slip_id,
            bucket=Bucket.DOCUMENTS.value,
            object_path=path,
            size_bytes=len(pdf),
            by=user.id,
        )
        repo.insert_slip(
            session,
            slip_id=slip_id,
            gs_id=gs_id,
            slip_no=slip_no,
            version_no=version_no,
            revision_no=revision_no,
            round_no=rnd,
            attachment_id=attachment_id,
            template_version_no=int(template["version_no"]),
            content=content,
            totals=totals,
            sha256=digest,
            remarks=remarks,
            by=user.id,
        )
        # AMD-17: Accounts is told the slip is ready. Recipients come from the notification rule
        # (seeded: ACCOUNTS role), not from code.
        what = (
            f"re-actioned the Pending pieces (round {rnd}, {totals['total_qty']} pc(s))"
            if rnd > 1
            else f"finalised the item actions ({totals['total_qty']} pc(s))"
        )
        notifications.publish(
            session,
            "AC_ACTIONS_SLIP_READY",
            title=f"{gs['gs_no']}: A/c Actions slip {slip_no} v{version_no} ready"
            + (f" (Pending re-action, round {rnd})" if rnd > 1 else ""),
            body=(
                f"{user.full_name} {what}. "
                "Open the goods slip to print the Replacement Slip \u2013 A/c Actions."
            ),
            entity_type=repo.AC_SLIP_ENTITY,
            entity_id=slip_id,
            gs_id=gs_id,
            data={"gs_no": gs["gs_no"], "slip_no": slip_no, "version_no": version_no},
            dedupe_key=f"ac-slip-ready:{slip_id}",
        )
        log.info(
            "ac_slip_finalised",
            gs_id=str(gs_id),
            slip_no=slip_no,
            version_no=version_no,
            revision_no=revision_no,
            round_no=rnd,
            size=len(pdf),
        )
        return self._state(session, gs_id, perms)

    def _slip_content(
        self,
        session: Session,
        gs: dict[str, Any],
        items: list[dict[str, Any]],
        *,
        slip_no: str,
        version_no: int,
        revision_no: int,
        round_no: int,
        user: CurrentUser,
        remarks: str | None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """The exact data printed on the slip (stored with the version, G-18). DEC-57: one line
        per item + condition + action of the round."""
        tz = _tz(session)
        fmt = _date_fmt(session)
        library = repo.action_library_labels(session)
        by_item: dict[UUID, list[dict[str, Any]]] = {}
        cond_order: dict[UUID | None, int] = {}
        for a in repo.current_actions(session, gs["id"], round_no):  # ordered by condition
            by_item.setdefault(a["gs_item_id"], []).append(a)
            cond_order.setdefault(a["condition_field_id"], len(cond_order))

        lines: list[dict[str, Any]] = []
        totals_by_code: dict[str, dict[str, Any]] = {}
        for q in items:
            acts = sorted(
                by_item.get(q["gs_item_id"], []),
                key=lambda a: (
                    cond_order[a["condition_field_id"]],
                    library.get(a["action_code"], {}).get("sort_order", 0),
                    a["action_code"],
                ),
            )
            for a in acts:
                lib = library.get(a["action_code"], {})
                lines.append(
                    {
                        "line_no": q["line_no"],
                        "product_code": q["product_code"],
                        "product_name": q["product_name"],
                        "counted_qty": q["counted_qty"],
                        "condition_code": a["condition_code"],
                        "condition_label": a["condition_label"],
                        "action_code": a["action_code"],
                        "action_label": a["label"],
                        "qty": a["qty"],
                        "requires_cn": bool(lib.get("requires_cn")),
                        "requires_challan": bool(lib.get("requires_challan")),
                    }
                )
                t = totals_by_code.setdefault(
                    a["action_code"],
                    {
                        "action_code": a["action_code"],
                        "action_label": a["label"],
                        "qty": 0,
                        "_sort": lib.get("sort_order", 0),
                    },
                )
                t["qty"] += a["qty"]

        by_action = [
            {k: v for k, v in t.items() if k != "_sort"}
            for t in sorted(totals_by_code.values(), key=lambda t: (t["_sort"], t["action_code"]))
        ]
        totals = {
            "total_qty": sum(t["qty"] for t in by_action),
            "counted_qty": sum(q["counted_qty"] for q in items),
            "by_action": by_action,
        }
        state_station = " / ".join(x for x in (gs["state_name"], gs["station_name"]) if x)
        docs = [
            " ".join(
                x
                for x in (d["doc_type_label"], d["doc_no"] or "", _fmt_date(d["doc_date"], fmt, tz))
                if x
            )
            for d in repo.list_gate_documents(session, gs["id"])
        ]
        content = {
            "slip_no": slip_no,
            "version_no": version_no,
            "revision_no": revision_no,
            "round_no": round_no,
            "gs_no": gs["gs_no"],
            "gs_date": _fmt_date(gs["created_at"], fmt, tz),
            "return_type": gs["return_type_label"] or gs["return_type_code"] or "",
            "carton_count": gs["carton_count"],
            "party_name": gs["party_name"] or "",
            "party_code": gs["party_code"] or "",
            "state_station": state_station,
            "gate_entry_no": gs["gate_entry_no"] or "",
            "gate_entry_date": _fmt_date(gs["gate_entry_date"], fmt, tz),
            "gate_documents": docs
            or (["No document (missing documentation)"] if gs["missing_documentation"] else []),
            "lines": lines,
            "totals": totals,
            "prepared_by": user.full_name,
            "finalised_at": datetime.now(tz).strftime(f"{fmt} %H:%M"),
            "remarks": remarks,
        }
        return content, totals

    def _slip_document(
        self, session: Session, template: dict[str, Any], c: dict[str, Any]
    ) -> SlipDocument:
        """Map the published template layout (DEC-41: branding is configuration) + content."""
        layout: dict[str, Any] = template["layout"] or {}
        titles = {
            s.get("id"): s.get("title") for s in layout.get("sections", []) if isinstance(s, dict)
        }

        def title(section_id: str, fallback: str) -> str:
            return str(titles.get(section_id) or fallback)

        brand = repo.get_setting(session, "branding_primary_color")
        signatures = []
        for i, block in enumerate(layout.get("signature_blocks", [])):
            if not isinstance(block, dict):
                continue
            signatures.append(
                SlipSignature(
                    label=str(block.get("label", "")),
                    role=str(block.get("role", "")),
                    name=c["prepared_by"] if i == 0 else None,
                )
            )
        rows = [
            [
                str(ln["line_no"]),
                ln["product_code"] or "",
                ln["product_name"],
                str(ln["counted_qty"]),
                ln.get("condition_label") or "",
                ln["action_label"],
                str(ln["qty"]),
            ]
            for ln in c["lines"]
        ]
        totals = c["totals"]
        round_no = int(c.get("round_no") or 1)
        sections = [
            SlipSection(
                title("gs_header", "Goods Slip"),
                [
                    SlipField("GS No.", c["gs_no"]),
                    SlipField("GS Date", c["gs_date"]),
                    SlipField("Return Type", c["return_type"]),
                    SlipField("Cartons", str(c["carton_count"] or "")),
                    SlipField("Slip No.", f"{c['slip_no']} (v{c['version_no']})"),
                    SlipField("Action Revision", str(c["revision_no"])),
                    *(
                        [SlipField("Round", f"{round_no} (re-action of Pending pieces)")]
                        if round_no > 1
                        else []
                    ),
                ],
            ),
            SlipSection(
                title("party", "Party"),
                [
                    SlipField("Party", c["party_name"]),
                    SlipField("Party Code", c["party_code"]),
                    SlipField("State / Station", c["state_station"]),
                ],
            ),
            SlipSection(
                title("gate_entry", "Gate Entry"),
                [
                    SlipField("Gate Entry No.", str(c["gate_entry_no"])),
                    SlipField("Gate Entry Date", c["gate_entry_date"]),
                    SlipField("Documents", "\n".join(c["gate_documents"])),
                    *([SlipField("Remarks", c["remarks"])] if c.get("remarks") else []),
                ],
            ),
        ]
        return SlipDocument(
            title=str(layout.get("header_title") or template.get("name") or ""),
            subtitle=str(layout.get("header_subtitle") or template.get("name") or ""),
            document_ref=f"{c['slip_no']} · Version {c['version_no']} · {c['gs_no']}",
            sections=sections,
            tables=[
                SlipTable(
                    title=title("items", "Item \u00d7 Action \u00d7 Qty"),
                    columns=[
                        SlipColumn("#", 0.4, "right"),
                        SlipColumn("Code", 1.0),
                        SlipColumn("Product", 2.4),
                        SlipColumn("Counted", 0.8, "right"),
                        SlipColumn("Condition", 1.4),
                        SlipColumn("Action", 1.4),
                        SlipColumn("Qty", 0.6, "right"),
                    ],
                    rows=rows,
                    total_row=[
                        "",
                        "",
                        "Total",
                        str(totals["counted_qty"]),
                        "",
                        "",
                        str(totals["total_qty"]),
                    ],
                ),
                SlipTable(
                    title=title("totals", "Totals by Action"),
                    columns=[SlipColumn("Action", 3), SlipColumn("Qty", 1, "right")],
                    rows=[[t["action_label"], str(t["qty"])] for t in totals["by_action"]],
                    total_row=["Total", str(totals["total_qty"])],
                ),
            ],
            signatures=signatures,
            signatures_title=title("signatures", "Signatures"),
            footer_text=str(layout.get("footer_text") or ""),
            generated_text=f"Finalised {c['finalised_at']} by {c['prepared_by']}",
            brand_color=str(brand or ""),
            paper_size=str(layout.get("paper_size") or "A4"),
            orientation=str(layout.get("orientation") or "portrait"),
            logo=template_logo(session, layout),  # DEC-65 / Q26
        )

    # === print / re-print ===

    def print_slip(
        self, gs_id: UUID, slip_id: UUID, user: CurrentUser, storage: StorageService
    ) -> AcSlipPrintOut:
        """Any version, any time (AMD-17). Every print is logged; the stored file is returned."""
        with self._uow.transaction(user.id) as session:
            slip = repo.get_slip(session, gs_id, slip_id)
            if not slip:
                raise NotFound(
                    f"Slip {slip_id} not found on goods slip {gs_id}", code="SLIP_NOT_FOUND"
                )
            ttl = signed_url_ttl(session)
            url = storage.create_signed_url(Bucket(slip["bucket"]), slip["object_path"], ttl)
            repo.insert_print_log(
                session,
                slip_id=slip_id,
                version_no=slip["version_no"],
                by=user.id,
                metadata={
                    "gs_id": str(gs_id),
                    "slip_no": slip["slip_no"],
                    "version_no": slip["version_no"],
                    "status": slip["status"],
                    "is_reprint": int(slip["print_count"]) > 0,
                },
            )
            return AcSlipPrintOut(
                slip_id=slip_id,
                slip_no=slip["slip_no"],
                version_no=slip["version_no"],
                status=slip["status"],
                url=url,
                expires_in=ttl,
                print_count=int(slip["print_count"]) + 1,
            )
