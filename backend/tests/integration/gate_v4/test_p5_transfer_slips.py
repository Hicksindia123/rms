"""Phase P5 (docs/RMS_PHASE_PROMPTS_20-11-2026.md) · DEC-65 (Q10 user, Q20 PROVISIONAL, Q26 user).

The Replacement Manager selects locked goods slips and generates ONE transfer slip per
Intermediate Store (a GS spanning 3 stores is on 3 slips; each slip covers every selected GS with
lines for its store) in one transaction with an Idempotency-Key. Each slip is backed by a custody
transfer INWARD_STAGING → TRANSIT → the store (G-09). "Send Edit Request" keeps a GS off the slips
until Management / Super Admin resolve it. A post-lock edit voids the live slips (Q10): stock back
to Inward Staging, the GSs wait for a new slip.
"""

from __future__ import annotations

import base64
import re
import uuid
import zlib
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import Connection, text

from tests.conftest import JwtFactory
from tests.integration.conftest import UserFactory, as_admin, fetch_all
from tests.integration.gate_v4.test_gate_v4 import Actors
from tests.integration.gate_v4.test_p4_categorisation_lock import (
    _bucket_codes,
    _choose,
    _items_gs,
    _line,
    _lock,
    _split,
)
from tests.integration.test_gate_inward import Masters, _auth
from tests.integration.test_itemization import key
from tests.integration.test_unboxing import FakeStorage

pytestmark = pytest.mark.gate_v4

SLIP_NO = re.compile(r"^TRF/(OP|DT|RI)/\d{4}-\d{2}/\d{4}$")


@pytest.fixture
def mgmt(users: UserFactory, make_token: JwtFactory) -> str:
    return make_token(users.create(roles=["MANAGEMENT"], full_name="Mgmt"))


@pytest.fixture
def rm(users: UserFactory, make_token: JwtFactory) -> str:
    return make_token(users.create(roles=["REPLACEMENT_MANAGER"], full_name="Pratham RM"))


@pytest.fixture
def products(db_conn: Connection) -> dict[str, str]:
    """One product per store: DMT → DT, ENCLOSED_OVAL → OP, PRISMATIC → RI (remapped here, the
    default mapping puts PRISMATIC on OP; GENERAL has no condition buckets on a fresh reset)."""
    c = as_admin(db_conn)
    c.execute(
        text(
            """
            update public.intermediate_store_category_map m
               set store_id = (select id from public.intermediate_stores where code = 'RI')
             where m.category_id = (select id from public.product_categories
                                     where code = 'PRISMATIC')
            """
        )
    )
    tag = uuid.uuid4().hex[:6].upper()
    out: dict[str, str] = {}
    for store, cat in (("DT", "DMT"), ("OP", "ENCLOSED_OVAL"), ("RI", "PRISMATIC")):
        out[store] = str(
            c.execute(
                text(
                    """insert into public.products (code, name, category_id)
                       select :code, :name, id from public.product_categories where code = :cat
                       returning id"""
                ),
                {"code": f"P5-{tag}-{store}", "name": f"P5 {cat} {tag}", "cat": cat},
            ).scalar_one()
        )
    return out


async def _locked(
    client: AsyncClient,
    storage: FakeStorage,
    a: Actors,
    m: Masters,
    lines: list[tuple[str, int]],
) -> tuple[str, list[str]]:
    """A locked Replacement GS: one line per (product, qty), split into its first bucket(s)."""
    gs_id = await _items_gs(client, storage, a, m)
    items = [await _line(client, a.aman, gs_id, p, q, q) for p, q in lines]
    assert (await _choose(client, a.aman, gs_id, "RO")).status_code == 200
    for item, (product, qty) in zip(items, lines, strict=True):
        codes = await _bucket_codes(client, a.aman, product)
        split = {codes[0]: qty} if qty < 2 or len(codes) < 2 else {codes[0]: qty - 1, codes[1]: 1}
        res = await _split(client, a.aman, gs_id, item, split)
        assert res.status_code == 200, res.text
    res = await _lock(client, a.aman, gs_id)
    assert res.status_code == 200, res.text
    return gs_id, items


async def _generate(
    client: AsyncClient, token: str, gs_ids: list[str], idem: str | None = None
) -> Any:
    return await client.post(
        "/api/v1/transfer-slips", json={"gs_ids": gs_ids}, headers=_auth(token, idem or key())
    )


