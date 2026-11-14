"""Role journey SQL (change plan Phase 10, AMD-22). SQL only, no business rules.

Each work queue (`journey_steps.queue_code`) is one fixed SQL fragment that yields the goods slips
waiting at that step. The fragments mirror the queue screens of the owning modules (cited per
queue) so the counts in My Work match what the queue screen shows.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

# "Since" for a status queue: when the GS entered its current status.
_SINCE_STATUS = """coalesce((select max(h."at") from public.gs_status_history h
                             where h.gs_id = g.id and h.to_status = g.status), g.created_at)"""

# Every fragment selects: gs_id, gs_no, party_name, station_name, target_id, since.
_GS_COLS = "g.id as gs_id, g.gs_no, pa.name as party_name, st.name as station_name"
_GS_JOINS = """left join public.parties pa on pa.id = g.party_id
               left join public.stations st on st.id = g.station_id"""

_QUEUES: dict[str, str] = {
    # AMD-04: Carton Opening works GATE_CREATED / UNBOXING (unboxing module).
    "CARTON_OPENING": f"""
        select {_GS_COLS}, g.id as target_id, {_SINCE_STATUS} as since
          from public.goods_slips g {_GS_JOINS}
         where g.status in ('GATE_CREATED', 'UNBOXING')""",  # noqa: S608
    # AMD-08: Counting = ITEMIZATION; Categorisation = CATEGORISATION (itemization module).
    "COUNTING": f"""
        select {_GS_COLS}, g.id as target_id, {_SINCE_STATUS} as since
          from public.goods_slips g {_GS_JOINS}
         where g.status = 'ITEMIZATION'""",  # noqa: S608
    "CATEGORISATION": f"""
        select {_GS_COLS}, g.id as target_id, {_SINCE_STATUS} as since
          from public.goods_slips g {_GS_JOINS}
         where g.status = 'CATEGORISATION'""",  # noqa: S608
    # AMD-12: RM review until the RM approves and the Transfer Slip is generated (rm_review).
    "RM_REVIEW": f"""
        select {_GS_COLS}, g.id as target_id, {_SINCE_STATUS} as since
          from public.goods_slips g {_GS_JOINS}
         where g.status = 'RM_REVIEW' and g.transfer_slip_id is null""",  # noqa: S608
    # AMD-13: Transfer Slip waiting for the intermediate store to accept it (custody).
    "STORE_ACCEPT": f"""
        select {_GS_COLS}, t.id as target_id, t.initiated_at as since
          from public.goods_slips g
          join public.custody_transfers t on t.id = g.transfer_slip_id {_GS_JOINS}
         where g.status = 'RM_REVIEW' and t.status = 'INITIATED'""",  # noqa: S608
    # AMD-14: held at the store, nothing routed yet, not finalised (department_routing queue).
    "DEPT_ROUTING": f"""
        select {_GS_COLS}, g.id as target_id, {_SINCE_STATUS} as since
          from public.goods_slips g {_GS_JOINS}
         where g.status = 'HELD_AT_INTERMEDIATE_STORE'
           and not exists (select 1 from public.department_routings dr
                            where dr.gs_id = g.id and dr.status <> 'CANCELLED')
           and not exists (select 1 from public.ac_action_slips s
                            where s.gs_id = g.id and s.status = 'CURRENT')""",  # noqa: S608
    # AMD-15: routings DISPATCHED / PARTIALLY_RECEIVED (department_routing receiving queue).
    "DEPT_RECEIVING": f"""
        select {_GS_COLS}, r.id as target_id, r.dispatched_at as since
          from public.department_routings r
          join public.goods_slips g on g.id = r.gs_id {_GS_JOINS}
         where r.status in ('DISPATCHED', 'PARTIALLY_RECEIVED')""",  # noqa: S608
    # AMD-16 / DEC-46: held, routed before, nothing at a department now, not finalised yet.
    "FINAL_ACTIONS": f"""
        select {_GS_COLS}, g.id as target_id, {_SINCE_STATUS} as since
          from public.goods_slips g {_GS_JOINS}
         where g.status = 'HELD_AT_INTERMEDIATE_STORE'
           and exists (select 1 from public.department_routings dr
                        where dr.gs_id = g.id and dr.status <> 'CANCELLED')
           and not exists (select 1 from public.department_routings dr
                            where dr.gs_id = g.id
                              and dr.status in ('DISPATCHED', 'PARTIALLY_RECEIVED'))
           and not exists (select 1 from public.ac_action_slips s
                            where s.gs_id = g.id and s.status = 'CURRENT')""",  # noqa: S608
    # AMD-05 / BR-06: documents not yet acknowledged by Accounts (unboxing document queue).
    "ACCOUNTS_DOCS": f"""
        select {_GS_COLS}, g.id as target_id,
               (select min(d.created_at) from public.gs_documents d
                 where d.gs_id = g.id and d.accounts_acknowledged_at is null) as since
          from public.goods_slips g {_GS_JOINS}
         where g.status not in ('GATE_CREATED', 'UNBOXING', 'CANCELLED')
           and exists (select 1 from public.gs_documents d
                        where d.gs_id = g.id and d.accounts_acknowledged_at is null)""",  # noqa: S608
    # AMD-18: CURRENT A/c Actions slip not yet completed by Accounts (ac_entry queue).
    "ACCOUNTS_ENTRY": f"""
        select {_GS_COLS}, g.id as target_id, s.finalised_at as since
          from public.ac_action_slips s
          join public.goods_slips g on g.id = s.gs_id {_GS_JOINS}
         where s.status = 'CURRENT' and g.status <> 'CANCELLED'
           and not exists (select 1 from public.ac_entry_completions c
                            where c.ac_action_slip_id = s.id)""",  # noqa: S608
    # AMD-19: Dispatch Slip READY, not dispatched yet (ac_entry dispatch slips).
    "DISPATCH_SLIP": f"""
        select {_GS_COLS}, d.id as target_id, d.generated_at as since
          from public.dispatch_slips d
          join public.goods_slips g on g.id = d.gs_id {_GS_JOINS}
         where d.status = 'READY'""",  # noqa: S608
    # AMD-20 / DEC-48: Accounts completed, no party email SENT yet, GS still open.
    "PARTY_EMAIL": f"""
        select {_GS_COLS}, g.id as target_id, c.completed_at as since
          from public.ac_entry_completions c
          join public.ac_action_slips s on s.id = c.ac_action_slip_id and s.status = 'CURRENT'
          join public.goods_slips g on g.id = c.gs_id {_GS_JOINS}
         where g.status not in ('CLOSED', 'CANCELLED')
           and not exists (select 1 from public.party_emails e
                            where e.ac_action_slip_id = s.id and e.status = 'SENT')""",  # noqa: S608
}

QUEUE_CODES = frozenset(_QUEUES)


def get_setting(session: Session, key: str) -> Any:
    return session.execute(
        text("select value from public.system_settings where key = :k"), {"k": key}
    ).scalar()


def list_catalogue(session: Session) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            select id, code, label, hint, kind, screen_key, item_screen_key, queue_code,
                   feature_code, perm_module, perm_action, sort_order, is_active
              from public.journey_steps
             order by sort_order, code
            """
        )
    ).mappings()
    return [dict(r) for r in rows]


