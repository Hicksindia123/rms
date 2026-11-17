"""Goods slip workflow and lifecycle domain service (master plan §8.4, prompts P2-01, P2-02).

Step-1 gate inward & GS creation service (master plan §2.2 Step-1, prompt P2-02).

Rules enforced here (and mirrored by DB constraints in 20261103000100_p2_02_gate_inward.sql):
* BR-01 / G-01 / DEC-01: every GS gets `rms_private.next_number('GS', today in the business
  timezone)` inside the creating transaction; the workflow version is pinned (G-18).
* DD r2-r4: delivery-mode conditional fields, via the published S1_GATE_INWARD form version and
  `validate_submission`; the contact number also matches the `contact_phone_pattern` setting.
* DD r5-r9 / BR-03 / DEC-05: gate document conditional fields; NO_DOCUMENT sets
  `missing_documentation`, returns a warning and alerts Accounts + the Replacement Manager (HIGH).
* DEC-02: state / station auto-fill from the party master; an override is flagged and audited.
  Unknown parties are created as provisional and the admins are notified.
* DD r10: GS Creation Format is AUTO_STANDARD (the only configured option; read-only in the UI).

Change plan 2026-11-12 · Phase 2 (form S1_GATE_INWARD v2, docs/RMS_MASTER_PLAN_ADDENDUM_2026-11.md):
* AMD-01: return type (RETURN_TYPE option set) is the first field.
* AMD-02 / DEC-38: Offline Return needs gate entry date (<= business today, optional
  `gate.max_backdate_days`) and a numeric gate entry number unique per financial year
  (409 GATE_ENTRY_NO_TAKEN; the DB unique index is the final word). DEC-39: E-Commerce has neither.
* AMD-03: carton_count replaces box_count (the DB keeps box_count in sync).
* AMD-04: many document rows (gs_gate_documents) or the "No Document Attached" flag (DEC-03).
* AMD-05: each saved row whose type is in `gate.accounts_alert_doc_types` alerts Accounts once
  (event GS_DOCUMENT_FOUND; recipients come from its notification rule).
GS pinned to form v1 (G-18) are still edited with the v1 fields.
"""

# --- P2-02 imports ---
from __future__ import annotations

import logging
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.db import UnitOfWork
from app.core.errors import (
    Conflict,
    NotFound,
    PermissionDenied,
    ServiceUnavailable,
    SystemGuardUnmet,
    ValidationFailed,
)
from app.core.idempotency import IdempotencyKey, IdempotentResult, run_idempotent
from app.core.permissions import EffectivePermissions, assert_step_actor
from app.core.security import CurrentUser
from app.modules.config.forms.validator import validate_submission
from app.modules.goods_slips import repository as repo
from app.modules.goods_slips.schemas import (
    AttachmentSummary,
    GateDocumentFileOut,
    GateDocumentIn,
    GateDocumentOut,
    GateDocumentTypeOut,
    GateEditIn,
    GateFormOut,
    GateInwardIn,
    GateInwardOut,
    GoodsSlipDetailOut,
    GoodsSlipOut,
    GsListItem,
    GsTagOut,
    GsWarning,
    LookupItem,
    PartyFallback,
    PartyLookupPage,
    StatusLabel,
    TagField,
    TagLabel,
    TagSection,
    TaskOut,
    TimelineEntry,
)
from app.modules.notifications import service as notifications
from app.shared.guards import g03_violation
from app.shared.pagination import Page, PageParams
from app.shared.rules_engine import evaluate_rule
from app.shared.workflow_engine import InMemoryWorkflowEntity, WorkflowEngine, WorkflowUser

logger = logging.getLogger(__name__)


def _resolve_user(user: Any) -> WorkflowUser:
    """Normalize user token or model into a WorkflowUser."""
    if isinstance(user, WorkflowUser):
        return user
    uid = getattr(user, "id", getattr(user, "sub", None))
    roles = getattr(user, "role_codes", None) or getattr(user, "roles", [])
    is_super_admin = getattr(user, "is_super_admin", False)
    return WorkflowUser(
        id=UUID(str(uid)) if uid else None,  # type: ignore[arg-type]
        roles=list(roles),
        is_super_admin=bool(is_super_admin),
    )


def create_goods_slip(
    session: Session,
    *,
    delivery_mode_code: str,
    box_count: int,
    party_id: UUID | None = None,
    state_id: UUID | None = None,
    station_id: UUID | None = None,
    courier_name: str | None = None,
    docket_no: str | None = None,
    vehicle_no: str | None = None,
    transporter_id: UUID | None = None,
    rep_name: str | None = None,
    rep_contact: str | None = None,
    gate_document_code: str | None = None,
    gate_doc_no: str | None = None,
    gate_doc_date: Any = None,
    gate_doc_remarks: str | None = None,
    missing_documentation: bool = False,
    category_code: str | None = None,
    user: Any | None = None,
) -> dict[str, Any]:
    """Create a goods slip, pin current workflow version, log history, and open task."""
    published_wf = repo.get_published_workflow_version(session, "RMS_STANDARD")
    workflow_version_id = published_wf["id"]
    snapshot = published_wf["snapshot"]

    acting_user = _resolve_user(user) if user else None
    created_by_id = acting_user.id if acting_user else None

    # Insert goods slip
    gs = repo.create_goods_slip(
        session,
        workflow_version_id=workflow_version_id,
        delivery_mode_code=delivery_mode_code,
        box_count=box_count,
        party_id=party_id,
        state_id=state_id,
        station_id=station_id,
        courier_name=courier_name,
        docket_no=docket_no,
        vehicle_no=vehicle_no,
        transporter_id=transporter_id,
        rep_name=rep_name,
        rep_contact=rep_contact,
        gate_document_code=gate_document_code,
        gate_doc_no=gate_doc_no,
        gate_doc_date=gate_doc_date,
        gate_doc_remarks=gate_doc_remarks,
        missing_documentation=missing_documentation,
        category_code=category_code,
        created_by=created_by_id,
    )

    gs_id = gs["id"]

    # Status history entry
    repo.record_status_history(
        session,
        gs_id=gs_id,
        from_status=None,
        to_status="GATE_CREATED",
        step_code="S1_GATE",
        reason="Initial gate inward creation",
        by_user_id=created_by_id,
    )

    # Open initial workflow task(s) for S1_GATE
    steps = snapshot.get("steps", [])
    step_meta = next((s for s in steps if s.get("code") == "S1_GATE"), None)
    if step_meta:
        sla_hours = step_meta.get("sla_hours")
        due_at = datetime.now(UTC) + timedelta(hours=float(sla_hours)) if sla_hours else None
        for assignment in step_meta.get("assignments", []):
            if assignment.get("assignment_type", "PERFORM") == "PERFORM":
                repo.create_workflow_task(
                    session,
                    gs_id=gs_id,
                    step_code="S1_GATE",
                    assigned_role_id=UUID(assignment["role_id"])
                    if assignment.get("role_id")
                    else None,
                    assigned_user_id=UUID(assignment["user_id"])
                    if assignment.get("user_id")
                    else None,
                    due_at=due_at,
                )

    return gs


def transition_gs(
    session: Session,
    *,
    gs_id: UUID,
    to_status: str,
    step_code: str,
    user: Any,
    reason: str | None = None,
    context_overrides: dict[str, Any] | None = None,
    actor_step_code: str | None = None,
    actor_assignment_type: str | None = None,
) -> dict[str, Any]:
    """Execute a guarded status transition on a goods slip.

    Pins workflow version if missing, evaluates conditions and non-bypassable system guards,
    records status history, closes current open tasks, and opens new workflow tasks
    for the assignees of the new step (APPROVE assignees for an approval step, else PERFORM).
    `actor_step_code` authorises the user on the step being completed (see WorkflowEngine).
    """
    gs = repo.get_goods_slip(session, gs_id, for_update=True)
    if not gs:
        raise NotFound(f"Goods slip '{gs_id}' not found")

    workflow_version_id = gs.get("workflow_version_id")
    if not workflow_version_id:
        published_wf = repo.get_published_workflow_version(session, "RMS_STANDARD")
        workflow_version_id = published_wf["id"]
        snapshot = published_wf["snapshot"]
    else:
        wf_version = repo.get_workflow_version_by_id(session, workflow_version_id)
        snapshot = wf_version["snapshot"]

    acting_user = _resolve_user(user)

    # Determine current step code: inspect current open task or map from status
    open_tasks = repo.get_open_tasks_for_gs(session, gs_id)
    current_step_code = open_tasks[0]["step_code"] if open_tasks else "S1_GATE"

    # Evaluate transition conditions and system guards
    engine = WorkflowEngine(snapshot)
    context = {
        "gs_no": gs.get("gs_no"),
        "category_code": gs.get("category_code"),
        "has_open_pendency": gs.get("has_open_pendency", False),
        "has_discrepancy": gs.get("has_discrepancy", False),
        "has_hazard": gs.get("has_hazard", False),
        "has_rejections": gs.get("has_rejections", False),
        "delivery_mode_code": gs.get("delivery_mode_code"),
        **(context_overrides or {}),
    }

    entity = InMemoryWorkflowEntity(
        id=gs["id"],
        workflow_version_id=workflow_version_id,
        current_step_code=current_step_code,
        status=gs["status"],
        context=context,
    )

    # Will raise TransitionError / TransitionNotAllowed / SystemGuardViolation if invalid
    engine.assert_can_transition(
        entity,
        step_code,
        acting_user,
        actor_step_code=actor_step_code,
        actor_assignment_type=actor_assignment_type,
    )

    # 1. Update goods slip status
    from_status = gs["status"]
    repo.update_gs_status(session, gs_id, to_status)

    # 2. Record status history entry
    repo.record_status_history(
        session,
        gs_id=gs_id,
        from_status=from_status,
        to_status=to_status,
        step_code=step_code,
        reason=reason,
        by_user_id=acting_user.id,
    )

    # 3. Close open tasks
    repo.complete_open_tasks(session, gs_id)

    # 4. Open new workflow tasks for the assignees of the target step
    _open_step_tasks(session, gs_id, snapshot, step_code)

    updated_gs = repo.get_goods_slip(session, gs_id)
    if not updated_gs:
        raise NotFound(f"Goods slip '{gs_id}' could not be loaded after transition")
    return updated_gs


