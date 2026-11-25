"""Management approval and the e-approval stamp (Phase P10; DEC-70; Q17 CONFIRMED, Q18 PROVISIONAL).

* Queue: goods slips a store sent for Management approval (open request, reason shown) and every
  goods slip between analysis and Accounts (ANALYSIS_COMPLETED), searchable.
* Changes: once every store submitted (ANALYSIS_COMPLETED), Management changes any decision of an
  item + condition to any other (incl. ISSUE_CN and back), moves quantities between actions and adds
  or removes decision lines; a reason per change; one revision per save (rm_item_actions history +
  gs_management_revisions). G-21: each item + condition still totals its pieces. Analysis moves no
  stock (DEC-69), so there is no stock to correct.
* Approve: the DB computes the canonical snapshot of the GS lines + decisions and its SHA-256 and
  stores the approval append-only (approver, role, time); the open request is resolved. Any later
  change makes the latest approval CHANGED (a new approval is needed).
* Stamp / Verify: "<title> — <name>, <date time>, ref <short hash>"; Verify recomputes the hash.
* Accounts gate (Q18): `assert_accounts_gate` (service) mirrors
  rms_private.gs_management_gate_problem (DB: G-03 exit of ANALYSIS_COMPLETED and the A/c slip
  insert). P11 calls it.

Commands run in one transaction and are idempotent on `Idempotency-Key` (G-16).
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from types import ModuleType
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
from app.modules.management_approval import repository as repo
from app.modules.management_approval.schemas import (
    AccountsGateOut,
    ActionOptionOut,
    ApprovalOut,
    ApprovalState,
    ApproveIn,
    ChangeDecisionOut,
    ChangeOut,
    ChangesIn,
    DecisionOut,
    GroupOut,
    ItemOut,
    ManagementGsOut,
    QueueRowOut,
    RequestOut,
    RevisionOut,
    StampOut,
    StoreProgressOut,
    VerifyOut,
)
from app.modules.notifications import service as notifications
from app.shared.storage import Bucket, StorageService

log = structlog.get_logger(__name__)


def ac_entry() -> ModuleType:
    """The Accounts service module (DEC-71 gate / reopen). Imported on use: ac_entry imports this
    module (stamp, gate), so a top-level import would be circular."""
    from app.modules.ac_entry import service

    return service


EDIT_STATUS = "ANALYSIS_COMPLETED"
# DEC-71 (P11): Management may also change a goods slip at Accounts (entry not completed) or on
# hold (all Not Allowed); the change reopens it (Replacement Slip withdrawn) and its next approval
# routes it to Accounts again.
REOPEN_STATUSES = frozenset({"ACCOUNTS_PENDING", "NOT_ALLOWED_HOLD"})
# DEC-69: Pending is not used on the Intermediate Store flow (single round); every other action of
# the product's profile is open to Management (DEC-70, incl. ISSUE_CN).
RETIRED_ACTIONS = frozenset({"PENDING_BP"})
# DEC-74: a store's "Issue CN Request" (stable code). Management answers it with Issue CN or another
# action; it is never a Management option, and the goods slip neither reaches Accounts nor is
# approved while pieces are still on it (DB: gs_management_gate_problem / approvals guard).
CN_REQUEST_ACTION = "ISSUE_CN_REQUEST"
NOT_MANAGEMENT_OPTIONS = RETIRED_ACTIONS | {CN_REQUEST_ACTION}
SHORT_REF = 12
STAMP_TITLE_SETTING = "management_approval_stamp_title"


# --- helpers ------------------------------------------------------------------------------------


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


def _datetime_text(session: Session, value: datetime) -> str:
    raw = str(repo.get_setting(session, "date_format") or "DD-MM-YYYY")
    fmt = raw.replace("YYYY", "%Y").replace("MM", "%m").replace("DD", "%d") + " %H:%M"
    return value.astimezone(_tz(session)).strftime(fmt)


def _approval_out(row: dict[str, Any]) -> ApprovalOut:
    return ApprovalOut(
        id=row["id"],
        approval_no=row["approval_no"],
        approver_name=row["approver_name"],
        approver_role=row["approver_role"],
        approved_at=row["approved_at"],
        revision_no=row["revision_no"],
        snapshot_sha256=row["snapshot_sha256"],
        short_ref=row["snapshot_sha256"][:SHORT_REF],
        has_issue_cn=row["has_issue_cn"],
        remarks=row["remarks"],
        request_id=row["request_id"],
    )


def _stamp_text(session: Session, approval: dict[str, Any]) -> str:
    title = repo.get_setting(session, STAMP_TITLE_SETTING)
    if not title:
        # Configuration problem, not a silent default (rule e / j): the stamp names its title.
        log.error("management_stamp_title_missing", key=STAMP_TITLE_SETTING)
        raise Conflict(
            f"System setting '{STAMP_TITLE_SETTING}' is empty",
            code="SETTING_INVALID",
            details={"key": STAMP_TITLE_SETTING},
        )
    when = _datetime_text(session, approval["approved_at"])
    return (
        f"{title} — {approval['approver_name']}, {when}, "
        f"ref {approval['snapshot_sha256'][:SHORT_REF]}"
    )


def _stamp(session: Session, gs: dict[str, Any]) -> StampOut:
    latest = repo.latest_approval(session, gs["id"])
    state = repo.approval_state(session, gs["id"])
    return StampOut(
        gs_id=gs["id"],
        gs_no=gs["gs_no"],
        state=state,  # type: ignore[arg-type]  # NONE | VALID | CHANGED from the DB function
        approval=_approval_out(latest) if latest else None,
        stamp_text=_stamp_text(session, latest) if latest and state == "VALID" else None,
    )


def stamp_for_print(session: Session, gs_id: UUID) -> str | None:
    """DEC-70: the stamp line printed on the Replacement Slip / Dispatch Slip of a goods slip,
    only while its latest Management approval is VALID (None otherwise). Service-to-service API for
    final_actions / ac_entry (rule g)."""
    if repo.approval_state(session, gs_id) != "VALID":
        return None
    latest = repo.latest_approval(session, gs_id)
    return _stamp_text(session, latest) if latest else None


def accounts_gate_problem(session: Session, gs_id: UUID) -> str | None:
    """DEC-70 / Q18: why the goods slip may not reach Accounts yet (None = the gate passes).
    Same rule as rms_private.gs_management_gate_problem. Service-to-service API for ac_entry."""
    problem = repo.gate_problem(session, gs_id)
    return str(problem) if problem else None


def assert_accounts_gate(session: Session, gs_id: UUID) -> None:
    """DEC-70 / Q18: a store-flow goods slip reaches Accounts only with no open Management request,
    Issue CN only under a VALID approval, and no Management change without a VALID approval. The DB
    enforces the same (G-03 exit of ANALYSIS_COMPLETED, A/c slip insert). Called by P11."""
    gs = repo.get_gs(session, gs_id)
    if not gs or not gs["on_store_flow"]:
        return
    problem = repo.gate_problem(session, gs_id)
    if problem:
        raise Conflict(
            problem,
            code="MANAGEMENT_APPROVAL_REQUIRED",
            details={"gs_no": gs["gs_no"], "approval_state": repo.approval_state(session, gs_id)},
        )


class ManagementApprovalService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    # --- queries -----------------------------------------------------------------------------

    def queue(self, actor: CurrentUser, q: str | None) -> list[QueueRowOut]:
        term = (q or "").strip() or None
        with self._uow.transaction(actor.id) as session:
            return [
                QueueRowOut.model_validate(r) for r in repo.queue(session, repo.OPEN_STATUSES, term)
            ]

    def get_gs(
        self, actor: CurrentUser, perms: EffectivePermissions, gs_id: UUID
    ) -> ManagementGsOut:
        with self._uow.transaction(actor.id) as session:
            return self._gs(session, perms, gs_id)

    def stamp(self, actor: CurrentUser, gs_id: UUID) -> StampOut:
        with self._uow.transaction(actor.id) as session:
            return _stamp(session, self._load_gs(session, gs_id))

    def verify(self, actor: CurrentUser, gs_id: UUID) -> VerifyOut:
        """Recompute the hash of the goods slip now and of the stored snapshot (Q17)."""
        with self._uow.transaction(actor.id) as session:
            gs = self._load_gs(session, gs_id)
            current_text, current_db = repo.current_snapshot(session, gs_id)
            current = hashlib.sha256(current_text.encode("utf-8")).hexdigest()
            if current != current_db:
                # Never expected: the canonical text hashes differently in Python and in the DB.
                log.error("management_snapshot_hash_mismatch", gs_id=str(gs_id))
                raise Conflict(
                    "The approval hash could not be recomputed consistently",
                    code="HASH_MISMATCH",
                )
            latest = repo.latest_approval(session, gs_id)
            now = datetime.now(UTC)
            if latest is None:
                return VerifyOut(
                    gs_id=gs["id"],
                    result="NONE",
                    current_sha256=current,
                    integrity_ok=True,
                    checked_at=now,
                )
            stored = str(latest["snapshot_sha256"])
            integrity = (
                hashlib.sha256(str(latest["snapshot_text"]).encode("utf-8")).hexdigest() == stored
                and latest["stored_snapshot_sha256"] == stored
            )
            result: ApprovalState = "VALID" if integrity and current == stored else "CHANGED"
            log.info(
                "management_approval_verified",
                gs_id=str(gs_id),
                approval_no=latest["approval_no"],
                result=result,
                integrity_ok=integrity,
            )
            return VerifyOut(
                gs_id=gs["id"],
                result=result,
                approval=_approval_out(latest),
                stored_sha256=stored,
                current_sha256=current,
                integrity_ok=integrity,
                checked_at=now,
            )

    @staticmethod
    def _load_gs(session: Session, gs_id: UUID, *, lock: bool = False) -> dict[str, Any]:
        gs = repo.get_gs(session, gs_id, lock=lock)
        if not gs:
            raise NotFound(f"Goods slip {gs_id} not found", code="GS_NOT_FOUND")
        return gs

    def _gs(self, session: Session, perms: EffectivePermissions, gs_id: UUID) -> ManagementGsOut:
        gs = self._load_gs(session, gs_id)
        if not gs["on_store_flow"]:
            raise NotFound(
                f"Goods slip {gs['gs_no']} is not on the Intermediate Store flow",
                code="GS_NOT_ON_STORE_FLOW",
            )
        version_id = gs["item_field_profile_version_id"]
        stores = [StoreProgressOut.model_validate(s) for s in repo.store_progress(session, gs_id)]
        decisions: dict[tuple[UUID, UUID | None], list[DecisionOut]] = {}
        for a in repo.current_actions(session, gs_id):
            decisions.setdefault((a["gs_item_id"], a["condition_field_id"]), []).append(
                DecisionOut(
                    action_code=a["action_code"],
                    label=a["label"],
                    qty=a["qty"],
                    is_cn_request=a["action_code"] == CN_REQUEST_ACTION,
                )
            )
        options: dict[UUID, list[ActionOptionOut]] = {}
        items: dict[UUID, ItemOut] = {}
        for g in repo.groups(session, gs_id):
            item = items.get(g["gs_item_id"])
            if item is None:
                if g["product_id"] not in options:
                    options[g["product_id"]] = [
                        ActionOptionOut(**a)
                        for a in repo.allowed_actions(session, g["product_id"], version_id)
                        if a["code"] not in NOT_MANAGEMENT_OPTIONS
                    ]
                item = items[g["gs_item_id"]] = ItemOut(
                    gs_item_id=g["gs_item_id"],
                    line_no=g["line_no"],
                    product_code=g["product_code"],
                    product_name=g["product_name"],
                    received_qty=g["received_qty"],
                    store_code=g["store_code"],
                    store_name=g["store_name"],
                    options=options[g["product_id"]],
                )
            group_decisions = decisions.get((g["gs_item_id"], g["condition_field_id"]), [])
            item.groups.append(
                GroupOut(
                    condition_field_id=g["condition_field_id"],
                    condition_code=g["condition_code"],
                    condition_label=g["condition_label"],
                    qty=g["available_qty"],
                    decisions=group_decisions,
                    cn_requested_qty=sum(d.qty for d in group_decisions if d.is_cn_request),
                )
            )
        requests = [RequestOut.model_validate(r) for r in repo.list_requests(session, gs_id)]
        open_request = next((r for r in requests if r.status == "OPEN"), None)
        may_approve = perms.allows("management_approval", "approve")
        waiting = [s.store_code for s in stores if s.analysis_status != "SUBMITTED"]
        blocked: str | None = None
        if gs["status"] != EDIT_STATUS:
            blocked = (
                f"Waiting for the analysis of {', '.join(waiting)}; Management changes and "
                "approves the goods slip once every store has submitted."
                if waiting
                else f"The goods slip is {gs['status']}; Management changes it between the "
                "analysis and Accounts."
            )
        problem = repo.gate_problem(session, gs_id)
        item_list = list(items.values())
        return ManagementGsOut(
            gs_id=gs["id"],
            gs_no=gs["gs_no"],
            status=gs["status"],
            party_name=gs["party_name"],
            station_name=gs["station_name"],
            stores=stores,
            items=item_list,
            cn_request_qty=sum(g.cn_requested_qty for it in item_list for g in it.groups),
            can_edit=may_approve
            and (gs["status"] == EDIT_STATUS or gs["status"] in REOPEN_STATUSES),
            can_approve=may_approve and gs["status"] == EDIT_STATUS,
            blocked_reason=blocked,
            open_request=open_request,
            requests=requests,
            revisions=[RevisionOut.model_validate(r) for r in repo.list_revisions(session, gs_id)],
            approvals=[_approval_out(a) for a in repo.list_approvals(session, gs_id)],
            stamp=_stamp(session, gs),
            accounts_gate=AccountsGateOut(passes=problem is None, problem=problem),
            reopen_notice=(
                "The goods slip is at Accounts: saving a change withdraws its Replacement Slip "
                "until you approve it again."
                if gs["status"] == "ACCOUNTS_PENDING"
                else "The goods slip is on hold (every decision Not Allowed): saving a change "
                "reopens it; approve it to send it on."
                if gs["status"] == "NOT_ALLOWED_HOLD"
                else None
            ),
        )

    def _editable(
        self, session: Session, gs_id: UUID, *, reopenable: bool = False
    ) -> dict[str, Any]:
        gs = self._load_gs(session, gs_id, lock=True)
        if not gs["on_store_flow"]:
            raise Conflict(
                f"Goods slip {gs['gs_no']} is not on the Intermediate Store flow",
                code="GS_NOT_ON_STORE_FLOW",
            )
        if gs["status"] != EDIT_STATUS and not (reopenable and gs["status"] in REOPEN_STATUSES):
            waiting = [
                s["store_code"]
                for s in repo.store_progress(session, gs_id)
                if s["analysis_status"] != "SUBMITTED"
            ]
            raise Conflict(
                f"{gs['gs_no']} is {gs['status']}: Management changes and approves a goods slip "
                "once every Intermediate Store has submitted its analysis"
                + (f" (waiting for {', '.join(waiting)})" if waiting else ""),
                code="INVALID_GS_STATUS",
                details={"status": gs["status"], "waiting_store_codes": waiting},
            )
        return gs

    # --- changes -----------------------------------------------------------------------------

    def save_changes(
        self,
        actor: CurrentUser,
        perms: EffectivePermissions,
        gs_id: UUID,
        payload: ChangesIn,
        idem: IdempotencyKey,
    ) -> IdempotentResult:
        with self._uow.transaction(actor.id) as session:
            return run_idempotent(
                session,
                idem,
                actor.id,
                lambda: (
                    200,
                    self._save_changes(session, actor, perms, gs_id, payload).model_dump(
                        mode="json"
                    ),
                ),
            )

    def _save_changes(
        self,
        session: Session,
        actor: CurrentUser,
        perms: EffectivePermissions,
        gs_id: UUID,
        payload: ChangesIn,
    ) -> ManagementGsOut:
        gs = self._editable(session, gs_id, reopenable=True)
        version_id = gs["item_field_profile_version_id"]
        groups = {
            (g["gs_item_id"], g["condition_field_id"]): g for g in repo.groups(session, gs_id)
        }
        current: dict[tuple[UUID, UUID | None], list[dict[str, Any]]] = {}
        for a in repo.current_actions(session, gs_id):
            current.setdefault((a["gs_item_id"], a["condition_field_id"]), []).append(a)

        def where(g: dict[str, Any]) -> str:
            cond = f" ({g['condition_label']})" if g["condition_label"] else ""
            return f"Item #{g['line_no']} {g['product_name']}{cond}"

        allowed: dict[UUID, dict[str, str]] = {}
        seen: set[tuple[UUID, UUID | None]] = set()
        planned: list[tuple[dict[str, Any], list[tuple[str, int]], str, list[dict[str, Any]]]] = []
        for change in payload.changes:
            key = (change.gs_item_id, change.condition_field_id)
            grp = groups.get(key)
            if grp is None:
                raise ValidationFailed(
                    f"A change names an item / condition that is not on {gs['gs_no']}",
                    code="CONDITION_NOT_IN_ITEM",
                    details={"gs_item_id": str(change.gs_item_id)},
                )
            if key in seen:
                raise ValidationFailed(
                    f"{where(grp)} is listed more than once", code="DUPLICATE_LINE"
                )
            seen.add(key)
            reason = change.reason.strip()
            if len(reason) < 3:
                raise ValidationFailed(
                    f"{where(grp)}: a reason is required (at least 3 characters)",
                    code="REASON_REQUIRED",
                )
            if grp["product_id"] not in allowed:
                allowed[grp["product_id"]] = {
                    a["code"]: a["label"]
                    for a in repo.allowed_actions(session, grp["product_id"], version_id)
                    if a["code"] not in NOT_MANAGEMENT_OPTIONS
                }
            codes: set[str] = set()
            new: list[tuple[str, int]] = []
            for d in change.decisions:
                if d.action_code in codes:
                    raise ValidationFailed(
                        f"{where(grp)}: {d.action_code} is listed twice", code="DUPLICATE_ACTION"
                    )
                codes.add(d.action_code)
                if d.qty == 0:
                    continue  # a removed line
                if d.action_code == CN_REQUEST_ACTION:
                    # DEC-74: Management answers a store's request; it never raises one.
                    raise ValidationFailed(
                        f"{where(grp)}: Issue CN Request is raised by a store; decide those pieces "
                        "as Issue CN or another action",
                        code="CN_REQUEST_NOT_MANAGEMENT",
                    )
                if d.action_code not in allowed[grp["product_id"]]:
                    raise SystemGuardViolation(
                        "G-21",
                        f"G-21: {d.action_code} is not allowed by the resolved profile of "
                        f"item #{grp['line_no']} ({grp['product_name']})",
                        details={"line_no": grp["line_no"], "action_code": d.action_code},
                    )
                new.append((d.action_code, d.qty))
            total = sum(q for _, q in new)
            if total != grp["available_qty"]:
                raise SystemGuardViolation(
                    "G-21",
                    f"G-21: {where(grp)}: decisions total {total} pc(s), it has "
                    f"{grp['available_qty']} pc(s)",
                    details={
                        "line_no": grp["line_no"],
                        "decided_qty": total,
                        "qty": grp["available_qty"],
                    },
                )
            before = current.get(key, [])
            if sorted(new) == sorted((a["action_code"], a["qty"]) for a in before):
                continue  # unchanged: nothing to record
            planned.append((grp, sorted(new), reason, before))
        if not planned:
            raise ValidationFailed("Nothing changed", code="NO_CHANGES")
        if gs["status"] in REOPEN_STATUSES:
            # DEC-71: withdraw the Replacement Slip / leave the hold first (one transaction).
            ac_entry().reopen_for_management(
                session, gs_id, actor, "; ".join(sorted({p[2] for p in planned}))
            )

        revision_no = repo.max_revision(session, gs_id) + 1
        history: list[dict[str, Any]] = []
        for grp, new, reason, before in planned:
            repo.retire_group(session, grp["gs_item_id"], grp["condition_field_id"])
            labels = allowed[grp["product_id"]]
            for code, qty in new:
                repo.insert_action(
                    session,
                    gs_item_id=grp["gs_item_id"],
                    revision_no=revision_no,
                    condition_field_id=grp["condition_field_id"],
                    action_code=code,
                    qty=qty,
                    reason=reason,
                    decided_by=actor.id,
                )
            history.append(
                ChangeOut(
                    line_no=grp["line_no"],
                    product_name=grp["product_name"],
                    condition_label=grp["condition_label"],
                    before=[
                        ChangeDecisionOut(
                            action_code=a["action_code"], label=a["label"], qty=a["qty"]
                        )
                        for a in before
                    ],
                    after=[
                        ChangeDecisionOut(action_code=c, label=labels.get(c, c), qty=q)
                        for c, q in new
                    ],
                    reason=reason,
                ).model_dump(mode="json")
            )
        repo.insert_revision(session, gs_id=gs_id, revision_no=revision_no, changes=history)
        # The DB checks the same now (and again at commit): G-21 per item + condition.
        repo.validate_store_analysis(session, gs_id)
        log.info(
            "management_changes_saved",
            gs_id=str(gs_id),
            revision_no=revision_no,
            groups=len(planned),
            approval_state=repo.approval_state(session, gs_id),
        )
        return self._gs(session, perms, gs_id)

    # --- approve -----------------------------------------------------------------------------

    def approve(
        self,
        actor: CurrentUser,
        perms: EffectivePermissions,
        gs_id: UUID,
        payload: ApproveIn,
        idem: IdempotencyKey,
        storage: StorageService,
    ) -> IdempotentResult:
        uploaded: list[str] = []
        try:
            with self._uow.transaction(actor.id) as session:
                return run_idempotent(
                    session,
                    idem,
                    actor.id,
                    lambda: (
                        200,
                        self._approve(
                            session, actor, perms, gs_id, payload, storage, uploaded.append
                        ).model_dump(mode="json"),
                    ),
                )
        except Exception:
            # Rolled back: the Replacement Slip PDF stored by the routing has no row; remove it.
            for path in uploaded:
                try:
                    storage.delete(Bucket.DOCUMENTS, path)
                except ServiceUnavailable:
                    log.error(
                        "replacement_slip_orphan_pdf_not_removed", gs_id=str(gs_id), path=path
                    )
            raise

    def _approve(
        self,
        session: Session,
        actor: CurrentUser,
        perms: EffectivePermissions,
        gs_id: UUID,
        payload: ApproveIn,
        storage: StorageService,
        on_uploaded: Callable[[str], None],
    ) -> ManagementGsOut:
        gs = self._editable(session, gs_id)
        pending_cn = repo.open_cn_request_qty(session, gs_id)
        if pending_cn > 0:
            # DEC-74 (the DB approvals guard refuses the same).
            raise Conflict(
                f"{gs['gs_no']}: {pending_cn} pc(s) are still an Issue CN Request from a store; "
                "decide them (Issue CN or another action) and save before approving",
                code="CN_REQUEST_UNDECIDED",
                details={"cn_request_qty": pending_cn},
            )
        requests = repo.list_requests(session, gs_id)
        open_request = next((r for r in requests if r["status"] == "OPEN"), None)
        if repo.approval_state(session, gs_id) == "VALID" and open_request is None:
            raise Conflict(
                f"{gs['gs_no']} is already approved as it is (nothing changed since)",
                code="ALREADY_APPROVED",
            )
        remarks = (payload.remarks or "").strip() or None
        approval_id = repo.insert_approval(session, gs_id=gs_id, remarks=remarks)
        approval = repo.latest_approval(session, gs_id)
        if approval is None or approval["id"] != approval_id:
            raise Conflict("The approval was not recorded", code="APPROVAL_NOT_RECORDED")
        ref = approval["snapshot_sha256"][:SHORT_REF]
        notifications.publish(
            session,
            "GS_MANAGEMENT_APPROVED",
            title=f"{gs['gs_no']}: approved by Management",
            body=(
                f"{actor.full_name}: approval {approval['approval_no']}, ref {ref}"
                + (" · includes Issue CN" if approval["has_issue_cn"] else "")
                + (f". Remarks: {remarks}" if remarks else "")
            ),
            entity_type="gs_management_approvals",
            entity_id=approval_id,
            gs_id=gs_id,
            user_ids=[open_request["requested_by"]] if open_request else (),
            role_codes=repo.store_role_codes(session, gs_id),
            data={"gs_no": gs["gs_no"], "ref": ref},
            dedupe_key=f"mgmt-approved:{approval_id}",
        )
        # DEC-71 (P11): with the gate passing, the goods slip goes on to Accounts (or on hold).
        routed = ac_entry().route_to_accounts(session, gs_id, actor, storage, on_uploaded)
        log.info(
            "management_approved",
            routed_to=routed,
            gs_id=str(gs_id),
            approval_no=approval["approval_no"],
            ref=ref,
            has_issue_cn=approval["has_issue_cn"],
            request_id=str(open_request["id"]) if open_request else None,
        )
        return self._gs(session, perms, gs_id)