def list_user_steps(session: Session, user_id: UUID) -> list[dict[str, Any]]:
    """Active steps assigned to any of the user's roles, with the lowest role sort order."""
    rows = session.execute(
        text(
            """
            select s.code, s.label, s.hint, s.kind, s.screen_key, s.item_screen_key, s.queue_code,
                   s.feature_code, s.perm_module, s.perm_action, s.sort_order as catalogue_order,
                   min(rjs.sort_order) as role_order
              from public.user_roles ur
              join public.role_journey_steps rjs on rjs.role_id = ur.role_id
              join public.journey_steps s on s.id = rjs.journey_step_id
             where ur.user_id = :uid and s.is_active
             group by s.id
             order by (s.kind = 'TOOL'), min(rjs.sort_order), s.sort_order
            """
        ),
        {"uid": user_id},
    ).mappings()
    return [dict(r) for r in rows]


def queue_summary(session: Session, queue_code: str) -> tuple[int, dict[str, Any] | None]:
    """(count, oldest waiting entry) of one queue."""
    sql = _QUEUES[queue_code]
    count = int(session.execute(text(f"select count(*) from ({sql}) q")).scalar_one())  # noqa: S608
    first = (
        session.execute(
            text(f"select * from ({sql}) q order by q.since nulls last, q.gs_no limit 1")  # noqa: S608
        )
        .mappings()
        .first()
    )
    return count, (dict(first) if first else None)