def _status(conn: Connection, gs_id: str) -> str:
    return str(
        conn.execute(
            text("select status from public.goods_slips where id = :g"), {"g": gs_id}
        ).scalar_one()
    )


def _stock_by_location(conn: Connection, gs_id: str) -> dict[str, int]:
    rows = fetch_all(
        conn,
        """select loc.code, sum(b.qty)::int as qty
             from public.stock_lots l
             join public.stock_balances b on b.lot_id = l.id and b.qty > 0
             join public.inventory_locations loc on loc.id = b.location_id
            where l.gs_id = :g group by loc.code""",
        g=gs_id,
    )
    return {r["code"]: r["qty"] for r in rows}


def _pdf_text(pdf: bytes) -> str:
    """Text of a reportlab PDF: decode the page streams (ASCII85 + Flate) and keep the (string)
    operands of the text operators."""
    chunks: list[str] = []
    for raw in re.findall(rb"stream\r?\n(.*?)endstream", pdf, re.S):
        data = raw.strip()
        try:
            if data.endswith(b"~>"):
                data = base64.a85decode(data[:-2])
            data = zlib.decompress(data)
        except (ValueError, zlib.error):
            continue  # an image or another binary stream
        chunks += [m.decode("latin-1") for m in re.findall(rb"\(((?:\\.|[^\\)])*)\)", data)]
    return " ".join(c.replace("\\(", "(").replace("\\)", ")") for c in chunks)


# --- generation -------------------------------------------------------------------------------
async def test_one_gs_one_store_gives_one_slip(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    products: dict[str, str],
    rm: str,
    db_conn: Connection,
) -> None:
    gs_id, _ = await _locked(
        client, storage, actors, masters, [(products["DT"], 3), (products["DT"], 2)]
    )

    pending = await client.get("/api/v1/transfer-slips/pending", headers=_auth(rm))
    assert pending.status_code == 200, pending.text
    row = next(p for p in pending.json() if p["gs_id"] == gs_id)
    assert [s["code"] for s in row["stores"]] == ["DT"]
    assert row["physical_qty"] == 5 and row["open_edit_request"] is None
    assert all(ln["buckets"] for ln in row["lines"])

    # The Replacement Executive has no part in it (DEC-65).
    assert (await _generate(client, actors.aman, [gs_id])).status_code == 403

    idem = key()
    first = await _generate(client, rm, [gs_id], idem)
    assert first.status_code == 201, first.text
    replay = await _generate(client, rm, [gs_id], idem)
    assert replay.status_code == 201 and replay.headers.get("Idempotency-Replayed") == "true"
    assert replay.json() == first.json()
    slips = first.json()["slips"]
    assert len(slips) == 1
    slip = slips[0]
    assert SLIP_NO.match(slip["slip_no"]) and slip["store"]["code"] == "DT"
    assert (slip["relevant_qty"], slip["grand_total_qty"], slip["gs_count"]) == (5, 5, 1)
    assert _status(db_conn, gs_id) == "TRANSFER_SLIP_GENERATED"
    # G-09: the goods are in TRANSIT on the slip's custody transfer, nothing left in staging.
    assert _stock_by_location(db_conn, gs_id) == {"TRANSIT": 5}
    ct = fetch_all(
        db_conn,
        """select t.transfer_no, t.status, l.code as to_code
             from public.transfer_slips s
             join public.custody_transfers t on t.id = s.custody_transfer_id
             join public.inventory_locations l on l.id = t.to_location_id
            where s.id = :s""",
        s=slip["id"],
    )
    assert ct == [{"transfer_no": slip["slip_no"], "status": "INITIATED", "to_code": "ISTORE_DT"}]
    count = fetch_all(
        db_conn, "select count(*)::int as n from public.transfer_slip_gs where gs_id = :g", g=gs_id
    )
    assert count[0]["n"] == 1  # the replay created nothing

    # Generating again for the same GS is refused (it is no longer pending).
    again = await _generate(client, rm, [gs_id])
    assert (
        again.status_code == 409 and again.json()["error"]["code"] == "GS_NOT_PENDING_TRANSFER_SLIP"
    )

    # On-screen view + PDF (A4, logo, both sections, totals).
    detail = await client.get(f"/api/v1/transfer-slips/{slip['id']}", headers=_auth(rm))
    assert detail.status_code == 200, detail.text
    lines = detail.json()["lines"]
    assert all(ln["is_relevant"] for ln in lines) and sum(ln["qty"] for ln in lines) == 5
    assert len(lines) == 4  # each line is split into two conditions (one slip line each)
    pdf = await client.get(f"/api/v1/transfer-slips/{slip['id']}/pdf", headers=_auth(rm))
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF-") and b"/Subtype /Image" in pdf.content  # Q26 logo
    words = _pdf_text(pdf.content)
    for expected in (
        slip["slip_no"],
        "Intermediate Store DT",
        "Total relevant qty",
        "Grand total",
        "Handed over by",
        "Received by",
        "Pratham RM",
    ):
        assert expected in words, expected
    again_pdf = await client.get(f"/api/v1/transfer-slips/{slip['id']}/pdf", headers=_auth(rm))
    assert again_pdf.content == pdf.content  # deterministic


