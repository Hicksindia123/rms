"""P2-08 · Phase 2 gate: configuration changes mid-flight are history-safe (G-18, rule e, U-02).

Scenario: GS-A is graded under S1_INSPECT_DMT v1. The Super Admin then relabels the DMT_DIRTY
condition and publishes S1_INSPECT_DMT v2, and also publishes a new workflow version. GS-A keeps the
original labels, its form version and its workflow version, and can still be completed; GS-B,
graded after the publish, shows the new label under v2; a GS created after the workflow publish
is pinned to the new workflow version.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import Connection

from tests.integration.conftest import fetch_all
from tests.integration.phase2_gate.helpers import (
    Admin,
    Products,
    finalise,
    grade,
    gs_at,
)
from tests.integration.test_gate_inward import Masters, _auth, _create, _values
from tests.integration.test_unboxing import Actors, FakeStorage

pytestmark = pytest.mark.asyncio

ORIGINAL = "DIRTY"
RELABELLED = "DIRTY - needs cleaning (P2-08 relabel)"


def published_form(conn: Connection, code: str) -> dict[str, Any]:
    return fetch_all(
        conn,
        """select v.id::text as id, v.version_no from public.form_versions v
             join public.form_definitions d on d.id = v.form_definition_id
            where d.code = :c and v.status = 'PUBLISHED'""",
        c=code,
    )[0]


def published_workflow(conn: Connection) -> str:
    return str(
        fetch_all(
            conn,
            """select v.id::text as id from public.workflow_versions v
                 join public.workflow_definitions d on d.id = v.workflow_definition_id
                where d.code = 'RMS_STANDARD' and v.status = 'PUBLISHED'""",
        )[0]["id"]
    )


def pins(conn: Connection, gs_id: str) -> dict[str, Any]:
    return fetch_all(
        conn,
        """select g.workflow_version_id::text as workflow_version_id,
                  i.form_version_id::text as form_version_id
             from public.goods_slips g
             join public.gs_items gi on gi.gs_id = g.id
             left join public.inspections i on i.gs_item_id = gi.id
            where g.id = :g""",
        g=gs_id,
    )[0]


async def labels_for(client: AsyncClient, token: str, gs_id: str) -> tuple[str, str]:
    """(DMT_DIRTY label in the condition picker, label of the recorded DMT_DIRTY allocation)."""
    res = await client.get(f"/api/v1/gs/{gs_id}/inspection", headers=_auth(token))
    assert res.status_code == 200, res.text
    line = res.json()["lines"][0]
    option = next(o["label"] for o in line["condition_options"] if o["code"] == "DMT_DIRTY")
    allocation = next(a["label"] for a in line["allocations"] if a["condition_code"] == "DMT_DIRTY")
    return option, allocation


async def test_relabel_and_new_versions_mid_flight_keep_history(
    client: AsyncClient,
    db_conn: Connection,
    storage: FakeStorage,
    actors: Actors,
    admin: Admin,
    masters: Masters,
    products: Products,
) -> None:
    v1 = published_form(db_conn, "S1_INSPECT_DMT")
    wf_v1 = published_workflow(db_conn)

    # --- GS-A in flight under v1 ---------------------------------------------------------------
    gs_a, items_a = await gs_at(client, storage, actors, masters, [(products.dmt, 6, 6)])
    res = await grade(
        client, actors.aman, items_a[0], {"DMT_OK_PACKED": 4, "DMT_DIRTY": 2}, packaging=6
    )
    assert res.status_code == 200, res.text
    assert pins(db_conn, gs_a) == {"workflow_version_id": wf_v1, "form_version_id": v1["id"]}
    assert await labels_for(client, actors.aman, gs_a) == (ORIGINAL, ORIGINAL)

    # --- Admin relabels the condition and publishes S1_INSPECT_DMT v2 --------------------------
    dmt = (
        await client.get("/api/v1/config/option-sets/DMT_CONDITION", headers=_auth(admin.token))
    ).json()
    item = next(i for i in dmt["items"] if i["code"] == "DMT_DIRTY")
    res = await client.put(
        f"/api/v1/config/option-sets/{dmt['id']}/items/{item['id']}",
        json={"label": RELABELLED},
        headers=_auth(admin.token),
    )
    assert res.status_code == 200, res.text
    assert (
        await client.post("/api/v1/config/forms/S1_INSPECT_DMT/draft", headers=_auth(admin.token))
    ).status_code == 200
    res = await client.post(
        "/api/v1/config/forms/S1_INSPECT_DMT/draft/publish",
        json={"version_notes": "P2-08 mid-flight relabel"},
        headers=_auth(admin.token),
    )
    assert res.status_code == 200, res.text
    v2 = published_form(db_conn, "S1_INSPECT_DMT")
    assert v2["version_no"] == v1["version_no"] + 1 and v2["id"] != v1["id"]

    # GS-A still shows the labels it was graded under (picker and recorded allocation).
    assert await labels_for(client, actors.aman, gs_a) == (ORIGINAL, ORIGINAL)

    # --- GS-B graded after the publish shows the new label under v2 ----------------------------
    gs_b, items_b = await gs_at(client, storage, actors, masters, [(products.dmt, 3, 3)])
    res = await grade(
        client, actors.aman, items_b[0], {"DMT_OK_PACKED": 2, "DMT_DIRTY": 1}, packaging=3
    )
    assert res.status_code == 200, res.text
    assert pins(db_conn, gs_b)["form_version_id"] == v2["id"]
    assert await labels_for(client, actors.aman, gs_b) == (RELABELLED, RELABELLED)

    # --- Admin publishes a new workflow version mid-flight -------------------------------------
    assert (
        await client.post("/api/v1/config/workflow/RMS_STANDARD/draft", headers=_auth(admin.token))
    ).status_code == 200
    res = await client.post(
        "/api/v1/config/workflow/RMS_STANDARD/draft/publish",
        json={"reason": "P2-08 mid-flight workflow publish"},
        headers=_auth(admin.token),
    )
    assert res.status_code == 200, res.text
    wf_v2 = published_workflow(db_conn)
    assert wf_v2 != wf_v1

    # GS-A completes under its pins; its recorded labels and versions are unchanged.
    res = await finalise(client, actors.aman, items_a[0])
    assert res.status_code == 200, res.text
    assert pins(db_conn, gs_a) == {"workflow_version_id": wf_v1, "form_version_id": v1["id"]}
    assert await labels_for(client, actors.aman, gs_a) == (ORIGINAL, ORIGINAL)
    snap = fetch_all(
        db_conn,
        """select a.label_snapshot from public.inspection_allocations a
             join public.inspections i on i.id = a.inspection_id
            where i.gs_item_id = :i and a.condition_code = 'DMT_DIRTY'""",
        i=items_a[0],
    )
    assert snap == [{"label_snapshot": ORIGINAL}]
    assert pins(db_conn, gs_b)["workflow_version_id"] == wf_v1

    # A GS created after the workflow publish is pinned to the new version and works.
    res = await _create(client, actors.gate, masters, _values())
    assert res.status_code == 201, res.text
    gs_c = res.json()["goods_slip"]["id"]
    assert fetch_all(
        db_conn,
        "select workflow_version_id::text as v from public.goods_slips where id = :g",
        g=gs_c,
    ) == [{"v": wf_v2}]
    res = await client.post(f"/api/v1/gs/{gs_c}/unboxing/start", headers=_auth(actors.aman))
    assert res.status_code == 200, res.text

    # The v1 snapshot itself still carries the original label (G-18 immutability).
    frozen = fetch_all(
        db_conn,
        """select o ->> 'label' as label from public.form_versions v,
                  lateral jsonb_array_elements(v.snapshot -> 'fields') f,
                  lateral jsonb_array_elements(coalesce(f -> 'option_items', '[]'::jsonb)) o
            where v.id = cast(:v as uuid) and o ->> 'code' = 'DMT_DIRTY'""",
        v=v1["id"],
    )
    assert frozen == [{"label": ORIGINAL}]
