"""Masters API: product sub-categories, product edit and CSV import.

Change plan 2026-11-12 Phase 1 · AMD-07 (Category -> Sub-Category -> Product; sub-category must
belong to the product's category, DB + service) · DEC-36 (product CSV with Sub-Category).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

from tests.conftest import JwtFactory
from tests.integration.conftest import UserFactory, as_admin


def _auth(token: str, key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if key:
        headers["Idempotency-Key"] = key
    return headers


def _category(conn: Connection, code: str, name: str | None = None) -> uuid.UUID:
    return uuid.UUID(
        str(
            as_admin(conn)
            .execute(
                text(
                    "insert into public.product_categories (code, name) values (:c, :n)"
                    " returning id"
                ),
                {"c": code, "n": name or code.title()},
            )
            .scalar_one()
        )
    )


def _product(conn: Connection, code: str, name: str, category_id: uuid.UUID) -> uuid.UUID:
    return uuid.UUID(
        str(
            as_admin(conn)
            .execute(
                text(
                    "insert into public.products (code, name, category_id) values (:c, :n, :cat)"
                    " returning id"
                ),
                {"c": code, "n": name, "cat": category_id},
            )
            .scalar_one()
        )
    )


async def _create_sub(
    client: AsyncClient, token: str, category_id: uuid.UUID, name: str, code: str | None = None
) -> dict[str, Any]:
    body: dict[str, Any] = {"category_id": str(category_id), "name": name}
    if code:
        body["code"] = code
    res = await client.post(
        "/api/v1/masters/product-subcategories",
        headers=_auth(token, f"test-{uuid.uuid4()}"),
        json=body,
    )
    assert res.status_code == 201, res.text
    return dict(res.json())


async def test_masters_require_masters_permission(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    gate = make_token(users.create(roles=["GATE_INWARD"]))
    res = await client.get("/api/v1/masters/product-categories", headers=_auth(gate))
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "PERMISSION_DENIED"

    admin = make_token(users.create(super_admin=True))
    res = await client.get("/api/v1/masters/product-categories", headers=_auth(admin))
    assert res.status_code == 200
    codes = {c["code"] for c in res.json()}
    assert {"DMT", "PRISMATIC", "ENCLOSED_OVAL"} <= codes


async def test_create_subcategory_idempotent_and_unique(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory, db_conn: Connection
) -> None:
    token = make_token(users.create(super_admin=True))
    cat = _category(db_conn, "PYT_SC_CAT")
    key = f"test-{uuid.uuid4()}"
    body = {"category_id": str(cat), "name": "Rectal (Blister Pack)"}

    first = await client.post(
        "/api/v1/masters/product-subcategories", headers=_auth(token, key), json=body
    )
    assert first.status_code == 201, first.text
    assert first.json()["code"] == "RECTAL_BLISTER_PACK"  # derived from the name

    # G-16 pattern: the same key returns the original result, nothing new is created.
    replay = await client.post(
        "/api/v1/masters/product-subcategories", headers=_auth(token, key), json=body
    )
    assert replay.status_code == 201
    assert replay.json()["id"] == first.json()["id"]

    dup = await client.post(
        "/api/v1/masters/product-subcategories",
        headers=_auth(token, f"test-{uuid.uuid4()}"),
        json={"category_id": str(cat), "name": "Other", "code": "RECTAL_BLISTER_PACK"},
    )
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "DUPLICATE_SUBCATEGORY"

    listed = await client.get(
        "/api/v1/masters/product-subcategories",
        headers=_auth(token),
        params={"category_id": str(cat)},
    )
    assert [s["code"] for s in listed.json()] == ["RECTAL_BLISTER_PACK"]


async def test_subcategory_update_keeps_code_immutable(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory, db_conn: Connection
) -> None:
    token = make_token(users.create(super_admin=True))
    cat = _category(db_conn, "PYT_SC_IMM")
    sub = await _create_sub(client, token, cat, "Prismatic")

    # The API has no code field (extra="forbid") ...
    res = await client.patch(
        f"/api/v1/masters/product-subcategories/{sub['id']}",
        headers=_auth(token),
        json={"code": "NEW_CODE"},
    )
    assert res.status_code == 422

    res = await client.patch(
        f"/api/v1/masters/product-subcategories/{sub['id']}",
        headers=_auth(token),
        json={"name": "Prismatic Clinical", "is_active": False},
    )
    assert res.status_code == 200, res.text
    assert res.json()["name"] == "Prismatic Clinical"
    assert res.json()["code"] == "PRISMATIC"
    assert res.json()["is_active"] is False

    # ... and the DB rejects a direct change too (AMD-07).
    with pytest.raises(IntegrityError, match="AMD-07"):
        as_admin(db_conn).execute(
            text("update public.product_subcategories set code = 'X_CHANGED' where id = :id"),
            {"id": sub["id"]},
        )


async def test_product_edit_enforces_subcategory_category_amd07(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory, db_conn: Connection
) -> None:
    token = make_token(users.create(super_admin=True))
    cat_a = _category(db_conn, "PYT_PE_A")
    cat_b = _category(db_conn, "PYT_PE_B")
    sub_a = await _create_sub(client, token, cat_a, "Sub A")
    sub_b = await _create_sub(client, token, cat_b, "Sub B")
    prod = _product(db_conn, "PYT-PE-1", "Pytest Product One", cat_a)

    ok = await client.patch(
        f"/api/v1/masters/products/{prod}",
        headers=_auth(token),
        json={"subcategory_id": sub_a["id"]},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["subcategory_code"] == "SUB_A"

    # AMD-07 (service): sub-category of another category is rejected with a clear 422.
    bad = await client.patch(
        f"/api/v1/masters/products/{prod}",
        headers=_auth(token),
        json={"subcategory_id": sub_b["id"]},
    )
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "SUBCATEGORY_CATEGORY_MISMATCH"

    # Changing the category without naming a sub-category clears the old one.
    moved = await client.patch(
        f"/api/v1/masters/products/{prod}",
        headers=_auth(token),
        json={"category_id": str(cat_b)},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["category_code"] == "PYT_PE_B"
    assert moved.json()["subcategory_id"] is None

    both = await client.patch(
        f"/api/v1/masters/products/{prod}",
        headers=_auth(token),
        json={"category_id": str(cat_b), "subcategory_id": sub_b["id"]},
    )
    assert both.status_code == 200
    assert both.json()["subcategory_code"] == "SUB_B"

    cleared = await client.patch(
        f"/api/v1/masters/products/{prod}", headers=_auth(token), json={"subcategory_id": None}
    )
    assert cleared.status_code == 200
    assert cleared.json()["subcategory_id"] is None

    # AMD-07 (DB): the composite FK rejects a mismatch even as rms_api, bypassing the service.
    # (Last statement of the test: the failed statement aborts the rolled-back outer transaction.)
    conn = as_admin(db_conn)
    conn.execute(text("set local role rms_api"))
    with pytest.raises(IntegrityError, match="products_subcategory_in_category_fkey"):
        conn.execute(
            text("update public.products set subcategory_id = :s where id = :id"),
            {"s": sub_a["id"], "id": prod},
        )


async def test_product_list_filters(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory, db_conn: Connection
) -> None:
    token = make_token(users.create(super_admin=True))
    cat = _category(db_conn, "PYT_PL")
    sub = await _create_sub(client, token, cat, "Listed")
    p1 = _product(db_conn, "PYT-PL-1", "Pytest Listed Alpha", cat)
    _product(db_conn, "PYT-PL-2", "Pytest Listed Beta", cat)
    await client.patch(
        f"/api/v1/masters/products/{p1}", headers=_auth(token), json={"subcategory_id": sub["id"]}
    )

    res = await client.get(
        "/api/v1/masters/products",
        headers=_auth(token),
        params={"category_id": str(cat), "page_size": 1},
    )
    body = res.json()
    assert res.status_code == 200
    assert body["total"] == 2 and len(body["items"]) == 1

    res = await client.get(
        "/api/v1/masters/products",
        headers=_auth(token),
        params={"subcategory_id": sub["id"]},
    )
    assert [p["code"] for p in res.json()["items"]] == ["PYT-PL-1"]

    res = await client.get(
        "/api/v1/masters/products",
        headers=_auth(token),
        params={"category_id": str(cat), "without_subcategory": True, "q": "beta"},
    )
    assert [p["code"] for p in res.json()["items"]] == ["PYT-PL-2"]


CSV = (
    "Item Name,Category,Sub-Category\n"
    "Pytest Existing Item,PYT_IMP,Blister Pack\n"
    "Pytest New Item,Pyt Imp,Blister Pack\n"
    "Pytest New Item,PYT_IMP,Blister Pack\n"
    "Pytest Other,Unknown Cat X,Whatever\n"
    ",PYT_IMP,\n"
    "Pytest Third,PYT_IMP,\n"
)


async def test_product_import_preview_then_apply(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory, db_conn: Connection
) -> None:
    token = make_token(users.create(super_admin=True))
    cat = _category(db_conn, "PYT_IMP", "Pyt Imp")
    _product(db_conn, "PYT-IMP-1", "PYTEST  existing item", cat)  # name match ignores case/spaces

    preview = await client.post(
        "/api/v1/masters/products/import/preview", headers=_auth(token), json={"csv_text": CSV}
    )
    assert preview.status_code == 200, preview.text
    p = preview.json()
    assert p["dry_run"] is True
    assert p["rows_read"] == 6
    assert [s["code"] for s in p["new_subcategories"]] == ["BLISTER_PACK"]
    assert [x["name"] for x in p["new_products"]] == ["Pytest New Item", "Pytest Third"]
    assert [u["product_code"] for u in p["updates"]] == ["PYT-IMP-1"]
    assert p["duplicates_in_file"] == 1
    reasons = sorted(e["reason"] for e in p["exceptions"])
    assert len(reasons) == 2
    assert any("Unknown Cat X" in r for r in reasons)
    assert any("Item Name is blank" in r for r in reasons)

    # The preview wrote nothing.
    n = (
        as_admin(db_conn)
        .execute(
            text("select count(*) from public.product_subcategories where category_id = :c"),
            {"c": cat},
        )
        .scalar_one()
    )
    assert n == 0

    key = f"test-{uuid.uuid4()}"
    applied = await client.post(
        "/api/v1/masters/products/import", headers=_auth(token, key), json={"csv_text": CSV}
    )
    assert applied.status_code == 200, applied.text
    a = applied.json()
    assert a["dry_run"] is False
    assert all(x["code"] and x["code"].startswith("ITM-") for x in a["new_products"])

    rows = (
        as_admin(db_conn)
        .execute(
            text(
                """
            select p.name, s.code from public.products p
              left join public.product_subcategories s on s.id = p.subcategory_id
             where p.category_id = :c order by p.name
            """
            ),
            {"c": cat},
        )
        .all()
    )
    assert [(r[0], r[1]) for r in rows] == [
        ("PYTEST  existing item", "BLISTER_PACK"),
        ("Pytest New Item", "BLISTER_PACK"),
        ("Pytest Third", None),
    ]

    # Same key: original result, nothing imported twice (G-16 pattern).
    replay = await client.post(
        "/api/v1/masters/products/import", headers=_auth(token, key), json={"csv_text": CSV}
    )
    assert replay.status_code == 200
    assert replay.headers.get("Idempotency-Replayed") == "true"
    assert replay.json() == a

    # A second import (new key) finds everything already in place.
    again = await client.post(
        "/api/v1/masters/products/import/preview", headers=_auth(token), json={"csv_text": CSV}
    )
    assert again.json()["new_products"] == [] and again.json()["updates"] == []
    assert again.json()["unchanged"] == 3


async def test_product_import_new_category_is_opt_in(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    token = make_token(users.create(super_admin=True))
    csv_text = "Category,Sub-Category,Product Name\nPytest Brand New Cat,Room,Pytest Wall Thermo\n"

    without = await client.post(
        "/api/v1/masters/products/import/preview",
        headers=_auth(token),
        json={"csv_text": csv_text},
    )
    assert without.json()["new_categories"] == []
    assert len(without.json()["exceptions"]) == 1

    with_flag = await client.post(
        "/api/v1/masters/products/import/preview",
        headers=_auth(token),
        json={"csv_text": csv_text, "create_categories": True},
    )
    body = with_flag.json()
    assert [c["code"] for c in body["new_categories"]] == ["PYTEST_BRAND_NEW_CAT"]
    assert [s["code"] for s in body["new_subcategories"]] == ["ROOM"]
    assert body["exceptions"] == []


async def test_product_import_rejects_csv_without_required_columns(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    token = make_token(users.create(super_admin=True))
    res = await client.post(
        "/api/v1/masters/products/import/preview",
        headers=_auth(token),
        json={"csv_text": "Name,Group\nA,B\n"},
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "CSV_INVALID"


async def test_product_import_requires_idempotency_key(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    token = make_token(users.create(super_admin=True))
    res = await client.post(
        "/api/v1/masters/products/import", headers=_auth(token), json={"csv_text": CSV}
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"
