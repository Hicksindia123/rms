"""SQL for item field profiles (AMD-10/11/16). No business rules here.

Profile resolution is never re-implemented in Python: `resolve_scope` / `resolve_product` call the
DB functions `rms_private.resolve_item_field_profile[_for_scope]` (migration 20261113000400).
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

_FIELD_COLUMNS = """
    l.id, l.field_group, l.code, l.label, l.description, l.sort_order, l.is_active, l.is_system,
    l.is_wastage, l.returns_to_routing, l.requires_cn, l.requires_challan, l.system_behavior,
    l.source_ref, l.updated_at,
    (select count(*) from public.item_field_assignments a where a.field_id = l.id)::int
      as assignment_count
"""

_RESOLVED_COLUMNS = """
    r.profile_version_id, r.profile_version_no, r.field_group, r.field_id, r.code, r.label,
    r.sort_order, r.source_scope_type, r.source_scope_id, r.is_wastage, r.returns_to_routing,
    r.requires_cn, r.requires_challan, r.system_behavior
"""


def list_fields(
    session: Session, field_group: str | None, include_inactive: bool
) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            f"""
            select {_FIELD_COLUMNS}
              from public.item_field_library l
             where (cast(:g as text) is null or l.field_group = :g)
               and (:inactive or l.is_active)
             order by l.field_group, l.sort_order, l.code
            """  # noqa: S608 - column list is a module constant
        ),
        {"g": field_group, "inactive": include_inactive},
    ).mappings()
    return [dict(r) for r in rows]


def get_field(session: Session, field_id: UUID) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(f"select {_FIELD_COLUMNS} from public.item_field_library l where l.id = :id"),  # noqa: S608
            {"id": field_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def get_fields(session: Session, field_ids: list[UUID]) -> dict[UUID, dict[str, Any]]:
    if not field_ids:
        return {}
    rows = session.execute(
        text(
            f"select {_FIELD_COLUMNS} from public.item_field_library l"  # noqa: S608
            " where l.id = any(cast(:ids as uuid[]))"
        ),
        {"ids": [str(i) for i in field_ids]},
    ).mappings()
    return {r["id"]: dict(r) for r in rows}


def field_code_exists(session: Session, field_group: str, code: str) -> bool:
    return (
        session.execute(
            text("select 1 from public.item_field_library where field_group = :g and code = :c"),
            {"g": field_group, "c": code},
        ).first()
        is not None
    )


def next_sort_order(session: Session, field_group: str) -> int:
    value = session.execute(
        text(
            "select coalesce(max(sort_order), 0) + 10 from public.item_field_library"
            " where field_group = :g"
        ),
        {"g": field_group},
    ).scalar_one()
    return int(value)


def insert_field(session: Session, data: dict[str, Any]) -> UUID:
    return UUID(
        str(
            session.execute(
                text(
                    """
                    insert into public.item_field_library
                      (field_group, code, label, description, sort_order, is_wastage,
                       returns_to_routing, requires_cn, requires_challan)
                    values (:field_group, :code, :label, :description, :sort_order, :is_wastage,
                            :returns_to_routing, :requires_cn, :requires_challan)
                    returning id
                    """
                ),
                data,
            ).scalar_one()
        )
    )


_UPDATABLE = (
    "label",
    "description",
    "sort_order",
    "is_active",
    "is_wastage",
    "returns_to_routing",
    "requires_cn",
    "requires_challan",
)


def update_field(session: Session, field_id: UUID, data: dict[str, Any]) -> None:
    cols = [c for c in _UPDATABLE if c in data]
    if not cols:
        return
    assignments = ", ".join(f"{c} = :{c}" for c in cols)
    session.execute(
        text(f"update public.item_field_library set {assignments} where id = :id"),  # noqa: S608
        {**{c: data[c] for c in cols}, "id": field_id},
    )


# --- scope lookups ---------------------------------------------------------------------------
def get_category(session: Session, category_id: UUID) -> dict[str, Any] | None:
    row = (
        session.execute(
            text("select id, code, name from public.product_categories where id = :id"),
            {"id": category_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def get_subcategory(session: Session, subcategory_id: UUID) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                "select id, code, name, category_id from public.product_subcategories"
                " where id = :id"
            ),
            {"id": subcategory_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def get_product(session: Session, product_id: UUID) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                "select id, code, name, category_id, subcategory_id from public.products"
                " where id = :id"
            ),
            {"id": product_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


# --- resolution (DB function only) -----------------------------------------------------------
def resolve_scope(
    session: Session,
    category_id: UUID,
    subcategory_id: UUID | None,
    product_id: UUID | None,
    version_id: UUID | None = None,
) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            f"""
            select {_RESOLVED_COLUMNS}
              from rms_private.resolve_item_field_profile_for_scope(
                     cast(:c as uuid), cast(:s as uuid), cast(:p as uuid), cast(:v as uuid)) r
            """  # noqa: S608
        ),
        {"c": category_id, "s": subcategory_id, "p": product_id, "v": version_id},
    ).mappings()
    return [dict(r) for r in rows]


def resolve_product(
    session: Session, product_id: UUID, version_id: UUID | None = None
) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            f"""
            select {_RESOLVED_COLUMNS}
              from rms_private.resolve_item_field_profile(cast(:p as uuid), cast(:v as uuid)) r
            """  # noqa: S608
        ),
        {"p": product_id, "v": version_id},
    ).mappings()
    return [dict(r) for r in rows]


# --- assignments -----------------------------------------------------------------------------
def list_scope_assignments(
    session: Session, scope_type: str, scope_id: UUID, field_group: str | None = None
) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            select a.id, a.field_id, a.field_group, a.is_included, a.sort_order,
                   l.code, l.label, l.is_active as field_is_active
              from public.item_field_assignments a
              join public.item_field_library l on l.id = a.field_id
             where a.scope_type = :t and a.scope_id = :s
               and (cast(:g as text) is null or a.field_group = :g)
             order by a.field_group, a.sort_order, l.sort_order, l.code
            """
        ),
        {"t": scope_type, "s": scope_id, "g": field_group},
    ).mappings()
    return [dict(r) for r in rows]


