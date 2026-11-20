"""Goods slip database access repository (master plan §8.4, prompt P2-01)."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import NotFound


def get_goods_slip(
    session: Session,
    gs_id: UUID,
    *,
    for_update: bool = False,
) -> dict[str, Any] | None:
    """Fetch a single goods slip by ID, optionally locking the row for updates."""
    lock_clause = " for update" if for_update else ""
    stmt = text(
        f"""
        select
          id, gs_no, workflow_version_id, party_id, state_id, station_id,
          delivery_mode_code, courier_name, docket_no, vehicle_no, transporter_id,
          rep_name, rep_contact, box_count, carton_count, return_type_code, gate_entry_date,
          gate_entry_no, gate_document_code, gate_doc_no,
          gate_doc_date, gate_doc_remarks, missing_documentation,
          missing_documentation_cleared_at, category_code,
          original_category_code, status, has_open_pendency, has_discrepancy,
          has_hazard, has_rejections, closed_at, closure_type, created_at,
          created_by, updated_at
        from public.goods_slips
        where id = :gs_id
        {lock_clause}
        """  # noqa: S608
    )
    row = session.execute(stmt, {"gs_id": gs_id}).mappings().first()
    return dict(row) if row else None


def get_published_workflow_version(
    session: Session,
    workflow_code: str = "RMS_STANDARD",
) -> dict[str, Any]:
    """Retrieve the currently published workflow version and snapshot for a workflow code."""
    stmt = text(
        """
        select v.id, v.workflow_definition_id, v.version_no, v.status, v.snapshot
        from public.workflow_versions v
        join public.workflow_definitions d on d.id = v.workflow_definition_id
        where d.code = :code and v.status = 'PUBLISHED'
        order by v.version_no desc
        limit 1
        """
    )
    row = session.execute(stmt, {"code": workflow_code}).mappings().first()
    if not row:
        raise NotFound(f"No published workflow version found for workflow '{workflow_code}'")
    return dict(row)


def get_workflow_version_by_id(
    session: Session,
    version_id: UUID,
) -> dict[str, Any]:
    """Retrieve a workflow version and its frozen snapshot by ID."""
    stmt = text(
        """
        select id, workflow_definition_id, version_no, status, snapshot
        from public.workflow_versions
        where id = :version_id
        """
    )
    row = session.execute(stmt, {"version_id": version_id}).mappings().first()
    if not row:
        raise NotFound(f"Workflow version '{version_id}' not found")
    return dict(row)


def create_goods_slip(
    session: Session,
    *,
    workflow_version_id: UUID,
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
    created_by: UUID | None = None,
) -> dict[str, Any]:
    """Create a new goods slip, generating the next GS number and pinning the workflow version."""
    # Generate sequential number via central number generator (DEC-01)
    gs_no = session.execute(text("select rms_private.next_number('GS') as gs_no")).scalar_one()

    stmt = text(
        """
        insert into public.goods_slips (
          gs_no, workflow_version_id, party_id, state_id, station_id,
          delivery_mode_code, courier_name, docket_no, vehicle_no, transporter_id,
          rep_name, rep_contact, box_count, gate_document_code, gate_doc_no,
          gate_doc_date, gate_doc_remarks, missing_documentation, category_code,
          status, created_by
        ) values (
          :gs_no, :workflow_version_id, :party_id, :state_id, :station_id,
          :delivery_mode_code, :courier_name, :docket_no, :vehicle_no, :transporter_id,
          :rep_name, :rep_contact, :box_count, :gate_document_code, :gate_doc_no,
          :gate_doc_date, :gate_doc_remarks, :missing_documentation, :category_code,
          'GATE_CREATED', :created_by
        )
        returning id
        """
    )
    gs_id = session.execute(
        stmt,
        {
            "gs_no": gs_no,
            "workflow_version_id": workflow_version_id,
            "party_id": party_id,
            "state_id": state_id,
            "station_id": station_id,
            "delivery_mode_code": delivery_mode_code,
            "courier_name": courier_name,
            "docket_no": docket_no,
            "vehicle_no": vehicle_no,
            "transporter_id": transporter_id,
            "rep_name": rep_name,
            "rep_contact": rep_contact,
            "box_count": box_count,
            "gate_document_code": gate_document_code,
            "gate_doc_no": gate_doc_no,
            "gate_doc_date": gate_doc_date,
            "gate_doc_remarks": gate_doc_remarks,
            "missing_documentation": missing_documentation,
            "category_code": category_code,
            "created_by": created_by,
        },
    ).scalar_one()

    created_gs = get_goods_slip(session, UUID(str(gs_id)))
    if not created_gs:
        raise NotFound(f"Goods slip '{gs_id}' could not be loaded after creation")
    return created_gs


def update_gs_status(
    session: Session,
    gs_id: UUID,
    status: str,
) -> None:
    """Update status of a goods slip and refresh updated_at."""
    session.execute(
        text(
            """
            update public.goods_slips
            set status = :status, updated_at = now()
            where id = :gs_id
            """
        ),
        {"gs_id": gs_id, "status": status},
    )


def record_status_history(
    session: Session,
    *,
    gs_id: UUID,
    from_status: str | None,
    to_status: str,
    step_code: str,
    reason: str | None = None,
    by_user_id: UUID | None = None,
) -> UUID:
    """Record a status transition entry in gs_status_history."""
    stmt = text(
        """
        insert into public.gs_status_history (
          gs_id, from_status, to_status, step_code, reason, "by", "at"
        ) values (
          :gs_id, :from_status, :to_status, :step_code, :reason, :by_user_id, clock_timestamp()
        )
        returning id
        """
    )
    hist_id = session.execute(
        stmt,
        {
            "gs_id": gs_id,
            "from_status": from_status,
            "to_status": to_status,
            "step_code": step_code,
            "reason": reason,
            "by_user_id": by_user_id,
        },
    ).scalar_one()
    return UUID(str(hist_id))


def complete_open_tasks(session: Session, gs_id: UUID) -> int:
    """Mark all currently OPEN tasks for a goods slip as DONE."""
    res = session.execute(
        text(
            """
            update public.workflow_tasks
            set status = 'DONE', completed_at = now()
            where gs_id = :gs_id and status = 'OPEN'
            """
        ),
        {"gs_id": gs_id},
    )
    return int(getattr(res, "rowcount", 0))


def create_workflow_task(
    session: Session,
    *,
    gs_id: UUID,
    step_code: str,
    assigned_role_id: UUID | None = None,
    assigned_user_id: UUID | None = None,
    due_at: datetime | None = None,
) -> UUID:
    """Create a new workflow task entry for step assignees."""
    stmt = text(
        """
        insert into public.workflow_tasks (
          gs_id, step_code, assigned_role_id, assigned_user_id, status, due_at, created_at
        ) values (
          :gs_id, :step_code, :assigned_role_id, :assigned_user_id, 'OPEN', :due_at, now()
        )
        returning id
        """
    )
    task_id = session.execute(
        stmt,
        {
            "gs_id": gs_id,
            "step_code": step_code,
            "assigned_role_id": assigned_role_id,
            "assigned_user_id": assigned_user_id,
            "due_at": due_at,
        },
    ).scalar_one()
    return UUID(str(task_id))


def get_open_tasks_for_gs(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    """Return all currently open workflow tasks for a goods slip."""
    stmt = text(
        """
        select id, gs_id, step_code, assigned_role_id, assigned_user_id, status, due_at, created_at
        from public.workflow_tasks
        where gs_id = :gs_id and status = 'OPEN'
        order by created_at
        """
    )
    rows = session.execute(stmt, {"gs_id": gs_id}).mappings().all()
    return [dict(r) for r in rows]


def get_status_history_for_gs(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    """Return status history for a goods slip in chronological order."""
    stmt = text(
        """
        select id, gs_id, from_status, to_status, step_code, reason, "by", "at"
        from public.gs_status_history
        where gs_id = :gs_id
        order by "at" asc
        """
    )
    rows = session.execute(stmt, {"gs_id": gs_id}).mappings().all()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------------------------
# P2-02 · Step-1 gate inward (master plan §2.2 Step-1, §3.2 DD r2-r10). SQL only, no rules.
# ---------------------------------------------------------------------------------------------

_GS_VIEW_SELECT = """
    select g.id, g.gs_no, g.status, g.workflow_version_id,
           g.party_id, p.name as party_name, p.is_provisional as party_is_provisional,
           g.state_id, s.name as state_name, g.station_id, st.name as station_name,
           g.state_station_overridden,
           g.delivery_mode_code, dm.label as delivery_mode_label,
           g.courier_name, g.docket_no, g.vehicle_no, g.transporter_id,
           coalesce(t.name, g.transporter_name) as transporter_name,
           g.rep_name, g.rep_contact, g.box_count, g.carton_count,
           g.return_type_code, rt.label as return_type_label, g.gate_entry_date, g.gate_entry_no,
           g.gate_document_code, gd.label as gate_document_label,
           g.gate_doc_no, g.gate_doc_date, g.gate_doc_remarks, g.missing_documentation,
           g.missing_documentation_cleared_at,
           g.category_code, g.original_category_code, g.csr_commercial_path,
           g.categorized_at, g.has_open_pendency, g.has_discrepancy, g.has_hazard,
           g.has_rejections, g.cancelled_at, g.cancel_reason,
           g.created_at, g.created_by, cb.full_name as created_by_name, g.updated_at
      from public.goods_slips g
      left join public.parties p on p.id = g.party_id
      left join public.states s on s.id = g.state_id
      left join public.stations st on st.id = g.station_id
      left join public.transporters t on t.id = g.transporter_id
      left join public.profiles cb on cb.id = g.created_by
      left join lateral (
        select oi.label from public.option_items oi
          join public.option_sets os on os.id = oi.option_set_id
         where os.code = 'DELIVERY_MODE' and oi.code = g.delivery_mode_code) dm on true
      left join lateral (
        select oi.label from public.option_items oi
          join public.option_sets os on os.id = oi.option_set_id
         where os.code = 'GATE_DOCUMENT' and oi.code = g.gate_document_code) gd on true
      left join lateral (
        select oi.label from public.option_items oi
          join public.option_sets os on os.id = oi.option_set_id
         where os.code = 'RETURN_TYPE' and oi.code = g.return_type_code) rt on true
