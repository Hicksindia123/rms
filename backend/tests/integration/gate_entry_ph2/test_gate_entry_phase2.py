"""Change plan 2026-11-12 · Phase 2 — gate entry revamp (docs/RMS_MASTER_PLAN_ADDENDUM_2026-11.md).

AMD-01 return type · AMD-02 / DEC-38 gate entry date & number · DEC-39 E-Commerce without gate
entry · AMD-03 carton count and G-02 "one video per carton" · AMD-04 gate document rows with files
· AMD-05 configurable Accounts alert. Every rule is proven through the API (service) and, where it
is a DB rule, directly against the database without the service.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from tests.integration.conftest import as_admin, fetch_all, force_gs_status
from tests.integration.test_gate_inward import (
    Masters,
    _auth,
    _create,
    _payload,
    _values,
    business_today,
    gate_entry_no,
)
from tests.integration.test_unboxing import (
    INVOICE,
    Actors,
    FakeStorage,
    classify,
    complete,
    started_gs,
    upload,
)

COURIER = {"delivery_mode_code": "COURIER_PARCEL", "courier_name": "A", "docket_no": "1"}


def _setting(conn: Connection, key: str, value: str) -> None:
    as_admin(conn).execute(
        text("update public.system_settings set value = cast(:v as jsonb) where key = :k"),
        {"k": key, "v": value},
    )


def _alerts(conn: Connection, user_id: uuid.UUID, gs_id: str) -> list[dict[str, Any]]:
    return fetch_all(
        conn,
        """select title, priority from public.notifications
            where user_id = :u and entity_id = :g and type = 'GS_DOCUMENT_FOUND'
            order by created_at""",
        u=user_id,
        g=gs_id,
    )


# =================================================================================================
# AMD-01 / AMD-02 / DEC-38 / DEC-39 through the API
# =================================================================================================
async def test_gate_form_v2_exposes_types_and_limits(
    client: AsyncClient, actors: Actors, db_conn: Connection
) -> None:
    _setting(db_conn, "gate.max_backdate_days", "5")
    res = await client.get("/api/v1/gs/gate-form", headers=_auth(actors.gate))
    assert res.status_code == 200, res.text
    body = res.json()
    keys = [f["field_key"] for f in body["snapshot"]["fields"]]
    # AMD-01 / AMD-02: return type first, gate entry above state and station.
    assert keys[:5] == ["return_type", "gate_entry_date", "gate_entry_no", "state", "station"]
    assert "carton_count" in keys and "box_count" not in keys and "accompanying_doc" not in keys
    codes = {t["code"]: t for t in body["document_types"]}
    assert {"INVOICE", "DEBIT_NOTE", "DELIVERY_CHALLAN", "COURIER_SLIP", "LR_BILITY"} <= set(codes)
    assert "NO_DOCUMENT" not in codes  # DEC-03: a GS-level flag, not a row type
    assert codes["INVOICE"]["required_fields"] == ["doc_no", "doc_date"]
    assert codes["HANDWRITTEN_SLIP"]["required_fields"] == ["remarks"]
    assert body["max_backdate_days"] == 5
    assert body["business_today"] == business_today().isoformat()


async def test_ecommerce_return_has_no_gate_entry(
    client: AsyncClient, actors: Actors, masters: Masters
) -> None:
    # DEC-39: the gate entry fields are hidden for E-Commerce; values sent anyway are dropped.
    res = await _create(client, actors.gate, masters, _values(return_type="ECOMMERCE_RETURN"))
    assert res.status_code == 201, res.text
    gs = res.json()["goods_slip"]
    assert gs["return_type_code"] == "ECOMMERCE_RETURN"
    assert gs["return_type_label"] == "E-Commerce Return"  # configured label
    assert gs["gate_entry_date"] is None and gs["gate_entry_no"] is None


async def test_gate_entry_number_unique_per_financial_year(
    client: AsyncClient, actors: Actors, masters: Masters
) -> None:
    number = gate_entry_no()
    first = await _create(client, actors.gate, masters, _values(gate_entry_no=number))
    assert first.status_code == 201, first.text
    gs = first.json()["goods_slip"]
    assert gs["gate_entry_no"] == number and gs["return_type_code"] == "OFFLINE_RETURN"

    dup = await _create(client, actors.gate, masters, _values(gate_entry_no=number))
    assert dup.status_code == 409, dup.text
    assert dup.json()["error"]["code"] == "GATE_ENTRY_NO_TAKEN"
    assert gs["gs_no"] in dup.json()["error"]["details"]["gate_entry_no"][0]

    # Another financial year may reuse the number (back-dating has no lower limit by default).
    old = date(business_today().year - 2, 6, 1).isoformat()
    other_fy = await _create(
        client, actors.gate, masters, _values(gate_entry_no=number, gate_entry_date=old)
    )
    assert other_fy.status_code == 201, other_fy.text

    # A cancelled GS frees its number (DEC-38).
    res = await client.post(
        f"/api/v1/gs/{gs['id']}/cancel", json={"reason": "Wrong entry"}, headers=_auth(actors.admin)
    )
    assert res.status_code == 200, res.text
    again = await _create(client, actors.gate, masters, _values(gate_entry_no=number))
    assert again.status_code == 201, again.text


async def test_gate_entry_backdate_limit_setting(
    client: AsyncClient, actors: Actors, masters: Masters, db_conn: Connection
) -> None:
    today = business_today()
    _setting(db_conn, "gate.max_backdate_days", "5")
    too_old = (today - timedelta(days=10)).isoformat()
    res = await _create(client, actors.gate, masters, _values(gate_entry_date=too_old))
    assert res.status_code == 422, res.text
    assert "gate_entry_date" in res.json()["error"]["details"]
    ok = (today - timedelta(days=5)).isoformat()
    res = await _create(client, actors.gate, masters, _values(gate_entry_date=ok))
    assert res.status_code == 201, res.text
    res = await _create(client, actors.gate, masters, _values(gate_entry_date=today.isoformat()))
    assert res.status_code == 201, res.text


# =================================================================================================
# AMD-04 document rows, AMD-05 Accounts alert
# =================================================================================================
async def test_document_rows_and_accounts_alert_once_per_row(
    client: AsyncClient, actors: Actors, masters: Masters, db_conn: Connection
) -> None:
    values = _values()
    values.documents = [
        {"doc_type_code": "INVOICE", "doc_no": "INV-1", "doc_date": "2026-10-30"},
        {"doc_type_code": "DEBIT_NOTE", "doc_no": "DN-1", "doc_date": "2026-10-29"},
        {"doc_type_code": "COURIER_SLIP", "doc_no": "CS-1", "remarks": "AWB on box"},
    ]
    res = await _create(client, actors.gate, masters, values)
    assert res.status_code == 201, res.text
    gs = res.json()["goods_slip"]
    docs = gs["documents"]
    assert [d["doc_type_code"] for d in docs] == ["INVOICE", "DEBIT_NOTE", "COURIER_SLIP"]
    assert docs[2]["doc_type_label"] == "Courier Slip"  # G-18 label snapshot
    assert gs["missing_documentation"] is False

    alerts = _alerts(db_conn, actors.accounts_id, gs["id"])
    assert len(alerts) == 2 and {a["priority"] for a in alerts} == {"HIGH"}
    assert [d["accounts_alerted_at"] is not None for d in docs] == [True, True, False]

    # Edit at the gate: keep two rows (ids), drop the courier slip, add a second invoice.
    patch = {
        "party_id": str(masters.party),
        "values": values,
        "documents": [
            {
                "id": docs[0]["id"],
                "doc_type_code": "INVOICE",
                "doc_no": "INV-1",
                "doc_date": "2026-10-30",
            },
            {
                "id": docs[1]["id"],
                "doc_type_code": "DEBIT_NOTE",
                "doc_no": "DN-1B",
                "doc_date": "2026-10-29",
            },
            {"doc_type_code": "INVOICE", "doc_no": "INV-2", "doc_date": "2026-10-31"},
        ],
        "reason": "Second invoice found in the courier pouch",
    }
    res = await client.patch(f"/api/v1/gs/{gs['id']}/gate", json=patch, headers=_auth(actors.gate))
    assert res.status_code == 200, res.text
    edited = res.json()["goods_slip"]["documents"]
    assert [(d["doc_type_code"], d["doc_no"]) for d in edited] == [
        ("INVOICE", "INV-1"),
        ("DEBIT_NOTE", "DN-1B"),
        ("INVOICE", "INV-2"),
    ]
    assert edited[0]["id"] == docs[0]["id"] and edited[1]["id"] == docs[1]["id"]
    # AMD-05: only the new invoice raised an alert; kept rows never alert twice.
    assert len(_alerts(db_conn, actors.accounts_id, gs["id"])) == 3

    # A row of another GS cannot be smuggled into this one.
    other = (await _create(client, actors.gate, masters, _values())).json()["goods_slip"]
    patch["documents"] = [
        {
            "id": other["documents"][0]["id"],
            "doc_type_code": "INVOICE",
            "doc_no": "X",
            "doc_date": "2026-10-30",
        }
    ]
    res = await client.patch(f"/api/v1/gs/{gs['id']}/gate", json=patch, headers=_auth(actors.gate))
    assert res.status_code == 422, res.text


async def test_accounts_alert_document_types_are_configurable(
    client: AsyncClient, actors: Actors, masters: Masters, db_conn: Connection
) -> None:
    _setting(db_conn, "gate.accounts_alert_doc_types", '["COURIER_SLIP"]')
    slip = (await _create(client, actors.gate, masters, _values(doc="COURIER_SLIP"))).json()
    alerts = _alerts(db_conn, actors.accounts_id, slip["goods_slip"]["id"])
    assert len(alerts) == 1 and "Courier Slip" in alerts[0]["title"]
    invoice = (await _create(client, actors.gate, masters, _values())).json()
    assert _alerts(db_conn, actors.accounts_id, invoice["goods_slip"]["id"]) == []


async def test_no_document_flag_excludes_rows(
    client: AsyncClient, actors: Actors, masters: Masters
) -> None:
    both = _values(doc="NO_DOCUMENT")
    both.documents = [{"doc_type_code": "COURIER_SLIP", "doc_no": "1"}]
    res = await _create(client, actors.gate, masters, both)
    assert res.status_code == 422 and "documents" in res.json()["error"]["details"]
    neither = _values()
    neither.documents = []
    res = await _create(client, actors.gate, masters, neither)
    assert res.status_code == 422 and "documents" in res.json()["error"]["details"]


async def test_gate_document_files(
    client: AsyncClient,
    actors: Actors,
    masters: Masters,
    storage: FakeStorage,
    db_conn: Connection,
) -> None:
    gs = (await _create(client, actors.gate, masters, _values())).json()["goods_slip"]
    doc_id = gs["documents"][0]["id"]
    url = f"/api/v1/gs/{gs['id']}/gate-documents/{doc_id}/files/upload-url"

    async def add(mime: str, name: str) -> dict[str, Any]:
        res = await client.post(
            url,
            json={"mime_type": mime, "size_bytes": 2048, "file_name": name},
            headers=_auth(actors.gate),
        )
        assert res.status_code == 201, res.text
        up = res.json()
        assert up["attachment"]["kind"] == "GATE_DOC"
        assert up["attachment"]["gate_document_id"] == doc_id
        storage.put(up["upload"]["bucket"], up["upload"]["object_path"], 2048, mime)
        res = await client.post(
            f"/api/v1/attachments/{up['attachment']['id']}/confirm",
            json={},
            headers=_auth(actors.gate),
        )
        assert res.status_code == 200, res.text
        return dict(res.json())

    photo = await add("image/png", "invoice.png")
    pdf = await add("application/pdf", "invoice.pdf")
    detail = (await client.get(f"/api/v1/gs/{gs['id']}", headers=_auth(actors.gate))).json()
    files = detail["goods_slip"]["documents"][0]["files"]
    assert {f["id"] for f in files} == {photo["id"], pdf["id"]}

    # Allow-list, unknown row and step actor.
    res = await client.post(
        url, json={"mime_type": "video/mp4", "size_bytes": 10}, headers=_auth(actors.gate)
    )
    assert res.status_code == 422 and res.json()["error"]["code"] == "FILE_NOT_ALLOWED"
    res = await client.post(
        f"/api/v1/gs/{gs['id']}/gate-documents/{uuid.uuid4()}/files/upload-url",
        json={"mime_type": "image/png", "size_bytes": 10},
        headers=_auth(actors.gate),
    )
    assert res.status_code == 404
    res = await client.post(
        url, json={"mime_type": "image/png", "size_bytes": 10}, headers=_auth(actors.aman)
    )
    assert res.status_code == 403

    # Removable at the gate, frozen once the GS moved on.
    res = await client.delete(f"/api/v1/attachments/{pdf['id']}", headers=_auth(actors.gate))
    assert res.status_code == 204, res.text
    force_gs_status(db_conn, gs["id"], "ITEMIZATION")
    res = await client.delete(f"/api/v1/attachments/{photo['id']}", headers=_auth(actors.gate))
    assert res.status_code == 409 and res.json()["error"]["code"] == "GS_NOT_AT_GATE"
    res = await client.post(
        url, json={"mime_type": "image/png", "size_bytes": 10}, headers=_auth(actors.gate)
    )
    assert res.status_code == 409 and res.json()["error"]["code"] == "GS_NOT_AT_GATE"


async def test_search_by_gate_entry_and_document_number(
    client: AsyncClient, actors: Actors, masters: Masters
) -> None:
    number = gate_entry_no()
    values = _values(gate_entry_no=number)
    values.documents = [{"doc_type_code": "COURIER_SLIP", "doc_no": f"AWB-{number}"}]
    gs = (await _create(client, actors.gate, masters, values)).json()["goods_slip"]
    for q in (str(number), f"AWB-{number}"):
        res = await client.get("/api/v1/gs", params={"q": q}, headers=_auth(actors.gate))
        assert res.status_code == 200, res.text
        items = res.json()["items"]
        assert [i["id"] for i in items] == [gs["id"]]
        assert items[0]["carton_count"] == 3 and items[0]["gate_entry_no"] == number


# =================================================================================================
# G-02 per carton (AMD-03): service and DB, Super Admin included
# =================================================================================================
async def test_g02_requires_one_video_per_carton(
    client: AsyncClient,
    actors: Actors,
    masters: Masters,
    storage: FakeStorage,
    db_conn: Connection,
) -> None:
    gs_id = await started_gs(client, actors, masters)  # 3 cartons
    res = await client.post(
        f"/api/v1/gs/{gs_id}/attachments/upload-url",
        json={"kind": "UNBOXING_VIDEO", "mime_type": "video/mp4", "size_bytes": 10, "box_no": 4},
        headers=_auth(actors.aman),
    )
    assert res.status_code == 422 and "Carton 4" in res.json()["error"]["message"]

    await upload(client, storage, actors.aman, gs_id, "UNBOXING_VIDEO", "video/mp4", box_no=1)
    photo = await upload(client, storage, actors.aman, gs_id, "DOC_PHOTO", "image/png")
    assert (await classify(client, actors.aman, gs_id, photo["id"], INVOICE)).status_code == 201

    for token in (actors.aman, actors.admin):  # G-02 is non-bypassable, even for Super Admin
        res = await complete(client, token, gs_id)
        assert res.status_code in (403, 422), res.text
        if res.status_code == 422:
            assert res.json()["error"]["details"]["missing"] == ["VIDEO_PER_CARTON"]
            assert res.json()["error"]["details"]["checklist"]["boxes_missing_video"] == [2, 3]

    conn = as_admin(db_conn)
    with (
        pytest.raises(DBAPIError, match=r"G-02: .*every carton \(missing carton 2, 3\)"),
        conn.begin_nested(),
    ):
        conn.execute(
            text("update public.goods_slips set status = 'ITEMIZATION' where id = :id"),
            {"id": gs_id},
        )

    for carton in (2, 3):
        await upload(
            client, storage, actors.aman, gs_id, "UNBOXING_VIDEO", "video/mp4", box_no=carton
        )
    res = await complete(client, actors.aman, gs_id)
    assert res.status_code == 200, res.text


# =================================================================================================
# DB layer: the rules hold without the service
# =================================================================================================
def _raw_gs(conn: Connection, **cols: Any) -> str:
    wv = conn.execute(
        text(
            """select v.id from public.workflow_versions v
                 join public.workflow_definitions d on d.id = v.workflow_definition_id
                where d.code = 'RMS_STANDARD' and v.status = 'PUBLISHED'"""
        )
    ).scalar_one()
    base: dict[str, Any] = {
        "gs_no": f"RAW-{uuid.uuid4().hex[:8]}",
        "workflow_version_id": wv,
        "carton_count": 1,
        **COURIER,
        **cols,
    }
    names = ", ".join(base)
    binds = ", ".join(f":{k}" for k in base)
    return str(
        conn.execute(
            text(f"insert into public.goods_slips ({names}) values ({binds}) returning id"),  # noqa: S608
            base,
        ).scalar_one()
    )


def _raw_doc(conn: Connection, gs_id: str, **cols: Any) -> None:
    base: dict[str, Any] = {
        "gs_id": gs_id,
        "doc_type_code": "COURIER_SLIP",
        "doc_type_label": "Courier Slip",
        **cols,
    }
    names = ", ".join(base)
    binds = ", ".join(f":{k}" for k in base)
    conn.execute(text(f"insert into public.gs_gate_documents ({names}) values ({binds})"), base)  # noqa: S608


def test_db_gate_entry_rules(db_conn: Connection) -> None:
    conn = as_admin(db_conn)
    today = business_today()
    with pytest.raises(IntegrityError, match="goods_slips_offline_gate_entry"), conn.begin_nested():
        _raw_gs(conn, return_type_code="OFFLINE_RETURN", gate_entry_date=today)
    with (
        pytest.raises(IntegrityError, match="goods_slips_ecommerce_no_gate_entry"),
        conn.begin_nested(),
    ):
        _raw_gs(conn, return_type_code="ECOMMERCE_RETURN", gate_entry_date=today, gate_entry_no=7)
    with pytest.raises(DBAPIError, match="AMD-01"), conn.begin_nested():
        _raw_gs(conn, return_type_code="WALK_IN")
    with pytest.raises(DBAPIError, match="AMD-02"), conn.begin_nested():
        _raw_gs(
            conn,
            return_type_code="OFFLINE_RETURN",
            gate_entry_date=today + timedelta(days=1),
            gate_entry_no=gate_entry_no(),
        )
    _setting(conn, "gate.max_backdate_days", "3")
    with pytest.raises(DBAPIError, match="DEC-38"), conn.begin_nested():
        _raw_gs(
            conn,
            return_type_code="OFFLINE_RETURN",
            gate_entry_date=today - timedelta(days=4),
            gate_entry_no=gate_entry_no(),
        )
    number = gate_entry_no()
    first = _raw_gs(
        conn, return_type_code="OFFLINE_RETURN", gate_entry_date=today, gate_entry_no=number
    )
    with (
        pytest.raises(IntegrityError, match="goods_slips_gate_entry_no_fy_key"),
        conn.begin_nested(),
    ):
        _raw_gs(
            conn, return_type_code="OFFLINE_RETURN", gate_entry_date=today, gate_entry_no=number
        )
    # The FY is derived by the DB, never taken from the client.
    with conn.begin_nested():
        conn.execute(
            text("update public.goods_slips set gate_entry_fy = 1999 where id = :id"), {"id": first}
        )
    fy = conn.execute(
        text("select gate_entry_fy from public.goods_slips where id = :id"), {"id": first}
    ).scalar_one()
    assert fy in (today.year, today.year - 1)


def test_db_carton_count_mirrors_box_count(db_conn: Connection) -> None:
    conn = as_admin(db_conn)
    gs_id = _raw_gs(conn, carton_count=4)
    row = fetch_all(
        conn, "select carton_count, box_count from public.goods_slips where id = :id", id=gs_id
    )
    assert row == [{"carton_count": 4, "box_count": 4}]
    conn.execute(text("update public.goods_slips set box_count = 2 where id = :id"), {"id": gs_id})
    row = fetch_all(
        conn, "select carton_count, box_count from public.goods_slips where id = :id", id=gs_id
    )
    assert row == [{"carton_count": 2, "box_count": 2}]
    with pytest.raises(IntegrityError), conn.begin_nested():
        conn.execute(
            text("update public.goods_slips set carton_count = 0 where id = :id"), {"id": gs_id}
        )


def test_db_gate_document_rules(db_conn: Connection) -> None:
    conn = as_admin(db_conn)
    gs_id = _raw_gs(conn)
    with (
        pytest.raises(IntegrityError, match="gs_gate_documents_doc_type_code_check"),
        conn.begin_nested(),
    ):
        _raw_doc(conn, gs_id, doc_type_code="NO_DOCUMENT", doc_type_label="No Document")
    with (
        pytest.raises(IntegrityError, match="gs_gate_documents_formal_fields"),
        conn.begin_nested(),
    ):
        _raw_doc(conn, gs_id, doc_type_code="INVOICE", doc_type_label="Invoice", doc_no="1")
    with pytest.raises(DBAPIError, match="AMD-04: unknown"), conn.begin_nested():
        _raw_doc(conn, gs_id, doc_type_code="BOGUS")
    with pytest.raises(DBAPIError, match="in the future"), conn.begin_nested():
        _raw_doc(conn, gs_id, doc_date=business_today() + timedelta(days=1))
    _raw_doc(conn, gs_id, doc_no="AWB-1")
    # DEC-03: "no document" and document rows exclude each other, both ways.
    with pytest.raises(DBAPIError, match="remove the document rows"), conn.begin_nested():
        conn.execute(
            text("update public.goods_slips set missing_documentation = true where id = :id"),
            {"id": gs_id},
        )
    flagged = _raw_gs(conn, missing_documentation=True)
    with pytest.raises(DBAPIError, match="cannot have document rows"), conn.begin_nested():
        _raw_doc(conn, flagged)
    # Gate rows are frozen once the GS left the gate.
    force_gs_status(conn, gs_id, "UNBOXING")
    with (
        pytest.raises(DBAPIError, match="only change while the GS is at the gate"),
        conn.begin_nested(),
    ):
        _raw_doc(conn, gs_id)
    with (
        pytest.raises(DBAPIError, match="only change while the GS is at the gate"),
        conn.begin_nested(),
    ):
        conn.execute(text("delete from public.gs_gate_documents where gs_id = :id"), {"id": gs_id})


def test_db_gate_settings_are_checked(db_conn: Connection) -> None:
    conn = as_admin(db_conn)
    for key, bad in (
        ("gate.max_backdate_days", "-1"),
        ("gate.max_backdate_days", "2.5"),
        ("gate.accounts_alert_doc_types", '"INVOICE"'),
        ("gate.accounts_alert_doc_types", "[1]"),
    ):
        with pytest.raises(IntegrityError), conn.begin_nested():
            _setting(conn, key, bad)


async def test_gate_document_payload_helper_shape() -> None:
    # Guards the shared helper other suites rely on (AMD-04 rows travel outside `values`).
    body = _payload(_values(doc="DEBIT_NOTE"))
    assert body["documents"][0]["doc_type_code"] == "DEBIT_NOTE"
    assert "accompanying_doc" not in body["values"]
