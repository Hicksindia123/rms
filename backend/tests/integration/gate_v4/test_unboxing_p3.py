"""Phase P3 (docs/RMS_PHASE_PROMPTS_20-11-2026.md) · DEC-62 · DEC-63 (user Q8 + Q25).

Step 2a on a gate v4 GS: Next (= complete carton opening) needs a confirmed video for every carton
and nothing else (no document photo, no RM Missing Document Exception, also when the GS is flagged
"No Documents From Party"); ONE optional "document found in carton" = a type from the active
GATE_DOCUMENT party types (not NO_DOCUMENT) + photos, no number / date / remarks; Invoice / GST
Debit Note alert Accounts (AMD-05). Service rules through the API, DB rules without the service.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError

from tests.integration.conftest import as_admin, fetch_all
from tests.integration.gate_v4.test_gate_v4 import Actors, _create, _values
from tests.integration.test_gate_inward import Masters, _auth
from tests.integration.test_itemization import key
from tests.integration.test_unboxing import FakeStorage, upload

pytestmark = pytest.mark.gate_v4


async def _unboxing_gs(
    client: AsyncClient,
    a: Actors,
    m: Masters,
    *,
    no_document: bool = False,
    documents: list[dict[str, Any]] | None = None,
) -> str:
    values = _values(no_document=True) if no_document else _values()
    res = await _create(client, a.gate, m, values, documents or [])
    assert res.status_code == 201, res.text
    gs_id = str(res.json()["goods_slip"]["id"])
    res = await client.post(f"/api/v1/gs/{gs_id}/unboxing/start", headers=_auth(a.aman))
    assert res.status_code == 200, res.text
    return gs_id


async def _videos(
    client: AsyncClient, storage: FakeStorage, token: str, gs_id: str, boxes: tuple[int, ...]
) -> None:
    for box in boxes:
        await upload(client, storage, token, gs_id, "UNBOXING_VIDEO", "video/mp4", box_no=box)


async def _complete(client: AsyncClient, token: str, gs_id: str) -> Any:
    return await client.post(f"/api/v1/gs/{gs_id}/unboxing/complete", headers=_auth(token))


async def _carton_doc(
    client: AsyncClient, token: str, gs_id: str, body: dict[str, Any], idem: str | None = None
) -> Any:
    return await client.post(
        f"/api/v1/gs/{gs_id}/carton-documents", json=body, headers=_auth(token, idem or key())
    )


def _alerts(conn: Connection, user_id: Any, gs_id: str) -> list[dict[str, Any]]:
    return fetch_all(
        conn,
        "select title from public.notifications where user_id = :u and entity_id = :g "
        "and type = 'GS_DOCUMENT_FOUND'",
        u=user_id,
        g=gs_id,
    )


# --- Next: a video per carton, nothing else (G-02, DEC-63) ----------------------------------------
async def test_next_blocked_until_every_carton_has_a_video(
    client: AsyncClient, actors: Actors, masters: Masters, storage: FakeStorage
) -> None:
    gs_id = await _unboxing_gs(client, actors, masters)  # 2 cartons, no documents
    res = await _complete(client, actors.aman, gs_id)
    assert res.status_code == 422 and res.json()["error"]["code"] == "G-02"
    await _videos(client, storage, actors.aman, gs_id, (1,))
    res = await _complete(client, actors.aman, gs_id)
    assert res.status_code == 422
    assert res.json()["error"]["details"]["missing"] == ["VIDEO_PER_CARTON"]
    assert res.json()["error"]["details"]["checklist"]["boxes_missing_video"] == [2]
    # Not bypassable by a Super Admin.
    res = await _complete(client, actors.admin, gs_id)
    assert res.status_code == 422 and res.json()["error"]["code"] == "G-02"

    await _videos(client, storage, actors.aman, gs_id, (2,))
    res = await _complete(client, actors.aman, gs_id)
    assert res.status_code == 200, res.text  # no document, no exception
    assert res.json()["goods_slip"]["status"] == "ITEMIZATION"


async def test_no_documents_from_party_gs_needs_no_rm_approval(
    client: AsyncClient,
    actors: Actors,
    masters: Masters,
    storage: FakeStorage,
    db_conn: Connection,
) -> None:
    gs_id = await _unboxing_gs(client, actors, masters, no_document=True)
    state = (await client.get(f"/api/v1/gs/{gs_id}/unboxing", headers=_auth(actors.aman))).json()
    assert state["goods_slip"]["missing_documentation"] is True
    assert state["checklist"]["missing"] == ["UNBOXING_VIDEO", "VIDEO_PER_CARTON"]
    await _videos(client, storage, actors.aman, gs_id, (1, 2))
    res = await _complete(client, actors.aman, gs_id)
    assert res.status_code == 200, res.text
    assert res.json()["goods_slip"]["missing_documentation"] is True
    exc = fetch_all(
        db_conn, "select 1 from public.missing_doc_exceptions where gs_id = :g", g=gs_id
    )
    assert exc == []


# --- the one optional carton document (DEC-62) ----------------------------------------------------
async def test_carton_document_is_optional_typed_and_image_only(
    client: AsyncClient,
    actors: Actors,
    masters: Masters,
    storage: FakeStorage,
    db_conn: Connection,
) -> None:
    gs_id = await _unboxing_gs(client, actors, masters)
    state = (await client.get(f"/api/v1/gs/{gs_id}/unboxing", headers=_auth(actors.aman))).json()
    codes = {t["code"] for t in state["document_types"]}
    assert codes == {"INVOICE", "DEBIT_NOTE", "HANDWRITTEN_SLIP"}  # active party types (DEC-62)

    # Doc type validated against the option set; no number / date / remarks.
    for body, field in (
        ({"doc_type_code": "NO_DOCUMENT"}, "documents.0.doc_type_code"),
        ({"doc_type_code": "BOGUS"}, "documents.0.doc_type_code"),
        ({"doc_type_code": "DELIVERY_CHALLAN"}, "documents.0.doc_type_code"),  # inactive (v4)
        ({"doc_type_code": "INVOICE", "doc_no": "INV-1"}, "documents.0.doc_no"),
        ({"doc_type_code": "INVOICE", "doc_date": "2026-11-19"}, "documents.0.doc_date"),
        ({"doc_type_code": "HANDWRITTEN_SLIP", "remarks": "3 broken"}, "documents.0.remarks"),
    ):
        res = await _carton_doc(client, actors.aman, gs_id, body)
        assert res.status_code == 422, (body, res.text)
        assert field in res.json()["error"]["details"], (body, res.json())

    # A valid one, idempotent (G-16); an Invoice alerts Accounts once.
    idem = key()
    first = await _carton_doc(client, actors.aman, gs_id, {"doc_type_code": "INVOICE"}, idem)
    again = await _carton_doc(client, actors.aman, gs_id, {"doc_type_code": "INVOICE"}, idem)
    assert first.status_code == again.status_code == 201, first.text
    doc = first.json()
    assert doc["id"] == again.json()["id"]
    assert (doc["doc_source"], doc["source_step"]) == ("CARTON", "S1_UNBOX")
    assert doc["doc_no"] is None and doc["doc_date"] is None and doc["remarks"] is None
    alerts = _alerts(db_conn, actors.accounts_id, gs_id)
    assert len(alerts) == 1 and "at carton opening" in alerts[0]["title"]

    # Only one carton document per GS.
    res = await _carton_doc(client, actors.aman, gs_id, {"doc_type_code": "DEBIT_NOTE"})
    assert res.status_code == 409 and res.json()["error"]["code"] == "CARTON_DOCUMENT_EXISTS"

    # Any number of photos on it (S1_UNBOX performer).
    url = f"/api/v1/gs/{gs_id}/gate-documents/{doc['id']}/files/upload-url"
    for n in (1, 2):
        file_body = {"mime_type": "image/jpeg", "size_bytes": 10, "file_name": f"p{n}.jpg"}
        res = await client.post(url, json=file_body, headers=_auth(actors.aman))
        assert res.status_code == 201, res.text
        up = res.json()
        storage.put(up["upload"]["bucket"], up["upload"]["object_path"], 10, "image/jpeg")
        res = await client.post(
            f"/api/v1/attachments/{up['attachment']['id']}/confirm",
            json={},
            headers=_auth(actors.aman),
        )
        assert res.status_code == 200, res.text
    state = (await client.get(f"/api/v1/gs/{gs_id}/unboxing", headers=_auth(actors.aman))).json()
    carton = next(d for d in state["gate_documents"] if d["doc_source"] == "CARTON")
    assert len(carton["files"]) == 2

    # Change the type (no number allowed on edit either); a debit note alerts too.
    res = await client.patch(
        f"/api/v1/gs/{gs_id}/carton-documents/{doc['id']}",
        json={"doc_type_code": "DEBIT_NOTE", "doc_no": "DN-1"},
        headers=_auth(actors.aman),
    )
    assert res.status_code == 422
    res = await client.patch(
        f"/api/v1/gs/{gs_id}/carton-documents/{doc['id']}",
        json={"doc_type_code": "DEBIT_NOTE"},
        headers=_auth(actors.aman),
    )
    assert res.status_code == 200, res.text
    # AMD-05: a row is alerted once; this one was already reported as an Invoice.
    alerts = _alerts(db_conn, actors.accounts_id, gs_id)
    assert len(alerts) == 1 and not alerts[0]["title"].endswith("(-)")

    # Remove, then a new one may be added; the gate user cannot add one.
    res = await client.delete(
        f"/api/v1/gs/{gs_id}/carton-documents/{doc['id']}", headers=_auth(actors.aman)
    )
    assert res.status_code == 204, res.text
    res = await _carton_doc(client, actors.gate, gs_id, {"doc_type_code": "HANDWRITTEN_SLIP"})
    assert res.status_code == 403
    res = await _carton_doc(client, actors.aman, gs_id, {"doc_type_code": "HANDWRITTEN_SLIP"})
    assert res.status_code == 201, res.text

    # The document is optional and does not change G-02.
    await _videos(client, storage, actors.aman, gs_id, (1, 2))
    res = await _complete(client, actors.aman, gs_id)
    assert res.status_code == 200, res.text


async def test_carton_document_on_a_gs_without_party_documents(
    client: AsyncClient, actors: Actors, masters: Masters
) -> None:
    gs_id = await _unboxing_gs(client, actors, masters, no_document=True)
    res = await _carton_doc(client, actors.aman, gs_id, {"doc_type_code": "INVOICE"})
    assert res.status_code == 201, res.text
    state = (await client.get(f"/api/v1/gs/{gs_id}/unboxing", headers=_auth(actors.aman))).json()
    # BR-03: the gate flag stays as recorded (open question to the user, P3 report).
    assert state["goods_slip"]["missing_documentation"] is True


async def test_carton_document_only_while_unboxing(
    client: AsyncClient, actors: Actors, masters: Masters
) -> None:
    res = await _create(client, actors.gate, masters, _values())
    gs_id = res.json()["goods_slip"]["id"]
    res = await _carton_doc(client, actors.aman, gs_id, {"doc_type_code": "INVOICE"})
    assert res.status_code == 409 and res.json()["error"]["code"] == "GS_NOT_UNBOXING"


def test_db_carton_document_rules(db_conn: Connection) -> None:
    """DB without the service: one CARTON row per GS, image only (migration 20261120000300)."""
    conn = as_admin(db_conn)
    gs_id = conn.execute(
        text(
            """insert into public.goods_slips (gs_no, workflow_version_id, delivery_mode_code,
                      courier_name, docket_no, carton_count, missing_documentation)
               select 'PYT-P3-DB', v.id, 'COURIER_PARCEL', 'A', '1', 1, true
                 from public.workflow_versions v
                 join public.workflow_definitions d on d.id = v.workflow_definition_id
                where d.code = 'RMS_STANDARD' and v.status = 'PUBLISHED'
               returning id"""
        )
    ).scalar_one()
    conn.execute(
        text("update public.goods_slips set status = 'UNBOXING' where id = :g"), {"g": gs_id}
    )
    insert = text(
        """insert into public.gs_gate_documents
                  (gs_id, doc_type_code, doc_type_label, source_step, doc_source, doc_no)
           values (:g, :t, 'x', 'S1_UNBOX', 'CARTON', :n)"""
    )
    with pytest.raises(DBAPIError, match="v4_image_only"), conn.begin_nested():
        conn.execute(insert, {"g": gs_id, "t": "INVOICE", "n": "INV-1"})
    conn.execute(insert, {"g": gs_id, "t": "INVOICE", "n": None})  # flagged GS: allowed
    with pytest.raises(DBAPIError, match="one_carton_doc"), conn.begin_nested():
        conn.execute(insert, {"g": gs_id, "t": "DEBIT_NOTE", "n": None})