_SCOPE_COLUMN = {
    "CATEGORY": "category_id",
    "SUBCATEGORY": "subcategory_id",
    "PRODUCT": "product_id",
}


def insert_assignment(
    session: Session,
    *,
    field_id: UUID,
    field_group: str,
    scope_type: str,
    scope_id: UUID,
    is_included: bool,
    sort_order: int,
) -> None:
    column = _SCOPE_COLUMN[scope_type]
    session.execute(
        text(
            f"""
            insert into public.item_field_assignments
              (field_id, field_group, scope_type, {column}, is_included, sort_order)
            values (:f, :g, :t, :s, :inc, :sort)
            """  # noqa: S608 - column picked from a fixed map
        ),
        {
            "f": field_id,
            "g": field_group,
            "t": scope_type,
            "s": scope_id,
            "inc": is_included,
            "sort": sort_order,
        },
    )


def update_assignment(session: Session, assignment_id: UUID, is_included: bool, sort: int) -> None:
    session.execute(
        text(
            "update public.item_field_assignments set is_included = :inc, sort_order = :sort"
            " where id = :id"
        ),
        {"id": assignment_id, "inc": is_included, "sort": sort},
    )


def delete_assignments(session: Session, assignment_ids: list[UUID]) -> None:
    if not assignment_ids:
        return
    session.execute(
        text("delete from public.item_field_assignments where id = any(cast(:ids as uuid[]))"),
        {"ids": [str(i) for i in assignment_ids]},
    )


# --- versions --------------------------------------------------------------------------------
def latest_version(session: Session) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                "select id, version_no from public.item_field_profile_versions"
                " order by version_no desc limit 1"
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def version_exists(session: Session, version_id: UUID) -> bool:
    return (
        session.execute(
            text("select 1 from public.item_field_profile_versions where id = :id"),
            {"id": version_id},
        ).first()
        is not None
    )


def version_no(session: Session, version_id: UUID) -> int | None:
    value = session.execute(
        text("select version_no from public.item_field_profile_versions where id = :id"),
        {"id": version_id},
    ).scalar_one_or_none()
    return int(value) if value is not None else None


def list_versions(session: Session, limit: int) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            select v.id, v.version_no, v.created_at, p.full_name as created_by_name,
                   jsonb_array_length(v.snapshot -> 'library') as library_count,
                   jsonb_array_length(v.snapshot -> 'assignments') as assignment_count
              from public.item_field_profile_versions v
              left join public.profiles p on p.id = v.created_by
             order by v.version_no desc
             limit :limit
            """
        ),
        {"limit": limit},
    ).mappings()
    return [dict(r) for r in rows]


def log_config_change(
    session: Session,
    *,
    entity_type: str,
    entity_id: str,
    action: str,
    before: Any,
    after: Any,
    reason: str | None,
) -> None:
    """Insert-only config change log (G-17); actor and request id come from the DB context."""
    session.execute(
        text(
            """
            insert into public.config_change_log
              (entity_type, entity_id, action, before, after, reason)
            values (:t, :id, :a, cast(:b as jsonb), cast(:af as jsonb), :r)
            """
        ),
        {
            "t": entity_type,
            "id": entity_id,
            "a": action,
            "b": json.dumps(before, default=str) if before is not None else None,
            "af": json.dumps(after, default=str) if after is not None else None,
            "r": reason,
        },
    )