"""


def get_setting(session: Session, key: str) -> Any:
    return session.execute(
        text("select value from public.system_settings where key = :key"), {"key": key}
    ).scalar()


def get_published_form(session: Session, form_code: str) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                """
                select v.id, v.version_no, v.snapshot
                  from public.form_versions v
                  join public.form_definitions d on d.id = v.form_definition_id
                 where d.code = :code and v.status = 'PUBLISHED'
                """
            ),
            {"code": form_code},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def get_form_version_snapshot(session: Session, version_id: UUID) -> dict[str, Any] | None:
    snapshot = session.execute(
        text("select snapshot from public.form_versions where id = :id"), {"id": version_id}
    ).scalar()
    return dict(snapshot) if snapshot else None


def get_party(session: Session, party_id: UUID) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                """
                select p.id, p.code, p.name, p.state_id, s.name as state_name,
                       p.station_id, st.name as station_name, p.is_provisional, p.is_active
                  from public.parties p
                  left join public.states s on s.id = p.state_id
                  left join public.stations st on st.id = p.station_id
                 where p.id = :id
                """
            ),
            {"id": party_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def get_state(session: Session, state_id: UUID) -> dict[str, Any] | None:
    row = (
        session.execute(
            text("select id, name, is_active from public.states where id = :id"), {"id": state_id}
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def get_station(session: Session, station_id: UUID) -> dict[str, Any] | None:
    row = (
        session.execute(
            text("select id, state_id, name, is_active from public.stations where id = :id"),
            {"id": station_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def get_transporter(session: Session, transporter_id: UUID) -> dict[str, Any] | None:
    row = (
        session.execute(
            text("select id, name, is_active from public.transporters where id = :id"),
            {"id": transporter_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def insert_provisional_party(
    session: Session, *, name: str, state_id: UUID, station_id: UUID
) -> UUID:
    """DEC-02 provisional party. The code is a system identifier, not a business number format."""
    party_id = session.execute(
        text(
            """
            insert into public.parties (code, name, state_id, station_id, is_provisional)
            values ('PROV-' || upper(substr(replace(gen_random_uuid()::text, '-', ''), 1, 10)),
                    :name, :state_id, :station_id, true)
            returning id
            """
        ),
        {"name": name, "state_id": state_id, "station_id": station_id},
    ).scalar_one()
    return UUID(str(party_id))


def next_gs_number(session: Session, timezone: str) -> str:
    """BR-01 / DEC-01: rms_private.next_number('GS', today in the business timezone)."""
    return str(
        session.execute(
            text("select rms_private.next_number('GS', (now() at time zone :tz)::date)"),
            {"tz": timezone},
        ).scalar_one()
    )


_GATE_COLUMNS = (
    "party_id",
    "state_id",
    "station_id",
    "state_station_overridden",
    "delivery_mode_code",
    "courier_name",
    "docket_no",
    "vehicle_no",
    "transporter_id",
    "transporter_name",
    "rep_name",
    "rep_contact",
    "carton_count",  # AMD-03 (box_count follows via the DB sync trigger)
    "return_type_code",  # AMD-01
    "gate_entry_date",  # AMD-02
    "gate_entry_no",  # AMD-02
    "gate_document_code",
    "gate_doc_no",
    "gate_doc_date",
    "gate_doc_remarks",
    "missing_documentation",
)


def insert_gate_goods_slip(
    session: Session, *, gs_no: str, workflow_version_id: UUID, fields: dict[str, Any]
) -> UUID:
    cols = ", ".join(_GATE_COLUMNS)
    binds = ", ".join(f":{c}" for c in _GATE_COLUMNS)
    params = {c: fields.get(c) for c in _GATE_COLUMNS}
    params.update(gs_no=gs_no, workflow_version_id=workflow_version_id)
    gs_id = session.execute(
        text(
            f"""
            insert into public.goods_slips (gs_no, workflow_version_id, status, {cols})
            values (:gs_no, :workflow_version_id, 'GATE_CREATED', {binds})
            returning id
            """  # noqa: S608 - column names come from the fixed _GATE_COLUMNS tuple
        ),
        params,
    ).scalar_one()
    return UUID(str(gs_id))


def update_gate_fields(session: Session, gs_id: UUID, fields: dict[str, Any]) -> None:
    assignments = ", ".join(f"{c} = :{c}" for c in _GATE_COLUMNS)
    params = {c: fields.get(c) for c in _GATE_COLUMNS}
    params["gs_id"] = gs_id
    session.execute(
        text(
            f"update public.goods_slips set {assignments}, updated_at = now() where id = :gs_id"  # noqa: S608
        ),
        params,
    )


def set_audit_reason(session: Session, reason: str | None) -> None:
    """G-17: the audit trigger copies app.reason into audit_log.reason for this transaction."""
    session.execute(text("select set_config('app.reason', :r, true)"), {"r": reason or ""})


def cancel_goods_slip(session: Session, gs_id: UUID, *, reason: str, by: UUID) -> None:
    session.execute(
        text(
            """
            update public.goods_slips
               set status = 'CANCELLED', cancelled_at = now(), cancelled_by = :by,
                   cancel_reason = :reason, updated_at = now()
             where id = :gs_id
            """
        ),
        {"gs_id": gs_id, "reason": reason, "by": by},
    )


def cancel_open_tasks(session: Session, gs_id: UUID) -> int:
    res = session.execute(
        text(
            """
            update public.workflow_tasks set status = 'CANCELLED', completed_at = now()
             where gs_id = :gs_id and status = 'OPEN'
            """
        ),
        {"gs_id": gs_id},
    )
    return int(getattr(res, "rowcount", 0))


def insert_form_response(
    session: Session,
    *,
    entity_type: str,
    entity_id: UUID,
    form_version_id: UUID,
    values: dict[str, Any],
    labels_snapshot: dict[str, Any],
) -> UUID:
    response_id = session.execute(
        text(
            """
            insert into public.form_responses
                   (entity_type, entity_id, form_version_id, "values", labels_snapshot)
            values (:et, :eid, :fv, cast(:vals as jsonb), cast(:labels as jsonb))
            returning id
            """
        ),
        {
            "et": entity_type,
            "eid": entity_id,
            "fv": form_version_id,
            "vals": json.dumps(values, default=str),
            "labels": json.dumps(labels_snapshot, default=str),
        },
    ).scalar_one()
    return UUID(str(response_id))


def get_form_response(
    session: Session, *, entity_type: str, entity_id: UUID, form_code: str
) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                """
                select r.id, r.form_version_id, r."values", r.labels_snapshot
                  from public.form_responses r
                  join public.form_versions v on v.id = r.form_version_id
                  join public.form_definitions d on d.id = v.form_definition_id
                 where r.entity_type = :et and r.entity_id = :eid and d.code = :code
                 order by r.submitted_at desc
                 limit 1
                """
            ),
            {"et": entity_type, "eid": entity_id, "code": form_code},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def update_form_response(
    session: Session, response_id: UUID, *, values: dict[str, Any], labels_snapshot: dict[str, Any]
) -> None:
    session.execute(
        text(
            """
            update public.form_responses
               set "values" = cast(:vals as jsonb), labels_snapshot = cast(:labels as jsonb),
                   updated_at = now()
             where id = :id
            """
        ),
        {
            "id": response_id,
            "vals": json.dumps(values, default=str),
            "labels": json.dumps(labels_snapshot, default=str),
        },
    )


def active_user_ids_with_permission(session: Session, module_code: str, action: str) -> list[UUID]:
    """Active Super Admins plus users whose roles grant module.action (minus live denies)."""
    rows = session.execute(
        text(
            """
            select p.id from public.profiles p
             where p.is_active
               and (p.is_super_admin
                    or (exists (
                          select 1 from public.user_roles ur
                            join public.role_permissions rp on rp.role_id = ur.role_id
                            join public.permissions pm on pm.id = rp.permission_id
                           where ur.user_id = p.id and pm.module_code = :m and pm.action = :a)
                        and not exists (
                          select 1 from public.user_permission_overrides o
                            join public.permissions pm on pm.id = o.permission_id
                           where o.user_id = p.id and o.effect = 'deny'
                             and pm.module_code = :m and pm.action = :a
                             and (o.expires_at is null or o.expires_at > now()))))
            """
        ),
        {"m": module_code, "a": action},
    ).scalars()
    return [UUID(str(r)) for r in rows]


def get_goods_slip_view(session: Session, gs_id: UUID) -> dict[str, Any] | None:
    row = (
        session.execute(text(_GS_VIEW_SELECT + " where g.id = :id"), {"id": gs_id})
        .mappings()
        .first()
    )
    return dict(row) if row else None


LIST_FLAG_COLUMNS = {
    "missing_documentation": "g.missing_documentation",
    "has_open_pendency": "g.has_open_pendency",
    "has_discrepancy": "g.has_discrepancy",
    "has_hazard": "g.has_hazard",
    "has_rejections": "g.has_rejections",
}
LIST_SORTS = {
    "created_at": "g.created_at",
    "gs_no": "g.gs_no",
    "status": "g.status",
    "box_count": "g.box_count",
    "carton_count": "g.carton_count",
}


def list_goods_slips(
    session: Session,
    *,
    statuses: list[str] | None,
    party_id: UUID | None,
    date_from: Any,
    date_to: Any,
    timezone: str,
    q: str | None,
    flags: list[str],
    scope_created_by: UUID | None,
    scope_department_of: UUID | None,
    order_by: str,
    limit: int,
    offset: int,
    cursor_created_at: Any = None,
    cursor_id: UUID | None = None,
) -> tuple[list[dict[str, Any]], int]:
    where = ["true"]
    params: dict[str, Any] = {"tz": timezone, "limit": limit, "offset": offset}
    if cursor_created_at and cursor_id:
        where.append("(g.created_at, g.id) < (:cursor_at, :cursor_id)")
        params["cursor_at"] = cursor_created_at
        params["cursor_id"] = cursor_id
        params["offset"] = 0
    if statuses:
        where.append("g.status = any(:statuses)")
        params["statuses"] = statuses
    if party_id:
        where.append("g.party_id = :party_id")
        params["party_id"] = party_id
    if date_from:
        where.append("(g.created_at at time zone :tz)::date >= :date_from")
        params["date_from"] = date_from
    if date_to:
        where.append("(g.created_at at time zone :tz)::date <= :date_to")
        params["date_to"] = date_to
    if q:
        # AMD-02 / AMD-04: the gate entry number and gate document numbers are searchable too.
        where.append(
            "(g.gs_no ilike :q or p.name ilike :q or g.gate_entry_no::text = :q_exact"
            " or exists (select 1 from public.gs_gate_documents d"
            " where d.gs_id = g.id and d.doc_no ilike :q))"
        )
        params["q_exact"] = q
        params["q"] = f"%{q}%"
    where.extend(LIST_FLAG_COLUMNS[flag] for flag in flags)
    if scope_created_by:
        where.append("g.created_by = :scope_uid")
        params["scope_uid"] = scope_created_by
    if scope_department_of:
        where.append(
            "cb.department_id is not distinct from "
            "(select department_id from public.profiles where id = :scope_dept_uid)"
        )
        params["scope_dept_uid"] = scope_department_of
    where_sql = " and ".join(where)
    base = f"""
        from public.goods_slips g
        left join public.parties p on p.id = g.party_id
        left join public.stations st on st.id = g.station_id
        left join public.profiles cb on cb.id = g.created_by
       where {where_sql}
    """
    total = int(session.execute(text("select count(*) " + base), params).scalar_one())
    rows = session.execute(
        text(
            f"""
            select g.id, g.gs_no, g.status, p.name as party_name,
                   p.is_provisional as party_is_provisional, st.name as station_name,
                   g.box_count, g.carton_count, g.return_type_code, g.gate_entry_no,
                   g.delivery_mode_code, g.missing_documentation,
                   g.has_open_pendency, g.has_discrepancy, g.has_hazard, g.has_rejections,
                   g.created_at
            {base}
            order by {order_by}
            limit :limit offset :offset
            """
        ),
        params,
    ).mappings()
    return [dict(r) for r in rows], total


def get_status_history_with_names(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            select h.from_status, h.to_status, h.step_code, h.reason, h."by", h."at",
                   p.full_name as by_name
              from public.gs_status_history h
              left join public.profiles p on p.id = h."by"
             where h.gs_id = :gs_id
             order by h."at", h.id
            """
        ),
        {"gs_id": gs_id},
    ).mappings()
    return [dict(r) for r in rows]