def queue_items(session: Session, queue_code: str, limit: int) -> tuple[list[dict[str, Any]], int]:
    sql = _QUEUES[queue_code]
    total = int(session.execute(text(f"select count(*) from ({sql}) q")).scalar_one())  # noqa: S608
    rows = session.execute(
        text(f"select * from ({sql}) q order by q.since nulls last, q.gs_no limit :lim"),  # noqa: S608
        {"lim": limit},
    ).mappings()
    return [dict(r) for r in rows], total


# --- admin ---------------------------------------------------------------------------------------


def list_roles(session: Session) -> list[dict[str, Any]]:
    rows = session.execute(
        text("select id, code, name from public.roles where code <> 'SUPER_ADMIN' order by name")
    ).mappings()
    return [dict(r) for r in rows]


def list_role_assignments(session: Session) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            select r.code as role_code, s.code as step_code, rjs.sort_order
              from public.role_journey_steps rjs
              join public.roles r on r.id = rjs.role_id
              join public.journey_steps s on s.id = rjs.journey_step_id
             order by r.code, rjs.sort_order, s.sort_order
            """
        )
    ).mappings()
    return [dict(r) for r in rows]


def get_role(session: Session, role_code: str) -> dict[str, Any] | None:
    row = (
        session.execute(
            text("select id, code, name from public.roles where code = :c"), {"c": role_code}
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def step_ids_by_code(session: Session, codes: list[str]) -> dict[str, UUID]:
    rows = session.execute(
        text("select code, id from public.journey_steps where code = any(:codes)"),
        {"codes": codes},
    ).all()
    return {str(r[0]): r[1] for r in rows}


def role_step_codes(session: Session, role_id: UUID) -> list[str]:
    rows = session.execute(
        text(
            """
            select s.code from public.role_journey_steps rjs
              join public.journey_steps s on s.id = rjs.journey_step_id
             where rjs.role_id = :rid
             order by rjs.sort_order, s.sort_order
            """
        ),
        {"rid": role_id},
    ).all()
    return [str(r[0]) for r in rows]


def replace_role_steps(session: Session, role_id: UUID, step_ids: list[UUID]) -> None:
    session.execute(
        text("delete from public.role_journey_steps where role_id = :rid"), {"rid": role_id}
    )
    for i, step_id in enumerate(step_ids):
        session.execute(
            text(
                """
                insert into public.role_journey_steps (role_id, journey_step_id, sort_order)
                values (:rid, :sid, :ord)
                """
            ),
            {"rid": role_id, "sid": step_id, "ord": (i + 1) * 10},
        )


def update_step_label(
    session: Session, code: str, *, label: str, hint: str | None, is_active: bool
) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                """
                update public.journey_steps
                   set label = :label, hint = :hint, is_active = :active
                 where code = :code
                returning id, code, label, hint, kind, screen_key, item_screen_key, queue_code,
                          feature_code, perm_module, perm_action, sort_order, is_active
                """
            ),
            {"code": code, "label": label, "hint": hint, "active": is_active},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def get_step(session: Session, code: str) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                """
                select id, code, label, hint, kind, screen_key, item_screen_key, queue_code,
                       feature_code, perm_module, perm_action, sort_order, is_active
                  from public.journey_steps where code = :code
                """
            ),
            {"code": code},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None
