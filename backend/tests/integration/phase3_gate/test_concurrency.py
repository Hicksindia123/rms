"""P3-08 · Phase 3 gate: concurrency (G-09, G-10, G-16, DEC-22).

* Simultaneous battery consumption: two technician receives race for the last batteries of a
  battery type → exactly one consumes, the other is refused, the stock never goes negative and
  Σ CONSUME = Σ batteries_installed (IC-09).
* Simultaneous CN issue with the same number: two credit notes issued at the same time with one
  CN No. → exactly one is ISSUED, the other gets 409 VOUCHER_NUMBER_TAKEN (not a 500).
* Simultaneous accept of the same transfer is covered by
  tests/integration/test_custody_concurrency.py (exactly one 200, one 409
  TRANSFER_NOT_AWAITING_ACCEPTANCE, stock credited once).

Real concurrency needs committed rows on separate connections: the requests go through the real
ASGI app with a session factory bound to the engine (one transaction per request, run on the
threadpool), and the tagged fixture rows are removed afterwards.
"""

# Teardown SQL below is assembled only from static fragments (no input): S608 does not apply.
# ruff: noqa: S608

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Connection, Engine, text
from sqlalchemy.orm import sessionmaker

from app.core.db import get_session_factory
from app.core.middleware import limiter
from tests.conftest import JwtFactory
from tests.integration.conftest import build_test_app
from tests.integration.phase3_gate.conftest import auth

pytestmark = pytest.mark.anyio

TAG = "p308c"
BATTERY = "P308CONC"

_USERS = f"select id from auth.users where email like '{TAG}-%@example.test'"
_PRODUCTS = f"select id from public.products where code like '{TAG.upper()}-%'"
_ITEMS = (
    "select id from public.stock_items where product_id in (" + _PRODUCTS + ") or "
    "battery_type_id in (select id from public.battery_types where code = '" + BATTERY + "')"
)
_LOTS = "select id from public.stock_lots where stock_item_id in (" + _ITEMS + ")"
_TRANSFERS = (
    "select distinct transfer_id from public.custody_transfer_lines where lot_id in (" + _LOTS + ")"
)
_BATCHES = (
    "select distinct batch_id from public.technician_batch_lines where lot_id in (" + _LOTS + ")"
)
_GS = f"select id from public.goods_slips where gs_no like 'GS-{TAG.upper()}-%'"
_PURGE = (
    "delete from public.notifications where entity_id in (" + _TRANSFERS + ") "
    "or entity_id in (" + _BATCHES + ") or entity_id in (" + _GS + ")",
    "delete from public.workflow_tasks where gs_id in (" + _GS + ")",
    "delete from public.technician_receiving_records where batch_id in (" + _BATCHES + ")",
    "delete from public.technician_batch_lines where batch_id in (" + _BATCHES + ")",
    "delete from public.technician_batches where id in (" + _BATCHES + ")",
    "delete from public.custody_transfer_lines where transfer_id in (" + _TRANSFERS + ")",
    "delete from public.custody_transfers where id in (" + _TRANSFERS + ")",
    "delete from public.battery_receipts where battery_type_id in "
    "(select id from public.battery_types where code = '" + BATTERY + "')",
    "delete from public.stock_movements where lot_id in (" + _LOTS + ")",
    "delete from public.stock_balances where lot_id in (" + _LOTS + ")",
    "delete from public.rate_verifications where credit_note_line_id in (select cl.id from "
    "public.credit_note_lines cl join public.credit_notes cn on cn.id = cl.credit_note_id "
    "where cn.gs_id in (" + _GS + "))",
    "delete from public.credit_note_lines where credit_note_id in "
    "(select id from public.credit_notes where gs_id in (" + _GS + "))",
    "delete from public.credit_notes where gs_id in (" + _GS + ")",
    "delete from public.rm_cn_decision_lines where decision_id in "
    "(select id from public.rm_cn_decisions where gs_id in (" + _GS + "))",
    "delete from public.rm_cn_decisions where gs_id in (" + _GS + ")",
    "delete from public.stock_lots where id in (" + _LOTS + ")",
    "delete from public.stock_items where id in (" + _ITEMS + ")",
    "delete from public.gs_items where gs_id in (" + _GS + ")",
    "delete from public.goods_slips where id in (" + _GS + ")",
    "delete from public.products where id in (" + _PRODUCTS + ")",
    "delete from public.battery_types where code = '" + BATTERY + "'",
    f"delete from rms_private.idempotency_keys where key like '{TAG}-%'",
    "delete from public.user_roles where user_id in (" + _USERS + ")",
    "delete from public.profiles where id in (" + _USERS + ")",
    f"delete from auth.users where email like '{TAG}-%@example.test'",
)


