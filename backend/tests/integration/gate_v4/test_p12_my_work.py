"""Phase P12 (docs/RMS_PHASE_PROMPTS_20-11-2026.md) · DEC-72: My Work counts per role on the
12-step offline flow.

The Accounts and Dispatch work queues (journeys repository, AMD-18 / AMD-19) were written before
the per-GS Accounts entry (DEC-71). A store-flow goods slip must show up in the Accounts Entry
queue while it is At Accounts, leave it when Accounts completes, and then show up in the Dispatch
queue; a goods slip on hold (Q21) is never in the Accounts queue.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import Connection

from tests.conftest import JwtFactory
from tests.integration.conftest import UserFactory
from tests.integration.gate_v4.test_gate_v4 import Actors
from tests.integration.gate_v4.test_p5_transfer_slips import mgmt, products, rm
from tests.integration.gate_v4.test_p7_store_routing import (
    StoreUsers,
    dec59,
    routing_products,
    stores,
)
from tests.integration.gate_v4.test_p9_store_analysis import _ready
from tests.integration.gate_v4.test_p11_accounts import (
    TODAY,
    _complete,
    _dt_submit,
    _entry,
    _op_submit,
    _save,
)
from tests.integration.test_gate_inward import Masters, _auth
from tests.integration.test_unboxing import FakeStorage

pytestmark = pytest.mark.gate_v4

# fixtures re-used from the P5 / P7 tests
__all__ = ["dec59", "mgmt", "products", "rm", "routing_products", "stores"]


@pytest.fixture
def accounts(users: UserFactory, make_token: JwtFactory) -> str:
    return make_token(users.create(roles=["ACCOUNTS"], full_name="Acc User"))


@pytest.fixture
def dispatcher(users: UserFactory, make_token: JwtFactory) -> str:
    return make_token(users.create(roles=["DISPATCH"], full_name="Dispatch User"))


async def _count(client: AsyncClient, token: str, step: str) -> int:
    body = (await client.get("/api/v1/me/journey", headers=_auth(token))).json()
    count: int = next(e for e in body["entries"] if e["code"] == step)["count"]
    return count


async def _queue(client: AsyncClient, token: str, step: str) -> set[str]:
    res = await client.get(f"/api/v1/me/journey/{step}", headers=_auth(token))
    assert res.status_code == 200, res.text
    items: list[dict[str, Any]] = res.json()["items"]
    return {i["gs_id"] for i in items}


async def test_accounts_and_dispatch_my_work_follow_the_store_flow(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    routing_products: dict[str, str],
    rm: str,
    stores: StoreUsers,
    accounts: str,
    dispatcher: str,
    db_conn: Connection,
) -> None:
    acc_before = await _count(client, accounts, "ACCOUNTS_ENTRY")
    dsp_before = await _count(client, dispatcher, "DISPATCH_SLIP")

    r = await _ready(client, storage, actors, masters, routing_products, rm, stores)
    await _dt_submit(client, stores, r, a={"SEND_NEW": 2}, b={"NOT_ALLOWED": 1})
    # One store still pending: nothing for Accounts yet.
    assert r.gs_id not in await _queue(client, accounts, "ACCOUNTS_ENTRY")
    done = await _op_submit(client, stores, r, SEND_REPAIRED=1)
    assert done["status"] == "ACCOUNTS_PENDING"

    # At Accounts: in the Accounts Entry queue, counted once.
    assert r.gs_id in await _queue(client, accounts, "ACCOUNTS_ENTRY")
    assert await _count(client, accounts, "ACCOUNTS_ENTRY") == acc_before + 1

    slip = (await _entry(client, accounts, r.gs_id)).json()["ac_action_slip_id"]
    saved = await _save(client, accounts, r.gs_id, slip, challan_no="CH-P12", challan_date=TODAY)
    assert saved.status_code == 200, saved.text
    res = await _complete(client, accounts, r.gs_id, slip)
    assert res.status_code == 200 and res.json()["gs_status"] == "DISPATCH_PENDING"

    # Completed: off the Accounts queue, on the Dispatch queue.
    assert r.gs_id not in await _queue(client, accounts, "ACCOUNTS_ENTRY")
    assert await _count(client, accounts, "ACCOUNTS_ENTRY") == acc_before
    assert r.gs_id in await _queue(client, dispatcher, "DISPATCH_SLIP")
    assert await _count(client, dispatcher, "DISPATCH_SLIP") == dsp_before + 1


async def test_goods_slip_on_hold_is_not_accounts_work(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    routing_products: dict[str, str],
    rm: str,
    stores: StoreUsers,
    accounts: str,
) -> None:
    before = await _count(client, accounts, "ACCOUNTS_ENTRY")
    r = await _ready(client, storage, actors, masters, routing_products, rm, stores)
    await _dt_submit(client, stores, r, a={"NOT_ALLOWED": 2}, b={"NOT_ALLOWED": 1})
    done = await _op_submit(client, stores, r, NOT_ALLOWED=1)
    assert done["status"] == "NOT_ALLOWED_HOLD"
    assert r.gs_id not in await _queue(client, accounts, "ACCOUNTS_ENTRY")
    assert await _count(client, accounts, "ACCOUNTS_ENTRY") == before
