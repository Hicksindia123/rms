"""Change plan 2026-11-12, Phase 3: Carton Opening & Counting.

Source: docs/RMS_MASTER_PLAN_ADDENDUM_2026-11.md. AMD-08 labels (Carton Opening / Counting /
Categorisation, codes unchanged), G-02 one video per carton with carton-wise progress (AMD-03),
carton-opening document rows (AMD-04) and the Accounts alert without duplicates (AMD-05),
Counting draft -> submit -> CATEGORISATION (BR-07, G-01, G-03, G-16). Status list confirmed by
the user on 2026-11-13.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError

from tests.integration.conftest import as_admin, fetch_all, force_gs_status
from tests.integration.phase2_gate.helpers import Products
from tests.integration.test_gate_inward import Masters, _auth, _create, _values
from tests.integration.test_itemization import (
    add_line,
    categorize,
    itemizing_gs,
    key,
    submit_counting,
)
from tests.integration.test_unboxing import Actors, FakeStorage, started_gs, upload


def _alerts(conn: Connection, user_id: uuid.UUID, gs_id: str) -> list[str]:
    rows = fetch_all(
        conn,
        """select title from public.notifications
            where user_id = :u and entity_id = :g and type = 'GS_DOCUMENT_FOUND'
            order by created_at""",
        u=user_id,
        g=gs_id,
    )
    return [str(r["title"]) for r in rows]


async def _carton_doc(
    client: AsyncClient, token: str, gs_id: str, body: dict[str, Any], idem: str | None = None
) -> Any:
    return await client.post(
        f"/api/v1/gs/{gs_id}/carton-documents", json=body, headers=_auth(token, idem or key())
    )


# =================================================================================================
# AMD-08 labels from configuration
# =================================================================================================
async def test_status_and_step_labels_come_from_config(
    client: AsyncClient, actors: Actors, masters: Masters
) -> None:
    res = await client.get("/api/v1/gs/lookups/statuses", headers=_auth(actors.aman))
    assert res.status_code == 200, res.text
    labels = {r["code"]: r["label"] for r in res.json()}
    assert labels["UNBOXING"] == "Carton Opening"
    assert labels["ITEMIZATION"] == "Counting"
    assert labels["CATEGORISATION"] == "Categorisation"
    assert labels["HELD_AT_INTERMEDIATE_STORE"] == "Held at Intermediate Store"
    assert len(labels) == 13

    # Workflow v2 (G-18: codes unchanged): the open S1_UNBOX task shows the new step label.
    gs = (await _create(client, actors.gate, masters, _values())).json()["goods_slip"]
    tasks = await client.get(
        "/api/v1/tasks/mine", params={"step_code": "S1_UNBOX"}, headers=_auth(actors.aman)
    )
    mine = next(t for t in tasks.json()["items"] if t["gs_id"] == gs["id"])
    assert mine["step_label"] == "Step-2 Carton Opening"
    assert mine["carton_count"] == 3


# =================================================================================================
# Carton Opening: carton-wise progress and document rows
# =================================================================================================
async def test_carton_progress(
    client: AsyncClient, actors: Actors, masters: Masters, storage: FakeStorage
) -> None:
    gs_id = await started_gs(client, actors, masters)  # 3 cartons
    state = (await client.get(f"/api/v1/gs/{gs_id}/unboxing", headers=_auth(actors.aman))).json()
    assert (state["checklist"]["carton_count"], state["checklist"]["cartons_with_video"]) == (3, 0)
    assert state["goods_slip"]["carton_count"] == 3
    await upload(client, storage, actors.aman, gs_id, "UNBOXING_VIDEO", "video/mp4", box_no=2)
    state = (await client.get(f"/api/v1/gs/{gs_id}/unboxing", headers=_auth(actors.aman))).json()
    assert state["checklist"]["cartons_with_video"] == 1
    assert state["checklist"]["boxes_missing_video"] == [1, 3]
    # The gate document row and the configured row types are part of the state (AMD-04).
    assert [d["doc_type_code"] for d in state["gate_documents"]] == ["INVOICE"]
    assert "COURIER_SLIP" in {t["code"] for t in state["document_types"]}


async def test_carton_documents_and_accounts_alert_without_duplicates(
    client: AsyncClient,
    actors: Actors,
    masters: Masters,
    storage: FakeStorage,
    db_conn: Connection,
) -> None:
    gs_id = await started_gs(client, actors, masters)  # gate: INVOICE INV-77 (alerted at gate)
    assert len(_alerts(db_conn, actors.accounts_id, gs_id)) == 1

    slip = await _carton_doc(
        client, actors.aman, gs_id, {"doc_type_code": "COURIER_SLIP", "doc_no": "AWB-1"}
    )
    assert slip.status_code == 201, slip.text
    assert slip.json()["source_step"] == "S1_UNBOX"
    assert len(_alerts(db_conn, actors.accounts_id, gs_id)) == 1  # not an alert type

    # The gate invoice found again in a carton: no second alert for the same document.
    again = await _carton_doc(
        client,
        actors.aman,
        gs_id,
        {"doc_type_code": "INVOICE", "doc_no": " inv-77 ", "doc_date": "2026-10-30"},
    )
    assert again.status_code == 201, again.text
    assert again.json()["accounts_alerted_at"] is not None
    assert len(_alerts(db_conn, actors.accounts_id, gs_id)) == 1

    # A new debit note alerts at once; the same Idempotency-Key replays without a second row.
    idem = key()
    body = {"doc_type_code": "DEBIT_NOTE", "doc_no": "DN-9", "doc_date": "2026-10-29"}
    first = await _carton_doc(client, actors.aman, gs_id, body, idem)
    second = await _carton_doc(client, actors.aman, gs_id, body, idem)
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    titles = _alerts(db_conn, actors.accounts_id, gs_id)
    # Both alerts share one test transaction (same created_at): check content, not order.
    assert len(titles) == 2
    assert sum("at carton opening" in t for t in titles) == 1

    # Changing the courier slip into an invoice alerts once.
    res = await client.patch(
        f"/api/v1/gs/{gs_id}/carton-documents/{slip.json()['id']}",
        json={"doc_type_code": "INVOICE", "doc_no": "INV-NEW", "doc_date": "2026-10-31"},
        headers=_auth(actors.aman),
    )
    assert res.status_code == 200, res.text
    assert len(_alerts(db_conn, actors.accounts_id, gs_id)) == 3

    # Validation, stage ownership, role.
    res = await _carton_doc(client, actors.aman, gs_id, {"doc_type_code": "INVOICE"})
    assert res.status_code == 422 and "documents.0.doc_no" in res.json()["error"]["details"]
    state = (await client.get(f"/api/v1/gs/{gs_id}/unboxing", headers=_auth(actors.aman))).json()
    gate_row = next(d for d in state["gate_documents"] if d["source_step"] == "S1_GATE")
    res = await client.delete(
        f"/api/v1/gs/{gs_id}/carton-documents/{gate_row['id']}", headers=_auth(actors.aman)
    )
    assert res.status_code == 409 and res.json()["error"]["code"] == "NOT_A_CARTON_DOCUMENT"
    res = await _carton_doc(client, actors.gate, gs_id, {"doc_type_code": "COURIER_SLIP"})
    assert res.status_code == 403

    # Files of a carton row: S1_UNBOX performer, not the gate user.
    url = f"/api/v1/gs/{gs_id}/gate-documents/{first.json()['id']}/files/upload-url"
    file_body = {"mime_type": "image/png", "size_bytes": 10, "file_name": "dn.png"}
    res = await client.post(url, json=file_body, headers=_auth(actors.gate))
    assert res.status_code == 403
    res = await client.post(url, json=file_body, headers=_auth(actors.aman))
    assert res.status_code == 201, res.text
    up = res.json()
    storage.put(up["upload"]["bucket"], up["upload"]["object_path"], 10, "image/png")
    res = await client.post(
        f"/api/v1/attachments/{up['attachment']['id']}/confirm", json={}, headers=_auth(actors.aman)
    )
    assert res.status_code == 200, res.text

    # Removing a carton row (with its file) while the GS is still being opened.
    res = await client.delete(
        f"/api/v1/gs/{gs_id}/carton-documents/{first.json()['id']}", headers=_auth(actors.aman)
    )
    assert res.status_code == 204, res.text


async def test_carton_documents_need_carton_opening(
    client: AsyncClient, actors: Actors, masters: Masters
) -> None:
    gs = (await _create(client, actors.gate, masters, _values())).json()["goods_slip"]
    res = await _carton_doc(client, actors.aman, gs["id"], {"doc_type_code": "COURIER_SLIP"})
    assert res.status_code == 409 and res.json()["error"]["code"] == "GS_NOT_UNBOXING"
    no_doc = await started_gs(client, actors, masters, doc="NO_DOCUMENT")
    res = await _carton_doc(client, actors.aman, no_doc, {"doc_type_code": "COURIER_SLIP"})
    assert res.status_code == 409 and res.json()["error"]["code"] == "GS_NO_DOCUMENT"


# =================================================================================================
# Counting: draft -> submit -> CATEGORISATION -> categorise
# =================================================================================================
async def test_counting_draft_submit_and_categorise(
    client: AsyncClient,
    actors: Actors,
    masters: Masters,
    storage: FakeStorage,
    products: Products,
    db_conn: Connection,
) -> None:
    gs_id = await itemizing_gs(client, storage, actors, masters)
    # The documented qty is optional at counting.
    res = await client.post(
        f"/api/v1/gs/{gs_id}/items",
        json={"product_id": products.dmt, "received_qty": 4},
        headers=_auth(actors.aman),
    )
    assert res.status_code == 201, res.text
    assert (res.json()["documented_qty"], res.json()["received_qty"]) == (0, 4)

    # Categorising before the count is submitted is refused (AMD-08), also for a Super Admin.
    res = await categorize(client, actors.admin, gs_id, "RO", submit=False)
    assert res.status_code == 409 and res.json()["error"]["code"] == "COUNTING_NOT_SUBMITTED"

    idem = key()
    first = await client.post(
        f"/api/v1/gs/{gs_id}/counting/submit", headers=_auth(actors.aman, idem)
    )
    replay = await client.post(
        f"/api/v1/gs/{gs_id}/counting/submit", headers=_auth(actors.aman, idem)
    )
    assert first.status_code == replay.status_code == 200, first.text
    assert replay.headers.get("Idempotency-Replayed") == "true"
    state = first.json()
    assert state["goods_slip"]["status"] == "CATEGORISATION"
    assert state["permissions"]["can_edit_lines"] is False
    assert state["permissions"]["can_categorize"] is True
    res = await submit_counting(client, actors.aman, gs_id)
    assert res.status_code == 409 and res.json()["error"]["code"] == "COUNTING_ALREADY_SUBMITTED"
    hist = fetch_all(
        db_conn,
        "select to_status, step_code from public.gs_status_history where gs_id = :g "
        "order by at desc limit 1",
        g=gs_id,
    )
    assert hist == [{"to_status": "CATEGORISATION", "step_code": "S1_ITEMIZE"}]

    # Lines are frozen once the count is submitted.
    res = await add_line(client, actors.aman, gs_id, products.dmt, 1, 1)
    assert res.status_code == 409

    res = await categorize(client, actors.aman, gs_id, "RO", submit=False)
    assert res.status_code == 200, res.text
    assert res.json()["state"]["goods_slip"]["status"] == "INSPECTION"


async def test_counting_product_search_by_category_and_subcategory(
    client: AsyncClient, actors: Actors, db_conn: Connection
) -> None:
    c = as_admin(db_conn)
    tag = uuid.uuid4().hex[:6].upper()
    cat_id = c.execute(
        text("select id from public.product_categories where code = 'DMT'")
    ).scalar_one()
    sub_id = c.execute(
        text(
            "insert into public.product_subcategories (category_id, code, name) "
            "values (:c, :code, :name) returning id"
        ),
        {"c": cat_id, "code": f"SUB_{tag}", "name": f"Pocket Digital {tag}"},
    ).scalar_one()
    prod_id = c.execute(
        text(
            "insert into public.products (code, name, category_id, subcategory_id) "
            "values (:code, :name, :c, :s) returning id"
        ),
        {"code": f"P-{tag}", "name": f"Thermo {tag}", "c": cat_id, "s": sub_id},
    ).scalar_one()

    by_sub_name = await client.get(
        "/api/v1/itemization/lookups/products",
        params={"q": f"Pocket Digital {tag}"},
        headers=_auth(actors.aman),
    )
    assert [p["id"] for p in by_sub_name.json()] == [str(prod_id)]
    assert by_sub_name.json()[0]["subcategory_name"] == f"Pocket Digital {tag}"
    filtered = await client.get(
        "/api/v1/itemization/lookups/products",
        params={"subcategory_id": str(sub_id)},
        headers=_auth(actors.aman),
    )
    assert [p["id"] for p in filtered.json()] == [str(prod_id)]
    other_cat = await client.get(
        "/api/v1/itemization/lookups/products",
        params={"q": tag, "category_id": str(uuid.uuid4())},
        headers=_auth(actors.aman),
    )
    assert other_cat.json() == []
    cats = await client.get("/api/v1/itemization/lookups/categories", headers=_auth(actors.aman))
    dmt = next(x for x in cats.json() if x["code"] == "DMT")
    assert str(sub_id) in {s["id"] for s in dmt["subcategories"]}


# =================================================================================================
# DB layer: G-03 / G-01 order without the service
# =================================================================================================
async def test_db_counting_order(
    client: AsyncClient,
    actors: Actors,
    masters: Masters,
    storage: FakeStorage,
    products: Products,
    db_conn: Connection,
) -> None:
    gs_id = await itemizing_gs(client, storage, actors, masters)
    conn = as_admin(db_conn)
    with pytest.raises(DBAPIError, match="G-01: counting cannot be submitted"), conn.begin_nested():
        conn.execute(
            text("update public.goods_slips set status = 'CATEGORISATION' where id = :g"),
            {"g": gs_id},
        )
    assert (await add_line(client, actors.aman, gs_id, products.dmt, 2, 2)).status_code == 201
    with pytest.raises(DBAPIError, match="G-03: counting is submitted"), conn.begin_nested():
        conn.execute(
            text(
                "update public.goods_slips set category_code = 'RO', status = 'INSPECTION' "
                "where id = :g"
            ),
            {"g": gs_id},
        )
    other = await started_gs(client, actors, masters)
    force_gs_status(conn, other, "INSPECTION")
    with pytest.raises(DBAPIError, match="only a GS in counting"), conn.begin_nested():
        conn.execute(
            text("update public.goods_slips set status = 'CATEGORISATION' where id = :g"),
            {"g": other},
        )
    with conn.begin_nested():
        conn.execute(
            text("update public.goods_slips set status = 'CATEGORISATION' where id = :g"),
            {"g": gs_id},
        )
    with pytest.raises(DBAPIError, match="cannot be added or removed"), conn.begin_nested():
        conn.execute(text("delete from public.gs_items where gs_id = :g"), {"g": gs_id})
    with pytest.raises(DBAPIError, match="without a category"), conn.begin_nested():
        conn.execute(
            text("update public.goods_slips set status = 'INSPECTION' where id = :g"), {"g": gs_id}
        )
