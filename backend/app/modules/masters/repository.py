"""Masters repository: SQL only, no business rules (CLAUDE.md rule g).

Functions take either an ORM Session (API, inside the service's Unit of Work) or a Core Connection
(`backend/scripts/import_products.py`); both expose the same `execute(text(...))` API.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from app.modules.masters.product_import import (
    CategoryRef,
    ImportPlan,
    MastersSnapshot,
    ProductRef,
    SubCategoryRef,
)

Db = Session | Connection

PRODUCT_CODE_PREFIX = "ITM-"  # system identifiers for imported products (docs/DECISIONS.md)
_IMPORT_LOCK = "rms.masters.product_import"


# --- categories ---------------------------------------------------------------------------------
def list_categories(db: Db) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            select c.id, c.code, c.name, c.is_active,
                   c.requires_full_opening, c.supports_battery, c.supports_dismantling,
                   c.hazard_capable,
                   (select count(*) from public.product_subcategories s
                     where s.category_id = c.id)                        as subcategory_count,
                   (select count(*) from public.products p
                     where p.category_id = c.id)                        as product_count
              from public.product_categories c
             order by c.name
            """
        )
    ).mappings()
    return [dict(r) for r in rows]


def get_category(db: Db, category_id: UUID) -> dict[str, Any] | None:
    row = (
        db.execute(
            text("select id, code, name, is_active from public.product_categories where id = :id"),
            {"id": category_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


# --- sub-categories -----------------------------------------------------------------------------
_SUB_SELECT = """
    select s.id, s.category_id, c.code as category_code, c.name as category_name,
           s.code, s.name, s.is_active, s.created_at, s.updated_at,
           (select count(*) from public.products p where p.subcategory_id = s.id) as product_count
      from public.product_subcategories s
      join public.product_categories c on c.id = s.category_id
"""


def list_subcategories(
    db: Db, category_id: UUID | None, include_inactive: bool
) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            _SUB_SELECT
            + """
             where (cast(:cid as uuid) is null or s.category_id = cast(:cid as uuid))
               and (:all or s.is_active)
             order by c.name, s.name
            """
        ),
        {"cid": category_id, "all": include_inactive},
    ).mappings()
    return [dict(r) for r in rows]


def get_subcategory(db: Db, subcategory_id: UUID) -> dict[str, Any] | None:
    row = (
        db.execute(text(_SUB_SELECT + " where s.id = :id"), {"id": subcategory_id})
        .mappings()
        .first()
    )
    return dict(row) if row else None


def subcategory_clash(db: Db, category_id: UUID, code: str, name: str) -> str | None:
    """'code' / 'name' when a sub-category of this category already uses it, else None."""
    row = db.execute(
        text(
            """
            select bool_or(code = :code) as code_used,
                   bool_or(lower(btrim(name)) = lower(btrim(:name))) as name_used
              from public.product_subcategories where category_id = :cid
            """
        ),
        {"cid": category_id, "code": code, "name": name},
    ).one()
    if row.code_used:
        return "code"
    if row.name_used:
        return "name"
    return None


def subcategory_name_used(db: Db, subcategory_id: UUID, name: str) -> bool:
    return bool(
        db.execute(
            text(
                """
                select exists (
                  select 1 from public.product_subcategories o
                    join public.product_subcategories s on s.id = :id
                   where o.category_id = s.category_id and o.id <> s.id
                     and lower(btrim(o.name)) = lower(btrim(:name)))
                """
            ),
            {"id": subcategory_id, "name": name},
        ).scalar_one()
    )


def insert_subcategory(db: Db, category_id: UUID, code: str, name: str) -> UUID:
    return UUID(
        str(
            db.execute(
                text(
                    "insert into public.product_subcategories (category_id, code, name)"
                    " values (:cid, :code, :name) returning id"
                ),
                {"cid": category_id, "code": code, "name": name},
            ).scalar_one()
        )
    )


def update_subcategory(db: Db, subcategory_id: UUID, *, name: str, is_active: bool) -> None:
    db.execute(
        text(
            "update public.product_subcategories set name = :name, is_active = :active"
            " where id = :id"
        ),
        {"id": subcategory_id, "name": name, "active": is_active},
    )


# --- products -----------------------------------------------------------------------------------
_PRODUCT_SELECT = """
    select p.id, p.code, p.name, p.uom, p.hsn_code, p.is_active,
           p.category_id, c.code as category_code, c.name as category_name,
           p.subcategory_id, s.code as subcategory_code, s.name as subcategory_name,
           p.updated_at
      from public.products p
      join public.product_categories c on c.id = p.category_id
      left join public.product_subcategories s on s.id = p.subcategory_id
"""


def list_products(
    db: Db,
    *,
    q: str | None,
    category_id: UUID | None,
    subcategory_id: UUID | None,
    without_subcategory: bool,
    include_inactive: bool,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    where = """
         where (:q = '' or p.name ilike :like or p.code ilike :like)
           and (cast(:cid as uuid) is null or p.category_id = cast(:cid as uuid))
           and (cast(:sid as uuid) is null or p.subcategory_id = cast(:sid as uuid))
           and (not :nosub or p.subcategory_id is null)
           and (:all or p.is_active)
    """
    binds = {
        "q": q or "",
        "like": f"%{q or ''}%",
        "cid": category_id,
        "sid": subcategory_id,
        "nosub": without_subcategory,
        "all": include_inactive,
    }
    total = db.execute(
        text(
            "select count(*) from public.products p"  # noqa: S608 - static SQL, bound values
            + where
        ),
        binds,
    ).scalar_one()
    rows = db.execute(
        text(_PRODUCT_SELECT + where + " order by p.name, p.code limit :limit offset :offset"),
        {**binds, "limit": limit, "offset": offset},
    ).mappings()
    return [dict(r) for r in rows], int(total)


def get_product(db: Db, product_id: UUID) -> dict[str, Any] | None:
    row = (
        db.execute(text(_PRODUCT_SELECT + " where p.id = :id"), {"id": product_id})
        .mappings()
        .first()
    )
    return dict(row) if row else None


def product_name_used(db: Db, product_id: UUID, name: str) -> bool:
    return bool(
        db.execute(
            text(
                "select exists (select 1 from public.products where id <> :id"
                " and upper(regexp_replace(btrim(name), '\\s+', ' ', 'g'))"
                "   = upper(regexp_replace(btrim(:name), '\\s+', ' ', 'g')))"
            ),
            {"id": product_id, "name": name},
        ).scalar_one()
    )


def update_product(
    db: Db,
    product_id: UUID,
    *,
    name: str,
    category_id: UUID,
    subcategory_id: UUID | None,
    uom: str,
    hsn_code: str | None,
    is_active: bool,
) -> None:
    db.execute(
        text(
            """
            update public.products
               set name = :name, category_id = :cid, subcategory_id = :sid, uom = :uom,
                   hsn_code = :hsn, is_active = :active
             where id = :id
            """
        ),
        {
            "id": product_id,
            "name": name,
            "cid": category_id,
            "sid": subcategory_id,
            "uom": uom,
            "hsn": hsn_code,
            "active": is_active,
        },
    )


# --- CSV import ---------------------------------------------------------------------------------
def lock_product_import(db: Db) -> None:
    """Serialise imports (ITM- code allocation) for the rest of the transaction."""
    db.execute(text("select pg_advisory_xact_lock(hashtext(:k))"), {"k": _IMPORT_LOCK})


def load_snapshot(db: Db) -> MastersSnapshot:
    categories = [
        CategoryRef(code=r.code, name=r.name, is_active=r.is_active)
        for r in db.execute(text("select code, name, is_active from public.product_categories"))
    ]
    subcategories = [
        SubCategoryRef(
            category_code=r.category_code, code=r.code, name=r.name, is_active=r.is_active
        )
        for r in db.execute(
            text(
                "select c.code as category_code, s.code, s.name, s.is_active"
                "  from public.product_subcategories s"
                "  join public.product_categories c on c.id = s.category_id"
            )
        )
    ]
    products = [
        ProductRef(
            id=str(r.id),
            code=r.code,
            name=r.name,
            category_code=r.category_code,
            subcategory_code=r.subcategory_code,
        )
        for r in db.execute(
            text(
                "select p.id, p.code, p.name, c.code as category_code, s.code as subcategory_code"
                "  from public.products p"
                "  join public.product_categories c on c.id = p.category_id"
                "  left join public.product_subcategories s on s.id = p.subcategory_id"
            )
        )
    ]
    return MastersSnapshot(categories, subcategories, products)


def apply_import(db: Db, plan: ImportPlan) -> list[str]:
    """Write the plan. Returns the ITM- codes given to new products (in plan order)."""
    for c in plan.new_categories:
        db.execute(
            text("insert into public.product_categories (code, name) values (:code, :name)"),
            {"code": c.code, "name": c.name},
        )
    cat_ids = {
        r.code: r.id for r in db.execute(text("select id, code from public.product_categories"))
    }
    for s in plan.new_subcategories:
        db.execute(
            text(
                "insert into public.product_subcategories (category_id, code, name)"
                " values (:cid, :code, :name)"
            ),
            {"cid": cat_ids[s.category_code], "code": s.code, "name": s.name},
        )
    sub_ids = {
        (r.category_code, r.code): r.id
        for r in db.execute(
            text(
                "select s.id, s.code, c.code as category_code from public.product_subcategories s"
                " join public.product_categories c on c.id = s.category_id"
            )
        )
    }

    def sub_id(category_code: str, code: str | None) -> Any:
        return None if code is None else sub_ids[(category_code, code)]

    max_code = db.execute(
        text(
            "select coalesce(max(substr(code, :n)::int), 0) from public.products"
            " where code ~ ('^' || :p || '[0-9]+$')"
        ),
        {"n": len(PRODUCT_CODE_PREFIX) + 1, "p": PRODUCT_CODE_PREFIX},
    ).scalar_one()
    codes = [
        f"{PRODUCT_CODE_PREFIX}{max_code + i:05d}" for i in range(1, len(plan.new_products) + 1)
    ]
    if plan.new_products:
        db.execute(
            text(
                "insert into public.products"
                " (code, name, category_id, subcategory_id, uom, hsn_code)"
                " values (:code, :name, :cid, :sid, :uom, :hsn)"
            ),
            [
                {
                    "code": code,
                    "name": p.name,
                    "cid": cat_ids[p.category_code],
                    "sid": sub_id(p.category_code, p.subcategory_code),
                    "uom": p.uom,
                    "hsn": p.hsn,
                }
                for code, p in zip(codes, plan.new_products, strict=True)
            ],
        )
    if plan.updates:
        db.execute(
            text(
                "update public.products set category_id = :cid, subcategory_id = :sid"
                " where id = :id"
            ),
            [
                {
                    "id": u.product_id,
                    "cid": cat_ids[u.to_category],
                    "sid": sub_id(u.to_category, u.to_subcategory),
                }
                for u in plan.updates
            ],
        )
    return codes
