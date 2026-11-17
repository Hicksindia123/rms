# ruff: noqa: F811  (pytest fixtures imported from the Phase 5 module are re-bound as parameters)
"""DEC-53: Counting & Categorisation merged into one step (AMD-08 + AMD-09, G-19, G-16, G-18).

The Inward Verifier records each line together with its condition split (buckets) while the GS is
ITEMIZATION; the split total must equal the physical qty. One submit runs
ITEMIZATION -> CATEGORISATION -> RM_REVIEW in a single transaction. After an RM send-back the GS is
in CATEGORISATION (lines locked, split-only edits) and the same submit returns it to RM_REVIEW.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import Connection, text

from tests.integration.conftest import as_admin
from tests.integration.test_categorisation_rm_review import (  # noqa: F401 (pytest fixtures)
    actors,
    client,
    masters,
    products,
    storage,
)
from tests.integration.test_gate_inward import Masters, _auth
from tests.integration.test_itemization import (
    Actors,
    FakeStorage,
    Products,
    add_line,
    itemizing_gs,
    key,
)

pytestmark = pytest.mark.asyncio


async def _bucket_codes(client: AsyncClient, token: str, product_id: str) -> list[str]:
    res = await client.get(
        f"/api/v1/itemization/lookups/products/{product_id}/fields", headers=_auth(token)
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["product_id"] == product_id
    codes = [b["field_code"] for b in body["allowed_buckets"]]
    assert len(codes) >= 2, "DMT needs at least two condition buckets for these tests"
    return codes


async def _add(
    client: AsyncClient,
    token: str,
    gs_id: str,
    product: str,
    doc: int,
    recv: int,
    buckets: list[dict[str, Any]],
    counts: list[dict[str, Any]] | None = None,
) -> Any:
    return await client.post(
        f"/api/v1/gs/{gs_id}/items",
        json={
            "product_id": product,
            "documented_qty": doc,
            "received_qty": recv,
            "buckets": buckets,
            "counts": counts or [],
        },
        headers=_auth(token),
    )


async def _submit(client: AsyncClient, token: str, gs_id: str, idem: str | None = None) -> Any:
    return await client.post(
        f"/api/v1/gs/{gs_id}/itemization/submit",
        json={"remarks": None},
        headers=_auth(token, idem or key()),
    )


async def _status(client: AsyncClient, token: str, gs_id: str) -> str:
    res = await client.get(f"/api/v1/gs/{gs_id}/itemization", headers=_auth(token))
    assert res.status_code == 200, res.text
    return str(res.json()["goods_slip"]["status"])


async def test_line_saved_with_split_and_one_submit_reaches_rm_review(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    products: Products,
    db_conn: Connection,
) -> None:
    gs_id = await itemizing_gs(client, storage, actors, masters)
    good, other = (await _bucket_codes(client, actors.aman, products.dmt))[:2]

    # 4 as per document, 3 physically received: 2 in one condition, 1 in another.
    res = await _add(
        client,
        actors.aman,
        gs_id,
        products.dmt,
        doc=4,
        recv=3,
        buckets=[{"field_code": good, "qty": 2}, {"field_code": other, "qty": 1}],
        counts=[{"count_type": "PACKAGING", "count_value": 3}],
    )
    assert res.status_code == 201, res.text
    line = res.json()
    assert line["is_balanced"] is True and line["bucket_total"] == 3
    assert {b["field_code"]: b["qty"] for b in line["buckets"]} == {good: 2, other: 1}
    assert [c["count_type"] for c in line["counts"]] == ["PACKAGING"]
    assert all(b["field_label"] for b in line["buckets"])  # G-18 label snapshot

    state = (await client.get(f"/api/v1/gs/{gs_id}/itemization", headers=_auth(actors.aman))).json()
    assert state["goods_slip"]["status"] == "ITEMIZATION"
    assert state["permissions"]["can_submit_to_rm"] is True
    assert state["items"][0]["is_balanced"] is True

    idem = key()
    sub = await _submit(client, actors.aman, gs_id, idem)
    assert sub.status_code == 200, sub.text
    assert sub.json()["status"] == "RM_REVIEW"

    # G-16: the same key replays the original result, nothing runs twice.
    again = await _submit(client, actors.aman, gs_id, idem)
    assert again.status_code == 200, again.text
    assert again.json() == sub.json()

    c = as_admin(db_conn)
    hops = c.execute(
        text(
            """select from_status, to_status from public.gs_status_history
                where gs_id = :g and to_status in ('CATEGORISATION', 'RM_REVIEW')
                order by "at", id"""
        ),
        {"g": gs_id},
    ).all()
    assert [tuple(h) for h in hops] == [
        ("ITEMIZATION", "CATEGORISATION"),
        ("CATEGORISATION", "RM_REVIEW"),
    ]
    inward = c.execute(
        text(
            """select coalesce(sum(m.qty), 0) from public.stock_movements m
                 join public.gs_items gi on gi.id = m.reference_id
                where gi.gs_id = :g and m.movement_type = 'INWARD'"""
        ),
        {"g": gs_id},
    ).scalar_one()
    assert int(inward) == 3  # DEC-28: only the physical qty is stocked, short qty never
    notified = c.execute(
        text(
            """select count(*) from public.notification_events
                where gs_id = :g and event_type = 'RM_REVIEW_REQUIRED'"""
        ),
        {"g": gs_id},
    ).scalar_one()
    assert int(notified) >= 1

    # The RM sees the split recorded at counting.
    rm = (await client.get(f"/api/v1/gs/{gs_id}/rm-review", headers=_auth(actors.rm))).json()
    assert rm["items"][0]["total_bucket_qty"] == 3


async def test_split_must_match_physical_qty_and_profile(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    products: Products,
) -> None:
    gs_id = await itemizing_gs(client, storage, actors, masters)
    good, _ = (await _bucket_codes(client, actors.aman, products.dmt))[:2]

    short = await _add(
        client, actors.aman, gs_id, products.dmt, 4, 4, [{"field_code": good, "qty": 3}]
    )
    assert short.status_code == 422, short.text
    assert short.json()["error"]["code"] == "BUCKET_TOTAL_MISMATCH"

    alien = await _add(
        client, actors.aman, gs_id, products.dmt, 1, 1, [{"field_code": "NOT_A_BUCKET", "qty": 1}]
    )
    assert alien.status_code == 422, alien.text
    assert alien.json()["error"]["code"] == "INVALID_FIELD"

    # Both refusals rolled back the line insert too: the GS has no lines.
    state = (await client.get(f"/api/v1/gs/{gs_id}/itemization", headers=_auth(actors.aman))).json()
    assert state["items"] == []
    assert state["permissions"]["can_submit_to_rm"] is False


async def test_edit_line_replaces_split_and_product_change_resets_it(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    products: Products,
) -> None:
    gs_id = await itemizing_gs(client, storage, actors, masters)
    good, other = (await _bucket_codes(client, actors.aman, products.dmt))[:2]
    line = (
        await _add(client, actors.aman, gs_id, products.dmt, 2, 2, [{"field_code": good, "qty": 2}])
    ).json()

    edited = await client.patch(
        f"/api/v1/gs/{gs_id}/items/{line['id']}",
        json={"received_qty": 3, "buckets": [{"field_code": other, "qty": 3}]},
        headers=_auth(actors.aman),
    )
    assert edited.status_code == 200, edited.text
    assert {b["field_code"]: b["qty"] for b in edited.json()["buckets"]} == {other: 3}

    # Changing the product drops the split (it belonged to the old product's profile).
    moved = await client.patch(
        f"/api/v1/gs/{gs_id}/items/{line['id']}",
        json={"product_id": products.prismatic},
        headers=_auth(actors.aman),
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["buckets"] == [] and moved.json()["is_balanced"] is False

    state = (await client.get(f"/api/v1/gs/{gs_id}/itemization", headers=_auth(actors.aman))).json()
    assert state["permissions"]["can_submit_to_rm"] is False

    # Deleting a line with a split works in ITEMIZATION (buckets cascade, DB guard allows it).
    deleted = await client.delete(
        f"/api/v1/gs/{gs_id}/items/{line['id']}", headers=_auth(actors.aman)
    )
    assert deleted.status_code == 204, deleted.text


async def test_unbalanced_line_blocks_submit_and_rolls_back_both_hops(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    products: Products,
) -> None:
    gs_id = await itemizing_gs(client, storage, actors, masters)
    # A line without a split (older API clients) cannot reach RM Review (G-19).
    assert (await add_line(client, actors.aman, gs_id, products.dmt, 2, 2)).status_code == 201
    res = await _submit(client, actors.aman, gs_id)
    assert res.status_code in (409, 422), res.text
    assert "G-19" in res.text
    # The counting hop was rolled back with it: still at Counting & Categorisation.
    assert await _status(client, actors.aman, gs_id) == "ITEMIZATION"

    empty = await itemizing_gs(client, storage, actors, masters)
    res = await _submit(client, actors.aman, empty)
    assert res.status_code == 422, res.text
    assert res.json()["error"]["code"] == "ITEMS_REQUIRED"  # G-01 / BR-07


async def test_send_back_is_split_only_then_same_submit_returns_to_rm(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    products: Products,
) -> None:
    gs_id = await itemizing_gs(client, storage, actors, masters)
    good, other = (await _bucket_codes(client, actors.aman, products.dmt))[:2]
    line = (
        await _add(client, actors.aman, gs_id, products.dmt, 3, 3, [{"field_code": good, "qty": 3}])
    ).json()
    assert (await _submit(client, actors.aman, gs_id)).status_code == 200

    back = await client.post(
        f"/api/v1/gs/{gs_id}/rm-send-back",
        json={"remarks": "One piece is scratched, re-check the condition"},
        headers=_auth(actors.rm, key()),
    )
    assert back.status_code == 200, back.text
    assert await _status(client, actors.aman, gs_id) == "CATEGORISATION"

    # Lines stay locked after a send-back (user decision): no new line.
    locked = await add_line(client, actors.aman, gs_id, products.dmt, 1, 1)
    assert locked.status_code == 409, locked.text

    fix = await client.put(
        f"/api/v1/gs/{gs_id}/items/{line['id']}/categorisation",
        json={
            "buckets": [{"field_code": good, "qty": 2}, {"field_code": other, "qty": 1}],
            "counts": [],
        },
        headers=_auth(actors.aman, key()),
    )
    assert fix.status_code == 200, fix.text
    res = await _submit(client, actors.aman, gs_id)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "RM_REVIEW"

    # Not at this step any more.
    late = await _submit(client, actors.aman, gs_id)
    assert late.status_code == 409, late.text
    assert late.json()["error"]["code"] == "GS_NOT_ITEMIZATION"
