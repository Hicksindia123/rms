"""Intermediate Stores SQL (Phase P1, DEC-61). SQL only, no business rules (rule g)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

_STORE_SELECT = """
select s.id, s.code, s.name, s.is_default, s.is_active, s.sort_order, s.created_at, s.updated_at,
       r.id as role_id, r.code as role_code, r.name as role_name,
       l.id as location_id, l.code as location_code, l.name as location_name,
       (select count(*) from public.intermediate_store_category_map m
         where m.store_id = s.id and m.category_id is not null) as category_count,
       (select count(*) from public.intermediate_store_category_map m
         where m.store_id = s.id and m.subcategory_id is not null) as subcategory_count
  from public.intermediate_stores s
  join public.roles r on r.id = s.role_id
  join public.inventory_locations l on l.id = s.location_id
"""


def _uuids(values: Sequence[UUID]) -> list[str]:
    return [str(v) for v in values]


def list_stores(db: Session) -> list[dict[str, Any]]:
    rows = db.execute(text(f"{_STORE_SELECT} order by s.sort_order, s.code")).mappings().all()
    return [dict(r) for r in rows]


def get_store(db: Session, store_id: UUID, *, for_update: bool = False) -> dict[str, Any] | None:
    sql = f"{_STORE_SELECT} where s.id = :id"
    if for_update:
        sql += " for update of s"
    row = db.execute(text(sql), {"id": store_id}).mappings().first()
    return dict(row) if row else None


def store_users(db: Session) -> list[dict[str, Any]]:
    """Users holding a store role (one row per store x user)."""
    rows = (
        db.execute(
            text(
                """
                select s.id as store_id, p.id, p.full_name, p.email::text as email, p.is_active
                  from public.intermediate_stores s
                  join public.user_roles ur on ur.role_id = s.role_id
                  join public.profiles p on p.id = ur.user_id
                 order by p.full_name
                """
            )
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


def store_code_taken(db: Session, code: str) -> bool:
    return bool(
        db.execute(
            text("select exists (select 1 from public.intermediate_stores where code = :c)"),
            {"c": code},
        ).scalar_one()
    )


def role_code_taken(db: Session, code: str) -> bool:
    return bool(
        db.execute(
            text("select exists (select 1 from public.roles where code = :c)"), {"c": code}
        ).scalar_one()
    )


def location_code_taken(db: Session, code: str) -> bool:
    return bool(
        db.execute(
            text("select exists (select 1 from public.inventory_locations where code = :c)"),
            {"c": code},
        ).scalar_one()
    )


def store_name_taken(db: Session, name: str, *, exclude_id: UUID | None = None) -> bool:
    return bool(
        db.execute(
            text(
                "select exists (select 1 from public.intermediate_stores"
                " where lower(btrim(name)) = lower(btrim(:n))"
                " and (cast(:x as uuid) is null or id <> cast(:x as uuid)))"
            ),
            {"n": name, "x": exclude_id},
        ).scalar_one()
    )


def default_store(db: Session) -> dict[str, Any] | None:
    row = (
        db.execute(text(f"{_STORE_SELECT} where s.is_default order by s.code limit 1"))
        .mappings()
        .first()
    )
    return dict(row) if row else None


def lock_stores(db: Session) -> None:
    """Serialise store writes that touch the default flag (exactly one default, DEC-61)."""
    db.execute(text("select id from public.intermediate_stores order by id for update"))


def insert_role(db: Session, code: str, name: str, description: str) -> UUID:
    return UUID(
        str(
            db.execute(
                text(
                    "insert into public.roles (code, name, description, is_system)"
                    " values (:c, :n, :d, false) returning id"
                ),
                {"c": code, "n": name, "d": description},
            ).scalar_one()
        )
    )


def copy_role_setup(db: Session, from_role_id: UUID, to_role_id: UUID) -> None:
    """Copy permission grants and journey menu entries from one role to another."""
    db.execute(
        text(
            """
            insert into public.role_permissions (role_id, permission_id, scope)
            select :to, permission_id, scope from public.role_permissions where role_id = :from
            on conflict (role_id, permission_id) do nothing
            """
        ),
        {"from": from_role_id, "to": to_role_id},
    )
    db.execute(
        text(
            """
            insert into public.role_journey_steps (role_id, journey_step_id, sort_order)
            select :to, journey_step_id, sort_order
              from public.role_journey_steps where role_id = :from
            on conflict (role_id, journey_step_id) do nothing
            """
        ),
        {"from": from_role_id, "to": to_role_id},
    )


def insert_location(db: Session, code: str, name: str, role_id: UUID, department_code: str) -> UUID:
    return UUID(
        str(
            db.execute(
                text(
                    """
                    insert into public.inventory_locations
                      (code, name, location_class, custodian_role_id, department_id)
                    values (:c, :n, 'FUNCTIONAL', :r,
                            (select id from public.departments where code = :d))
                    returning id
                    """
                ),
                {"c": code, "n": name, "r": role_id, "d": department_code},
            ).scalar_one()
        )
    )


def insert_store(
    db: Session, *, code: str, name: str, role_id: UUID, location_id: UUID, sort_order: int
) -> UUID:
    return UUID(
        str(
            db.execute(
                text(
                    """
                    insert into public.intermediate_stores
                      (code, name, role_id, location_id, sort_order, is_default)
                    values (:c, :n, :r, :l, :o, false)
                    returning id
                    """
                ),
                {"c": code, "n": name, "r": role_id, "l": location_id, "o": sort_order},
            ).scalar_one()
        )
    )


def update_store(db: Session, store_id: UUID, fields: dict[str, Any]) -> None:
    allowed = {"name", "sort_order", "is_active", "is_default"}
    if set(fields) - allowed:
        raise ValueError(f"not updatable: {sorted(set(fields) - allowed)}")
    if not fields:
        return
    assignments = ", ".join(f"{col} = :{col}" for col in sorted(fields))
    db.execute(
        text(f"update public.intermediate_stores set {assignments} where id = :id"),  # noqa: S608
        {**fields, "id": store_id},
    )


def clear_default(db: Session) -> None:
    db.execute(text("update public.intermediate_stores set is_default = false where is_default"))


def rename_role(db: Session, role_id: UUID, name: str) -> None:
    db.execute(text("update public.roles set name = :n where id = :id"), {"n": name, "id": role_id})


def rename_location(db: Session, location_id: UUID, name: str) -> None:
    db.execute(
        text("update public.inventory_locations set name = :n where id = :id"),
        {"n": name, "id": location_id},
    )


# --- mapping ----------------------------------------------------------------------------------


def mapping_tree(db: Session) -> list[dict[str, Any]]:
    """Every category and sub-category with the store it is mapped to (if any)."""
    rows = (
        db.execute(
            text(
                """
                select 'C' as kind, c.id, c.code, c.name, c.is_active, null::uuid as category_id,
                       s.id as store_id, s.code as store_code, s.name as store_name,
                       s.is_active as store_is_active
                  from public.product_categories c
                  left join public.intermediate_store_category_map m on m.category_id = c.id
                  left join public.intermediate_stores s on s.id = m.store_id
                union all
                select 'S', sc.id, sc.code, sc.name, sc.is_active, sc.category_id,
                       s.id, s.code, s.name, s.is_active
                  from public.product_subcategories sc
                  left join public.intermediate_store_category_map m on m.subcategory_id = sc.id
                  left join public.intermediate_stores s on s.id = m.store_id
                order by 1, 4, 3
                """
            )
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


def existing_category_ids(db: Session, ids: Sequence[UUID]) -> set[UUID]:
    rows = db.execute(
        text("select id from public.product_categories where id = any(cast(:ids as uuid[]))"),
        {"ids": _uuids(ids)},
    ).all()
    return {r.id for r in rows}


def existing_subcategory_ids(db: Session, ids: Sequence[UUID]) -> set[UUID]:
    rows = db.execute(
        text("select id from public.product_subcategories where id = any(cast(:ids as uuid[]))"),
        {"ids": _uuids(ids)},
    ).all()
    return {r.id for r in rows}


def store_mapping(db: Session, store_id: UUID) -> tuple[list[UUID], list[UUID]]:
    rows = db.execute(
        text(
            "select category_id, subcategory_id from public.intermediate_store_category_map"
            " where store_id = :s"
        ),
        {"s": store_id},
    ).all()
    cats = sorted((r.category_id for r in rows if r.category_id), key=str)
    subs = sorted((r.subcategory_id for r in rows if r.subcategory_id), key=str)
    return cats, subs


def mapped_elsewhere(
    db: Session, store_id: UUID, category_ids: Sequence[UUID], subcategory_ids: Sequence[UUID]
) -> list[dict[str, Any]]:
    rows = (
        db.execute(
            text(
                """
                select case when m.category_id is not null then 'CATEGORY' else 'SUBCATEGORY' end
                         as kind,
                       coalesce(c.id, sc.id) as id, coalesce(c.code, sc.code) as code,
                       coalesce(c.name, sc.name) as name,
                       s.id as store_id, s.code as store_code, s.name as store_name
                  from public.intermediate_store_category_map m
                  join public.intermediate_stores s on s.id = m.store_id
                  left join public.product_categories c on c.id = m.category_id
                  left join public.product_subcategories sc on sc.id = m.subcategory_id
                 where m.store_id <> :s
                   and (m.category_id = any(cast(:cats as uuid[]))
                        or m.subcategory_id = any(cast(:subs as uuid[])))
                 order by 1, 3
                """
            ),
            {"s": store_id, "cats": _uuids(category_ids), "subs": _uuids(subcategory_ids)},
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


def replace_store_mapping(
    db: Session, store_id: UUID, category_ids: Sequence[UUID], subcategory_ids: Sequence[UUID]
) -> None:
    """Make the store own exactly these (sub-)categories; rows of other stores for them move."""
    cats, subs = _uuids(category_ids), _uuids(subcategory_ids)
    db.execute(
        text(
            """
            delete from public.intermediate_store_category_map
             where (store_id = :s
                    and not (coalesce(category_id = any(cast(:cats as uuid[])), false)
                             or coalesce(subcategory_id = any(cast(:subs as uuid[])), false)))
                or (store_id <> :s
                    and (category_id = any(cast(:cats as uuid[]))
                         or subcategory_id = any(cast(:subs as uuid[]))))
            """
        ),
        {"s": store_id, "cats": cats, "subs": subs},
    )
    db.execute(
        text(
            """
            insert into public.intermediate_store_category_map (store_id, category_id)
            select :s, x from unnest(cast(:cats as uuid[])) as x
            on conflict do nothing
            """
        ),
        {"s": store_id, "cats": cats},
    )
    db.execute(
        text(
            """
            insert into public.intermediate_store_category_map (store_id, subcategory_id)
            select :s, x from unnest(cast(:subs as uuid[])) as x
            on conflict do nothing
            """
        ),
        {"s": store_id, "subs": subs},
    )


# --- resolution -------------------------------------------------------------------------------


def user_stores(db: Session, user_id: UUID) -> list[dict[str, Any]]:
    rows = (
        db.execute(
            text(
                """
                select s.id, s.code, s.name, s.is_default, l.code as location_code
                  from rms_private.user_store_ids(:u) as u(id)
                  join public.intermediate_stores s on s.id = u.id
                  join public.inventory_locations l on l.id = s.location_id
                 order by s.sort_order, s.code
                """
            ),
            {"u": user_id},
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


def resolve_products(db: Session, product_ids: Sequence[UUID]) -> list[dict[str, Any]]:
    rows = (
        db.execute(
            text(
                """
                select p.id as product_id, p.code as product_code,
                       rms_private.store_for_product(p.id) as store_id
                  from public.products p
                 where p.id = any(cast(:ids as uuid[]))
                 order by p.code
                """
            ),
            {"ids": _uuids(product_ids)},
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


def assert_store_for_products(db: Session, product_ids: Sequence[UUID]) -> None:
    """DB guard (DEC-61): raises STORE_MAPPING_MISSING inside the caller's transaction."""
    db.execute(
        text("select rms_private.assert_store_for_products(cast(:ids as uuid[]))"),
        {"ids": _uuids(product_ids)},
    )
