"""Unit of Work audit attribution (G-17), idempotency (G-16) and pagination, through the module
template mounted on a test app."""

import uuid

from httpx import AsyncClient
from sqlalchemy import Connection

from tests.conftest import JwtFactory
from tests.integration.conftest import Override, UserFactory, fetch_all

URL = "/api/v1/template/departments"


def _headers(token: str, key: str | None = None, rid: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if key:
        headers["Idempotency-Key"] = key
    if rid:
        headers["X-Request-ID"] = rid
    return headers


def _code() -> str:
    return "TST_" + uuid.uuid4().hex[:10].upper()


def _creator(users: UserFactory) -> uuid.UUID:
    return users.create(
        overrides=[Override("masters", "create", "grant"), Override("masters", "view", "grant")]
    )


async def test_audit_rows_are_attributed_to_the_calling_user(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory, db_conn: Connection
) -> None:
    uid = _creator(users)
    rid = "req-" + uuid.uuid4().hex
    res = await client.post(
        URL,
        json={"code": _code(), "name": "Audit Dept"},
        headers=_headers(make_token(uid), key=uuid.uuid4().hex, rid=rid),
    )
    assert res.status_code == 201, res.text
    assert res.headers["X-Request-ID"] == rid
    dept = res.json()
    assert dept["created_by"] == str(uid)

    audit = fetch_all(
        db_conn,
        """select action, actor_id, request_id from public.audit_log
            where table_name = 'public.departments' and row_id = :rid""",
        rid=dept["id"],
    )
    assert audit == [{"action": "INSERT", "actor_id": uid, "request_id": rid}]


async def test_idempotent_replay_returns_identical_response(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory, db_conn: Connection
) -> None:
    uid = _creator(users)
    token = make_token(uid)
    key = uuid.uuid4().hex
    code = _code()
    first = await client.post(
        URL, json={"code": code, "name": "Idem"}, headers=_headers(token, key)
    )
    # Same request, different JSON key order: same canonical hash.
    second = await client.post(
        URL, json={"name": "Idem", "code": code}, headers=_headers(token, key)
    )
    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    assert "Idempotency-Replayed" not in first.headers
    assert second.headers["Idempotency-Replayed"] == "true"
    rows = fetch_all(db_conn, "select id from public.departments where code = :c", c=code)
    assert len(rows) == 1


async def test_same_key_with_different_request_is_409(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    uid = _creator(users)
    token = make_token(uid)
    key = uuid.uuid4().hex
    ok = await client.post(URL, json={"code": _code(), "name": "A"}, headers=_headers(token, key))
    assert ok.status_code == 201
    res = await client.post(URL, json={"code": _code(), "name": "B"}, headers=_headers(token, key))
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


async def test_same_key_from_another_user_is_409(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    key = uuid.uuid4().hex
    body = {"code": _code(), "name": "Shared"}
    first = await client.post(URL, json=body, headers=_headers(make_token(_creator(users)), key))
    assert first.status_code == 201
    res = await client.post(URL, json=body, headers=_headers(make_token(_creator(users)), key))
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


async def test_failed_command_releases_the_key(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory, db_conn: Connection
) -> None:
    uid = _creator(users)
    token = make_token(uid)
    taken = _code()
    assert (
        await client.post(
            URL, json={"code": taken, "name": "x"}, headers=_headers(token, uuid.uuid4().hex)
        )
    ).status_code == 201
    key = uuid.uuid4().hex
    dup = await client.post(URL, json={"code": taken, "name": "x"}, headers=_headers(token, key))
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "DUPLICATE_CODE"
    stored = fetch_all(db_conn, "select 1 from rms_private.idempotency_keys where key = :k", k=key)
    assert stored == []  # rolled back with the failed command


async def test_missing_idempotency_key_is_rejected(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    res = await client.post(
        URL, json={"code": _code(), "name": "x"}, headers=_headers(make_token(_creator(users)))
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"


async def test_body_validation_uses_the_envelope(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    res = await client.post(
        URL,
        json={"code": "lower", "name": "x", "extra": 1},
        headers=_headers(make_token(_creator(users)), uuid.uuid4().hex),
    )
    assert res.status_code == 422
    err = res.json()["error"]
    assert err["code"] == "VALIDATION_FAILED"
    assert {tuple(d["loc"]) for d in err["details"]} >= {("body", "code"), ("body", "extra")}
    assert all("input" not in d for d in err["details"])


async def test_list_is_paginated_sorted_and_filtered(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory, settings: object
) -> None:
    uid = _creator(users)
    token = make_token(uid)
    codes = sorted(_code() for _ in range(3))
    for c in codes:
        await client.post(
            URL, json={"code": c, "name": c}, headers=_headers(token, uuid.uuid4().hex)
        )

    res = await client.get(URL, params={"page_size": 2, "sort": "-code"}, headers=_headers(token))
    assert res.status_code == 200
    page = res.json()
    assert page["page"] == 1 and page["page_size"] == 2 and len(page["items"]) == 2
    assert page["total"] >= 3

    one = await client.get(URL, params={"filter[code]": codes[1]}, headers=_headers(token))
    assert [d["code"] for d in one.json()["items"]] == [codes[1]]

    capped = await client.get(URL, params={"page_size": 100000}, headers=_headers(token))
    assert capped.json()["page_size"] == 100  # PAGE_SIZE_MAX default

    bad = await client.get(URL, params={"sort": "password"}, headers=_headers(token))
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "INVALID_SORT"
    bad_filter = await client.get(URL, params={"filter[name]": "x"}, headers=_headers(token))
    assert bad_filter.json()["error"]["code"] == "INVALID_FILTER"