def get_audit_entries_for_gs(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    """G-17 audit rows for the GS header row."""
    rows = session.execute(
        text(
            """
            select a.action, a.changed_fields, a.reason, a.actor_id, a.at, p.full_name as by_name
              from public.audit_log a
              left join public.profiles p on p.id = a.actor_id
             where a.table_name = 'public.goods_slips' and a.row_id = :rid
             order by a.at, a.id
            """
        ),
        {"rid": str(gs_id)},
    ).mappings()
    return [dict(r) for r in rows]


def get_tasks_for_gs(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            select t.id, t.gs_id, t.step_code, ws.label as step_label,
                   r.code as assigned_role_code, t.assigned_user_id, t.status, t.due_at,
                   t.created_at, t.completed_at
              from public.workflow_tasks t
              join public.goods_slips g on g.id = t.gs_id
              left join public.roles r on r.id = t.assigned_role_id
              left join public.workflow_steps ws
                     on ws.workflow_version_id = g.workflow_version_id and ws.code = t.step_code
             where t.gs_id = :gs_id
             order by t.created_at
            """
        ),
        {"gs_id": gs_id},
    ).mappings()
    return [dict(r) for r in rows]


def get_attachment_summary(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            select kind, status, count(*)::integer as count
              from public.attachments where gs_id = :gs_id
             group by kind, status order by kind, status
            """
        ),
        {"gs_id": gs_id},
    ).mappings()
    return [dict(r) for r in rows]