def _open_step_tasks(
    session: Session, gs_id: UUID, snapshot: dict[str, Any], step_code: str
) -> list[UUID]:
    """Tasks for the step's actors: APPROVE assignees of an approval step (e.g. S1_CSR_APPROVAL ->
    Replacement Manager), PERFORM assignees otherwise."""
    steps = snapshot.get("steps", [])
    step_meta = next((s for s in steps if s.get("code") == step_code), None)
    if not step_meta:
        return []
    wanted = "APPROVE" if step_meta.get("requires_approval") else "PERFORM"
    sla_hours = step_meta.get("sla_hours")
    due_at = datetime.now(UTC) + timedelta(hours=float(sla_hours)) if sla_hours else None
    task_ids: list[UUID] = []
    for assignment in step_meta.get("assignments", []):
        if assignment.get("assignment_type", "PERFORM") != wanted:
            continue
        task_ids.append(
            repo.create_workflow_task(
                session,
                gs_id=gs_id,
                step_code=step_code,
                assigned_role_id=UUID(assignment["role_id"]) if assignment.get("role_id") else None,
                assigned_user_id=UUID(assignment["user_id"]) if assignment.get("user_id") else None,
                due_at=due_at,
            )
        )
    return task_ids


# =============================================================================================
# P2-02 · Step-1 gate inward & GS creation
# =============================================================================================

FORM_CODE = "S1_GATE_INWARD"
GATE_STEP = "S1_GATE"
WORKFLOW_CODE = "RMS_STANDARD"
ENTITY_TYPE = "goods_slip"
TAG_TEMPLATE = "GS_TAG"
DEFAULT_TIMEZONE = "Asia/Kolkata"

# Stable option codes (§3.2). Business logic keys off codes, never labels (CLAUDE.md rule e).
DOC_NONE = "NO_DOCUMENT"  # DD r9
MODE_TRUCK = "DIRECT_TRUCK"  # DD r3
RETURN_OFFLINE = "OFFLINE_RETURN"  # AMD-01 / AMD-02: the return type that carries a gate entry
# option_items.required_fields of GATE_DOCUMENT (DD r5-r8) → gs_gate_documents columns.
_DOC_REQUIRED_FIELD_COLUMNS = {
    "gate_doc_no": "doc_no",
    "gate_doc_date": "doc_date",
    "gate_doc_remarks": "remarks",
    "doc_no": "doc_no",
    "doc_date": "doc_date",
    "remarks": "remarks",
}
_DOC_COLUMN_LABELS = {"doc_no": "Document No.", "doc_date": "Document Date", "remarks": "Remarks"}
# DEC-05: who receives the high-priority missing-documentation alert.
NO_DOC_ALERT_ROLES = ["ACCOUNTS", "REPLACEMENT_MANAGER"]
# §6.5: CANCELLED is allowed only before Step-2 (unboxing) completes.
CANCELLABLE_STATUSES = frozenset({"GATE_CREATED", "UNBOXING"})
# Form fields filled from masters (DEC-02), never trusted from the client.
_MASTER_FIELDS = ("party_name", "state", "station")
# Columns that are part of a status change; their audit rows are already shown from history.
_STATUS_ONLY_FIELDS = frozenset({"status", "cancelled_at", "cancelled_by", "cancel_reason"})


def _field_error(field: str, message: str) -> ValidationFailed:
    return ValidationFailed(message, code="FORM_VALIDATION_FAILED", details={field: [message]})


def is_gs_admin(user: CurrentUser, perms: EffectivePermissions) -> bool:
    """'Admin' for gate edits/cancellation: Super Admin or holder of goods_slips.configure."""
    return user.is_super_admin or perms.allows("goods_slips", "configure")


DOC_IMAGE_FIELD: dict[str, Any] = {
    "field_key": "gate_doc_image",
    "label": "Document Picture / Image",
    "control_type": "file",
    "is_required": False,
    "is_core": False,
    "sort_order": 145,
    "section": "Documentation",
    "help_text": "Upload or take photo of the physical invoice or slip",
    "visible_when": {
        "field": "accompanying_doc",
        "op": "in",
        "value": ["INVOICE", "DEBIT_NOTE", "DELIVERY_CHALLAN", "HANDWRITTEN_SLIP"],
    },
    "required_when": None,
    "validation": None,
    "option_items": [],
}


def _with_doc_image_field(form: dict[str, Any]) -> dict[str, Any]:
    snapshot = dict(form.get("snapshot") or {})
    fields = list(snapshot.get("fields") or [])
    # v1 forms only: form v2 (AMD-04) carries files per gate document row instead.
    is_v1 = any(f.get("field_key") == "accompanying_doc" for f in fields)
    if is_v1 and not any(f.get("field_key") == "gate_doc_image" for f in fields):
        fields.append(DOC_IMAGE_FIELD)
        snapshot["fields"] = sorted(fields, key=lambda f: f.get("sort_order", 0))
        form = dict(form)
        form["snapshot"] = snapshot
    return form