def _purge(db_engine: Engine) -> None:
    with db_engine.begin() as conn:
        conn.execute(text("set local session_replication_role = replica"))
        for stmt in _PURGE:
            conn.execute(text(stmt))


@pytest.fixture
def committed(db_engine: Engine) -> Iterator[Engine]:
    _purge(db_engine)
    try:
        yield db_engine
    finally:
        _purge(db_engine)


@pytest.fixture
async def live(committed: Engine) -> AsyncIterator[AsyncClient]:
    factory = sessionmaker(bind=committed, expire_on_commit=False, autoflush=False)
    app = build_test_app()
    app.dependency_overrides[get_session_factory] = lambda: factory
    limiter.reset()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    limiter.reset()


def _user(conn: Connection, *roles: str) -> uuid.UUID:
    uid = uuid.uuid4()
    conn.execute(
        text(
            """insert into auth.users (id, email, raw_app_meta_data, raw_user_meta_data)
               values (:id, :e, cast(:app as jsonb), cast(:meta as jsonb))"""
        ),
        {
            "id": uid,
            "e": f"{TAG}-{uid.hex[:12]}@example.test",
            "app": json.dumps({"rms_activate": True}),
            "meta": json.dumps({"full_name": f"P308 concurrency {'/'.join(roles)}"}),
        },
    )
    conn.execute(
        text(
            "insert into public.user_roles (user_id, role_id) "
            "select :u, id from public.roles where code = any(:r)"
        ),
        {"u": uid, "r": list(roles)},
    )
    return uid


def _idem() -> str:
    return f"{TAG}-{uuid.uuid4().hex}"


def _lot_in_store(conn: Connection, qty: int) -> uuid.UUID:
    """A GS-less DMT lot (supports_battery) in the Intermediate Store, credited via the ledger."""
    tag = uuid.uuid4().hex[:6].upper()
    product = conn.execute(
        text(
            """insert into public.products (code, name, category_id)
               select :c, 'P308 concurrency DMT', id from public.product_categories
                where code = 'DMT' returning id"""
        ),
        {"c": f"{TAG.upper()}-{tag}"},
    ).scalar_one()
    item = conn.execute(
        text(
            "insert into public.stock_items (item_kind, product_id) "
            "values ('FINISHED_GOOD', :p) returning id"
        ),
        {"p": product},
    ).scalar_one()
    lot = conn.execute(
        text(
            """insert into public.stock_lots (stock_item_id, condition_class, source_condition_code)
               values (:i, 'AS_RECEIVED', 'DMT_DISPLAY_ISSUE') returning id"""
        ),
        {"i": item},
    ).scalar_one()
    conn.execute(
        text(
            """select rms_private.rms_move_stock(
                 p_lot => :lot, p_from => null,
                 p_to => (select id from public.inventory_locations
                           where code = 'INTERMEDIATE_STORE'),
                 p_qty => :q, p_type => 'INWARD', p_ref_type => 'p308_concurrency',
                 p_ref_id => null, p_idem_key => :k, p_actor => null, p_reason => 'fixture')"""
        ),
        {"lot": lot, "q": qty, "k": _idem()},
    )
    return uuid.UUID(str(lot))