def get_published_template(session: Session, code: str) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                """
                select code, version_no, coalesce(snapshot, layout) as layout
                  from public.print_templates where code = :code and status = 'PUBLISHED'
                """
            ),
            {"code": code},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def search_parties(session: Session, q: str | None, limit: int) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            select p.id, p.name, p.code, p.state_id, s.name as state_name,
                   p.station_id, st.name as station_name, p.is_provisional
              from public.parties p
              left join public.states s on s.id = p.state_id
              left join public.stations st on st.id = p.station_id
             where p.is_active and (:q = '' or p.name ilike :like or p.code ilike :like)
             order by p.name
             limit :limit
            """
        ),
        {"q": q or "", "like": f"%{q or ''}%", "limit": limit},
    ).mappings()
    return [dict(r) for r in rows]


def count_station_parties(session: Session, station_id: UUID) -> int:
    return int(
        session.execute(
            text("select count(*) from public.parties where is_active and station_id = :sid"),
            {"sid": station_id},
        ).scalar_one()
    )


def search_parties_paged(
    session: Session,
    *,
    q: str | None,
    state_id: UUID | None,
    station_id: UUID | None,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    """Active parties, optionally limited to a state and/or station, searchable by name/code."""
    where = """
         where p.is_active
           and (cast(:state as uuid) is null or p.state_id = cast(:state as uuid))
           and (cast(:station as uuid) is null or p.station_id = cast(:station as uuid))
           and (:q = '' or p.name ilike :like or p.code ilike :like)
    """
    binds = {"q": q or "", "like": f"%{q or ''}%", "state": state_id, "station": station_id}
    total = session.execute(
        text("select count(*) from public.parties p" + where),  # noqa: S608 - static SQL
        binds,
    ).scalar_one()
    rows = session.execute(
        text(
            """
            select p.id, p.name, p.code, p.state_id, s.name as state_name,
                   p.station_id, st.name as station_name, p.is_provisional
              from public.parties p
              left join public.states s on s.id = p.state_id
              left join public.stations st on st.id = p.station_id
            """  # noqa: S608 - static SQL; values are bound
            + where
            + " order by p.name, p.code limit :limit offset :offset"
        ),
        {**binds, "limit": limit, "offset": offset},
    ).mappings()
    return [dict(r) for r in rows], int(total)


def list_states(session: Session) -> list[dict[str, Any]]:
    rows = session.execute(
        text("select id, name, code from public.states where is_active order by name")
    ).mappings()
    return [dict(r) for r in rows]


def list_stations(session: Session, state_id: UUID | None) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            select st.id, st.name, st.state_id, s.name as state_name
              from public.stations st join public.states s on s.id = st.state_id
             where st.is_active and (cast(:sid as uuid) is null or st.state_id = cast(:sid as uuid))
             order by s.name, st.name
            """
        ),
        {"sid": state_id},
    ).mappings()
    return [dict(r) for r in rows]


