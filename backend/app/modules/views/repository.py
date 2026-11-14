"""Repository for Saved Views (P4-04)."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import CursorResult, text
from sqlalchemy.orm import Session

_COLS = (
    "id, user_id, view_code, name, filters, columns, sort_by, sort_dir, "
    "is_default, created_at, updated_at"
)


def list_saved_views(
    session: Session, user_id: UUID, view_code: str | None = None
) -> list[dict[str, Any]]:
    sql = f"select {_COLS} from public.saved_views where user_id = :uid"  # noqa: S608
    params: dict[str, Any] = {"uid": user_id}
    if view_code:
        sql += " and view_code = :vcode"
        params["vcode"] = view_code
    sql += " order by is_default desc, name asc"
    rows = session.execute(text(sql), params).mappings().all()
    return [dict(r) for r in rows]


def get_saved_view(session: Session, view_id: UUID, user_id: UUID) -> dict[str, Any] | None:
    sql = f"select {_COLS} from public.saved_views where id = :vid and user_id = :uid"  # noqa: S608
    row = session.execute(text(sql), {"vid": view_id, "uid": user_id}).mappings().one_or_none()
    return dict(row) if row else None


def name_exists(
    session: Session, user_id: UUID, view_code: str, name: str, exclude_id: UUID | None = None
) -> bool:
    sql = (
        "select exists (select 1 from public.saved_views where user_id = :uid "
        "and view_code = :vcode and lower(name) = lower(:name)"
    )
    params: dict[str, Any] = {"uid": user_id, "vcode": view_code, "name": name.strip()}
    if exclude_id:
        sql += " and id <> :eid"
        params["eid"] = exclude_id
    sql += ")"
    return bool(session.execute(text(sql), params).scalar())


def insert_saved_view(
    session: Session,
    *,
    user_id: UUID,
    view_code: str,
    name: str,
    filters: list[dict[str, Any]],
    columns: list[str],
    sort_by: str | None,
    sort_dir: str | None,
    is_default: bool,
) -> dict[str, Any]:
    sql = """
        insert into public.saved_views (
            user_id, view_code, name, filters, columns, sort_by, sort_dir, is_default
        ) values (
            :uid, :vcode, :name, cast(:filters as jsonb), :columns, :sort_by, :sort_dir, :is_default
        )
        returning id, user_id, view_code, name, filters, columns, sort_by,
                  sort_dir, is_default, created_at, updated_at
    """
    row = (
        session.execute(
            text(sql),
            {
                "uid": user_id,
                "vcode": view_code.strip(),
                "name": name.strip(),
                "filters": json.dumps(filters),
                "columns": columns,
                "sort_by": sort_by.strip() if sort_by else None,
                "sort_dir": sort_dir,
                "is_default": is_default,
            },
        )
        .mappings()
        .one()
    )
    return dict(row)


def update_saved_view(
    session: Session,
    view_id: UUID,
    user_id: UUID,
    *,
    name: str | None,
    filters: list[dict[str, Any]] | None,
    columns: list[str] | None,
    sort_by: str | None,
    sort_dir: str | None,
    is_default: bool | None,
) -> dict[str, Any] | None:
    updates: list[str] = []
    params: dict[str, Any] = {"vid": view_id, "uid": user_id}

    if name is not None:
        updates.append("name = :name")
        params["name"] = name.strip()
    if filters is not None:
        updates.append("filters = cast(:filters as jsonb)")
        params["filters"] = json.dumps(filters)
    if columns is not None:
        updates.append("columns = :columns")
        params["columns"] = columns
    if sort_by is not None:
        updates.append("sort_by = :sort_by")
        params["sort_by"] = sort_by.strip() if sort_by else None
    if sort_dir is not None:
        updates.append("sort_dir = :sort_dir")
        params["sort_dir"] = sort_dir
    if is_default is not None:
        updates.append("is_default = :is_default")
        params["is_default"] = is_default

    if not updates:
        return get_saved_view(session, view_id, user_id)

    sql = (
        f"update public.saved_views set {', '.join(updates)}, updated_at = now() "  # noqa: S608
        f"where id = :vid and user_id = :uid returning {_COLS}"
    )
    row = session.execute(text(sql), params).mappings().one_or_none()
    return dict(row) if row else None


def delete_saved_view(session: Session, view_id: UUID, user_id: UUID) -> bool:
    sql = "delete from public.saved_views where id = :vid and user_id = :uid"
    result = session.execute(text(sql), {"vid": view_id, "uid": user_id})
    return bool(isinstance(result, CursorResult) and result.rowcount > 0)