async def test_simultaneous_battery_consumption_never_goes_negative(
    live: AsyncClient, committed: Engine, make_token: JwtFactory
) -> None:
    with committed.begin() as conn:
        sahil = _user(conn, "INTERMEDIATE_STORE_MANAGER", "TECHNICIAN_COORDINATOR")
        spm = _user(conn, "SPARE_PARTS_MANAGER")
        conn.execute(
            text("insert into public.battery_types (code, name) values (:c, 'P308 test cell')"),
            {"c": BATTERY},
        )
        lots = [_lot_in_store(conn, 4), _lot_in_store(conn, 4)]
        tech = conn.execute(
            text("select id from public.technicians where is_active order by display_name limit 1")
        ).scalar_one()
    coordinator, keeper = make_token(sahil), make_token(spm)

    res = await live.post(
        "/api/v1/inventory/batteries/receipts",
        json={"battery_type": BATTERY, "qty": 5, "ref": "P308-CONC"},
        headers={**auth(keeper), "Idempotency-Key": _idem()},
    )
    assert res.status_code == 201, res.text
    type_id = next(
        t["id"]
        for t in (await live.get("/api/v1/inventory/batteries/types", headers=auth(keeper))).json()
        if t["code"] == BATTERY
    )

    batches = []
    for lot in lots:
        res = await live.post(
            "/api/v1/servicing/batches",
            json={"technician_id": str(tech), "lines": [{"lot_id": str(lot), "qty": 4}]},
            headers={**auth(coordinator), "Idempotency-Key": _idem()},
        )
        assert res.status_code == 201, res.text
        batches.append(res.json())

    def receive(batch: dict[str, Any]) -> Any:
        return live.post(
            f"/api/v1/servicing/batches/{batch['id']}/receive",
            json={
                "lines": [
                    {
                        "batch_line_id": batch["lines"][0]["id"],
                        "qty_receiving": 4,
                        "battery_check_code": "BATTERY_REPLACED",
                        "pieces_checked": 4,
                        "batteries_installed": 4,
                        "battery_type_id": type_id,
                        "allocations": {"FUNCTIONAL_REPAIRED": 4},
                    }
                ]
            },
            headers={**auth(coordinator), "Idempotency-Key": _idem()},
        )

    # 5 batteries, two receives of 4 each at the same time: one wins, one is refused (G-16).
    results = await asyncio.gather(*(receive(b) for b in batches))
    assert sorted(r.status_code for r in results) == [200, 409], [r.text for r in results]

    with committed.connect() as conn:
        bal = conn.execute(
            text(
                """select coalesce(sum(b.qty), 0) from public.stock_balances b
                     join public.stock_lots l on l.id = b.lot_id
                     join public.stock_items si on si.id = l.stock_item_id
                     join public.battery_types bt on bt.id = si.battery_type_id
                    where bt.code = :c"""
            ),
            {"c": BATTERY},
        ).scalar_one()
        installed = conn.execute(
            text(
                """select coalesce(sum(r.batteries_installed), 0)
                     from public.technician_receiving_records r
                     join public.battery_types bt on bt.id = r.battery_type_id
                    where bt.code = :c"""
            ),
            {"c": BATTERY},
        ).scalar_one()
        consumed = conn.execute(
            text(
                """select coalesce(sum(m.qty), 0) from public.stock_movements m
                     join public.stock_lots l on l.id = m.lot_id
                     join public.stock_items si on si.id = l.stock_item_id
                     join public.battery_types bt on bt.id = si.battery_type_id
                    where bt.code = :c and m.movement_type = 'CONSUME'"""
            ),
            {"c": BATTERY},
        ).scalar_one()
    assert (bal, installed, consumed) == (1, 4, 4)