def search_transporters(session: Session, q: str | None, limit: int) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            select id, name from public.transporters
             where is_active and (:q = '' or name ilike :like)
             order by name limit :limit
            """
        ),
        {"q": q or "", "like": f"%{q or ''}%", "limit": limit},
    ).mappings()
    return [dict(r) for r in rows]


# --- P2-04 · categorisation -----------------------------------------------------------------
def set_category(
    session: Session,
    gs_id: UUID,
    *,
    category_code: str,
    by: UUID,
    form_version_id: UUID,
    labels_snapshot: dict[str, Any],
) -> None:
    session.execute(
        text(
            """
            update public.goods_slips
               set category_code = :code, original_category_code = :code,
                   categorized_by = :by, categorized_at = now(),
                   category_form_version_id = :fv,
                   category_labels_snapshot = cast(:labels as jsonb), updated_at = now()
             where id = :id
            """
        ),
        {
            "id": gs_id,
            "code": category_code,
            "by": by,
            "fv": form_version_id,
            "labels": json.dumps(labels_snapshot, default=str),
        },
    )


def update_category(session: Session, gs_id: UUID, category_code: str) -> None:
    session.execute(
        text(
            "update public.goods_slips set category_code = :code, updated_at = now() where id = :id"
        ),
        {"id": gs_id, "code": category_code},
    )


def update_status_and_category(
    session: Session, gs_id: UUID, status: str, category_code: str
) -> None:
    session.execute(
        text(
            "update public.goods_slips set status = :s, category_code = :c, updated_at = now() "
            "where id = :id"
        ),
        {"id": gs_id, "s": status, "c": category_code},
    )


def set_csr_commercial_path(session: Session, gs_id: UUID, value: bool) -> None:
    session.execute(
        text(
            "update public.goods_slips set csr_commercial_path = :v, updated_at = now() "
            "where id = :id"
        ),
        {"id": gs_id, "v": value},
    )


# --- P3-01 · custody engine helpers (tasks, discrepancy flag) ------------------------------------
def set_task_status(session: Session, task_id: UUID, status: str) -> None:
    session.execute(
        text(
            """
            update public.workflow_tasks set status = :s, completed_at = now()
             where id = :id and status = 'OPEN'
            """
        ),
        {"id": task_id, "s": status},
    )


def open_tasks_for_step(
    session: Session, gs_id: UUID, step_code: str, role_id: UUID | None
) -> list[UUID]:
    rows = session.execute(
        text(
            """
            select id from public.workflow_tasks
             where gs_id = :gs and step_code = :step and status = 'OPEN'
               and assigned_role_id is not distinct from :role
            """
        ),
        {"gs": gs_id, "step": step_code, "role": role_id},
    ).scalars()
    return [UUID(str(r)) for r in rows]


def set_discrepancy_flag(session: Session, gs_id: UUID, value: bool) -> None:
    session.execute(
        text(
            "update public.goods_slips set has_discrepancy = :v, updated_at = now() "
            "where id = :id and has_discrepancy is distinct from :v"
        ),
        {"id": gs_id, "v": value},
    )


# --- P3-07 · closure engine helpers -------------------------------------------------------------


def complete_step_tasks(session: Session, gs_id: UUID, step_code: str) -> int:
    res = session.execute(
        text(
            """
            update public.workflow_tasks set status = 'DONE', completed_at = now()
             where gs_id = :gs and step_code = :step and status = 'OPEN'
            """
        ),
        {"gs": gs_id, "step": step_code},
    )
    return int(getattr(res, "rowcount", 0))


def has_open_step_task(session: Session, gs_id: UUID, step_code: str) -> bool:
    return bool(
        session.execute(
            text(
                "select exists (select 1 from public.workflow_tasks "
                "where gs_id = :gs and step_code = :step and status = 'OPEN')"
            ),
            {"gs": gs_id, "step": step_code},
        ).scalar_one()
    )


def set_closed(session: Session, gs_id: UUID, closure_type: str) -> None:
    """G-15: the DB trigger re-runs the closure checklist on this statement."""
    session.execute(
        text(
            """
            update public.goods_slips
               set status = 'CLOSED', closure_type = :ct, closed_at = clock_timestamp(),
                   updated_at = now()
             where id = :id
            """
        ),
        {"id": gs_id, "ct": closure_type},
    )


def set_reopened(session: Session, gs_id: UUID, to_status: str) -> None:
    session.execute(
        text(
            """
            update public.goods_slips
               set status = :st, closure_type = null, closed_at = null, updated_at = now()
             where id = :id
            """
        ),
        {"id": gs_id, "st": to_status},
    )


# ---------------------------------------------------------------------------------------------
# Change plan 2026-11-12 · Phase 2 — gate entry & gate documents (AMD-01 … AMD-05). SQL only.
# ---------------------------------------------------------------------------------------------


def business_today(session: Session) -> date:
    """Today in the business timezone (same function the DB guards use)."""
    return cast(date, session.execute(text("select rms_private.business_today()")).scalar_one())


def gate_entry_no_taken(
    session: Session, *, gate_entry_no: int, gate_entry_date: date, exclude_gs_id: UUID | None
) -> str | None:
    """GS number already holding this gate entry number in the same financial year (DEC-38).
    The FY uses the GS number series start month, exactly as the DB trigger does."""
    return session.execute(
        text(
            """
            with fy as (
              select (extract(year from cast(:d as date))::int
                      - case when extract(month from cast(:d as date))::int
                                  < coalesce((select fy_start_month from public.number_series
                                               where code = 'GS'), 4)
                             then 1 else 0 end)::smallint as y
            )
            select g.gs_no from public.goods_slips g, fy
             where g.gate_entry_no = :no and g.gate_entry_fy = fy.y and g.status <> 'CANCELLED'
               and (cast(:exclude as uuid) is null or g.id <> cast(:exclude as uuid))
             limit 1
            """
        ),
        {"no": gate_entry_no, "d": gate_entry_date, "exclude": exclude_gs_id},
    ).scalar()


def gate_document_types(
    session: Session, set_code: str = "GATE_DOCUMENT", *, active_only: bool = True
) -> list[dict[str, Any]]:
    """Document type option items (code, label, required_fields, is_active) of GATE_DOCUMENT or,
    for gate v4 transport documents, GATE_TRANSPORT_DOCUMENT (DEC-62)."""
    rows = session.execute(
        text(
            """
            select oi.code, oi.label, oi.required_fields, oi.sort_order, oi.is_active
              from public.option_items oi
              join public.option_sets os on os.id = oi.option_set_id
             where os.code = :set_code and (oi.is_active or not :active_only)
             order by oi.sort_order, oi.code
            """
        ),
        {"set_code": set_code, "active_only": active_only},
    ).mappings()
    return [dict(r) for r in rows]


def set_no_document_cleared(session: Session, gs_id: UUID, *, by: UUID | None) -> None:
    """Q27: clear (by = the user) or restore (by = None) the "No Documents From Party" flag."""
    session.execute(
        text(
            """
            update public.goods_slips
               set missing_documentation = (cast(:by as uuid) is null),
                   missing_documentation_cleared_at = case when cast(:by as uuid) is null
                                                           then null else now() end,
                   missing_documentation_cleared_by = cast(:by as uuid)
             where id = :gs_id
            """
        ),
        {"gs_id": gs_id, "by": by},
    )


def list_gate_documents(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            select d.id, d.gs_id, d.doc_type_code, d.doc_type_label, d.doc_no, d.doc_date,
                   d.remarks, d.source_step, d.doc_source, d.sort_order, d.accounts_alerted_at,
                   d.created_at
              from public.gs_gate_documents d
             where d.gs_id = :gs_id
             order by d.sort_order, d.created_at
            """
        ),
        {"gs_id": gs_id},
    ).mappings()
    return [dict(r) for r in rows]


