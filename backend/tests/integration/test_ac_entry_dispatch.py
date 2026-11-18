"""Integration tests for change plan 2026-11-12 Phase 8 (AMD-18, AMD-19; DEC-22, DEC-26, DEC-47;
G-15, G-16, G-22).

1. Accounts work queue: GSs with a CURRENT A/c Actions slip. Per action line the fields come from
   the action flags (requires_cn -> CN No./Date/Value, requires_challan -> Challan No./Date);
   G-22 rejects fields an action does not take, completion with an incomplete line, and edits
   after completion. CN No. is used by one goods slip only (DEC-22).
2. Completion with goods-shipping lines generates a numbered Dispatch Slip PDF and notifies
   DISPATCH; without them the goods slip settles its returned pieces and goes to closure.
3. Dispatch issues the goods via rms_move_stock (DEC-47 locations per action code), records date /
   transporter / docket (DEC-26), and hands the GS to the closure engine (G-15). Idempotent (G-16).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import date, timedelta
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from app.core.db import get_session_factory
from app.core.middleware import limiter
from app.shared.storage import get_storage
from tests.conftest import JwtFactory
from tests.integration.conftest import UserFactory, as_admin, build_test_app
from tests.integration.test_department_routing import _seed_gs_held_at_intermediate_store
from tests.integration.test_final_actions import PdfStorage, _split
from tests.integration.test_gate_inward import _auth

TODAY = date.today().isoformat()


def _key() -> str:
    return f"test-ph8-{uuid.uuid4().hex}"


@pytest.fixture
def storage() -> PdfStorage:
    return PdfStorage()


@pytest.fixture
async def client(
    session_factory: sessionmaker[Session], storage: PdfStorage
) -> AsyncIterator[AsyncClient]:
    app = build_test_app()
    app.dependency_overrides[get_session_factory] = lambda: session_factory
    app.dependency_overrides[get_storage] = lambda: storage
    limiter.reset()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    limiter.reset()


@pytest.fixture
def actors(users: UserFactory, make_token: JwtFactory) -> dict[str, Any]:
    rm_id = users.create(roles=["REPLACEMENT_MANAGER"], full_name="Pratham")
    acc_id = users.create(roles=["ACCOUNTS"], full_name="Deepak")
    disp_id = users.create(roles=["DISPATCH"], full_name="Vikas")
    tech_id = users.create(roles=["TECHNICIAN"], full_name="Ramesh")
    return {
        "rm": make_token(rm_id),
        "rm_id": str(rm_id),
        "accounts": make_token(acc_id),
        "accounts_id": str(acc_id),
        "dispatch": make_token(disp_id),
        "dispatch_id": str(disp_id),
        "tech": make_token(tech_id),
    }


async def _finalise(
    client: AsyncClient, db_conn: Connection, actors: dict[str, Any], **split: int
) -> dict[str, Any]:
    """Phase 7: a GS held at the intermediate store with finalised actions (default 6/3/1)."""
    fx = _seed_gs_held_at_intermediate_store(db_conn)
    split = split or {"SEND_NEW": 6, "SEND_REPAIRED": 3, "ISSUE_CN": 1}
    save = await client.put(
        f"/api/v1/gs/{fx['gs_id']}/final-actions",
        headers=_auth(actors["rm"], _key()),
        json={"lines": [_split(fx["item_id"], **split)]},
    )
    assert save.status_code == 200, save.text
    fin = await client.post(
        f"/api/v1/gs/{fx['gs_id']}/final-actions/finalise",
        headers=_auth(actors["rm"], _key()),
        json={},
    )
    assert fin.status_code == 200, fin.text
    fx["ac_slip_id"] = fin.json()["current_slip"]["id"]
    return fx


async def _state(client: AsyncClient, token: str, gs_id: str) -> dict[str, Any]:
    res = await client.get(f"/api/v1/ac-entry/gs/{gs_id}", headers=_auth(token))
    assert res.status_code == 200, res.text
    return dict(res.json())


def _by_action(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {ln["action_code"]: ln for ln in state["lines"]}


async def _save(
    client: AsyncClient, actors: dict[str, Any], fx: dict[str, Any], lines: list[dict[str, Any]]
) -> Any:
    return await client.put(
        f"/api/v1/ac-entry/gs/{fx['gs_id']}/lines",
        headers=_auth(actors["accounts"], _key()),
        json={"ac_action_slip_id": fx["ac_slip_id"], "lines": lines},
    )


async def _fill_all(
    client: AsyncClient, actors: dict[str, Any], fx: dict[str, Any], cn_no: str
) -> dict[str, Any]:
    state = await _state(client, actors["accounts"], fx["gs_id"])
    lines = []
    for ln in state["lines"]:
        body: dict[str, Any] = {"line_id": ln["id"]}
        if ln["requires_cn"]:
            body |= {"cn_no": cn_no, "cn_date": TODAY, "cn_value": "1250.50"}
        if ln["requires_challan"]:
            body |= {"challan_no": f"CH-{ln['action_code']}", "challan_date": TODAY}
        lines.append(body)
    res = await _save(client, actors, fx, lines)
    assert res.status_code == 200, res.text
    return dict(res.json())


async def _complete(client: AsyncClient, actors: dict[str, Any], fx: dict[str, Any]) -> Any:
    return await client.post(
        f"/api/v1/ac-entry/gs/{fx['gs_id']}/complete",
        headers=_auth(actors["accounts"], _key()),
        json={"ac_action_slip_id": fx["ac_slip_id"]},
    )


def _balances(db_conn: Connection, gs_id: str) -> dict[str, int]:
    rows = (
        as_admin(db_conn)
        .execute(
            text(
                """
                select loc.code, sum(b.qty)::int as qty
                  from public.stock_balances b
                  join public.stock_lots l on l.id = b.lot_id
                  join public.inventory_locations loc on loc.id = b.location_id
                 where l.gs_id = cast(:g as uuid) and b.qty > 0
                 group by loc.code
                """
            ),
            {"g": gs_id},
        )
        .all()
    )
    return {r[0]: r[1] for r in rows}


def _gs_status(db_conn: Connection, gs_id: str) -> str:
    return str(
        as_admin(db_conn)
        .execute(
            text("select status from public.goods_slips where id = cast(:g as uuid)"), {"g": gs_id}
        )
        .scalar_one()
    )


# =================================================================================================


async def test_queue_lists_finalised_gs_with_fields_from_action_flags(
    client: AsyncClient, db_conn: Connection, actors: dict[str, Any]
) -> None:
    """AMD-18: lines come from the finalised slip; which fields each needs comes from flags."""
    fx = await _finalise(client, db_conn, actors)
    queue = await client.get("/api/v1/ac-entry/queue", headers=_auth(actors["accounts"]))
    assert queue.status_code == 200, queue.text
    item = next(q for q in queue.json() if q["gs_id"] == fx["gs_id"])
    assert (item["lines_total"], item["lines_needing_data"], item["lines_complete"]) == (3, 3, 0)
    assert item["is_completed"] is False

    state = await _state(client, actors["accounts"], fx["gs_id"])
    lines = _by_action(state)
    assert (lines["ISSUE_CN"]["requires_cn"], lines["ISSUE_CN"]["requires_challan"]) == (
        True,
        False,
    )
    for code in ("SEND_NEW", "SEND_REPAIRED"):
        assert (lines[code]["requires_cn"], lines[code]["requires_challan"]) == (False, True)
    assert {c: ln["qty"] for c, ln in lines.items()} == {
        "SEND_NEW": 6,
        "SEND_REPAIRED": 3,
        "ISSUE_CN": 1,
    }
    assert state["can_edit"] is True and state["can_complete"] is False
    assert state["shipping_lines"] == 2

    # Flags are configuration (AMD-18): a library edit applies to slips finalised afterwards,
    # the snapshot of this slip stays (G-18).
    as_admin(db_conn).execute(
        text(
            "update public.item_field_library set requires_cn = true"
            " where field_group = 'ACTION' and code = 'NOT_ALLOWED'"
        )
    )
    fx2 = await _finalise(client, db_conn, actors, NOT_ALLOWED=10)
    state2 = await _state(client, actors["accounts"], fx2["gs_id"])
    assert state2["lines"][0]["requires_cn"] is True
    assert (
        _by_action(await _state(client, actors["accounts"], fx["gs_id"]))["SEND_NEW"]["requires_cn"]
        is False
    )

    # Permissions: technician cannot read; dispatch cannot edit.
    tech = await client.get(f"/api/v1/ac-entry/gs/{fx['gs_id']}", headers=_auth(actors["tech"]))
    assert tech.status_code == 403
    res = await client.put(
        f"/api/v1/ac-entry/gs/{fx['gs_id']}/lines",
        headers=_auth(actors["dispatch"], _key()),
        json={
            "ac_action_slip_id": fx["ac_slip_id"],
            "lines": [
                {"line_id": lines["SEND_NEW"]["id"], "challan_no": "X", "challan_date": TODAY}
            ],
        },
    )
    assert res.status_code == 403


async def test_g22_fields_only_where_action_flag_requires_them(
    client: AsyncClient, db_conn: Connection, actors: dict[str, Any]
) -> None:
    fx = await _finalise(client, db_conn, actors)
    lines = _by_action(await _state(client, actors["accounts"], fx["gs_id"]))

    cn_on_send_new = await _save(
        client,
        actors,
        fx,
        [{"line_id": lines["SEND_NEW"]["id"], "cn_no": "CN1", "cn_date": TODAY, "cn_value": "10"}],
    )
    assert cn_on_send_new.status_code == 409 and cn_on_send_new.json()["error"]["code"] == "G-22"
    challan_on_cn = await _save(
        client,
        actors,
        fx,
        [{"line_id": lines["ISSUE_CN"]["id"], "challan_no": "CH1", "challan_date": TODAY}],
    )
    assert challan_on_cn.status_code == 409 and challan_on_cn.json()["error"]["code"] == "G-22"

    partial = await _save(
        client, actors, fx, [{"line_id": lines["ISSUE_CN"]["id"], "cn_no": "CN1"}]
    )
    assert partial.status_code == 422 and partial.json()["error"]["code"] == "CN_FIELDS_INCOMPLETE"
    future = (date.today() + timedelta(days=1)).isoformat()
    fut = await _save(
        client,
        actors,
        fx,
        [{"line_id": lines["SEND_NEW"]["id"], "challan_no": "CH1", "challan_date": future}],
    )
    assert fut.status_code == 422 and fut.json()["error"]["code"] == "DATE_IN_FUTURE"
    zero = await _save(
        client,
        actors,
        fx,
        [{"line_id": lines["ISSUE_CN"]["id"], "cn_no": "C", "cn_date": TODAY, "cn_value": "0"}],
    )
    assert zero.status_code == 422

    # Partial save is fine; completion is refused until every line is complete (G-22).
    ok = await _save(
        client,
        actors,
        fx,
        [{"line_id": lines["SEND_NEW"]["id"], "challan_no": " CH-77 ", "challan_date": TODAY}],
    )
    assert ok.status_code == 200, ok.text
    saved = _by_action(ok.json())["SEND_NEW"]
    assert (saved["challan_no"], saved["is_complete"], saved["entered_by_name"]) == (
        "CH-77",
        True,
        "Deepak",
    )
    assert ok.json()["lines_complete"] == 1
    early = await _complete(client, actors, fx)
    assert early.status_code == 409 and early.json()["error"]["code"] == "G-22"
    assert "line 1" in early.json()["error"]["message"]

    # Idempotency-Key is mandatory (G-16).
    no_key = await client.put(
        f"/api/v1/ac-entry/gs/{fx['gs_id']}/lines",
        headers=_auth(actors["accounts"]),
        json={"ac_action_slip_id": fx["ac_slip_id"], "lines": [{"line_id": saved["id"]}]},
    )
    assert no_key.status_code in (400, 422)


async def test_cn_number_belongs_to_one_goods_slip(
    client: AsyncClient, db_conn: Connection, actors: dict[str, Any]
) -> None:
    """DEC-22 (credit_notes rule reused): an external CN No. is recorded once."""
    fx1 = await _finalise(client, db_conn, actors)
    fx2 = await _finalise(client, db_conn, actors)
    cn = f"CN-{uuid.uuid4().hex[:6]}"
    await _fill_all(client, actors, fx1, cn)
    line2 = _by_action(await _state(client, actors["accounts"], fx2["gs_id"]))["ISSUE_CN"]
    taken = await _save(
        client,
        actors,
        fx2,
        [{"line_id": line2["id"], "cn_no": cn.lower(), "cn_date": TODAY, "cn_value": "5"}],
    )
    assert taken.status_code == 409 and taken.json()["error"]["code"] == "VOUCHER_NUMBER_TAKEN"


async def test_complete_generates_dispatch_slip_then_dispatch_moves_stock_and_closes_flow(
    client: AsyncClient,
    db_conn: Connection,
    actors: dict[str, Any],
    storage: PdfStorage,
) -> None:
    """AMD-18 -> AMD-19 end to end: 6 Send New, 3 Send Repaired, 1 Issue CN."""
    fx = await _finalise(client, db_conn, actors)
    gs_id = fx["gs_id"]
    await _fill_all(client, actors, fx, f"CN-{uuid.uuid4().hex[:6]}")
    uploads_before = len(storage.uploads)

    key = _key()
    done = await client.post(
        f"/api/v1/ac-entry/gs/{gs_id}/complete",
        headers=_auth(actors["accounts"], key),
        json={"ac_action_slip_id": fx["ac_slip_id"], "remarks": "GST input checked"},
    )
    assert done.status_code == 200, done.text
    state = done.json()
    assert state["is_completed"] is True and state["can_edit"] is False
    dslip = state["dispatch_slip"]
    assert dslip["status"] == "READY" and dslip["slip_no"].startswith("DS/")
    assert dslip["total_qty"] == 9  # Send New 6 + Send Repaired 3 ship goods; the CN line does not
    assert len(storage.uploads) == uploads_before + 1
    pdf = list(storage.uploads.values())[-1]
    assert pdf.startswith(b"%PDF-")
    assert _gs_status(db_conn, gs_id) == "HELD_AT_INTERMEDIATE_STORE"

    # Idempotent replay: same key returns the same result, no second slip (G-16).
    replay = await client.post(
        f"/api/v1/ac-entry/gs/{gs_id}/complete",
        headers=_auth(actors["accounts"], key),
        json={"ac_action_slip_id": fx["ac_slip_id"], "remarks": "GST input checked"},
    )
    assert replay.status_code == 200 and replay.headers.get("Idempotency-Replayed") == "true"
    assert len(storage.uploads) == uploads_before + 1

    c = as_admin(db_conn)
    # DISPATCH notified by the seeded rule; the RM told that Accounts completed.
    for user_id, ntype in (
        (actors["dispatch_id"], "DISPATCH_SLIP_READY"),
        (actors["rm_id"], "AC_ENTRY_COMPLETED"),
    ):
        n = c.execute(
            text(
                "select count(*) from public.notifications"
                " where user_id = cast(:u as uuid) and type = :t"
            ),
            {"u": user_id, "t": ntype},
        ).scalar_one()
        assert n == 1, ntype
    # The Dispatch alert says what to send per line with the challan Accounts entered (AMD-19).
    title, body = c.execute(
        text(
            "select title, body from public.notifications"
            " where user_id = cast(:u as uuid) and type = 'DISPATCH_SLIP_READY'"
        ),
        {"u": actors["dispatch_id"]},
    ).one()
    assert dslip["slip_no"] in title and "send 9 pc" in title
    assert "Challan CH-SEND_NEW" in body and "Challan CH-SEND_REPAIRED" in body
    assert ": 6 pc" in body and ": 3 pc" in body
    assert body.count("•") == 2  # two shipping lines; the CN line ships no goods

    # Frozen: Accounts cannot edit, the RM cannot revise the A/c Actions slip (G-22).
    lines = _by_action(state)
    frozen = await _save(
        client,
        actors,
        fx,
        [{"line_id": lines["SEND_NEW"]["id"], "challan_no": "OTHER", "challan_date": TODAY}],
    )
    assert frozen.status_code == 409 and frozen.json()["error"]["code"] == "G-22"
    revise = await client.put(
        f"/api/v1/gs/{gs_id}/final-actions",
        headers=_auth(actors["rm"], _key()),
        json={
            "lines": [_split(fx["item_id"], SEND_NEW=5, SEND_REPAIRED=4, ISSUE_CN=1)],
            "reason": "late change",
        },
    )
    assert revise.status_code == 409 and revise.json()["error"]["code"] == "G-22"

    # Dispatch queue (DISPATCH role) and print (logged).
    listing = await client.get(
        "/api/v1/dispatch-slips?status=READY", headers=_auth(actors["dispatch"])
    )
    assert listing.status_code == 200
    detail = next(d for d in listing.json() if d["id"] == dslip["id"])
    assert {(ln["action_code"], ln["qty"]) for ln in detail["lines"]} == {
        ("SEND_NEW", 6),
        ("SEND_REPAIRED", 3),
    }
    printed = await client.post(
        f"/api/v1/dispatch-slips/{dslip['id']}/print", headers=_auth(actors["dispatch"])
    )
    assert printed.status_code == 200 and printed.json()["print_count"] == 1
    assert (
        await client.get("/api/v1/dispatch-slips", headers=_auth(actors["accounts"]))
    ).status_code == 403

    # DEC-26: docket or vehicle required; Accounts cannot dispatch.
    url = f"/api/v1/dispatch-slips/{dslip['id']}/dispatch"
    no_docket = await client.post(
        url,
        headers=_auth(actors["dispatch"], _key()),
        json={"dispatch_date": TODAY, "transporter": "Blue Dart"},
    )
    assert no_docket.status_code == 422 and no_docket.json()["error"]["code"] == "TRACKING"
    forbidden = await client.post(
        url,
        headers=_auth(actors["accounts"], _key()),
        json={"dispatch_date": TODAY, "transporter": "Blue Dart", "docket_no": "D1"},
    )
    assert forbidden.status_code == 403

    dkey = _key()
    body = {"dispatch_date": TODAY, "transporter": "Blue Dart", "docket_no": "BD123456"}
    sent = await client.post(url, headers=_auth(actors["dispatch"], dkey), json=body)
    assert sent.status_code == 200, sent.text
    out = sent.json()
    assert (out["status"], out["docket_no"], out["dispatched_by_name"]) == (
        "DISPATCHED",
        "BD123456",
        "Vikas",
    )

    # Stock (DEC-47 + DEC-57 Q12): 3 repaired pieces shipped back, 1 credited, and the 6 old pieces
    # of Send New (new stock ships outside the ledger, DEC-26) go to the Non-Functional Store.
    assert _balances(db_conn, gs_id) == {
        "DISPATCHED": 3,
        "CREDITED": 1,
        "NON_FUNCTIONAL_STORE": 6,
    }
    checklist = (
        await client.get(f"/api/v1/gs/{gs_id}/closure", headers=_auth(actors["rm"]))
    ).json()
    items = {i["code"]: i for i in checklist["items"]}
    assert items["AC_ENTRY_COMPLETE"]["passed"] is True
    assert items["DISPATCH_SLIP_DISPATCHED"]["passed"] is True
    assert items["CN_DECISION_RECORDED"]["applicable"] is False
    assert items["STOCK_ACCOUNTED"]["passed"] is True  # Non-Functional Store is accounted
    assert items["NO_PENDING_REACTION"]["passed"] is True
    # Every piece is accounted, so the closure engine moves on; the CN entered by Accounts still
    # needs the prior party notification (BR-38).
    assert items["PRIOR_NOTIFICATION"]["passed"] is False
    assert _gs_status(db_conn, gs_id) == "AWAITING_NOTIFICATION"

    # Idempotent replay; a second dispatch with a new key is refused.
    again = await client.post(url, headers=_auth(actors["dispatch"], dkey), json=body)
    assert again.status_code == 200 and again.headers.get("Idempotency-Replayed") == "true"
    twice = await client.post(url, headers=_auth(actors["dispatch"], _key()), json=body)
    assert twice.status_code == 409 and twice.json()["error"]["code"] == "ALREADY_DISPATCHED"
    assert _balances(db_conn, gs_id)["DISPATCHED"] == 3


async def test_no_shipping_lines_settles_and_goes_to_closure(
    client: AsyncClient, db_conn: Connection, actors: dict[str, Any], storage: PdfStorage
) -> None:
    """Only Issue CN: no Dispatch Slip; pieces credited; the closure engine takes over (G-15)."""
    fx = await _finalise(client, db_conn, actors, ISSUE_CN=10)
    await _fill_all(client, actors, fx, f"CN-{uuid.uuid4().hex[:6]}")
    uploads_before = len(storage.uploads)
    done = await _complete(client, actors, fx)
    assert done.status_code == 200, done.text
    assert done.json()["dispatch_slip"] is None
    assert len(storage.uploads) == uploads_before
    assert _balances(db_conn, fx["gs_id"]) == {"CREDITED": 10}
    # Stock accounted -> COMMERCIAL_RESOLUTION -> a CN needs a prior party notification (BR-38).
    assert _gs_status(db_conn, fx["gs_id"]) == "AWAITING_NOTIFICATION"
    checklist = (
        await client.get(f"/api/v1/gs/{fx['gs_id']}/closure", headers=_auth(actors["rm"]))
    ).json()
    items = {i["code"]: i for i in checklist["items"]}
    assert items["PRIOR_NOTIFICATION"]["applicable"] is True
    assert items["PRIOR_NOTIFICATION"]["passed"] is False
    assert items["DISPATCH_SLIP_DISPATCHED"]["applicable"] is False


async def test_legacy_replacement_dispatch_refuses_amd_flow_gs(
    client: AsyncClient, db_conn: Connection, actors: dict[str, Any]
) -> None:
    """AMD-19 / G-22: on the A/c Actions flow goods ship only against the Dispatch Slip."""
    fx = await _finalise(client, db_conn, actors)
    res = await client.post(
        "/api/v1/dispatches",
        headers=_auth(actors["dispatch"], _key()),
        json={
            "gs_id": fx["gs_id"],
            "dispatch_type": "SEND_NEW",
            "transporter": "Blue Dart",
            "lines": [{"gs_item_id": fx["item_id"], "qty": 1}],
        },
    )
    assert res.status_code == 409 and res.json()["error"]["code"] == "G-22", res.text
    queue = await client.get("/api/v1/dispatches/queue", headers=_auth(actors["dispatch"]))
    assert all(q["gs_id"] != fx["gs_id"] for q in queue.json())


async def test_db_guards_reject_direct_writes(
    client: AsyncClient, db_conn: Connection, actors: dict[str, Any]
) -> None:
    """G-22 in the DB: holds without the API."""
    fx = await _finalise(client, db_conn, actors)
    c = as_admin(db_conn)
    lines = _by_action(await _state(client, actors["accounts"], fx["gs_id"]))

    def rejected(sql: str, params: dict[str, Any]) -> str:
        sp = c.begin_nested()
        with pytest.raises(DBAPIError) as exc:
            c.execute(text(sql), params)
            c.execute(text("set constraints all immediate"))
        sp.rollback()
        return str(exc.value)

    # Fields only where the flag asks (constraint) and no deletes (trigger).
    assert "ac_entry_lines_cn_fields" in rejected(
        "update public.ac_entry_lines set cn_no = 'X', cn_date = current_date, cn_value = 1"
        " where id = cast(:i as uuid)",
        {"i": lines["SEND_NEW"]["id"]},
    )
    assert "G-22" in rejected(
        "delete from public.ac_entry_lines where id = cast(:i as uuid)",
        {"i": lines["SEND_NEW"]["id"]},
    )
    assert "G-22" in rejected(
        "update public.ac_entry_lines set qty = 99 where id = cast(:i as uuid)",
        {"i": lines["SEND_NEW"]["id"]},
    )
    # Completion needs every line complete.
    assert "G-22" in rejected(
        "insert into public.ac_entry_completions (gs_id, ac_action_slip_id, completed_by)"
        " values (cast(:g as uuid), cast(:s as uuid), cast(:u as uuid))",
        {"g": fx["gs_id"], "s": fx["ac_slip_id"], "u": actors["accounts_id"]},
    )
    # A Dispatch Slip needs a completion first.
    assert "G-22" in rejected(
        """
        insert into public.dispatch_slips
               (gs_id, ac_action_slip_id, slip_no, attachment_id, template_version_no, content,
                sha256, generated_by)
        values (cast(:g as uuid), cast(:s as uuid), 'DS/TEST/1', gen_random_uuid(), 1, '{}',
                repeat('a', 64), cast(:u as uuid))
        """,
        {"g": fx["gs_id"], "s": fx["ac_slip_id"], "u": actors["accounts_id"]},
    )
    # CN No. on another goods slip (DEC-22) is rejected by the trigger too.
    cn = f"CN-{uuid.uuid4().hex[:6]}"
    await _fill_all(client, actors, fx, cn)
    fx2 = await _finalise(client, db_conn, actors)
    line2 = _by_action(await _state(client, actors["accounts"], fx2["gs_id"]))["ISSUE_CN"]
    assert "G-22" in rejected(
        "update public.ac_entry_lines set cn_no = :cn, cn_date = current_date, cn_value = 1"
        " where id = cast(:i as uuid)",
        {"cn": cn, "i": line2["id"]},
    )

    # After completion + dispatch slip: the slip is final; the A/c Actions slip cannot be
    # superseded; the legacy dispatch table refuses the GS.
    done = await _complete(client, actors, fx)
    assert done.status_code == 200, done.text
    dslip_id = done.json()["dispatch_slip"]["id"]
    assert "G-22" in rejected(
        "update public.dispatch_slips set slip_no = 'X' where id = cast(:d as uuid)",
        {"d": dslip_id},
    )
    assert "G-22" in rejected(
        "delete from public.dispatch_slips where id = cast(:d as uuid)", {"d": dslip_id}
    )
    assert "dispatch_slips_dispatched_fields" in rejected(
        "update public.dispatch_slips set status = 'DISPATCHED', dispatch_date = current_date,"
        " dispatched_by = cast(:u as uuid), dispatched_at = now() where id = cast(:d as uuid)",
        {"d": dslip_id, "u": actors["dispatch_id"]},
    )
    assert "G-22" in rejected(
        """
        update public.ac_action_slips set status = 'SUPERSEDED', superseded_at = now(),
               superseded_by = cast(:u as uuid), supersede_reason = 'late'
         where id = cast(:s as uuid)
        """,
        {"s": fx["ac_slip_id"], "u": actors["rm_id"]},
    )
    assert "G-22" in rejected(
        """
        insert into public.replacement_dispatches (dispatch_no, gs_id, dispatch_type, transporter)
        values ('DSP/TEST/1', cast(:g as uuid), 'SEND_NEW', 'X')
        """,
        {"g": fx["gs_id"]},
    )