async def test_simultaneous_cn_issue_with_the_same_number(
    live: AsyncClient, committed: Engine, make_token: JwtFactory
) -> None:
    with committed.begin() as conn:
        accounts = _user(conn, "ACCOUNTS")
        conn.execute(text("set local session_replication_role = replica"))  # fixture end-state
        wv = conn.execute(
            text(
                "select id from public.workflow_versions where status = 'PUBLISHED' "
                "order by version_no desc limit 1"
            )
        ).scalar_one()
        gs = conn.execute(
            text(
                """insert into public.goods_slips (gs_no, party_id, workflow_version_id,
                       delivery_mode_code, courier_name, docket_no, box_count, carton_count,
                       status, category_code, original_category_code)
                   values (:no, (select id from public.parties order by created_at limit 1), :wv,
                           'COURIER_PARCEL', 'BlueDart', 'DKT-P308C', 1, 1,
                           'COMMERCIAL_RESOLUTION', 'RO', 'RO') returning id"""
            ),
            {"no": f"GS-{TAG.upper()}-{uuid.uuid4().hex[:6].upper()}", "wv": wv},
        ).scalar_one()
        product = conn.execute(
            text(
                """insert into public.products (code, name, category_id)
                   select :c, 'P308 CN product', id from public.product_categories
                    where code = 'DMT' returning id, category_id"""
            ),
            {"c": f"{TAG.upper()}-{uuid.uuid4().hex[:6].upper()}"},
        ).one()
        item = conn.execute(
            text(
                """insert into public.gs_items (gs_id, line_no, product_id, category_id,
                       documented_qty, received_qty) values (:g, 1, :p, :c, 2, 2) returning id"""
            ),
            {"g": gs, "p": product.id, "c": product.category_id},
        ).scalar_one()
        decision = conn.execute(
            text(
                "insert into public.rm_cn_decisions (gs_id, decision_by, is_current) "
                "values (:g, :u, true) returning id"
            ),
            {"g": gs, "u": accounts},
        ).scalar_one()
        conn.execute(
            text(
                "insert into public.rm_cn_decision_lines (decision_id, gs_item_id, "
                "decision_code, qty) values (:d, :i, 'ALLOW_CN', 2)"
            ),
            {"d": decision, "i": item},
        )
        cns = []
        for _ in range(2):
            cn = conn.execute(
                text(
                    """insert into public.credit_notes (gs_id, cn_type_code, gst_portal_code,
                           status, created_by)
                       values (:g, 'GENERAL_CN', 'GST_REFLECTED', 'DRAFT', :u) returning id"""
                ),
                {"g": gs, "u": accounts},
            ).scalar_one()
            line = conn.execute(
                text(
                    """insert into public.credit_note_lines (credit_note_id, gs_item_id, line_no,
                           qty, rate) values (:cn, :i, 1, 1, 100) returning id"""
                ),
                {"cn": cn, "i": item},
            ).scalar_one()
            conn.execute(
                text(
                    """insert into public.rate_verifications (credit_note_line_id,
                           reference_code, ref_doc_no, ref_doc_date, rate, verified_by)
                       values (:l, 'RATE_SALES', 'SI-P308C', current_date, 100, :u)"""
                ),
                {"l": line, "u": accounts},
            )
            cns.append(cn)
    token = make_token(accounts)
    number = f"CN-P308C-{uuid.uuid4().hex[:6]}"

    def issue(cn: Any) -> Any:
        return live.post(
            f"/api/v1/credit-notes/{cn}/issue",
            json={"cn_no": number, "cn_date": "2026-11-05"},
            headers={**auth(token), "Idempotency-Key": _idem()},
        )

    results = await asyncio.gather(*(issue(cn) for cn in cns))
    codes = sorted(r.status_code for r in results)
    assert codes == [200, 409], [r.text for r in results]
    loser = next(r for r in results if r.status_code == 409)
    assert loser.json()["error"]["code"] == "VOUCHER_NUMBER_TAKEN"
    with committed.connect() as conn:
        rows = conn.execute(
            text("select status, cn_no from public.credit_notes where gs_id = :g order by status"),
            {"g": gs},
        ).all()
    assert sorted((r.status, r.cn_no) for r in rows) == [("DRAFT", None), ("ISSUED", number)]
