"""GET /gs/lookups/parties/by-location — Distributor list by State + Station.

Change plan 2026-11-12 Phase 1 step 5 · AMD-06 · DEC-35
(`gate.party_fallback` = STATE | ALL | NONE).
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

URL = "/api/v1/gs/lookups/parties/by-location"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _fixture(conn: Connection) -> dict[str, Any]:
    """A fresh state with two stations: BUSY has two parties, EMPTY has none.

    Plus one party in another state.
    """
    c = as_admin(conn)
    sfx = uuid.uuid4().hex[:6].upper()
    state = c.execute(
        text("insert into public.states (code, name) values (:c, :n) returning id"),
        {"c": f"T{sfx}", "n": f"Pytest State {sfx}"},
    ).scalar_one()
    other_state = c.execute(
        text("insert into public.states (code, name) values (:c, :n) returning id"),
        {"c": f"U{sfx}", "n": f"Pytest Other State {sfx}"},
    ).scalar_one()
    ids: dict[str, Any] = {"state": state, "other_state": other_state, "sfx": sfx}
    for key, st, name in (
        ("busy", state, "Busy"),
        ("empty", state, "Empty"),
        ("elsewhere", other_state, "Elsewhere"),
    ):
        ids[key] = c.execute(
            text("insert into public.stations (state_id, name) values (:s, :n) returning id"),
            {"s": st, "n": f"{name} {sfx}"},
        ).scalar_one()
    for code, name, st_key in (
        ("A", "Alpha Medicos", "busy"),
        ("B", "Beta Surgicals", "busy"),
        ("C", "Gamma Pharma", "elsewhere"),
    ):
        state_id = other_state if st_key == "elsewhere" else state
        c.execute(
            text(
                "insert into public.parties (code, name, state_id, station_id)"
                " values (:code, :name, :st, :stn)"
            ),
            {
                "code": f"PYT-{sfx}-{code}",
                "name": f"{name} {sfx}",
                "st": state_id,
                "stn": ids[st_key],
            },
        )
    return ids


def _set_fallback(conn: Connection, value: str) -> None:
    as_admin(conn).execute(
        text(
            "update public.system_settings set value = to_jsonb(cast(:v as text))"
            " where key = 'gate.party_fallback'"
        ),
        {"v": value},
    )


async def test_station_with_parties_returns_station_list(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory, db_conn: Connection
) -> None:
    ids = _fixture(db_conn)
    token = make_token(users.create(roles=["GATE_INWARD"]))
    res = await client.get(
        URL,
        headers=_auth(token),
        params={"state_id": str(ids["state"]), "station_id": str(ids["busy"])},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["scope"] == "STATION" and body["fallback_applied"] is False
    assert body["total"] == 2
    assert all(p["station_id"] == str(ids["busy"]) for p in body["items"])

    # Paged + searchable; a search miss inside a busy station does NOT fall back (DEC-35).
    res = await client.get(
        URL,
        headers=_auth(token),
        params={"state_id": str(ids["state"]), "station_id": str(ids["busy"]), "page_size": 1},
    )
    assert res.json()["total"] == 2 and len(res.json()["items"]) == 1
    res = await client.get(
        URL,
        headers=_auth(token),
        params={"state_id": str(ids["state"]), "station_id": str(ids["busy"]), "q": "beta"},
    )
    assert [p["name"].split()[0] for p in res.json()["items"]] == ["Beta"]
    res = await client.get(
        URL,
        headers=_auth(token),
        params={"state_id": str(ids["state"]), "station_id": str(ids["busy"]), "q": "gamma"},
    )
    assert res.json()["scope"] == "STATION" and res.json()["total"] == 0


@pytest.mark.parametrize(
    ("setting", "scope", "expect_other_state"),
    [("STATE", "STATE", False), ("ALL", "ALL", True), ("NONE", "NONE", False)],
)
async def test_empty_station_uses_configured_fallback(
    client: AsyncClient,
    users: UserFactory,
    make_token: JwtFactory,
    db_conn: Connection,
    setting: str,
    scope: str,
    expect_other_state: bool,
) -> None:
    ids = _fixture(db_conn)
    _set_fallback(db_conn, setting)
    token = make_token(users.create(roles=["GATE_INWARD"]))
    # Search by the fixture's unique suffix so the ALL list (2,000+ parties) stays small.
    res = await client.get(
        URL,
        headers=_auth(token),
        params={
            "state_id": str(ids["state"]),
            "station_id": str(ids["empty"]),
            "q": str(ids["sfx"]),
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["scope"] == scope
    assert body["fallback_applied"] is True
    assert body["fallback_setting"] == setting
    state_ids = {p["state_id"] for p in body["items"]}
    if setting == "NONE":
        assert body["items"] == [] and body["total"] == 0
    elif setting == "STATE":
        assert body["total"] == 2 and state_ids == {str(ids["state"])}
    else:
        assert body["total"] == 3
    assert (str(ids["other_state"]) in state_ids) is expect_other_state


async def test_state_only_lists_state_parties(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory, db_conn: Connection
) -> None:
    ids = _fixture(db_conn)
    token = make_token(users.create(roles=["GATE_INWARD"]))
    res = await client.get(URL, headers=_auth(token), params={"state_id": str(ids["state"])})
    assert res.status_code == 200
    assert res.json()["scope"] == "STATE" and res.json()["fallback_applied"] is False
    assert res.json()["total"] == 2


async def test_station_must_belong_to_state(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory, db_conn: Connection
) -> None:
    ids = _fixture(db_conn)
    token = make_token(users.create(roles=["GATE_INWARD"]))
    res = await client.get(
        URL,
        headers=_auth(token),
        params={"state_id": str(ids["state"]), "station_id": str(ids["elsewhere"])},
    )
    assert res.status_code == 422
    assert "station" in res.json()["error"]["details"]


async def test_lookup_requires_goods_slip_view(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory, db_conn: Connection
) -> None:
    ids = _fixture(db_conn)
    token = make_token(users.create(roles=["TECHNICIAN"]))
    res = await client.get(URL, headers=_auth(token), params={"state_id": str(ids["state"])})
    assert res.status_code == 403


def test_party_fallback_setting_rejects_unknown_value_in_db(db_conn: Connection) -> None:
    """DEC-35: the setting only takes STATE | ALL | NONE (DB CHECK, not only the UI)."""
    with pytest.raises(IntegrityError, match="system_settings_gate_party_fallback_check"):
        _set_fallback(db_conn, "STATION")