def list_gate_document_files(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            select a.id, a.gate_document_id, a.mime_type, a.size_bytes, a.status,
                   a.preview_unsupported, a.created_at
              from public.attachments a
             where a.gs_id = :gs_id and a.kind = 'GATE_DOC' and a.status <> 'REJECTED'
             order by a.created_at
            """
        ),
        {"gs_id": gs_id},
    ).mappings()
    return [dict(r) for r in rows]


def insert_gate_document(
    session: Session,
    *,
    gs_id: UUID,
    fields: dict[str, Any],
    sort_order: int,
    source_step: str = "S1_GATE",
    doc_source: str | None = None,
) -> UUID:
    doc_id = session.execute(
        text(
            """
            insert into public.gs_gate_documents
                   (gs_id, doc_type_code, doc_type_label, doc_no, doc_date, remarks,
                    source_step, doc_source, sort_order)
            values (:gs_id, :doc_type_code, :doc_type_label, :doc_no, :doc_date, :remarks,
                    :source_step, :doc_source, :sort_order)
            returning id
            """
        ),
        {
            "gs_id": gs_id,
            "sort_order": sort_order,
            "source_step": source_step,
            "doc_source": doc_source,
            **fields,
        },
    ).scalar_one()
    return UUID(str(doc_id))


def update_gate_document(
    session: Session, doc_id: UUID, *, fields: dict[str, Any], sort_order: int
) -> None:
    session.execute(
        text(
            """
            update public.gs_gate_documents
               set doc_type_code = :doc_type_code, doc_type_label = :doc_type_label,
                   doc_no = :doc_no, doc_date = :doc_date, remarks = :remarks,
                   sort_order = :sort_order, updated_at = now()
             where id = :id
            """
        ),
        {"id": doc_id, "sort_order": sort_order, **fields},
    )


def delete_gate_documents(session: Session, doc_ids: list[UUID]) -> None:
    if doc_ids:
        session.execute(
            text("delete from public.gs_gate_documents where id = any(:ids)"), {"ids": doc_ids}
        )


def mark_gate_documents_alerted(session: Session, doc_ids: list[UUID]) -> None:
    if doc_ids:
        session.execute(
            text(
                "update public.gs_gate_documents set accounts_alerted_at = now() "
                "where id = any(:ids) and accounts_alerted_at is null"
            ),
            {"ids": doc_ids},
        )


def next_gate_document_sort(session: Session, gs_id: UUID) -> int:
    return int(
        session.execute(
            text(
                "select coalesce(max(sort_order), 0) + 1 from public.gs_gate_documents "
                "where gs_id = :gs_id"
            ),
            {"gs_id": gs_id},
        ).scalar_one()
    )


def gs_status_labels(session: Session) -> list[dict[str, Any]]:
    """AMD-08: GS_STATUS option set (code = goods_slips.status, admin-editable label)."""
    rows = session.execute(
        text(
            """
            select oi.code, oi.label
              from public.option_items oi
              join public.option_sets os on os.id = oi.option_set_id
             where os.code = 'GS_STATUS' and oi.is_active
             order by oi.sort_order, oi.code
            """
        )
    ).mappings()
    return [dict(r) for r in rows]
