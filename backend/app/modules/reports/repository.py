"""Reports SQL execution and preference storage (prompt P4-02). SQL only, no business rules."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.reports.sql import LOOKUPS

STREAM_BATCH = 1000


# --- configuration ------------------------------------------------------------------------------
def get_setting(session: Session, key: str) -> Any:
    return session.execute(
        text("select value from public.system_settings where key = :k"), {"k": key}
    ).scalar()


def today_in(session: Session, timezone: str) -> Any:
    return session.execute(
        text("select (now() at time zone :tz)::date"), {"tz": timezone}
    ).scalar_one()


def catalogue(session: Session) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            select code, group_code, group_title, title, description, column_labels,
                   sort_order, is_active
              from public.report_definitions
             order by sort_order, code
            """
        )
    ).mappings()
    return [dict(r) for r in rows]


def definition(session: Session, code: str) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                """
                select code, group_code, group_title, title, description, column_labels,
                       sort_order, is_active
                  from public.report_definitions where code = :c
                """
            ),
            {"c": code},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def lookup(session: Session, name: str) -> list[dict[str, Any]]:
    return [dict(r) for r in session.execute(text(LOOKUPS[name])).mappings()]


def option_labels(session: Session, set_code: str) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            select i.code as value, i.label
              from public.option_items i
              join public.option_sets s on s.id = i.option_set_id
             where s.code = :s
             order by i.sort_order, i.code
            """
        ),
        {"s": set_code},
    ).mappings()
    return [dict(r) for r in rows]


def branding(session: Session) -> dict[str, Any]:
    rows = session.execute(
        text(
            "select key, value from public.system_settings "
            "where key in ('app_name', 'branding_logo_url', 'branding_primary_color')"
        )
    ).mappings()
    return {r["key"]: r["value"] for r in rows}


# --- report execution ---------------------------------------------------------------------------
def fetch_all(session: Session, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(r) for r in session.execute(text(sql), params).mappings()]


def fetch_one(session: Session, sql: str, params: dict[str, Any]) -> dict[str, Any]:
    return dict(session.execute(text(sql), params).mappings().one())


def stream(session: Session, sql: str, params: dict[str, Any]) -> Iterator[tuple[Any, ...]]:
    """Server-side cursor: rows arrive in batches, never all at once (memory-flat exports)."""
    result = session.execute(
        text(sql).execution_options(stream_results=True, yield_per=STREAM_BATCH), params
    )
    for partition in result.partitions(STREAM_BATCH):
        for row in partition:
            yield tuple(row)


# --- users & roles ------------------------------------------------------------------------------
def user_roles_in_order(session: Session, user_id: UUID) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            select r.id, r.code, r.name
              from public.user_roles ur join public.roles r on r.id = ur.role_id
             where ur.user_id = :uid
             order by ur.created_at, r.code
            """
        ),
        {"uid": user_id},
    ).mappings()
    return [dict(r) for r in rows]