class GateInwardService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    # ---------------------------------------------------------------- reads -----------------
    def gate_form(self, user: CurrentUser) -> GateFormOut:
        with self._uow.transaction(user.id) as session:
            form = self._published_form(session)
            pattern = repo.get_setting(session, "contact_phone_pattern")
            autofill = repo.get_setting(session, "party_state_station_autofill")
            return GateFormOut(
                form_version_id=form["id"],
                snapshot=dict(form["snapshot"]),
                contact_phone_pattern=pattern if isinstance(pattern, str) else None,
                party_state_station_autofill=autofill is not False,
                document_types=[
                    GateDocumentTypeOut(
                        code=t["code"],
                        label=t["label"],
                        required_fields=_doc_required_fields(t),
                    )
                    for t in repo.gate_document_types(session)
                    if t["code"] != DOC_NONE
                ],
                business_today=repo.business_today(session),
                max_backdate_days=_max_backdate_days(session),
            )

    def lookup_parties(self, user: CurrentUser, q: str | None, limit: int) -> list[LookupItem]:
        with self._uow.transaction(user.id) as session:
            return [LookupItem(**r) for r in repo.search_parties(session, q, limit)]

    def lookup_parties_by_location(
        self,
        user: CurrentUser,
        *,
        state_id: UUID,
        station_id: UUID | None,
        q: str | None,
        page: int,
        page_size: int,
    ) -> PartyLookupPage:
        """AMD-06: Distributor list filtered by State + Station.

        When the station has no active parties at all, `gate.party_fallback` (DEC-35, PROVISIONAL)
        decides: STATE = parties of the selected state, ALL = every party, NONE = empty list.
        A search that finds nothing inside a station with parties does NOT fall back.
        Creating a provisional party stays available in the gate form (DEC-02).
        """
        with self._uow.transaction(user.id) as session:
            setting = repo.get_setting(session, "gate.party_fallback")
            if setting not in ("STATE", "ALL", "NONE"):
                # The DB CHECK (migration 20261112000100) makes this unreachable; never guess.
                logger.error("gate.party_fallback is missing or invalid: %r", setting)
                raise ServiceUnavailable(
                    "System setting gate.party_fallback is missing or invalid",
                    code="SETTING_INVALID",
                    details={"key": "gate.party_fallback"},
                )
            fallback: PartyFallback = setting
            if station_id is not None:
                self._check_state_station(session, state_id, station_id)
            else:
                state = repo.get_state(session, state_id)
                if not state or not state["is_active"]:
                    raise _field_error("state", "State not found or inactive")

            scope: Literal["STATION", "STATE", "ALL", "NONE"] = "STATE"
            fallback_applied = False
            if station_id is not None:
                scope = "STATION"
                if repo.count_station_parties(session, station_id) == 0:
                    fallback_applied = True
                    scope = fallback
            rows: list[dict[str, Any]] = []
            total = 0
            if scope != "NONE":
                rows, total = repo.search_parties_paged(
                    session,
                    q=(q or "").strip() or None,
                    state_id=None if scope == "ALL" else state_id,
                    station_id=station_id if scope == "STATION" else None,
                    limit=page_size,
                    offset=(page - 1) * page_size,
                )
            return PartyLookupPage(
                items=[LookupItem(**r) for r in rows],
                total=total,
                page=page,
                page_size=page_size,
                scope=scope,
                fallback_applied=fallback_applied,
                fallback_setting=fallback,
            )

    def status_labels(self, user: CurrentUser) -> list[StatusLabel]:
        """AMD-08: goods-slip status labels from configuration (rule e)."""
        with self._uow.transaction(user.id) as session:
            return [StatusLabel(**r) for r in repo.gs_status_labels(session)]

    def lookup_states(self, user: CurrentUser) -> list[LookupItem]:
        with self._uow.transaction(user.id) as session:
            return [LookupItem(**r) for r in repo.list_states(session)]

    def lookup_stations(self, user: CurrentUser, state_id: UUID | None) -> list[LookupItem]:
        with self._uow.transaction(user.id) as session:
            return [LookupItem(**r) for r in repo.list_stations(session, state_id)]

    def lookup_transporters(self, user: CurrentUser, q: str | None, limit: int) -> list[LookupItem]:
        with self._uow.transaction(user.id) as session:
            return [LookupItem(**r) for r in repo.search_transporters(session, q, limit)]

    def list_goods_slips(
        self,
        user: CurrentUser,
        perms: EffectivePermissions,
        params: PageParams,
        *,
        statuses: list[str] | None,
        party_id: UUID | None,
        date_from: date | None,
        date_to: date | None,
        q: str | None,
        flags: list[str],
    ) -> Page[GsListItem]:
        unknown = sorted(set(flags) - set(repo.LIST_FLAG_COLUMNS))
        if unknown:
            raise ValidationFailed(
                f"Unknown flag filter: {', '.join(unknown)}",
                code="INVALID_FILTER",
                details={"allowed": sorted(repo.LIST_FLAG_COLUMNS)},
            )
        order_by = params.order_by_sql(repo.LIST_SORTS, "g.created_at desc")
        scope = perms.scope("goods_slips", "view")
        parsed_cursor = params.parse_cursor()
        cursor_at = parsed_cursor[0] if parsed_cursor else None
        cursor_id = UUID(parsed_cursor[1]) if parsed_cursor else None
        with self._uow.transaction(user.id) as session:
            rows, total = repo.list_goods_slips(
                session,
                statuses=statuses,
                party_id=party_id,
                date_from=date_from,
                date_to=date_to,
                timezone=self._timezone(session),
                q=q.strip() if q and q.strip() else None,
                flags=flags,
                scope_created_by=user.id if scope == "own" else None,
                scope_department_of=user.id if scope == "department" else None,
                order_by=order_by,
                limit=params.page_size,
                offset=params.offset,
                cursor_created_at=cursor_at,
                cursor_id=cursor_id,
            )
        next_cursor = None
        if len(rows) == params.page_size and rows:
            last = rows[-1]
            if last.get("created_at") and last.get("id"):
                next_cursor = f"{last['created_at'].isoformat()}|{last['id']}"

        return Page[GsListItem](
            items=[GsListItem(**r) for r in rows],
            total=total,
            page=params.page,
            page_size=params.page_size,
            next_cursor=next_cursor,
        )

    def get_detail(
        self, user: CurrentUser, perms: EffectivePermissions, gs_id: UUID
    ) -> GoodsSlipDetailOut:
        with self._uow.transaction(user.id) as session:
            gs = self._visible_gs(session, user, perms, gs_id)
            response = repo.get_form_response(
                session, entity_type=ENTITY_TYPE, entity_id=gs_id, form_code=FORM_CODE
            )
            timeline = self._timeline(session, gs_id)
            tasks = [TaskOut(**t) for t in repo.get_tasks_for_gs(session, gs_id)]
            attachments = [
                AttachmentSummary(**a) for a in repo.get_attachment_summary(session, gs_id)
            ]
            documents = _documents_out(session, gs_id)
        admin = is_gs_admin(user, perms)
        return GoodsSlipDetailOut(
            goods_slip=GoodsSlipOut(**gs, documents=documents),
            form_version_id=response["form_version_id"] if response else None,
            form_values=dict(response["values"]) if response else {},
            labels_snapshot=dict(response["labels_snapshot"]) if response else {},
            timeline=timeline,
            tasks=tasks,
            attachments=attachments,
            can_edit_gate=gs["status"] == "GATE_CREATED"
            and (admin or perms.allows("goods_slips", "create")),  # DEC-51: any gate user
            can_cancel=admin and gs["status"] in CANCELLABLE_STATUSES,
        )

    def tag(self, user: CurrentUser, perms: EffectivePermissions, gs_id: UUID) -> GsTagOut:
        """BR-02: data for the GS_TAG print template, one label per box."""
        with self._uow.transaction(user.id) as session:
            gs = self._visible_gs(session, user, perms, gs_id)
            template = repo.get_published_template(session, TAG_TEMPLATE)
            if not template:
                raise NotFound("No published GS_TAG print template", code="TEMPLATE_NOT_FOUND")
            tz = self._timezone(session)
            form = repo.get_published_form(session, FORM_CODE)
        received = _local_date(gs["created_at"], tz)
        n = int(gs["carton_count"])  # AMD-03
        layout = dict(template["layout"])
        values: dict[str, str | None] = {
            "gs_no": gs["gs_no"],
            "qr_code": f"{gs['gs_no']}|{gs['id']}",
            "party_name": gs["party_name"],
            "state_station": " / ".join(str(p) for p in (gs["state_name"], gs["station_name"]) if p)
            or None,
            "carton_count": str(n),
            "box_count": str(n),  # templates published before AMD-03
            "return_type": gs.get("return_type_label"),
            "gate_entry_no": str(gs["gate_entry_no"]) if gs.get("gate_entry_no") else None,
            "received_date": received.isoformat(),
            "transporter": _transport_text(gs),
            "delivery_mode": gs["delivery_mode_label"],
        }
        labels = _tag_field_labels(layout, dict(form["snapshot"]) if form else {})
        # Caption word from the template (rule e); "Carton" per AMD-03 when not configured.
        carton_word = str(layout.get("label_unit") or "Carton")
        sections = [
            TagSection(
                id=str(sec.get("id", "")),
                title=str(sec.get("title", "")),
                fields=[
                    TagField(key=k, label=labels(k), value=values.get(k))
                    for k in sec.get("fields") or []
                ],
            )
            for sec in layout.get("sections") or []
        ]
        return GsTagOut(
            template_code=template["code"],
            template_version=template["version_no"],
            layout=layout,
            gs_id=gs["id"],
            gs_no=gs["gs_no"],
            qr_payload=f"{gs['gs_no']}|{gs['id']}",
            party_name=gs["party_name"],
            state_name=gs["state_name"],
            station_name=gs["station_name"],
            transporter=_transport_text(gs),
            carton_count=n,
            box_count=n,
            received_date=received,
            sections=sections,
            labels=[
                TagLabel(box_no=i, box_count=n, caption=f"{carton_word} {i} of {n}")
                for i in range(1, n + 1)
            ],
        )

    # ---------------------------------------------------------------- commands --------------
    def create(
        self, user: CurrentUser, payload: GateInwardIn, idem: IdempotencyKey
    ) -> IdempotentResult:
        with self._uow.transaction(user.id) as session:
            assert_step_actor(session, user, GATE_STEP, "PERFORM")
            return run_idempotent(
                session, idem, user.id, lambda: (201, self._create(session, user, payload))
            )

    def edit_gate(
        self, user: CurrentUser, perms: EffectivePermissions, gs_id: UUID, payload: GateEditIn
    ) -> GoodsSlipDetailOut:
        with self._uow.transaction(user.id) as session:
            gs = repo.get_goods_slip(session, gs_id, for_update=True)
            if not gs:
                raise NotFound("Goods slip not found")
            admin = is_gs_admin(user, perms)
            # DEC-51: any gate user (goods_slips.create) may edit, not only the GS creator.
            gate_user = perms.allows("goods_slips", "create")
            if not (admin or gate_user):
                raise PermissionDenied(
                    "Only a gate user or an admin can edit gate details", code="NOT_GS_CREATOR"
                )
            if gs["status"] != "GATE_CREATED":
                raise Conflict(
                    "Gate details can only be edited while the GS is at gate (GATE_CREATED)",
                    code="GS_NOT_EDITABLE",
                    details={"status": gs["status"]},
                )
            response = repo.get_form_response(
                session, entity_type=ENTITY_TYPE, entity_id=gs_id, form_code=FORM_CODE
            )
            # G-18: re-validate against the form version the GS was created under.
            if response:
                form_version_id = response["form_version_id"]
                snapshot = repo.get_form_version_snapshot(session, form_version_id)
            else:
                form = self._published_form(session)
                form_version_id, snapshot = form["id"], dict(form["snapshot"])
            if not snapshot:
                raise NotFound("Form version for this GS not found")
            resolved = self._resolve_and_validate(session, payload, snapshot, gs_id=gs_id)
            resolved.persist_new_party(session)

            reason = payload.reason.strip()
            if resolved.override_note:
                reason = f"{reason} ({resolved.override_note})"
            repo.set_audit_reason(session, reason)
            # AMD-04: rows left out are removed first (so "no document" can be set), then the GS,
            # then the kept / new rows (so a GS that drops "no document" can take rows).
            existing = {d["id"]: d for d in repo.list_gate_documents(session, gs_id)}
            unknown = [d["id"] for d in resolved.documents if d["id"] and d["id"] not in existing]
            if unknown:
                raise _field_error("documents", "A document row does not belong to this GS")
            kept = {d["id"] for d in resolved.documents if d["id"]}
            repo.delete_gate_documents(session, [i for i in existing if i not in kept])
            repo.update_gate_fields(session, gs_id, resolved.columns)
            changed_doc_ids = _save_documents(session, gs_id, resolved.documents, existing)
            if response:
                repo.update_form_response(
                    session,
                    response["id"],
                    values=resolved.values,
                    labels_snapshot=resolved.labels,
                )
            else:
                repo.insert_form_response(
                    session,
                    entity_type=ENTITY_TYPE,
                    entity_id=gs_id,
                    form_version_id=form_version_id,
                    values=resolved.values,
                    labels_snapshot=resolved.labels,
                )
            repo.set_audit_reason(session, None)
            if resolved.columns["missing_documentation"] and not gs["missing_documentation"]:
                self._notify_missing_documentation(session, gs_id, gs["gs_no"])
            self._notify_provisional_party(session, resolved, gs_id, gs["gs_no"])
            self._notify_accounts_documents(session, resolved, gs_id, gs["gs_no"], changed_doc_ids)
        return self.get_detail(user, perms, gs_id)

    def cancel(
        self, user: CurrentUser, perms: EffectivePermissions, gs_id: UUID, reason: str
    ) -> GoodsSlipDetailOut:
        if not is_gs_admin(user, perms):
            raise PermissionDenied("Only an admin can cancel a goods slip", code="NOT_GS_ADMIN")
        reason = reason.strip()
        if not reason:
            raise _field_error("reason", "A cancellation reason is required")
        with self._uow.transaction(user.id) as session:
            gs = repo.get_goods_slip(session, gs_id, for_update=True)
            if not gs:
                raise NotFound("Goods slip not found")
            if gs["status"] not in CANCELLABLE_STATUSES:
                raise Conflict(
                    "A goods slip can only be cancelled before unboxing completes",
                    code="GS_NOT_CANCELLABLE",
                    details={"status": gs["status"]},
                )
            repo.set_audit_reason(session, reason)
            repo.cancel_goods_slip(session, gs_id, reason=reason, by=user.id)
            repo.record_status_history(
                session,
                gs_id=gs_id,
                from_status=gs["status"],
                to_status="CANCELLED",
                step_code=GATE_STEP,
                reason=reason,
                by_user_id=user.id,
            )
            repo.cancel_open_tasks(session, gs_id)
            repo.set_audit_reason(session, None)
        return self.get_detail(user, perms, gs_id)

    # ---------------------------------------------------------------- internals -------------
    def _create(self, session: Session, user: CurrentUser, payload: GateInwardIn) -> GateInwardOut:
        form = self._published_form(session)
        snapshot = dict(form["snapshot"])
        resolved = self._resolve_and_validate(session, payload, snapshot)
        resolved.persist_new_party(session)

        workflow = repo.get_published_workflow_version(session, WORKFLOW_CODE)
        gs_no = repo.next_gs_number(session, self._timezone(session))  # BR-01, DEC-01
        # DEC-02: the INSERT's audit row carries the override note.
        repo.set_audit_reason(session, resolved.override_note)
        gs_id = repo.insert_gate_goods_slip(
            session, gs_no=gs_no, workflow_version_id=workflow["id"], fields=resolved.columns
        )
        repo.set_audit_reason(session, None)
        repo.record_status_history(
            session,
            gs_id=gs_id,
            from_status=None,
            to_status="GATE_CREATED",
            step_code=GATE_STEP,
            reason="Gate inward: GS created",
            by_user_id=user.id,
        )
        repo.insert_form_response(
            session,
            entity_type=ENTITY_TYPE,
            entity_id=gs_id,
            form_version_id=form["id"],
            values=resolved.values,
            labels_snapshot=resolved.labels,
        )
        doc_ids = _save_documents(session, gs_id, resolved.documents, {})  # AMD-04
        task_ids = self._open_next_step_tasks(session, gs_id, dict(workflow["snapshot"]), resolved)

        warnings: list[GsWarning] = []
        notified = 0
        if resolved.columns["missing_documentation"]:
            warnings.append(GsWarning(code="MISSING_DOCUMENTATION", message=resolved.no_doc_text))
            notified += self._notify_missing_documentation(session, gs_id, gs_no)
        notified += self._notify_provisional_party(session, resolved, gs_id, gs_no)
        # Requirement A / AMD-05: Accounts is alerted per Invoice / Debit Note row (configurable).
        notified += self._notify_accounts_documents(session, resolved, gs_id, gs_no, doc_ids)
        # P4-03: GS_CREATED (rule seeded inactive; addresses the next step's assignees). Not part
        # of `notified_user_count`, which keeps counting the gate alerts (DEC-02 / DEC-05).
        notifications.publish(
            session,
            "GS_CREATED",
            title=f"{gs_no}: goods slip created at gate",
            body=f"Created by {user.full_name}.",
            entity_type=ENTITY_TYPE,
            entity_id=gs_id,
            gs_id=gs_id,
            data={"gs_no": gs_no},
        )

        gs = repo.get_goods_slip_view(session, gs_id)
        if not gs:
            raise NotFound("Goods slip could not be loaded after creation")
        return GateInwardOut(
            goods_slip=GoodsSlipOut(**gs, documents=_documents_out(session, gs_id)),
            warnings=warnings,
            task_ids=task_ids,
            notified_user_count=notified,
        )

    def _resolve_and_validate(
        self,
        session: Session,
        payload: GateInwardIn,
        snapshot: dict[str, Any],
        *,
        gs_id: UUID | None = None,
    ) -> _Resolved:
        # --- party (existing or provisional, DEC-02) ---
        prov = payload.provisional_party
        if (payload.party_id is None) == (prov is None):
            raise _field_error(
                "party_name", "Select an existing party or create a provisional party"
            )
        party_name: str
        party_state_id: UUID | None
        party_station_id: UUID | None
        new_party = None
        if prov is None:
            party = repo.get_party(session, payload.party_id) if payload.party_id else None
            if not party or not party["is_active"]:
                raise _field_error("party_name", "Party not found or inactive")
            party_name = party["name"]
            party_state_id, party_station_id = party["state_id"], party["station_id"]
        else:
            name = prov.name.strip()
            if not name:
                raise _field_error("party_name", "Provisional party name is required")
            self._check_state_station(session, prov.state_id, prov.station_id, prefix="Party ")
            party_name = name
            party_state_id, party_station_id = prov.state_id, prov.station_id
            new_party = (name, prov.state_id, prov.station_id)

        # --- state / station: auto-filled from the party, editable, override audited ---
        autofill = repo.get_setting(session, "party_state_station_autofill") is not False
        state_id = payload.state_id or (party_state_id if autofill else None)
        station_id = payload.station_id or (party_station_id if autofill else None)
        if state_id is None:
            raise _field_error("state", "State is required")
        if station_id is None:
            raise _field_error("station", "Station is required")
        state, station = self._check_state_station(session, state_id, station_id)
        overridden = party_state_id is not None and (
            state_id != party_state_id or station_id != party_station_id
        )
        override_note = None
        if overridden:
            override_note = (
                f"DEC-02 state/station override at gate for party '{party_name}': "
                f"{state['name']} / {station['name']} instead of the party master values"
            )

        # --- transporter (DD r3: master or new name) ---
        values = {k: v for k, v in payload.values.items() if k not in _MASTER_FIELDS}
        transporter_id = payload.transporter_id
        if transporter_id is not None:
            transporter = repo.get_transporter(session, transporter_id)
            if not transporter or not transporter["is_active"]:
                raise _field_error("transporter_name", "Transporter not found or inactive")
            values["transporter_name"] = transporter["name"]
        values["party_name"] = party_name
        values["state"] = state["name"]
        values["station"] = station["name"]

        # DD r10: AUTO_STANDARD is the only creation format; default it when omitted.
        fmt_field = _field(snapshot, "gs_creation_format")
        if fmt_field and values.get("gs_creation_format") in (None, ""):
            default = fmt_field.get("default_value")
            values["gs_creation_format"] = default if isinstance(default, str) else None

        # --- form-driven conditional validation (published / pinned version) ---
        result = validate_submission(snapshot, values)
        errors = {k: list(v) for k, v in result.errors.items()}
        clean = dict(result.sanitized_values)

        # AMD-03: form v2 asks for carton_count; GS pinned to v1 (G-18) still send box_count.
        is_v2 = _field(snapshot, "carton_count") is not None
        count_key = "carton_count" if is_v2 else "box_count"
        count = clean.get(count_key)
        if count is not None and (
            isinstance(count, bool) or not isinstance(count, int) or count < 1
        ):
            label = (_field(snapshot, count_key) or {}).get("label", count_key)
            errors.setdefault(count_key, []).append(f"{label} must be a whole number above 0")

        pattern = repo.get_setting(session, "contact_phone_pattern")
        contact = clean.get("rep_contact")
        if (
            isinstance(pattern, str)
            and isinstance(contact, str)
            and contact.strip()
            and not re.search(pattern, contact.strip())
        ):
            errors.setdefault("rep_contact", []).append(
                "Representative Contact No. is not a valid phone number"
            )

        today = repo.business_today(session)
        gate_entry: dict[str, Any] = {
            "return_type_code": None,
            "gate_entry_date": None,
            "gate_entry_no": None,
        }
        documents: list[dict[str, Any]] = []
        doc_code: str | None = None
        doc_date: date | None = None
        if is_v2:
            # BR-03 / DEC-52: ticking "No Document Attached" is enough; no separate
            # acknowledgement is asked for at the gate.
            no_document = clean.get("no_document") is True
            gate_entry = self._validate_gate_entry(session, clean, today, gs_id, errors)
            documents = _validate_documents(
                repo.gate_document_types(session), payload.documents, today, errors
            )
            if no_document and documents:
                errors.setdefault("documents", []).append(
                    "Remove the document rows or untick the no-document option"
                )
            if not no_document and not payload.documents:
                errors.setdefault("documents", []).append(
                    "Add at least one document, or tick the no-document option (BR-03)"
                )
            missing_documentation = no_document
        else:
            if payload.documents:
                errors.setdefault("documents", []).append(
                    "This goods slip uses gate form v1: use the accompanying document field"
                )
            doc_code = clean.get("accompanying_doc")
            raw_date = clean.get("gate_doc_date")
            if isinstance(raw_date, str) and raw_date.strip():
                try:
                    doc_date = date.fromisoformat(raw_date.strip()[:10])
                except ValueError:
                    errors.setdefault("gate_doc_date", []).append(
                        "Gate Document Date must be a valid date (YYYY-MM-DD)"
                    )
            missing_documentation = doc_code == DOC_NONE  # BR-03
            if doc_code and doc_code != DOC_NONE and not errors:
                # AMD-04: gs_gate_documents is the source of truth for v1 edits as well.
                types = {t["code"]: t for t in repo.gate_document_types(session)}
                documents = [
                    {
                        "id": None,
                        "doc_type_code": doc_code,
                        "doc_type_label": str(types.get(doc_code, {}).get("label") or doc_code),
                        "doc_no": _text(clean.get("gate_doc_no")),
                        "doc_date": doc_date,
                        "remarks": _text(clean.get("gate_doc_remarks")),
                    }
                ]

        if errors:
            raise ValidationFailed(
                "The gate inward form has errors",
                code="FORM_VALIDATION_FAILED",
                details=errors,
            )

        mode = clean["delivery_mode"]
        columns: dict[str, Any] = {
            "party_id": payload.party_id,
            "state_id": state_id,
            "station_id": station_id,
            "state_station_overridden": overridden,
            "delivery_mode_code": mode,
            "courier_name": _text(clean.get("courier_name")),
            "docket_no": _text(clean.get("docket_no")),
            "vehicle_no": _text(clean.get("vehicle_no")),
            "transporter_id": transporter_id if mode == MODE_TRUCK else None,
            "transporter_name": _text(clean.get("transporter_name")),
            "rep_name": _text(clean.get("rep_name")),
            "rep_contact": _text(clean.get("rep_contact")),
            "carton_count": int(clean[count_key]),  # AMD-03
            **gate_entry,  # AMD-01 / AMD-02
            # AMD-04: the single gate document columns are only written for v1 GS.
            "gate_document_code": doc_code,
            "gate_doc_no": None if is_v2 else _text(clean.get("gate_doc_no")),
            "gate_doc_date": doc_date,
            "gate_doc_remarks": None if is_v2 else _text(clean.get("gate_doc_remarks")),
            "missing_documentation": missing_documentation,  # BR-03 / DEC-03
        }
        labels = _labels_snapshot(snapshot, clean)
        if is_v2:
            no_doc_text = _no_document_text(session, snapshot)
        else:
            no_doc_text = _option_text(snapshot, "accompanying_doc", DOC_NONE)
        resolved = _Resolved(
            columns=columns,
            values=clean,
            labels=labels,
            override_note=override_note,
            new_party=new_party,
            no_doc_text=no_doc_text,
        )
        resolved.documents = documents
        return resolved

    def _validate_gate_entry(
        self,
        session: Session,
        clean: dict[str, Any],
        today: date,
        gs_id: UUID | None,
        errors: dict[str, list[str]],
    ) -> dict[str, Any]:
        """AMD-01 / AMD-02 / DEC-38 / DEC-39 (mirrored by DB CHECKs, trigger and unique index)."""
        return_type = clean.get("return_type")
        out: dict[str, Any] = {
            "return_type_code": return_type,
            "gate_entry_date": None,
            "gate_entry_no": None,
        }
        if return_type != RETURN_OFFLINE:
            # DEC-39: E-Commerce has no gate entry date / number (hidden fields are pruned).
            return out
        raw_date = clean.get("gate_entry_date")
        entry_date: date | None = None
        if isinstance(raw_date, str) and raw_date.strip():
            try:
                entry_date = date.fromisoformat(raw_date.strip()[:10])
            except ValueError:
                errors.setdefault("gate_entry_date", []).append(
                    "Gate Entry Date must be a valid date (YYYY-MM-DD)"
                )
        if entry_date is not None:
            if entry_date > today:
                errors.setdefault("gate_entry_date", []).append(
                    "Gate Entry Date cannot be later than today"
                )
            max_days = _max_backdate_days(session)
            if max_days is not None and entry_date < today - timedelta(days=max_days):
                errors.setdefault("gate_entry_date", []).append(
                    f"Gate Entry Date can be at most {max_days} days back (DEC-38)"
                )
        number = clean.get("gate_entry_no")
        if number is not None and (
            isinstance(number, bool) or not isinstance(number, int) or number < 1
        ):
            errors.setdefault("gate_entry_no", []).append(
                "Gate Entry Number must be a whole number above 0"
            )
            number = None
        if entry_date is not None and isinstance(number, int) and not errors:
            taken_by = repo.gate_entry_no_taken(
                session, gate_entry_no=number, gate_entry_date=entry_date, exclude_gs_id=gs_id
            )
            if taken_by:
                raise Conflict(
                    f"Gate Entry Number {number} is already used by {taken_by} in this "
                    "financial year",
                    code="GATE_ENTRY_NO_TAKEN",
                    details={"gate_entry_no": [f"Already used by {taken_by} (DEC-38)"]},
                )
        out["gate_entry_date"] = entry_date
        out["gate_entry_no"] = number
        return out

    def _check_state_station(
        self, session: Session, state_id: UUID, station_id: UUID, *, prefix: str = ""
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        state = repo.get_state(session, state_id)
        if not state or not state["is_active"]:
            raise _field_error("state", f"{prefix}State not found or inactive")
        station = repo.get_station(session, station_id)
        if not station or not station["is_active"]:
            raise _field_error("station", f"{prefix}Station not found or inactive")
        if station["state_id"] != state_id:
            raise _field_error("station", f"{prefix}Station does not belong to the selected state")
        return state, station

    def _open_next_step_tasks(
        self,
        session: Session,
        gs_id: UUID,
        wf_snapshot: dict[str, Any],
        resolved: _Resolved,
    ) -> list[UUID]:
        """Open tasks for the step(s) the pinned workflow routes S1_GATE to (S1_UNBOX in v1)."""
        context = {
            "delivery_mode_code": resolved.columns["delivery_mode_code"],
            "missing_documentation": resolved.columns["missing_documentation"],
        }
        transitions = sorted(
            (
                t
                for t in wf_snapshot.get("transitions") or []
                if t.get("from_step_code") == GATE_STEP
            ),
            key=lambda t: -(t.get("priority") or 0),
        )
        target = next((t for t in transitions if evaluate_rule(t.get("condition"), context)), None)
        if target is None:
            raise Conflict(
                "The published workflow has no transition out of S1_GATE",
                code="WORKFLOW_MISCONFIGURED",
            )
        step = next(
            (s for s in wf_snapshot.get("steps") or [] if s.get("code") == target["to_step_code"]),
            None,
        )
        if step is None:
            raise Conflict(
                f"Workflow step {target['to_step_code']} is missing", code="WORKFLOW_MISCONFIGURED"
            )
        sla = step.get("sla_hours")
        due_at = datetime.now(UTC) + timedelta(hours=float(sla)) if sla else None
        task_ids: list[UUID] = []
        for a in step.get("assignments") or []:
            if a.get("assignment_type", "PERFORM") != "PERFORM":
                continue
            task_ids.append(
                repo.create_workflow_task(
                    session,
                    gs_id=gs_id,
                    step_code=step["code"],
                    assigned_role_id=UUID(a["role_id"]) if a.get("role_id") else None,
                    assigned_user_id=UUID(a["user_id"]) if a.get("user_id") else None,
                    due_at=due_at,
                )
            )
        return task_ids

    def _notify_missing_documentation(self, session: Session, gs_id: UUID, gs_no: str) -> int:
        """BR-03 / DEC-05: high-priority alert to Accounts and the Replacement Manager."""
        return notifications.publish(
            session,
            "MISSING_DOCUMENTS",
            role_codes=NO_DOC_ALERT_ROLES,
            notification_type="GS_MISSING_DOCUMENTATION",
            title=f"{gs_no}: no document attached at gate",
            body="Consignment flagged for missing documentation; verify at Step-2 (BR-03).",
            entity_type=ENTITY_TYPE,
            entity_id=gs_id,
            gs_id=gs_id,
            data={"gs_no": gs_no},
            priority="HIGH",
        )

    def _notify_provisional_party(
        self, session: Session, resolved: _Resolved, gs_id: UUID, gs_no: str
    ) -> int:
        """DEC-02: admins review provisional parties created at the gate."""
        if resolved.created_party_id is None:
            return 0
        return notifications.publish(
            session,
            "PROVISIONAL_PARTY_CREATED",
            user_ids=repo.active_user_ids_with_permission(session, "masters", "edit"),
            notification_type="PROVISIONAL_PARTY_CREATED",
            title=f"Provisional party '{resolved.values['party_name']}' created at gate",
            body=f"Created with {gs_no}. Review and complete the party master record (DEC-02).",
            entity_type="party",
            entity_id=resolved.created_party_id,
            priority="NORMAL",
        )

    def _notify_accounts_documents(
        self,
        session: Session,
        resolved: _Resolved,
        gs_id: UUID,
        gs_no: str,
        doc_ids: list[UUID],
    ) -> int:
        """Requirement A / AMD-05: alert Accounts once per saved document row whose type is in
        `gate.accounts_alert_doc_types`. Recipients come from the GS_DOCUMENT_FOUND notification
        rule (ACCOUNTS by default); the dedupe key and accounts_alerted_at prevent repeats."""
        return alert_accounts_for_documents(
            session,
            gs_id=gs_id,
            gs_no=gs_no,
            party_name=resolved.values.get("party_name"),
            doc_ids=doc_ids,
        )

    def _published_form(self, session: Session) -> dict[str, Any]:
        form = repo.get_published_form(session, FORM_CODE)
        if not form or not form.get("snapshot"):
            raise NotFound(f"No published {FORM_CODE} form", code="FORM_NOT_PUBLISHED")
        return _with_doc_image_field(form)

    def _timezone(self, session: Session) -> str:
        tz = repo.get_setting(session, "timezone")
        return tz if isinstance(tz, str) and tz else DEFAULT_TIMEZONE

    def _visible_gs(
        self, session: Session, user: CurrentUser, perms: EffectivePermissions, gs_id: UUID
    ) -> dict[str, Any]:
        gs = repo.get_goods_slip_view(session, gs_id)
        if not gs:
            raise NotFound("Goods slip not found")
        scope = perms.scope("goods_slips", "view")
        if scope == "own" and gs["created_by"] != user.id:
            raise NotFound("Goods slip not found")
        return gs

    def _timeline(self, session: Session, gs_id: UUID) -> list[TimelineEntry]:
        entries = [
            TimelineEntry(
                at=h["at"],
                kind="STATUS",
                title=f"{h['from_status'] or 'New'} → {h['to_status']}",
                from_status=h["from_status"],
                to_status=h["to_status"],
                step_code=h["step_code"],
                reason=h["reason"],
                by_user_id=h["by"],
                by_name=h["by_name"],
            )
            for h in repo.get_status_history_with_names(session, gs_id)
        ]
        for a in repo.get_audit_entries_for_gs(session, gs_id):
            changed = [c for c in (a["changed_fields"] or []) if c != "updated_at"]
            if a["action"] == "INSERT":
                if not a["reason"]:
                    continue  # creation is shown from status history
                title = "Created with state/station override"
            elif not changed or set(changed) <= _STATUS_ONLY_FIELDS:
                continue  # status changes are shown from gs_status_history
            else:
                title = "Gate details edited"
            entries.append(
                TimelineEntry(
                    at=a["at"],
                    kind="AUDIT",
                    title=title,
                    reason=a["reason"],
                    changed_fields=changed or None,
                    by_user_id=a["actor_id"],
                    by_name=a["by_name"],
                )
            )
        return sorted(entries, key=lambda e: e.at)


class _Resolved:
    """Validated gate submission: typed columns + form values/labels to store."""

    def __init__(
        self,
        *,
        columns: dict[str, Any],
        values: dict[str, Any],
        labels: dict[str, Any],
        override_note: str | None,
        new_party: tuple[str, UUID, UUID] | None,
        no_doc_text: str,
    ) -> None:
        self.columns = columns
        self.values = values
        self.labels = labels
        self.override_note = override_note
        self.new_party = new_party
        self.no_doc_text = no_doc_text
        self.created_party_id: UUID | None = None
        self.documents: list[dict[str, Any]] = []  # AMD-04 validated rows

    def persist_new_party(self, session: Session) -> None:
        if self.new_party is None:
            return
        name, state_id, station_id = self.new_party
        self.created_party_id = repo.insert_provisional_party(
            session, name=name, state_id=state_id, station_id=station_id
        )
        self.columns["party_id"] = self.created_party_id


def _doc_required_fields(doc_type: dict[str, Any]) -> list[str]:
    raw = doc_type.get("required_fields") or []
    cols = [_DOC_REQUIRED_FIELD_COLUMNS.get(str(f)) for f in raw]
    return [c for c in dict.fromkeys(cols) if c]


def _validate_documents(
    types: list[dict[str, Any]],
    docs: list[GateDocumentIn],
    today: date,
    errors: dict[str, list[str]],
) -> list[dict[str, Any]]:
    """AMD-04: each row needs an active GATE_DOCUMENT type (not NO_DOCUMENT, which is the
    GS-level flag) and the fields that type requires (DD r5-r8, option_items.required_fields)."""
    by_code = {t["code"]: t for t in types if t["code"] != DOC_NONE}
    out: list[dict[str, Any]] = []
    seen: set[UUID] = set()
    for i, doc in enumerate(docs):
        key = f"documents.{i}"
        if doc.id is not None:
            if doc.id in seen:
                errors.setdefault(f"{key}.id", []).append("Duplicate document row")
            seen.add(doc.id)
        dtype = by_code.get(doc.doc_type_code)
        if dtype is None:
            errors.setdefault(f"{key}.doc_type_code", []).append(
                "Unknown or inactive document type"
            )
            continue
        row: dict[str, Any] = {
            "id": doc.id,
            "doc_type_code": dtype["code"],
            "doc_type_label": dtype["label"],  # G-18 label snapshot
            "doc_no": _text(doc.doc_no),
            "doc_date": doc.doc_date,
            "remarks": _text(doc.remarks),
        }
        for col in _doc_required_fields(dtype):
            if row[col] is None:
                errors.setdefault(f"{key}.{col}", []).append(
                    f"{_DOC_COLUMN_LABELS[col]} is required for {dtype['label']}"
                )
        if doc.doc_date is not None and doc.doc_date > today:
            errors.setdefault(f"{key}.doc_date", []).append("Document Date cannot be in the future")
        out.append(row)
    return out


def _save_documents(
    session: Session,
    gs_id: UUID,
    documents: list[dict[str, Any]],
    existing: dict[UUID, dict[str, Any]],
) -> list[UUID]:
    """Insert new rows, update kept rows; returns the ids that are new or changed type (the
    candidates for the AMD-05 Accounts alert)."""
    changed: list[UUID] = []
    for order, doc in enumerate(documents, start=1):
        fields = {
            k: doc[k] for k in ("doc_type_code", "doc_type_label", "doc_no", "doc_date", "remarks")
        }
        if doc["id"] is None:
            changed.append(
                repo.insert_gate_document(session, gs_id=gs_id, fields=fields, sort_order=order)
            )
            continue
        before = existing[doc["id"]]
        repo.update_gate_document(session, doc["id"], fields=fields, sort_order=order)
        if before["doc_type_code"] != doc["doc_type_code"]:
            changed.append(doc["id"])
    return changed


def _documents_out(session: Session, gs_id: UUID) -> list[GateDocumentOut]:
    files: dict[UUID, list[GateDocumentFileOut]] = {}
    for f in repo.list_gate_document_files(session, gs_id):
        files.setdefault(f["gate_document_id"], []).append(
            GateDocumentFileOut(**{k: f[k] for k in GateDocumentFileOut.model_fields})
        )
    return [
        GateDocumentOut(
            **{k: d[k] for k in GateDocumentOut.model_fields if k != "files"},
            files=files.get(d["id"], []),
        )
        for d in repo.list_gate_documents(session, gs_id)
    ]


def _max_backdate_days(session: Session) -> int | None:
    """DEC-38: `gate.max_backdate_days` (null = unlimited; the DB CHECK keeps it a whole number)."""
    value = repo.get_setting(session, "gate.max_backdate_days")
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        logger.error("gate.max_backdate_days is invalid: %r", value)
        raise ServiceUnavailable(
            "System setting gate.max_backdate_days is invalid",
            code="SETTING_INVALID",
            details={"key": "gate.max_backdate_days"},
        )
    return int(value)


def _accounts_alert_doc_types(session: Session) -> set[str]:
    """AMD-05: `gate.accounts_alert_doc_types` (array of GATE_DOCUMENT codes; DB CHECK)."""
    value = repo.get_setting(session, "gate.accounts_alert_doc_types")
    if not isinstance(value, list):
        logger.error("gate.accounts_alert_doc_types is missing or invalid: %r", value)
        raise ServiceUnavailable(
            "System setting gate.accounts_alert_doc_types is missing or invalid",
            code="SETTING_INVALID",
            details={"key": "gate.accounts_alert_doc_types"},
        )
    return {str(v) for v in value}


def _no_document_text(session: Session, snapshot: dict[str, Any]) -> str:
    """Warning text for "no document" (form v2): the configured NO_DOCUMENT option texts."""
    item = next((t for t in repo.gate_document_types(session) if t["code"] == DOC_NONE), None)
    field = _field(snapshot, "no_document") or {}
    if item is None:
        return str(field.get("label") or DOC_NONE)
    return _option_text({"fields": [{"field_key": "x", "option_items": [item]}]}, "x", DOC_NONE)


def _field(snapshot: dict[str, Any], key: str) -> dict[str, Any] | None:
    return next((f for f in snapshot.get("fields") or [] if f.get("field_key") == key), None)


def _option_text(snapshot: dict[str, Any], field_key: str, code: str) -> str:
    """Warning text from the configured option (label + rule + remarks), never hard-coded."""
    field = _field(snapshot, field_key) or {}
    item = next((o for o in field.get("option_items") or [] if o.get("code") == code), None)
    if not item:
        return code
    parts = [item.get("rule_text"), item.get("next_action_text"), item.get("remarks")]
    detail = ". ".join(p for p in parts if p)
    return f"{item.get('label', code)}: {detail}" if detail else str(item.get("label", code))


def _labels_snapshot(snapshot: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    """G-18 / rule e: field labels and option labels as shown at submission time."""
    out: dict[str, Any] = {}
    for field in snapshot.get("fields") or []:
        key = field.get("field_key")
        if key not in values:
            continue
        entry: dict[str, Any] = {"label": field.get("label", key), "value": values[key]}
        options = {o.get("code"): o.get("label") for o in field.get("option_items") or []}
        if options:
            raw = values[key]
            entry["value_label"] = (
                [options.get(v, v) for v in raw] if isinstance(raw, list) else options.get(raw, raw)
            )
        out[key] = entry
    return out


def _tag_field_labels(layout: dict[str, Any], form_snapshot: dict[str, Any]) -> Any:
    """Tag field labels come from config: the template's optional `field_labels`, then the
    S1_GATE_INWARD form labels (party_name, box_count, delivery_mode), else the humanised key."""
    explicit = layout.get("field_labels") or {}
    form_labels = {f.get("field_key"): f.get("label") for f in form_snapshot.get("fields") or []}
    state, station = form_labels.get("state"), form_labels.get("station")
    if state and station:
        form_labels.setdefault("state_station", f"{state} / {station}")

    def label(key: str) -> str:
        found = explicit.get(key) or form_labels.get(key)
        return str(found) if found else key.replace("_", " ").title()

    return label


def _text(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _transport_text(gs: dict[str, Any]) -> str | None:
    parts: list[Any] = [
        gs.get("delivery_mode_label"),
        gs.get("courier_name"),
        gs.get("docket_no"),
        gs.get("transporter_name"),
        gs.get("vehicle_no"),
        gs.get("rep_name"),
    ]
    text_parts = [str(p) for p in parts if p]
    return " · ".join(text_parts) if text_parts else None


def _local_date(ts: datetime, tz: str) -> date:
    return ts.astimezone(ZoneInfo(tz)).date()


# =============================================================================================
# P2-03 · cross-module helpers (service-to-service; other modules never call this repository)
# =============================================================================================


def get_visible_goods_slip(
    session: Session, user: CurrentUser, perms: EffectivePermissions, gs_id: UUID
) -> dict[str, Any]:
    """The GS view row if the user may view it: 404 when it does not exist, 403 when the user's
    goods_slips.view scope does not cover it (per-GS view permission, §9.6)."""
    gs = repo.get_goods_slip_view(session, gs_id)
    if not gs:
        raise NotFound("Goods slip not found")
    scope = perms.scope("goods_slips", "view")
    if scope is None or (scope == "own" and gs["created_by"] != user.id):
        raise PermissionDenied("You do not have access to this goods slip", code="GS_ACCESS_DENIED")
    return gs


def lock_goods_slip(session: Session, gs_id: UUID) -> dict[str, Any]:
    """`SELECT … FOR UPDATE` on the GS row: serialises Step-2 commands on one GS."""
    gs = repo.get_goods_slip(session, gs_id, for_update=True)
    if not gs:
        raise NotFound("Goods slip not found")
    return gs


def change_status_within_step(
    session: Session,
    *,
    gs_id: UUID,
    from_status: str,
    to_status: str,
    step_code: str,
    reason: str,
    by: UUID,
) -> None:
    """Status change that stays on the current workflow step (e.g. S1_UNBOX: GATE_CREATED →
    UNBOXING). The step's open task is unchanged; DB guards (G-01, G-02) still apply."""
    repo.update_gs_status(session, gs_id, to_status)
    repo.record_status_history(
        session,
        gs_id=gs_id,
        from_status=from_status,
        to_status=to_status,
        step_code=step_code,
        reason=reason,
        by_user_id=by,
    )


def workflow_user(user: CurrentUser) -> WorkflowUser:
    """The acting user as the workflow engine sees it (role codes, Super Admin flag)."""
    return WorkflowUser(
        id=user.id, roles=sorted(user.role_codes), is_super_admin=user.is_super_admin
    )


def open_task_ids(session: Session, gs_id: UUID) -> list[UUID]:
    return [UUID(str(t["id"])) for t in repo.get_open_tasks_for_gs(session, gs_id)]


# =============================================================================================
# P2-04 · cross-module helpers for Step-3 itemisation / CSR decision (service-to-service)
# =============================================================================================


def pinned_workflow_snapshot(session: Session, gs: dict[str, Any]) -> dict[str, Any]:
    """The workflow version the GS was created under (G-18)."""
    version = repo.get_workflow_version_by_id(session, gs["workflow_version_id"])
    if not version:
        raise NotFound("The workflow version of this goods slip is missing")
    return dict(version["snapshot"] or {})


def step_role_codes(
    session: Session, gs: dict[str, Any], step_code: str, assignment_type: str
) -> list[str]:
    """Role codes assigned to a step of the GS's pinned workflow (who gets alerts / tasks)."""
    snapshot = pinned_workflow_snapshot(session, gs)
    step = next((s for s in snapshot.get("steps") or [] if s.get("code") == step_code), None)
    return sorted(
        {
            str(a["role_code"])
            for a in (step or {}).get("assignments") or []
            if a.get("assignment_type") == assignment_type and a.get("role_code")
        }
    )


def set_category(
    session: Session,
    gs_id: UUID,
    *,
    category_code: str,
    by: UUID,
    form_version_id: UUID,
    labels_snapshot: dict[str, Any],
) -> None:
    """BR-07: record the GS-wise category (and keep it as the original category)."""
    repo.set_category(
        session,
        gs_id,
        category_code=category_code,
        by=by,
        form_version_id=form_version_id,
        labels_snapshot=labels_snapshot,
    )


def convert_category(session: Session, gs_id: UUID, category_code: str) -> None:
    """BR-08: CSR -> RO on rejection (or back on an admin reopen); the original category stays.
    The DB G-03 trigger only allows it with a matching decision state."""
    repo.update_category(session, gs_id, category_code)


def set_csr_commercial_path(session: Session, gs_id: UUID, value: bool) -> None:
    """BR-09: an approved CSR is flagged for the Step-7 commercial path (CN, CSR closure)."""
    repo.set_csr_commercial_path(session, gs_id, value)


def assert_csr_decided(gs: dict[str, Any], current_decision: dict[str, Any] | None) -> None:
    """G-03 for any downstream action (inspection, handover, Stage-6): 422 `G-03` while a CSR GS
    has no (consistent) Replacement Manager decision. Super Admin cannot bypass it."""
    problem = g03_violation(
        {
            "category_code": gs.get("category_code"),
            "original_category_code": gs.get("original_category_code"),
            "csr_decision": (current_decision or {}).get("decision_code"),
            "csr_decision_authorized": current_decision is not None,
        }
    )
    if problem:
        raise SystemGuardUnmet(
            "G-03",
            "This Complete Sales Return is waiting for the Replacement Manager's decision",
            details={"reason": problem, "status": gs.get("status")},
        )


def reroute_to_step(
    session: Session,
    *,
    gs_id: UUID,
    from_status: str,
    to_status: str,
    step_code: str,
    reason: str,
    by: UUID,
    category_code: str | None = None,
) -> list[UUID]:
    """Admin reopen: cancel the open tasks, record the status change (and category, in the same
    statement) and open the step's tasks again. DB guards (G-03) still apply."""
    gs = lock_goods_slip(session, gs_id)
    repo.cancel_open_tasks(session, gs_id)
    if category_code is None:
        repo.update_gs_status(session, gs_id, to_status)
    else:
        repo.update_status_and_category(session, gs_id, to_status, category_code)
    repo.record_status_history(
        session,
        gs_id=gs_id,
        from_status=from_status,
        to_status=to_status,
        step_code=step_code,
        reason=reason,
        by_user_id=by,
    )
    return _open_step_tasks(session, gs_id, pinned_workflow_snapshot(session, gs), step_code)


def set_audit_reason(session: Session, reason: str | None) -> None:
    """G-17: the reason recorded on the audit rows of this transaction's following writes."""
    repo.set_audit_reason(session, reason)


# =============================================================================================
# P3-01 · cross-module helpers for the custody engine (service-to-service)
# =============================================================================================


def open_task(
    session: Session,
    *,
    gs_id: UUID,
    step_code: str,
    role_id: UUID | None,
    user_id: UUID | None = None,
) -> UUID:
    """An OPEN workflow task for one assignee (e.g. the receiver of a custody transfer)."""
    return repo.create_workflow_task(
        session,
        gs_id=gs_id,
        step_code=step_code,
        assigned_role_id=role_id,
        assigned_user_id=user_id,
    )


def close_task(session: Session, task_id: UUID, *, cancelled: bool = False) -> None:
    repo.set_task_status(session, task_id, "CANCELLED" if cancelled else "DONE")


def sync_step_task(
    session: Session, *, gs_id: UUID, step_code: str, role_id: UUID | None, needed: bool
) -> None:
    """Keep exactly one OPEN task of `step_code` for the role while `needed`, none otherwise."""
    open_ids = repo.open_tasks_for_step(session, gs_id, step_code, role_id)
    if needed and not open_ids:
        repo.create_workflow_task(
            session, gs_id=gs_id, step_code=step_code, assigned_role_id=role_id
        )
    elif not needed:
        for task_id in open_ids:
            repo.set_task_status(session, task_id, "DONE")


def set_discrepancy_flag(session: Session, gs_id: UUID, value: bool) -> None:
    """§6.5 flag `has_discrepancy`: a custody transfer of the GS is frozen in DISCREPANCY."""
    repo.set_discrepancy_flag(session, gs_id, value)


# =============================================================================================
# P3-07 · cross-module helpers for party notification & the closure engine (service-to-service)
# =============================================================================================


def change_status(
    session: Session,
    *,
    gs_id: UUID,
    from_status: str,
    to_status: str,
    step_code: str,
    reason: str,
    by: UUID | None,
) -> None:
    """System status automation (§6.5) recorded in the status history; DB guards still apply."""
    repo.update_gs_status(session, gs_id, to_status)
    repo.record_status_history(
        session,
        gs_id=gs_id,
        from_status=from_status,
        to_status=to_status,
        step_code=step_code,
        reason=reason,
        by_user_id=by,
    )


def open_step_tasks(session: Session, gs: dict[str, Any], step_code: str) -> list[UUID]:
    """Open the tasks of `step_code` for its assignees in the GS's pinned workflow (G-18)."""
    return _open_step_tasks(session, gs["id"], pinned_workflow_snapshot(session, gs), step_code)


def has_open_step_task(session: Session, gs_id: UUID, step_code: str) -> bool:
    return repo.has_open_step_task(session, gs_id, step_code)


def complete_step_tasks(session: Session, gs_id: UUID, step_code: str) -> int:
    return repo.complete_step_tasks(session, gs_id, step_code)


def close_goods_slip(
    session: Session, *, gs_id: UUID, from_status: str, closure_type: str, by: UUID, reason: str
) -> None:
    """G-15 / BR-39: status CLOSED with the closure type; every open task is completed."""
    repo.set_closed(session, gs_id, closure_type)
    repo.record_status_history(
        session,
        gs_id=gs_id,
        from_status=from_status,
        to_status="CLOSED",
        step_code="S6_CLOSE",
        reason=reason,
        by_user_id=by,
    )
    repo.complete_open_tasks(session, gs_id)


def reopen_goods_slip(
    session: Session, *, gs: dict[str, Any], to_status: str, by: UUID, reason: str
) -> None:
    """§6.5: Super Admin reopen (the gs_closures reopen fields are written first)."""
    repo.set_reopened(session, gs["id"], to_status)
    repo.record_status_history(
        session,
        gs_id=gs["id"],
        from_status="CLOSED",
        to_status=to_status,
        step_code="S6_CLOSE",
        reason=reason,
        by_user_id=by,
    )
    _open_step_tasks(session, gs["id"], pinned_workflow_snapshot(session, gs), "S6_CLOSE")


def status_history(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    return repo.get_status_history_with_names(session, gs_id)


# =============================================================================================
# Change plan 2026-11-12 · Phase 2/3: gate & carton-opening document rows (AMD-04, AMD-05).
# Service-to-service helpers (the unboxing module adds carton-opening rows through these).
# =============================================================================================
GATE_DOC_STEP = "S1_GATE"
CARTON_DOC_STEP = "S1_UNBOX"  # Carton Opening (AMD-08 label of the unboxing step)


def _norm_doc_no(value: Any) -> str:
    return " ".join(str(value or "").split()).lower()


def alert_accounts_for_documents(
    session: Session,
    *,
    gs_id: UUID,
    gs_no: str,
    party_name: str | None,
    doc_ids: list[UUID],
) -> int:
    """Requirement A / AMD-05: alert Accounts once per saved document row whose type is in
    `gate.accounts_alert_doc_types`, at the gate or at carton opening. Recipients come from the
    GS_DOCUMENT_FOUND notification rule (ACCOUNTS by default).

    No duplicates: a row is alerted once (`accounts_alerted_at` + per-row dedupe key), and a row
    that repeats a document Accounts was already alerted about for this GS (same type and number,
    e.g. the gate invoice found again in a carton) is marked as alerted without a new alert."""
    if not doc_ids:
        return 0
    codes = _accounts_alert_doc_types(session)
    wanted = set(doc_ids)
    all_rows = repo.list_gate_documents(session, gs_id)
    known = {
        (d["doc_type_code"], _norm_doc_no(d["doc_no"]))
        for d in all_rows
        if d["accounts_alerted_at"] is not None and _norm_doc_no(d["doc_no"])
    }
    candidates = [
        d
        for d in all_rows
        if d["id"] in wanted and d["doc_type_code"] in codes and d["accounts_alerted_at"] is None
    ]
    party = party_name or "-"
    notified = 0
    marked: list[UUID] = []
    for d in candidates:
        key = (d["doc_type_code"], _norm_doc_no(d["doc_no"]))
        marked.append(d["id"])
        if key[1] and key in known:
            continue  # the same document was already reported to Accounts
        known.add(key)
        doc_no = d["doc_no"] or "-"
        date_str = f" dated {d['doc_date'].isoformat()}" if d["doc_date"] else ""
        where = "at carton opening" if d["source_step"] == CARTON_DOC_STEP else "at gate"
        notified += notifications.publish(
            session,
            "GS_DOCUMENT_FOUND",
            notification_type="GS_DOCUMENT_FOUND",
            title=f"{gs_no}: {d['doc_type_label']} received {where} ({doc_no})",
            body=(
                f"Consignment from {party} has {d['doc_type_label']} No. {doc_no}{date_str}. "
                "Check the GST input now; no need to wait for the next step."
            ),
            entity_type=ENTITY_TYPE,
            entity_id=gs_id,
            gs_id=gs_id,
            data={
                "gs_no": gs_no,
                "gate_document_id": str(d["id"]),
                "gate_document_code": d["doc_type_code"],
                "gate_doc_no": doc_no,
                "source_step": d["source_step"],
                "party_name": party,
            },
            priority="HIGH",
            dedupe_key=f"GS_DOCUMENT_FOUND:{d['id']}",
        )
    repo.mark_gate_documents_alerted(session, marked)
    return notified


def validate_document_row(session: Session, doc: GateDocumentIn) -> dict[str, Any]:
    """One document row (AMD-04): active GATE_DOCUMENT type (not NO_DOCUMENT) + the fields that
    type requires (DD r5-r8). Raises FORM_VALIDATION_FAILED with `documents.0.*` keys."""
    errors: dict[str, list[str]] = {}
    rows = _validate_documents(
        repo.gate_document_types(session), [doc], repo.business_today(session), errors
    )
    if errors:
        raise ValidationFailed(
            "The document has errors", code="FORM_VALIDATION_FAILED", details=errors
        )
    return rows[0]


def add_document_row(
    session: Session, gs_id: UUID, row: dict[str, Any], *, source_step: str
) -> UUID:
    fields = {
        k: row[k] for k in ("doc_type_code", "doc_type_label", "doc_no", "doc_date", "remarks")
    }
    return repo.insert_gate_document(
        session,
        gs_id=gs_id,
        fields=fields,
        sort_order=repo.next_gate_document_sort(session, gs_id),
        source_step=source_step,
    )


def get_document_row(session: Session, gs_id: UUID, doc_id: UUID) -> dict[str, Any]:
    doc = next((d for d in repo.list_gate_documents(session, gs_id) if d["id"] == doc_id), None)
    if doc is None:
        raise NotFound("Document not found on this goods slip")
    return doc


def update_document_row(session: Session, doc: dict[str, Any], row: dict[str, Any]) -> bool:
    """Returns True when the type changed (a candidate for the AMD-05 alert)."""
    fields = {
        k: row[k] for k in ("doc_type_code", "doc_type_label", "doc_no", "doc_date", "remarks")
    }
    repo.update_gate_document(session, doc["id"], fields=fields, sort_order=doc["sort_order"])
    return bool(doc["doc_type_code"] != row["doc_type_code"])


def delete_document_row(session: Session, doc_id: UUID) -> None:
    repo.delete_gate_documents(session, [doc_id])


def documents_out(session: Session, gs_id: UUID) -> list[GateDocumentOut]:
    return _documents_out(session, gs_id)


def document_types_out(session: Session) -> list[GateDocumentTypeOut]:
    """Active GATE_DOCUMENT row types (NO_DOCUMENT is the GS-level flag, DEC-03)."""
    return [
        GateDocumentTypeOut(
            code=t["code"], label=t["label"], required_fields=_doc_required_fields(t)
        )
        for t in repo.gate_document_types(session)
        if t["code"] != DOC_NONE
    ]