async def test_one_gs_three_stores_gives_three_slips(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    products: dict[str, str],
    rm: str,
    db_conn: Connection,
) -> None:
    gs_id, _ = await _locked(
        client,
        storage,
        actors,
        masters,
        [(products["DT"], 2), (products["OP"], 3), (products["RI"], 1)],
    )
    res = await _generate(client, rm, [gs_id])
    assert res.status_code == 201, res.text
    slips = {s["store"]["code"]: s for s in res.json()["slips"]}
    assert set(slips) == {"DT", "OP", "RI"}
    assert {c: (s["relevant_qty"], s["grand_total_qty"]) for c, s in slips.items()} == {
        "DT": (2, 6),
        "OP": (3, 6),
        "RI": (1, 6),
    }
    for code, s in slips.items():
        assert s["slip_no"].startswith(f"TRF/{code}/")
        d = (await client.get(f"/api/v1/transfer-slips/{s['id']}", headers=_auth(rm))).json()
        relevant = [ln for ln in d["lines"] if ln["is_relevant"]]
        greyed = [ln for ln in d["lines"] if not ln["is_relevant"]]
        assert sum(ln["qty"] for ln in relevant) == s["relevant_qty"]
        assert sum(ln["qty"] for ln in relevant + greyed) == 6
        assert {ln["belongs_store_name"] for ln in greyed} == {
            f"Intermediate Store {c}" for c in slips if c != code
        }
    assert _stock_by_location(db_conn, gs_id) == {"TRANSIT": 6}


async def test_three_gs_mixed_gives_one_slip_per_store(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    products: dict[str, str],
    rm: str,
) -> None:
    gs_a, _ = await _locked(
        client, storage, actors, masters, [(products["DT"], 2), (products["OP"], 1)]
    )
    gs_b, _ = await _locked(client, storage, actors, masters, [(products["DT"], 4)])
    gs_c, _ = await _locked(client, storage, actors, masters, [(products["OP"], 5)])
    res = await _generate(client, rm, [gs_a, gs_b, gs_c])
    assert res.status_code == 201, res.text
    slips = {s["store"]["code"]: s for s in res.json()["slips"]}
    assert set(slips) == {"DT", "OP"}
    assert (
        slips["DT"]["relevant_qty"],
        slips["DT"]["grand_total_qty"],
        slips["DT"]["gs_count"],
    ) == (6, 7, 2)
    assert (
        slips["OP"]["relevant_qty"],
        slips["OP"]["grand_total_qty"],
        slips["OP"]["gs_count"],
    ) == (6, 8, 2)
    d = (await client.get(f"/api/v1/transfer-slips/{slips['DT']['id']}", headers=_auth(rm))).json()
    per_gs = {g["gs_id"]: (g["relevant_qty"], g["total_qty"]) for g in d["goods_slips"]}
    assert per_gs == {gs_a: (2, 3), gs_b: (4, 4)}
    listing = await client.get(
        "/api/v1/transfer-slips", params={"status": "GENERATED"}, headers=_auth(rm)
    )
    assert listing.status_code == 200
    assert {s["id"] for s in listing.json()["items"]} >= {slips["DT"]["id"], slips["OP"]["id"]}


