"""Item field profiles API (change plan 2026-11-12 Phase 4).

AMD-10: library + scope assignments, most specific scope wins (PRODUCT > SUBCATEGORY > CATEGORY),
resolution only through the DB function; profiles are versioned (G-18).
AMD-11: Packaging / Container / User Manual are the ITEM_COUNT group.
AMD-16: the action catalogue is the ACTION group; codes immutable, labels snapshotted.
"""

from __future__ import annotations

import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import Connection, text
from sqlalchemy.orm import Session

from app.modules.rm_actions import repository as rm_repo
from tests.conftest import JwtFactory
from tests.integration.conftest import UserFactory, as_admin

BASE = "/api/v1/config/item-field-profiles"


def _auth(token: str, key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if key:
        headers["Idempotency-Key"] = key
    return headers


def _scalar(conn: Connection, sql: str, **params: Any) -> Any:
    return as_admin(conn).execute(text(sql), params).scalar_one()


def _hierarchy(conn: Connection) -> dict[str, uuid.UUID]:
    """A fresh category -> sub-category -> product chain (+ a product of another category)."""
    tag = uuid.uuid4().hex[:6].upper()
    cat = _scalar(
        conn,
        "insert into public.product_categories (code, name) values (:c, :c) returning id",
        c=f"T_IFP_{tag}",
    )
    other = _scalar(
        conn,
        "insert into public.product_categories (code, name) values (:c, :c) returning id",
        c=f"T_IFP_O_{tag}",
    )
    sub = _scalar(
        conn,
        "insert into public.product_subcategories (category_id, code, name)"
        " values (:cat, 'SUB', 'Sub') returning id",
        cat=cat,
    )
    prod = _scalar(
        conn,
        "insert into public.products (code, name, category_id, subcategory_id)"
        " values (:c, :c, :cat, :sub) returning id",
        c=f"T-IFP-{tag}",
        cat=cat,
        sub=sub,
    )
    other_prod = _scalar(
        conn,
        "insert into public.products (code, name, category_id) values (:c, :c, :cat) returning id",
        c=f"T-IFP-O-{tag}",
        cat=other,
    )
    return {"cat": cat, "sub": sub, "prod": prod, "other_prod": other_prod}


async def _create_field(
    client: AsyncClient, token: str, group: str, label: str, **extra: Any
) -> dict[str, Any]:
    res = await client.post(
        f"{BASE}/fields",
        headers=_auth(token, f"t-{uuid.uuid4()}"),
        json={"field_group": group, "label": label, **extra},
    )
    assert res.status_code == 201, res.text
    return dict(res.json())


def _group(profile: dict[str, Any], group: str) -> dict[str, Any]:
    return next(g for g in profile["groups"] if g["field_group"] == group)


async def test_requires_config_permission(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    gate = make_token(users.create(roles=["GATE_INWARD"]))
    res = await client.get(f"{BASE}/fields", headers=_auth(gate))
    assert res.status_code == 403
    res = await client.post(
        f"{BASE}/fields",
        headers=_auth(gate, "k-forbidden"),
        json={"field_group": "DEPARTMENT", "label": "Nope"},
    )
    assert res.status_code == 403


async def test_seeded_library_keeps_existing_codes(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    """AMD-10 / AMD-16: existing action codes and AMD-11 counts are library entries."""
    token = make_token(users.create(super_admin=True))
    res = await client.get(f"{BASE}/fields", headers=_auth(token), params={"field_group": "ACTION"})
    assert res.status_code == 200
    actions = {f["code"]: f for f in res.json()}
    # DEC-74 adds ISSUE_CN_REQUEST (store analysis only; no Accounts flags, never system-assigned).
    assert set(actions) == {
        "SEND_NEW",
        "SEND_REPAIRED",
        "ISSUE_CN",
        "NOT_ALLOWED",
        "PENDING_BP",
        "ISSUE_CN_REQUEST",
    }
    assert actions["ISSUE_CN"]["requires_cn"] is True
    assert not actions["ISSUE_CN_REQUEST"]["requires_cn"]
    assert not actions["ISSUE_CN_REQUEST"]["requires_challan"]
    assert actions["SEND_NEW"]["requires_challan"] is True
    counts = await client.get(
        f"{BASE}/fields", headers=_auth(token), params={"field_group": "ITEM_COUNT"}
    )
    assert {f["code"] for f in counts.json()} >= {"PACKAGING", "CONTAINER", "USER_MANUAL"}


async def test_create_field_idempotent_and_code_immutable(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    token = make_token(users.create(super_admin=True))
    key = f"t-{uuid.uuid4()}"
    body = {"field_group": "CATEGORISATION", "label": "Body  Broken T1", "is_wastage": True}
    first = await client.post(f"{BASE}/fields", headers=_auth(token, key), json=body)
    assert first.status_code == 201, first.text
    assert first.json()["code"] == "BODY_BROKEN_T1"
    assert first.json()["label"] == "Body Broken T1"
    # G-16 pattern: the same key returns the original result, nothing is created twice.
    again = await client.post(f"{BASE}/fields", headers=_auth(token, key), json=body)
    assert again.status_code == 201
    assert again.json()["id"] == first.json()["id"]
    # A new request with the same code is a conflict.
    dup = await client.post(f"{BASE}/fields", headers=_auth(token, f"t-{uuid.uuid4()}"), json=body)
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "DUPLICATE_CODE"
    # G-18: the code (and group) cannot be changed through the API.
    bad = await client.patch(
        f"{BASE}/fields/{first.json()['id']}",
        headers=_auth(token),
        json={"code": "OTHER"},
    )
    assert bad.status_code == 422
    ok = await client.patch(
        f"{BASE}/fields/{first.json()['id']}",
        headers=_auth(token),
        json={"label": "Body Broken (T1)", "reason": "relabel"},
    )
    assert ok.status_code == 200
    assert ok.json()["label"] == "Body Broken (T1)"
    assert ok.json()["code"] == "BODY_BROKEN_T1"


async def test_flags_are_checked_per_group(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    token = make_token(users.create(super_admin=True))
    res = await client.post(
        f"{BASE}/fields",
        headers=_auth(token, f"t-{uuid.uuid4()}"),
        json={"field_group": "CATEGORISATION", "label": "CN bucket", "requires_cn": True},
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "FLAG_NOT_ALLOWED"
    res = await client.post(
        f"{BASE}/fields",
        headers=_auth(token, f"t-{uuid.uuid4()}"),
        json={"field_group": "ACTION", "label": "Wastage action", "is_wastage": True},
    )
    assert res.status_code == 422


async def test_category_profile_from_condition_options(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory, db_conn: Connection
) -> None:
    """AMD-10: DMT's buckets are its condition options; DMT_SHORT_QTY is excluded (G-07)."""
    token = make_token(users.create(super_admin=True))
    dmt = _scalar(db_conn, "select id from public.product_categories where code = 'DMT'")
    res = await client.get(f"{BASE}/scope", headers=_auth(token), params={"category_id": str(dmt)})
    assert res.status_code == 200, res.text
    cat = _group(res.json(), "CATEGORISATION")
    assert cat["overridden"] is True
    assert cat["inherited"] == []
    effective = [f["code"] for f in cat["effective"]]
    assert "DMT_OK_PACKED" in effective
    assert "DMT_SHORT_QTY" not in effective
    assert any(r["code"] == "DMT_SHORT_QTY" and not r["is_included"] for r in cat["own"])
    assert len(_group(res.json(), "ACTION")["effective"]) == 5


async def test_override_inheritance_and_resolution(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory, db_conn: Connection
) -> None:
    """AMD-10 resolution rule end to end: CATEGORY -> SUBCATEGORY -> PRODUCT."""
    token = make_token(users.create(super_admin=True))
    h = _hierarchy(db_conn)
    b1 = await _create_field(client, token, "CATEGORISATION", f"Good {uuid.uuid4().hex[:5]}")
    b2 = await _create_field(client, token, "CATEGORISATION", f"Damaged {uuid.uuid4().hex[:5]}")
    dept = await _create_field(client, token, "DEPARTMENT", f"Repair T {uuid.uuid4().hex[:5]}")

    # Category: b1, b2 + a department.
    res = await client.put(
        f"{BASE}/scope/CATEGORISATION",
        headers=_auth(token),
        json={
            "category_id": str(h["cat"]),
            "fields": [
                {"field_id": b2["id"], "sort_order": 1},
                {"field_id": b1["id"], "sort_order": 2},
            ],
        },
    )
    assert res.status_code == 200, res.text
    assert [f["code"] for f in _group(res.json(), "CATEGORISATION")["effective"]] == [
        b2["code"],
        b1["code"],
    ]
    res = await client.put(
        f"{BASE}/scope/DEPARTMENT",
        headers=_auth(token),
        json={"category_id": str(h["cat"]), "fields": [{"field_id": dept["id"]}]},
    )
    assert res.status_code == 200

    # Product scope inherits from the category (the sub-category has no rows yet).
    params = {"category_id": str(h["cat"]), "product_id": str(h["prod"])}
    res = await client.get(f"{BASE}/scope", headers=_auth(token), params=params)
    assert res.status_code == 200
    body = res.json()
    assert [r["scope_type"] for r in body["chain"]] == ["CATEGORY", "SUBCATEGORY", "PRODUCT"]
    g = _group(body, "CATEGORISATION")
    assert g["overridden"] is False
    assert g["inherited_from"]["scope_type"] == "CATEGORY"
    assert [f["code"] for f in g["effective"]] == [b2["code"], b1["code"]]

    # Sub-category override: only b1.
    res = await client.put(
        f"{BASE}/scope/CATEGORISATION",
        headers=_auth(token),
        json={
            "category_id": str(h["cat"]),
            "subcategory_id": str(h["sub"]),
            "fields": [{"field_id": b1["id"]}],
        },
    )
    assert res.status_code == 200
    res = await client.get(f"{BASE}/scope", headers=_auth(token), params=params)
    g = _group(res.json(), "CATEGORISATION")
    assert g["inherited_from"]["scope_type"] == "SUBCATEGORY"
    assert [f["code"] for f in g["effective"]] == [b1["code"]]

    # Product override of an exclusion only: no buckets, departments still inherited.
    override = {
        "category_id": str(h["cat"]),
        "product_id": str(h["prod"]),
        "fields": [{"field_id": b1["id"], "is_included": False}],
    }
    res = await client.put(f"{BASE}/scope/CATEGORISATION", headers=_auth(token), json=override)
    assert res.status_code == 200
    assert _group(res.json(), "CATEGORISATION")["effective"] == []
    assert [f["code"] for f in _group(res.json(), "DEPARTMENT")["effective"]] == [dept["code"]]

    resolved = await client.get(f"{BASE}/resolve/{h['prod']}", headers=_auth(token))
    assert resolved.status_code == 200
    assert resolved.json()["groups"]["CATEGORISATION"] == []
    assert [f["code"] for f in resolved.json()["groups"]["DEPARTMENT"]] == [dept["code"]]

    # Idempotent by content: the same PUT writes nothing (no new change-log row).
    logs_before = _scalar(
        db_conn,
        "select count(*) from public.config_change_log where entity_type = 'item_field_profile'",
    )
    res = await client.put(f"{BASE}/scope/CATEGORISATION", headers=_auth(token), json=override)
    assert res.status_code == 200
    logs_after = _scalar(
        db_conn,
        "select count(*) from public.config_change_log where entity_type = 'item_field_profile'",
    )
    assert logs_after == logs_before

    # An empty list removes the override: the product inherits from the sub-category again.
    res = await client.put(
        f"{BASE}/scope/CATEGORISATION",
        headers=_auth(token),
        json={**override, "fields": []},
    )
    assert res.status_code == 200
    g = _group(res.json(), "CATEGORISATION")
    assert g["overridden"] is False
    assert [f["code"] for f in g["effective"]] == [b1["code"]]


async def test_override_validation(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory, db_conn: Connection
) -> None:
    token = make_token(users.create(super_admin=True))
    h = _hierarchy(db_conn)
    dept = await _create_field(client, token, "DEPARTMENT", f"Cleaning T {uuid.uuid4().hex[:5]}")
    # A DEPARTMENT field cannot be put in the ACTION group.
    res = await client.put(
        f"{BASE}/scope/ACTION",
        headers=_auth(token),
        json={"category_id": str(h["cat"]), "fields": [{"field_id": dept["id"]}]},
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "FIELD_GROUP_MISMATCH"
    # The product must belong to the category of the chain.
    res = await client.put(
        f"{BASE}/scope/DEPARTMENT",
        headers=_auth(token),
        json={
            "category_id": str(h["cat"]),
            "product_id": str(h["other_prod"]),
            "fields": [{"field_id": dept["id"]}],
        },
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "SCOPE_MISMATCH"
    # Duplicates in one request are rejected.
    res = await client.put(
        f"{BASE}/scope/DEPARTMENT",
        headers=_auth(token),
        json={
            "category_id": str(h["cat"]),
            "fields": [{"field_id": dept["id"]}, {"field_id": dept["id"]}],
        },
    )
    assert res.status_code == 422
    # An inactive field cannot be included.
    await client.patch(
        f"{BASE}/fields/{dept['id']}", headers=_auth(token), json={"is_active": False}
    )
    res = await client.put(
        f"{BASE}/scope/DEPARTMENT",
        headers=_auth(token),
        json={"category_id": str(h["cat"]), "fields": [{"field_id": dept["id"]}]},
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "FIELD_INACTIVE"


async def test_versions_and_resolve_against_version(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory, db_conn: Connection
) -> None:
    """G-18: a committed change creates a version; resolution can use any stored version."""
    token = make_token(users.create(super_admin=True))
    h = _hierarchy(db_conn)
    b1 = await _create_field(client, token, "CATEGORISATION", f"Wastage T {uuid.uuid4().hex[:5]}")
    res = await client.put(
        f"{BASE}/scope/CATEGORISATION",
        headers=_auth(token),
        json={"category_id": str(h["cat"]), "fields": [{"field_id": b1["id"]}]},
    )
    assert res.status_code == 200
    # The test transaction never commits: fire the deferred version trigger explicitly.
    as_admin(db_conn).execute(text("set constraints all immediate"))
    versions = await client.get(f"{BASE}/versions", headers=_auth(token))
    assert versions.status_code == 200
    latest = versions.json()[0]
    assert latest["library_count"] >= 1
    assert latest["assignment_count"] >= 1

    at_version = await client.get(
        f"{BASE}/resolve/{h['prod']}",
        headers=_auth(token),
        params={"version_id": latest["id"]},
    )
    assert at_version.status_code == 200
    assert at_version.json()["version_no"] == latest["version_no"]
    assert [f["code"] for f in at_version.json()["groups"]["CATEGORISATION"]] == [b1["code"]]

    missing = await client.get(
        f"{BASE}/resolve/{h['prod']}",
        headers=_auth(token),
        params={"version_id": str(uuid.uuid4())},
    )
    assert missing.status_code == 404


async def test_rm_action_options_follow_the_action_library(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory, db_conn: Connection
) -> None:
    """AMD-16: relabelling a library action changes the RM action options; the code stays."""
    token = make_token(users.create(super_admin=True))
    send_new = _scalar(
        db_conn,
        "select id from public.item_field_library"
        " where field_group = 'ACTION' and code = 'SEND_NEW'",
    )
    res = await client.patch(
        f"{BASE}/fields/{send_new}", headers=_auth(token), json={"label": "Send New Unit"}
    )
    assert res.status_code == 200
    # The RM action screen reads its options from the library (no hard-coded list any more).
    options = rm_repo.get_rm_action_options(Session(bind=as_admin(db_conn)))
    by_code = {o["code"]: o for o in options}
    assert by_code["SEND_NEW"]["label"] == "Send New Unit"
    # The library holds DEC-74's ISSUE_CN_REQUEST too; the RM service filters it out (the RM
    # action API test checks the five RM options).
    assert set(by_code) == {
        "SEND_NEW",
        "SEND_REPAIRED",
        "ISSUE_CN",
        "NOT_ALLOWED",
        "PENDING_BP",
        "ISSUE_CN_REQUEST",
    }
    # Rule texts still come from the workbook option row (WF r6).
    assert by_code["SEND_NEW"]["rule_text"]
