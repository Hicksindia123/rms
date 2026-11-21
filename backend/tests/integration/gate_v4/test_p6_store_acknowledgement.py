"""Phase P6 (docs/RMS_PHASE_PROMPTS_20-11-2026.md) · DEC-66 (Q12 user, Q13 PROVISIONAL).

A user of the Intermediate Store a transfer slip is addressed to (OP / DT / RI, not the Main
Store) acknowledges it in full, in one transaction with an Idempotency-Key (G-16): slip
ACKNOWLEDGED, its custody transfer accepted (TRANSIT -> the store's location, G-09), a routing task
per GS for the store; a GS whose slips are all acknowledged is STORE_ACKNOWLEDGED. "Report
discrepancy" is a remark that alerts the RM + Management; the slip stays GENERATED. A VOIDED slip
cannot be acknowledged, and a post-lock edit (Q10) now also voids an acknowledged slip, bringing
its goods back to Inward Staging. Store users see only their store's slips.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import Connection

from tests.conftest import JwtFactory
from tests.integration.conftest import UserFactory, fetch_all
from tests.integration.gate_v4.test_gate_v4 import Actors
from tests.integration.gate_v4.test_p4_categorisation_lock import _bucket_codes
from tests.integration.gate_v4.test_p5_transfer_slips import (
    _generate,
    _locked,
    _pdf_text,
    _status,
    _stock_by_location,
    mgmt,
    products,
    rm,
)
from tests.integration.test_gate_inward import Masters, _auth
from tests.integration.test_itemization import key
from tests.integration.test_unboxing import FakeStorage

pytestmark = pytest.mark.gate_v4

__all__ = ["mgmt", "products", "rm"]  # fixtures re-used from the P5 tests


@pytest.fixture
def dt_user(users: UserFactory, make_token: JwtFactory) -> str:
    return make_token(users.create(roles=["ISTORE_DT"], full_name="Dinesh DT Store"))


@pytest.fixture
def super_admin_token(users: UserFactory, make_token: JwtFactory) -> str:
    return make_token(users.create(super_admin=True, full_name="P6 Super Admin"))


@pytest.fixture
def op_user(users: UserFactory, make_token: JwtFactory) -> str:
    return make_token(users.create(roles=["ISTORE_OP"], full_name="Om OP Store"))


async def _ack(client: AsyncClient, token: str, slip_id: str, idem: str | None = None, **body: str):  # type: ignore[no-untyped-def]
    return await client.post(
        f"/api/v1/transfer-slips/{slip_id}/acknowledge",
        json=body,
        headers=_auth(token, idem or key()),
    )


async def _two_store_slips(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    products: dict[str, str],
    rm: str,
) -> tuple[str, list[str], dict[str, dict]]:  # type: ignore[type-arg]
    """One GS with a DT line (3) and an OP line (1): two slips."""
    gs_id, items = await _locked(
        client, storage, actors, masters, [(products["DT"], 3), (products["OP"], 1)]
    )
    gen = await _generate(client, rm, [gs_id])
    assert gen.status_code == 201, gen.text
    return gs_id, items, {s["store"]["code"]: s for s in gen.json()["slips"]}


def _open_tasks(conn: Connection, gs_id: str) -> list[str]:
    rows = fetch_all(
        conn,
        """select r.code from public.workflow_tasks t
             join public.roles r on r.id = t.assigned_role_id
            where t.gs_id = :g and t.step_code = 'STORE_ROUTING' and t.status = 'OPEN'
            order by r.code""",
        g=gs_id,
    )
    return [r["code"] for r in rows]


# --- acknowledgement --------------------------------------------------------------------------
async def test_store_acknowledges_its_slip_in_full(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    products: dict[str, str],
    rm: str,
    mgmt: str,
    dt_user: str,
    op_user: str,
    db_conn: Connection,
) -> None:
    gs_id, _, slips = await _two_store_slips(client, storage, actors, masters, products, rm)
    dt, op = slips["DT"], slips["OP"]

    # Generation alerts the users of each slip's store (no generic TRANSFER_INITIATED any more).
    notes = fetch_all(
        db_conn,
        """select type, entity_id::text as slip from public.notifications
            where entity_id = any(cast(:ids as uuid[])) order by type""",
        ids=[dt["id"], op["id"]],
    )
    assert {n["type"] for n in notes} == {"TRANSFER_SLIP_GENERATED"}

    # A store user sees only its own store's slips (list, detail, queue).
    mine = await client.get("/api/v1/transfer-slips", headers=_auth(dt_user))
    assert mine.status_code == 200, mine.text
    assert {s["store"]["code"] for s in mine.json()["items"]} == {"DT"}
    assert (
        await client.get(f"/api/v1/transfer-slips/{op['id']}", headers=_auth(dt_user))
    ).status_code == 404
    assert (
        await client.get("/api/v1/transfer-slips/pending", headers=_auth(dt_user))
    ).status_code == 403
    detail = (await client.get(f"/api/v1/transfer-slips/{dt['id']}", headers=_auth(dt_user))).json()
    assert detail["can_acknowledge"] is True and detail["status"] == "GENERATED"
    journey = (await client.get("/api/v1/me/journey", headers=_auth(dt_user))).json()
    ack_entry = next(e for e in journey["entries"] if e["code"] == "ACK_TRANSFER_SLIPS")
    assert ack_entry["count"] >= 1
    queue = (
        await client.get("/api/v1/me/journey/ACK_TRANSFER_SLIPS", headers=_auth(dt_user))
    ).json()
    assert dt["id"] in {i["target_id"] for i in queue["items"]}
    assert op["id"] not in {i["target_id"] for i in queue["items"]}

    # Only the slip's store acknowledges: not the RM, not Management, not another store.
    assert (await _ack(client, rm, dt["id"])).status_code == 403
    assert (await _ack(client, mgmt, dt["id"])).status_code == 403
    assert (await _ack(client, op_user, dt["id"])).status_code == 404

    idem = key()
    first = await _ack(client, dt_user, dt["id"], idem, remarks="All 3 received")
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["status"] == "ACKNOWLEDGED" and body["acknowledge_remarks"] == "All 3 received"
    assert body["acknowledged_by_name"] == "Dinesh DT Store" and body["can_acknowledge"] is False
    # G-16: the same key returns the first result; a new key on an acknowledged slip is a 409.
    replay = await _ack(client, dt_user, dt["id"], idem, remarks="All 3 received")
    assert replay.status_code == 200 and replay.headers.get("Idempotency-Replayed") == "true"
    assert replay.json() == body
    again = await _ack(client, dt_user, dt["id"])
    assert again.status_code == 409 and again.json()["error"]["code"] == (
        "TRANSFER_SLIP_ALREADY_ACKNOWLEDGED"
    )

    # Stock: the DT pieces are in the DT store's own location; the OP piece is still in transit.
    assert _stock_by_location(db_conn, gs_id) == {"ISTORE_DT": 3, "TRANSIT": 1}
    ct = fetch_all(
        db_conn,
        """select t.status, p.full_name from public.transfer_slips s
             join public.custody_transfers t on t.id = s.custody_transfer_id
             join public.profiles p on p.id = t.accepted_by where s.id = :s""",
        s=dt["id"],
    )
    assert ct == [{"status": "ACCEPTED", "full_name": "Dinesh DT Store"}]
    # One slip of two: the GS is still on transfer slips; DT may route its part (P7 task).
    assert _status(db_conn, gs_id) == "TRANSFER_SLIP_GENERATED"
    assert _open_tasks(db_conn, gs_id) == ["ISTORE_DT"]

    assert (await _ack(client, op_user, op["id"])).status_code == 200
    assert _status(db_conn, gs_id) == "STORE_ACKNOWLEDGED"
    assert _stock_by_location(db_conn, gs_id) == {"ISTORE_DT": 3, "ISTORE_OP": 1}
    assert _open_tasks(db_conn, gs_id) == ["ISTORE_DT", "ISTORE_OP"]
    accepted = fetch_all(
        db_conn,
        """select 1 from public.notifications n join public.transfer_slips s
               on s.custody_transfer_id = n.entity_id
            where n.type = 'TRANSFER_ACCEPTED' and s.id = :s""",
        s=op["id"],
    )
    assert accepted, "the RM who generated the slip is told"

    # The RM and Management still see every slip; the PDF shows the acknowledgement.
    all_slips = (await client.get("/api/v1/transfer-slips", headers=_auth(mgmt))).json()
    assert {dt["id"], op["id"]} <= {s["id"] for s in all_slips["items"]}
    pdf = await client.get(f"/api/v1/transfer-slips/{dt['id']}/pdf", headers=_auth(dt_user))
    assert pdf.status_code == 200
    assert "Acknowledged" in _pdf_text(pdf.content)


async def test_generic_custody_accept_and_cancel_are_refused(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    products: dict[str, str],
    rm: str,
    super_admin_token: str,
    db_conn: Connection,
) -> None:
    """The custody transfer behind a slip follows the slip (service 409; the DB refuses too)."""
    gs_id, _ = await _locked(client, storage, actors, masters, [(products["DT"], 2)])
    slip = (await _generate(client, rm, [gs_id])).json()["slips"][0]
    detail = (await client.get(f"/api/v1/transfer-slips/{slip['id']}", headers=_auth(rm))).json()
    tid = detail["custody_transfer_id"]
    res = await client.post(
        f"/api/v1/custody/transfers/{tid}/cancel",
        json={"reason": "not by hand"},
        headers=_auth(super_admin_token, key()),
    )
    assert res.status_code == 409 and res.json()["error"]["code"] == "TRANSFER_SLIP_BACKED"
    res = await client.post(
        f"/api/v1/custody/transfers/{tid}/accept",
        json={
            "acceptance_code": "ACCEPTED_VERIFIED",
            "lines": [
                {"lot_id": r["lot_id"], "qty_counted": r["qty"]}
                for r in fetch_all(
                    db_conn,
                    """select lot_id::text, qty_sent as qty from public.custody_transfer_lines
                        where transfer_id = :t""",
                    t=tid,
                )
            ],
        },
        headers=_auth(super_admin_token, key()),
    )
    assert res.status_code == 409 and res.json()["error"]["code"] == "TRANSFER_SLIP_BACKED"


async def test_super_admin_may_acknowledge_but_not_the_slip_generator(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    products: dict[str, str],
    users: UserFactory,
    make_token: JwtFactory,
    super_admin_token: str,
    db_conn: Connection,
) -> None:
    """Segregation of duties (custody §9.3, DEC-66): the RM who generated a slip never
    acknowledges it, even when that user also holds the store role."""
    both = make_token(users.create(roles=["REPLACEMENT_MANAGER", "ISTORE_DT"], full_name="Both"))
    gs_id, _ = await _locked(client, storage, actors, masters, [(products["DT"], 1)])
    slip = (await _generate(client, both, [gs_id])).json()["slips"][0]
    res = await _ack(client, both, slip["id"])
    assert res.status_code == 403 and res.json()["error"]["code"] == "SEGREGATION_OF_DUTIES"
    assert (await _ack(client, super_admin_token, slip["id"])).status_code == 200
    assert _status(db_conn, gs_id) == "STORE_ACKNOWLEDGED"


# --- discrepancy ------------------------------------------------------------------------------
async def test_report_discrepancy_keeps_the_slip_open(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    products: dict[str, str],
    rm: str,
    dt_user: str,
    op_user: str,
    db_conn: Connection,
) -> None:
    gs_id, _ = await _locked(client, storage, actors, masters, [(products["DT"], 2)])
    slip = (await _generate(client, rm, [gs_id])).json()["slips"][0]
    url = f"/api/v1/transfer-slips/{slip['id']}/discrepancies"

    short = await client.post(url, json={"remark": "x"}, headers=_auth(dt_user, key()))
    assert short.status_code == 422
    assert (
        await client.post(url, json={"remark": "One short"}, headers=_auth(op_user, key()))
    ).status_code == 404
    res = await client.post(
        url, json={"remark": "Carton 2 had one piece less"}, headers=_auth(dt_user, key())
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["status"] == "GENERATED" and body["discrepancy_count"] == 1
    assert body["discrepancies"][0]["remark"] == "Carton 2 had one piece less"
    # No quantity change: everything is still in transit; RM + Management are alerted.
    assert _stock_by_location(db_conn, gs_id) == {"TRANSIT": 2}
    alerts = fetch_all(
        db_conn,
        """select distinct r.code from public.notifications n
             join public.user_roles ur on ur.user_id = n.user_id
             join public.roles r on r.id = ur.role_id
            where n.type = 'TRANSFER_SLIP_DISCREPANCY' and n.entity_id = :s""",
        s=slip["id"],
    )
    assert {"REPLACEMENT_MANAGER"} <= {a["code"] for a in alerts}

    # Still acknowledgeable after the report; no report on an acknowledged slip.
    assert (await _ack(client, dt_user, slip["id"])).status_code == 200
    late = await client.post(url, json={"remark": "Too late"}, headers=_auth(dt_user, key()))
    assert late.status_code == 409


# --- void (Q10) -------------------------------------------------------------------------------
async def test_voided_slip_cannot_be_acknowledged(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    products: dict[str, str],
    rm: str,
    mgmt: str,
    dt_user: str,
) -> None:
    gs_id, items = await _locked(client, storage, actors, masters, [(products["DT"], 2)])
    slip = (await _generate(client, rm, [gs_id])).json()["slips"][0]
    edit = await client.patch(
        f"/api/v1/gs/{gs_id}/locked/items/{items[0]}",
        json={"documented_qty": 3, "reason": "doc qty corrected"},
        headers=_auth(mgmt, key()),
    )
    assert edit.status_code == 200, edit.text
    res = await _ack(client, dt_user, slip["id"])
    assert res.status_code == 409 and res.json()["error"]["code"] == "TRANSFER_SLIP_VOIDED"


async def test_edit_after_acknowledgement_returns_the_goods_to_staging(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    products: dict[str, str],
    rm: str,
    mgmt: str,
    dt_user: str,
    op_user: str,
    db_conn: Connection,
) -> None:
    """P5 refused this (409 TRANSFER_SLIP_ACKNOWLEDGED); P6 voids the acknowledged slip too: its
    goods go back from the store's location to Inward Staging through an accepted return transfer,
    the store's routing task closes, the GS waits for a new slip and the store re-acknowledges."""
    gs_id, items, slips = await _two_store_slips(client, storage, actors, masters, products, rm)
    assert (await _ack(client, dt_user, slips["DT"]["id"])).status_code == 200
    assert (await _ack(client, op_user, slips["OP"]["id"])).status_code == 200
    assert _status(db_conn, gs_id) == "STORE_ACKNOWLEDGED"

    code = (await _bucket_codes(client, mgmt, products["DT"]))[0]
    edit = await client.patch(
        f"/api/v1/gs/{gs_id}/locked/items/{items[0]}",
        json={"received_qty": 2, "buckets": [{"field_code": code, "qty": 2}], "reason": "recount"},
        headers=_auth(mgmt, key()),
    )
    assert edit.status_code == 200, edit.text

    rows = fetch_all(
        db_conn,
        """select s.status, rt.status as ret_status, rt.purpose_code, fl.code as ret_from,
                  tl.code as ret_to
             from public.transfer_slips s
             join public.custody_transfers rt on rt.id = s.void_return_transfer_id
             join public.inventory_locations fl on fl.id = rt.from_location_id
             join public.inventory_locations tl on tl.id = rt.to_location_id
            where s.id = any(cast(:ids as uuid[])) order by fl.code""",
        ids=[slips["DT"]["id"], slips["OP"]["id"]],
    )
    assert rows == [
        {
            "status": "VOIDED",
            "ret_status": "ACCEPTED",
            "purpose_code": "TRANSFER_SLIP_VOID",
            "ret_from": "ISTORE_DT",
            "ret_to": "INWARD_STAGING",
        },
        {
            "status": "VOIDED",
            "ret_status": "ACCEPTED",
            "purpose_code": "TRANSFER_SLIP_VOID",
            "ret_from": "ISTORE_OP",
            "ret_to": "INWARD_STAGING",
        },
    ]
    assert _stock_by_location(db_conn, gs_id) == {"INWARD_STAGING": 3}
    assert _status(db_conn, gs_id) == "PENDING_TRANSFER_SLIP"
    assert _open_tasks(db_conn, gs_id) == []

    regen = await _generate(client, rm, [gs_id])
    assert regen.status_code == 201, regen.text
    new_dt = next(s for s in regen.json()["slips"] if s["store"]["code"] == "DT")
    assert new_dt["relevant_qty"] == 2
    assert (await _ack(client, dt_user, new_dt["id"])).status_code == 200
    assert _open_tasks(db_conn, gs_id) == ["ISTORE_DT"]