# --- edit request -----------------------------------------------------------------------------
async def test_edit_request_keeps_the_gs_off_the_slips(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    products: dict[str, str],
    rm: str,
    mgmt: str,
    db_conn: Connection,
) -> None:
    gs_id, items = await _locked(client, storage, actors, masters, [(products["DT"], 3)])
    url = f"/api/v1/gs/{gs_id}/edit-requests"
    assert (
        await client.post(url, json={"reason": "qty"}, headers=_auth(actors.aman, key()))
    ).status_code == 403
    assert (
        await client.post(url, json={"reason": " "}, headers=_auth(rm, key()))
    ).status_code == 422
    res = await client.post(
        url, json={"reason": "Physical qty looks wrong"}, headers=_auth(rm, key())
    )
    assert res.status_code == 201, res.text
    req = res.json()
    assert req["status"] == "OPEN" and req["requested_by_name"] == "Pratham RM"
    dup = await client.post(url, json={"reason": "again"}, headers=_auth(rm, key()))
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "EDIT_REQUEST_OPEN"
    notes = fetch_all(
        db_conn,
        "select 1 from public.notifications where entity_id = :g and type = 'GS_EDIT_REQUESTED'",
        g=gs_id,
    )
    assert notes, "Management / Super Admin are told"

    gen = await _generate(client, rm, [gs_id])
    assert gen.status_code == 409 and gen.json()["error"]["code"] == "EDIT_REQUEST_OPEN"
    pending = (await client.get("/api/v1/transfer-slips/pending", headers=_auth(rm))).json()
    assert next(p for p in pending if p["gs_id"] == gs_id)["open_edit_request"]["id"] == req["id"]

    resolve = f"/api/v1/transfer-slips/edit-requests/{req['id']}/resolve"
    assert (
        await client.post(
            resolve, json={"outcome": "REJECTED", "note": "ok"}, headers=_auth(rm, key())
        )
    ).status_code == 403
    no_edit = await client.post(resolve, json={"outcome": "EDITED"}, headers=_auth(mgmt, key()))
    assert no_edit.status_code == 409 and no_edit.json()["error"]["code"] == "NO_EDIT_SINCE_REQUEST"
    no_note = await client.post(resolve, json={"outcome": "REJECTED"}, headers=_auth(mgmt, key()))
    assert (
        no_note.status_code == 409 and no_note.json()["error"]["code"] == "REJECT_REASON_REQUIRED"
    )

    # Management edits the GS (P4 rules), then marks the request edited.
    code = (await _bucket_codes(client, mgmt, products["DT"]))[0]
    edit = await client.patch(
        f"/api/v1/gs/{gs_id}/locked/items/{items[0]}",
        json={
            "received_qty": 2,
            "buckets": [{"field_code": code, "qty": 2}],
            "reason": "recounted",
        },
        headers=_auth(mgmt, key()),
    )
    assert edit.status_code == 200, edit.text
    done = await client.post(resolve, json={"outcome": "EDITED"}, headers=_auth(mgmt, key()))
    assert done.status_code == 200 and done.json()["status"] == "EDITED", done.text
    gen = await _generate(client, rm, [gs_id])
    assert gen.status_code == 201, gen.text
    assert gen.json()["slips"][0]["relevant_qty"] == 2


async def test_rejected_edit_request_releases_the_gs(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    products: dict[str, str],
    rm: str,
    mgmt: str,
) -> None:
    gs_id, _ = await _locked(client, storage, actors, masters, [(products["OP"], 2)])
    req = (
        await client.post(
            f"/api/v1/gs/{gs_id}/edit-requests", json={"reason": "check"}, headers=_auth(rm, key())
        )
    ).json()
    res = await client.post(
        f"/api/v1/transfer-slips/edit-requests/{req['id']}/resolve",
        json={"outcome": "REJECTED", "note": "Counts are right"},
        headers=_auth(mgmt, key()),
    )
    assert res.status_code == 200 and res.json()["status"] == "REJECTED", res.text
    view = (await client.get(f"/api/v1/gs/{gs_id}/transfer-slips", headers=_auth(rm))).json()
    assert view["open_edit_request"] is None and view["edit_requests"][0]["status"] == "REJECTED"
    assert (await _generate(client, rm, [gs_id])).status_code == 201