def role_by_code(session: Session, code: str) -> dict[str, Any] | None:
    row = (
        session.execute(
            text("select id, code, name from public.roles where code = :c"), {"c": code}
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def list_roles(session: Session) -> list[dict[str, Any]]:
    return [
        dict(r)
        for r in session.execute(
            text("select id, code, name from public.roles order by name")
        ).mappings()
    ]


# --- column preferences -------------------------------------------------------------------------
def user_columns(session: Session, user_id: UUID, report_code: str) -> list[str] | None:
    value = session.execute(
        text(
            "select columns from public.report_column_prefs where user_id = :u and report_code = :c"
        ),
        {"u": user_id, "c": report_code},
    ).scalar()
    return list(value) if value is not None else None


def role_columns_for_user(
    session: Session, user_id: UUID, report_code: str
) -> tuple[str, list[str]] | None:
    """The admin default of the user's earliest-assigned role that has one."""
    row = (
        session.execute(
            text(
                """
                select r.code, p.columns
                  from public.user_roles ur
                  join public.roles r on r.id = ur.role_id
                  join public.report_column_prefs p
                       on p.role_id = ur.role_id and p.report_code = :c
                 where ur.user_id = :u
                 order by ur.created_at, r.code
                 limit 1
                """
            ),
            {"u": user_id, "c": report_code},
        )
        .mappings()
        .first()
    )
    return (row["code"], list(row["columns"])) if row else None


def upsert_user_columns(session: Session, user_id: UUID, report_code: str, cols_json: str) -> None:
    session.execute(
        text(
            """
            insert into public.report_column_prefs (user_id, report_code, columns)
            values (:u, :c, cast(:cols as jsonb))
            on conflict (user_id, report_code) where user_id is not null
            do update set columns = excluded.columns
            """
        ),
        {"u": user_id, "c": report_code, "cols": cols_json},
    )


def delete_user_columns(session: Session, user_id: UUID, report_code: str) -> int:
    res = session.execute(
        text("delete from public.report_column_prefs where user_id = :u and report_code = :c"),
        {"u": user_id, "c": report_code},
    )
    return int(getattr(res, "rowcount", 0))


def role_columns(session: Session, role_id: UUID, report_code: str) -> list[str] | None:
    value = session.execute(
        text(
            "select columns from public.report_column_prefs "
            "where role_id = :r and report_code = :c for update"
        ),
        {"r": role_id, "c": report_code},
    ).scalar()
    return list(value) if value is not None else None


def all_role_columns(session: Session) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            select p.report_code, r.code as role_code, r.name as role_name, p.columns,
                   p.updated_at
              from public.report_column_prefs p join public.roles r on r.id = p.role_id
             order by p.report_code, r.name
            """
        )
    ).mappings()
    return [dict(r) for r in rows]


def upsert_role_columns(session: Session, role_id: UUID, report_code: str, cols_json: str) -> None:
    session.execute(
        text(
            """
            insert into public.report_column_prefs (role_id, report_code, columns)
            values (:r, :c, cast(:cols as jsonb))
            on conflict (role_id, report_code) where role_id is not null
            do update set columns = excluded.columns
            """
        ),
        {"r": role_id, "c": report_code, "cols": cols_json},
    )


def delete_role_columns(session: Session, role_id: UUID, report_code: str) -> int:
    res = session.execute(
        text("delete from public.report_column_prefs where role_id = :r and report_code = :c"),
        {"r": role_id, "c": report_code},
    )
    return int(getattr(res, "rowcount", 0))


def insert_config_change(
    session: Session,
    *,
    entity_type: str,
    entity_id: str,
    action: str,
    before_json: str | None,
    after_json: str | None,
    reason: str | None,
) -> None:
    session.execute(
        text(
            """
            insert into public.config_change_log
                   (entity_type, entity_id, action, before, after, reason)
            values (:et, :eid, :action, cast(:before as jsonb), cast(:after as jsonb), :reason)
            """
        ),
        {
            "et": entity_type,
            "eid": entity_id,
            "action": action,
            "before": before_json,
            "after": after_json,
            "reason": reason,
        },
    )


# --- saved filters ------------------------------------------------------------------------------
_SAVED_COLS = "id, report_code, name, params, is_default, created_at, updated_at"


def saved_filters(session: Session, user_id: UUID, report_code: str) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            f"select {_SAVED_COLS} from public.report_saved_filters "  # noqa: S608 - fixed columns
            "where user_id = :u and report_code = :c order by is_default desc, lower(name)"
        ),
        {"u": user_id, "c": report_code},
    ).mappings()
    return [dict(r) for r in rows]


def saved_filter_name_taken(session: Session, user_id: UUID, report_code: str, name: str) -> bool:
    return bool(
        session.execute(
            text(
                "select exists (select 1 from public.report_saved_filters "
                "where user_id = :u and report_code = :c and lower(name) = lower(:n))"
            ),
            {"u": user_id, "c": report_code, "n": name},
        ).scalar()
    )


def clear_default_filter(session: Session, user_id: UUID, report_code: str) -> None:
    session.execute(
        text(
            "update public.report_saved_filters set is_default = false "
            "where user_id = :u and report_code = :c and is_default"
        ),
        {"u": user_id, "c": report_code},
    )


def insert_saved_filter(
    session: Session,
    *,
    user_id: UUID,
    report_code: str,
    name: str,
    params_json: str,
    is_default: bool,
) -> dict[str, Any]:
    row = (
        session.execute(
            text(
                f"""
                insert into public.report_saved_filters
                       (user_id, report_code, name, params, is_default)
                values (:u, :c, :n, cast(:p as jsonb), :d)
                returning {_SAVED_COLS}
                """  # noqa: S608 - fixed columns
            ),
            {"u": user_id, "c": report_code, "n": name, "p": params_json, "d": is_default},
        )
        .mappings()
        .one()
    )
    return dict(row)


def delete_saved_filter(session: Session, user_id: UUID, report_code: str, filter_id: UUID) -> int:
    res = session.execute(
        text(
            "delete from public.report_saved_filters "
            "where id = :id and user_id = :u and report_code = :c"
        ),
        {"id": filter_id, "u": user_id, "c": report_code},
    )
    return int(getattr(res, "rowcount", 0))