# --- Q10: an edit after the slips exist voids them ------------------------------------------
async def test_management_edit_voids_the_slips(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    products: dict[str, str],
    rm: str,
    mgmt: str,
    db_conn: Connection,
) -> None:
    gs_a, items_a = await _locked(
        client, storage, actors, masters, [(products["DT"], 3), (products["OP"], 1)]
    )
    gs_b, _ = await _locked(client, storage, actors, masters, [(products["DT"], 2)])
    gen = await _generate(client, rm, [gs_a, gs_b])
    assert gen.status_code == 201, gen.text
    slips = {s["store"]["code"]: s for s in gen.json()["slips"]}
    assert _status(db_conn, gs_a) == _status(db_conn, gs_b) == "TRANSFER_SLIP_GENERATED"

    state = (await client.get(f"/api/v1/gs/{gs_a}/itemization", headers=_auth(mgmt))).json()
    assert state["permissions"]["can_edit_locked"] is True
    code = (await _bucket_codes(client, mgmt, products["DT"]))[0]
    edit = await client.patch(
        f"/api/v1/gs/{gs_a}/locked/items/{items_a[0]}",
        json={
            "received_qty": 2,
            "buckets": [{"field_code": code, "qty": 2}],
            "reason": "one was extra",
        },
        headers=_auth(mgmt, key()),
    )
    assert edit.status_code == 200, edit.text

    rows = fetch_all(
        db_conn,
        """select s.slip_no, s.status, t.status as ct_status from public.transfer_slips s
             join public.custody_transfers t on t.id = s.custody_transfer_id
            where s.id = any(cast(:ids as uuid[])) order by s.slip_no""",
        ids=[slips["DT"]["id"], slips["OP"]["id"]],
    )
    assert {(r["status"], r["ct_status"]) for r in rows} == {("VOIDED", "CANCELLED")}
    # Stock back in Inward Staging (GS A with the corrected qty), both GSs pending again.
    assert _stock_by_location(db_conn, gs_a) == {"INWARD_STAGING": 3}
    assert _stock_by_location(db_conn, gs_b) == {"INWARD_STAGING": 2}
    assert _status(db_conn, gs_a) == _status(db_conn, gs_b) == "PENDING_TRANSFER_SLIP"
    notes = fetch_all(
        db_conn, "select 1 from public.notifications where type = 'TRANSFER_SLIP_VOIDED'"
    )
    assert notes, "the RM is told to regenerate"

    regen = await _generate(client, rm, [gs_a, gs_b])
    assert regen.status_code == 201, regen.text
    new = {s["store"]["code"]: s for s in regen.json()["slips"]}
    assert (new["DT"]["relevant_qty"], new["OP"]["relevant_qty"]) == (4, 1)
    assert new["DT"]["slip_no"] != slips["DT"]["slip_no"]
    voided = await client.get(
        "/api/v1/transfer-slips", params={"status": "VOIDED"}, headers=_auth(rm)
    )
    assert {slips["DT"]["id"], slips["OP"]["id"]} <= {s["id"] for s in voided.json()["items"]}


async def test_partial_void_regenerates_only_the_uncovered_lines(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    products: dict[str, str],
    rm: str,
    mgmt: str,
    db_conn: Connection,
) -> None:
    """GS A (DT only) and GS B (DT + OP) share the DT slip. Editing GS A voids the DT slip only;
    GS B keeps its live OP slip and its new slip covers just its DT line."""
    gs_a, items_a = await _locked(client, storage, actors, masters, [(products["DT"], 2)])
    gs_b, _ = await _locked(
        client, storage, actors, masters, [(products["DT"], 1), (products["OP"], 3)]
    )
    gen = (await _generate(client, rm, [gs_a, gs_b])).json()
    op_slip = next(s for s in gen["slips"] if s["store"]["code"] == "OP")
    code = (await _bucket_codes(client, mgmt, products["DT"]))[0]
    edit = await client.patch(
        f"/api/v1/gs/{gs_a}/locked/items/{items_a[0]}",
        json={"documented_qty": 3, "reason": "doc qty corrected"},
        headers=_auth(mgmt, key()),
    )
    assert edit.status_code == 200, edit.text
    assert code
    assert _status(db_conn, gs_b) == "PENDING_TRANSFER_SLIP"
    live = fetch_all(
        db_conn, "select status from public.transfer_slips where id = :s", s=op_slip["id"]
    )
    assert live == [{"status": "GENERATED"}]
    pending = (await client.get("/api/v1/transfer-slips/pending", headers=_auth(rm))).json()
    row_b = next(p for p in pending if p["gs_id"] == gs_b)
    assert row_b["partially_on_slips"] is True
    regen = await _generate(client, rm, [gs_b])
    assert regen.status_code == 201, regen.text
    assert [(s["store"]["code"], s["relevant_qty"]) for s in regen.json()["slips"]] == [("DT", 1)]
    assert _status(db_conn, gs_b) == "TRANSFER_SLIP_GENERATED"
    assert _stock_by_location(db_conn, gs_b) == {"TRANSIT": 4}
