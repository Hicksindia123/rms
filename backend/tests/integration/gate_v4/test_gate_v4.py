"""Phase P2 (docs/RMS_PHASE_PROMPTS_20-11-2026.md) · DEC-62 · gate form S1_GATE_INWARD v4.

Received Through (Courier → courier name + docket no.; Transport → transport name only, Q5; By Hand
→ contact name + number with the phone pattern), optional image-only party / transport documents
(BR-03 missing_documentation + Accounts alert kept), Return Type and Gate Entry kept (Q23, Q24),
and GSs pinned to v3 still readable / editable with the v3 rules (G-18). Every rule is proven
through the API (service) and, where it is a DB rule, against the database without the service.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from tests.conftest import JwtFactory
from tests.integration.conftest import UserFactory, as_admin, fetch_all, use_gate_form_v3
from tests.integration.test_gate_inward import (
    Masters,
    _auth,
    business_today,
    gate_entry_no,
)
from tests.integration.test_unboxing import FakeStorage

pytestmark = pytest.mark.gate_v4

MODES: dict[str, dict[str, Any]] = {
    "COURIER_PARCEL": {"courier_name": "BlueDart", "docket_no": "BD-1001"},
    "DIRECT_TRUCK": {"transporter_name": "Agra Roadways"},
    "SELF_PARTY_REP": {"rep_name": "Ramesh", "rep_contact": "9876543210"},
}
V4_DEACTIVATED = ["DELIVERY_CHALLAN", "LR_BILITY", "DELIVERY_NOTE", "OTHER", "COURIER_SLIP"]


class Actors:
    def __init__(self, users: UserFactory, make_token: JwtFactory) -> None:
        self.gate = make_token(users.create(roles=["GATE_INWARD"], full_name="Anuj"))
        self.accounts_id = users.create(roles=["ACCOUNTS"], full_name="Deepak")
        self.rm_id = users.create(roles=["REPLACEMENT_MANAGER"], full_name="Pratham")
        self.aman = make_token(users.create(roles=["INWARD_VERIFIER"], full_name="Aman"))
        self.admin = make_token(users.create(super_admin=True, full_name="Admin"))


@pytest.fixture
def actors(users: UserFactory, make_token: JwtFactory) -> Actors:
    return Actors(users, make_token)


@pytest.fixture
def masters(db_conn: Connection) -> Masters:
    return Masters(db_conn)


def _values(mode: str = "COURIER_PARCEL", **extra: Any) -> dict[str, Any]:
    return {
        "return_type": "OFFLINE_RETURN",
        "gate_entry_date": (business_today() - timedelta(days=1)).isoformat(),
        "gate_entry_no": gate_entry_no(),
        "carton_count": 2,
        "delivery_mode": mode,
        **MODES[mode],
        "gs_creation_format": "AUTO_STANDARD",
        **extra,
    }


def _drop(values: dict[str, Any], key: str) -> dict[str, Any]:
    return {k: v for k, v in values.items() if k != key}


async def _create(
    client: AsyncClient,
    token: str,
    masters: Masters,
    values: dict[str, Any],
    documents: list[dict[str, Any]] | None = None,
    *,
    key: str | None = None,
    **body: Any,
) -> Any:
    payload = {
        "party_id": str(masters.party),
        "values": values,
        "documents": documents or [],
        **body,
    }
    return await client.post(
        "/api/v1/gs", json=payload, headers=_auth(token, key or f"v4-{uuid.uuid4()}")
    )


def _published_gate_version(conn: Connection) -> Any:
    return (
        as_admin(conn)
        .execute(
            text(
                """select v.id from public.form_versions v
                 join public.form_definitions d on d.id = v.form_definition_id
                where d.code = 'S1_GATE_INWARD' and v.status = 'PUBLISHED'"""
            )
        )
        .scalar_one()
    )


def _republish(conn: Connection, version_id: Any) -> None:
    """Test SETUP: make `version_id` the published gate form again and retire the DEC-62 types
    again (undoes use_gate_form_v3 inside the rolled-back test transaction)."""
    c = as_admin(conn)
    c.execute(text("set local session_replication_role = replica"))
    try:
        c.execute(
            text(
                """update public.form_versions set status = 'RETIRED'
                    where status = 'PUBLISHED' and form_definition_id =
                          (select id from public.form_definitions where code = 'S1_GATE_INWARD')"""
            )
        )
        c.execute(
            text("update public.form_versions set status = 'PUBLISHED' where id = :id"),
            {"id": version_id},
        )
    finally:
        c.execute(text("set local session_replication_role = origin"))
    c.execute(
        text(
            """update public.option_items oi set is_active = false
                 from public.option_sets os
                where os.id = oi.option_set_id and os.code = 'GATE_DOCUMENT'
                  and oi.code = any(:codes)"""
        ),
        {"codes": V4_DEACTIVATED},
    )


# =================================================================================================
# The published form (config-driven labels, required_when, document lists)
# =================================================================================================
async def test_gate_form_v4_is_published_with_dec62_fields(
    client: AsyncClient, actors: Actors
) -> None:
    res = await client.get("/api/v1/gs/gate-form", headers=_auth(actors.gate))
    assert res.status_code == 200, res.text
    body = res.json()
    fields = {f["field_key"]: f for f in body["snapshot"]["fields"]}
    keys = [f["field_key"] for f in body["snapshot"]["fields"]]
    # Q23 / Q24: Return Type and the gate entry fields stay first.
    assert keys[:6] == [
        "return_type",
        "gate_entry_date",
        "gate_entry_no",
        "state",
        "station",
        "party_name",
    ]
    assert "vehicle_no" not in fields  # Q5: Transport Name only
    assert "transport_document" in fields and "no_document" in fields
    labels = {k: fields[k]["label"] for k in fields}
    assert labels["delivery_mode"] == "Received Through"
    assert labels["carton_count"] == "Cartons"
    assert labels["transporter_name"] == "Transport Name"
    assert labels["rep_name"] == "Contact Name" and labels["rep_contact"] == "Contact Number"
    assert labels["docket_no"] == "Docket No."
    assert labels["no_document"] == "No Documents From Party"
    # Required = is_required or required_when (drives the red asterisks in the UI).
    assert fields["return_type"]["is_required"] and fields["carton_count"]["is_required"]
    assert fields["delivery_mode"]["is_required"]
    assert not fields["transport_document"]["is_required"]
    for key, mode in [
        ("courier_name", "COURIER_PARCEL"),
        ("docket_no", "COURIER_PARCEL"),
        ("transporter_name", "DIRECT_TRUCK"),
        ("rep_name", "SELF_PARTY_REP"),
        ("rep_contact", "SELF_PARTY_REP"),
    ]:
        assert fields[key]["required_when"] == {
            "field": "delivery_mode",
            "op": "eq",
            "value": mode,
        }, key
    modes = {o["code"]: o["label"] for o in fields["delivery_mode"]["option_items"]}
    assert modes == {
        "COURIER_PARCEL": "Courier",
        "DIRECT_TRUCK": "Transport",
        "SELF_PARTY_REP": "By Hand",
    }
    # Party list: Invoice / GST Debit Note / Hand Written Slip (+ the no-document choice).
    assert [(t["code"], t["label"]) for t in body["document_types"]] == [
        ("INVOICE", "Invoice"),
        ("DEBIT_NOTE", "GST Debit Note"),
        ("HANDWRITTEN_SLIP", "Hand Written Slip"),
    ]
    assert [(t["code"], t["label"]) for t in body["transport_document_types"]] == [
        ("COURIER_SLIP", "Courier Slip")
    ]


# =================================================================================================
# Received Through: conditional required fields, server side (no UI needed)
# =================================================================================================
@pytest.mark.parametrize(
    ("mode", "missing"),
    [
        ("COURIER_PARCEL", "docket_no"),
        ("COURIER_PARCEL", "courier_name"),
        ("DIRECT_TRUCK", "transporter_name"),
        ("SELF_PARTY_REP", "rep_name"),
        ("SELF_PARTY_REP", "rep_contact"),
    ],
)
async def test_missing_mode_field_is_a_422_field_error(
    client: AsyncClient, actors: Actors, masters: Masters, mode: str, missing: str
) -> None:
    res = await _create(client, actors.gate, masters, _drop(_values(mode), missing))
    assert res.status_code == 422, res.text
    err = res.json()["error"]
    assert err["code"] == "FORM_VALIDATION_FAILED"
    assert missing in err["details"], err
    assert "is required" in err["details"][missing][0]


@pytest.mark.parametrize("mode", list(MODES))
async def test_each_mode_creates_a_v4_gs(
    client: AsyncClient, actors: Actors, masters: Masters, mode: str
) -> None:
    res = await _create(client, actors.gate, masters, _values(mode))
    assert res.status_code == 201, res.text
    gs = res.json()["goods_slip"]
    assert gs["delivery_mode_code"] == mode and gs["status"] == "GATE_CREATED"
    assert gs["return_type_code"] == "OFFLINE_RETURN" and gs["gate_entry_no"] is not None
    assert gs["vehicle_no"] is None  # Q5: never asked on v4
    if mode == "DIRECT_TRUCK":
        assert gs["transporter_name"] == "Agra Roadways"


async def test_transport_ignores_a_vehicle_number_and_links_the_master(
    client: AsyncClient, actors: Actors, masters: Masters
) -> None:
    res = await _create(
        client,
        actors.gate,
        masters,
        _values("DIRECT_TRUCK", vehicle_no="UP80 AB 1234", transporter_name="ignored"),
        transporter_id=str(masters.transporter),
    )
    assert res.status_code == 201, res.text
    gs = res.json()["goods_slip"]
    assert gs["vehicle_no"] is None  # not a v4 field: dropped, never stored
    assert gs["transporter_id"] == str(masters.transporter)


async def test_by_hand_contact_number_format(
    client: AsyncClient, actors: Actors, masters: Masters
) -> None:
    res = await _create(client, actors.gate, masters, _values("SELF_PARTY_REP", rep_contact="12ab"))
    assert res.status_code == 422, res.text
    assert res.json()["error"]["details"]["rep_contact"] == [
        "Contact Number is not a valid phone number"
    ]


@pytest.mark.parametrize("cartons", [0, -1, 2.5, "x"])
async def test_cartons_must_be_a_whole_number_of_at_least_one(
    client: AsyncClient, actors: Actors, masters: Masters, cartons: Any
) -> None:
    res = await _create(client, actors.gate, masters, _values(carton_count=cartons))
    assert res.status_code == 422, res.text
    assert "carton_count" in res.json()["error"]["details"]


async def test_return_type_and_gate_entry_still_validated(
    client: AsyncClient, actors: Actors, masters: Masters
) -> None:
    # Q24: the Return Type stays required on v4; Q23: Offline needs the gate entry.
    res = await _create(client, actors.gate, masters, _drop(_values(), "return_type"))
    assert res.status_code == 422 and "return_type" in res.json()["error"]["details"]
    res = await _create(client, actors.gate, masters, _drop(_values(), "gate_entry_no"))
    assert res.status_code == 422 and "gate_entry_no" in res.json()["error"]["details"]
    ecom = _drop(_drop(_values(return_type="ECOMMERCE_RETURN"), "gate_entry_no"), "gate_entry_date")
    res = await _create(client, actors.gate, masters, ecom)
    assert res.status_code == 201, res.text
    assert res.json()["goods_slip"]["return_type_code"] == "ECOMMERCE_RETURN"


async def test_idempotent_create_returns_the_same_gs(
    client: AsyncClient, actors: Actors, masters: Masters
) -> None:
    # G-16: the summary sheet's key makes a double tap on Submit safe.
    key = f"v4-{uuid.uuid4()}"
    values = _values()
    first = await _create(client, actors.gate, masters, values, key=key)
    again = await _create(client, actors.gate, masters, values, key=key)
    assert first.status_code == 201 and again.status_code == 201, again.text
    assert first.json()["goods_slip"]["id"] == again.json()["goods_slip"]["id"]


# =================================================================================================
# Documents: optional, image only, per source (BR-03 flag and the Accounts alert are kept)
# =================================================================================================
def _notifications(conn: Connection, user_id: uuid.UUID, gs_id: str) -> list[str]:
    return [
        r["type"]
        for r in fetch_all(
            conn,
            "select type from public.notifications where user_id = :u and entity_id = :g",
            u=user_id,
            g=gs_id,
        )
    ]


async def test_documents_are_optional_and_flag_missing_documentation(
    client: AsyncClient, actors: Actors, masters: Masters, db_conn: Connection
) -> None:
    res = await _create(client, actors.gate, masters, _values())
    assert res.status_code == 201, res.text
    body = res.json()
    gs = body["goods_slip"]
    assert gs["documents"] == []
    assert gs["missing_documentation"] is True  # BR-03: nothing from the party
    assert [w["code"] for w in body["warnings"]] == ["MISSING_DOCUMENTATION"]
    assert "No Documents From Party" in body["warnings"][0]["message"]  # configured label
    # DEC-05: high-priority alert to Accounts and the Replacement Manager.
    assert "GS_MISSING_DOCUMENTATION" in _notifications(db_conn, actors.accounts_id, gs["id"])
    assert "GS_MISSING_DOCUMENTATION" in _notifications(db_conn, actors.rm_id, gs["id"])


async def test_no_documents_from_party_choice_with_a_courier_slip(
    client: AsyncClient, actors: Actors, masters: Masters
) -> None:
    res = await _create(
        client,
        actors.gate,
        masters,
        _values(no_document=True),
        [{"doc_type_code": "COURIER_SLIP", "source": "TRANSPORT"}],
    )
    assert res.status_code == 201, res.text
    gs = res.json()["goods_slip"]
    assert gs["missing_documentation"] is True
    assert [(d["doc_type_code"], d["doc_source"]) for d in gs["documents"]] == [
        ("COURIER_SLIP", "TRANSPORT")
    ]


async def test_party_and_transport_documents_alert_accounts(
    client: AsyncClient, actors: Actors, masters: Masters, db_conn: Connection
) -> None:
    res = await _create(
        client,
        actors.gate,
        masters,
        _values(),
        [
            {"doc_type_code": "INVOICE"},  # source omitted = PARTY
            {"doc_type_code": "HANDWRITTEN_SLIP", "source": "PARTY"},
            {"doc_type_code": "COURIER_SLIP", "source": "TRANSPORT"},
        ],
    )
    assert res.status_code == 201, res.text
    body = res.json()
    gs = body["goods_slip"]
    assert gs["missing_documentation"] is False and body["warnings"] == []
    docs = [
        (d["doc_type_code"], d["doc_type_label"], d["doc_source"], d["doc_no"])
        for d in gs["documents"]
    ]
    assert docs == [
        ("INVOICE", "Invoice", "PARTY", None),
        ("HANDWRITTEN_SLIP", "Hand Written Slip", "PARTY", None),
        ("COURIER_SLIP", "Courier Slip", "TRANSPORT", None),
    ]
    # AMD-05: only INVOICE / DEBIT_NOTE (setting gate.accounts_alert_doc_types) alert Accounts.
    alerts = _notifications(db_conn, actors.accounts_id, gs["id"])
    assert alerts.count("GS_DOCUMENT_FOUND") == 1, alerts
    invoice = next(d for d in gs["documents"] if d["doc_type_code"] == "INVOICE")
    assert invoice["accounts_alerted_at"] is not None


@pytest.mark.parametrize(
    ("doc", "field"),
    [
        ({"doc_type_code": "INVOICE", "doc_no": "INV-1"}, "doc_no"),
        ({"doc_type_code": "DEBIT_NOTE", "doc_date": "2026-11-01"}, "doc_date"),
        ({"doc_type_code": "HANDWRITTEN_SLIP", "remarks": "note"}, "remarks"),
        ({"doc_type_code": "DELIVERY_CHALLAN"}, "doc_type_code"),  # deactivated (DEC-62)
        ({"doc_type_code": "LR_BILITY"}, "doc_type_code"),
        ({"doc_type_code": "NO_DOCUMENT"}, "doc_type_code"),  # the GS flag, not a row
        ({"doc_type_code": "COURIER_SLIP", "source": "PARTY"}, "doc_type_code"),
        ({"doc_type_code": "INVOICE", "source": "TRANSPORT"}, "doc_type_code"),
    ],
)
async def test_invalid_document_rows_are_field_errors(
    client: AsyncClient, actors: Actors, masters: Masters, doc: dict[str, Any], field: str
) -> None:
    res = await _create(client, actors.gate, masters, _values(), [doc])
    assert res.status_code == 422, res.text
    assert f"documents.0.{field}" in res.json()["error"]["details"], res.text


async def test_no_documents_choice_excludes_party_rows(
    client: AsyncClient, actors: Actors, masters: Masters
) -> None:
    res = await _create(
        client, actors.gate, masters, _values(no_document=True), [{"doc_type_code": "INVOICE"}]
    )
    assert res.status_code == 422, res.text
    assert "No Documents From Party" in res.json()["error"]["details"]["documents"][0]


async def test_v4_document_row_takes_files(
    client: AsyncClient, actors: Actors, masters: Masters, storage: FakeStorage
) -> None:
    gs = (
        await _create(
            client,
            actors.gate,
            masters,
            _values(),
            [{"doc_type_code": "COURIER_SLIP", "source": "TRANSPORT"}],
        )
    ).json()["goods_slip"]
    doc_id = gs["documents"][0]["id"]
    res = await client.post(
        f"/api/v1/gs/{gs['id']}/gate-documents/{doc_id}/files/upload-url",
        json={"mime_type": "image/jpeg", "size_bytes": 2048, "file_name": "slip.jpg"},
        headers=_auth(actors.gate),
    )
    assert res.status_code == 201, res.text
    assert res.json()["attachment"]["gate_document_id"] == doc_id


async def test_v4_gs_moves_on_to_carton_opening(
    client: AsyncClient, actors: Actors, masters: Masters
) -> None:
    gs = (await _create(client, actors.gate, masters, _values())).json()["goods_slip"]
    res = await client.post(f"/api/v1/gs/{gs['id']}/unboxing/start", headers=_auth(actors.aman))
    assert res.status_code == 200, res.text
    assert res.json()["goods_slip"]["status"] == "UNBOXING"


# =================================================================================================
# G-18: a GS created under v3 stays readable and keeps the v3 rules on an edit
# =================================================================================================
async def test_v3_gs_is_readable_and_edited_with_v3_rules(
    client: AsyncClient, actors: Actors, masters: Masters, db_conn: Connection
) -> None:
    v4_id = _published_gate_version(db_conn)
    use_gate_form_v3(db_conn)
    v3_id = _published_gate_version(db_conn)
    v3_values = {
        **_values("DIRECT_TRUCK", vehicle_no="UP80 AB 1234"),
        "no_document": False,
    }
    v3_docs = [{"doc_type_code": "DELIVERY_CHALLAN", "doc_no": "DC-5", "doc_date": "2026-11-01"}]
    res = await _create(client, actors.gate, masters, v3_values, v3_docs)
    assert res.status_code == 201, res.text
    gs = res.json()["goods_slip"]
    _republish(db_conn, v4_id)

    res = await client.get(f"/api/v1/gs/{gs['id']}", headers=_auth(actors.gate))
    assert res.status_code == 200, res.text
    detail = res.json()
    assert detail["form_version_id"] == str(v3_id)
    assert detail["goods_slip"]["vehicle_no"] == "UP80 AB 1234"
    doc = detail["goods_slip"]["documents"][0]
    assert (doc["doc_type_code"], doc["doc_no"], doc["doc_source"]) == (
        "DELIVERY_CHALLAN",
        "DC-5",
        None,
    )
    assert detail["form_values"]["vehicle_no"] == "UP80 AB 1234"

    # The edit is validated against v3 (vehicle no. still required there) ...
    edit = {"party_id": str(masters.party), "reason": "Fix docket", "values": v3_values}
    res = await client.patch(
        f"/api/v1/gs/{gs['id']}/gate",
        json={
            **edit,
            "values": _drop(v3_values, "vehicle_no"),
            "documents": [{**v3_docs[0], "id": doc["id"]}],
        },
        headers=_auth(actors.gate),
    )
    assert res.status_code == 422 and "vehicle_no" in res.json()["error"]["details"], res.text
    # ... the kept row keeps its now-deactivated type; a new row of that type is refused.
    res = await client.patch(
        f"/api/v1/gs/{gs['id']}/gate",
        json={**edit, "documents": [{**v3_docs[0], "id": doc["id"]}]},
        headers=_auth(actors.gate),
    )
    assert res.status_code == 200, res.text
    res = await client.patch(
        f"/api/v1/gs/{gs['id']}/gate",
        json={**edit, "documents": [{**v3_docs[0], "id": doc["id"]}, v3_docs[0]]},
        headers=_auth(actors.gate),
    )
    assert res.status_code == 422, res.text
    assert "documents.1.doc_type_code" in res.json()["error"]["details"]


# =================================================================================================
# The DB rules on their own (no service)
# =================================================================================================
async def test_db_v4_document_rules(
    client: AsyncClient, actors: Actors, masters: Masters, db_conn: Connection
) -> None:
    gs = (await _create(client, actors.gate, masters, _values())).json()["goods_slip"]
    other = (
        await _create(client, actors.gate, masters, _values(), [{"doc_type_code": "INVOICE"}])
    ).json()["goods_slip"]
    conn = as_admin(db_conn)

    def insert(gs_id: str, code: str, source: str | None, **cols: Any) -> Any:
        return conn.execute(
            text(
                """insert into public.gs_gate_documents
                       (gs_id, doc_type_code, doc_type_label, doc_source, doc_no, doc_date, remarks)
                   values (:g, :c, :c, :s, :no, :dt, :rm) returning id"""
            ),
            {
                "g": gs_id,
                "c": code,
                "s": source,
                "no": cols.get("doc_no"),
                "dt": cols.get("doc_date"),
                "rm": cols.get("remarks"),
            },
        ).scalar_one()

    # gs is flagged "no documents from party" (nothing recorded): transport rows are still fine.
    insert(gs["id"], "COURIER_SLIP", "TRANSPORT")
    with pytest.raises(DBAPIError, match="cannot have document rows"), conn.begin_nested():
        insert(gs["id"], "INVOICE", "PARTY")
    # Image only (DEC-62 c) for v4 rows; the DD r5-r8 fields stay required on legacy rows.
    with pytest.raises(IntegrityError, match="v4_image_only"), conn.begin_nested():
        insert(other["id"], "INVOICE", "PARTY", doc_no="INV-1")
    with pytest.raises(IntegrityError, match="formal_fields"), conn.begin_nested():
        insert(other["id"], "INVOICE", None)
    with pytest.raises(IntegrityError, match="slip_fields"), conn.begin_nested():
        insert(other["id"], "HANDWRITTEN_SLIP", None)
    party_row = insert(other["id"], "HANDWRITTEN_SLIP", "PARTY")
    # Type per source: transport rows use GATE_TRANSPORT_DOCUMENT, party rows GATE_DOCUMENT.
    with pytest.raises(DBAPIError, match="GATE_TRANSPORT_DOCUMENT"), conn.begin_nested():
        insert(other["id"], "INVOICE", "TRANSPORT")
    with pytest.raises(DBAPIError, match="unknown or inactive"), conn.begin_nested():
        insert(other["id"], "COURIER_SLIP", "PARTY")
    with pytest.raises(DBAPIError, match="unknown or inactive"), conn.begin_nested():
        insert(other["id"], "DELIVERY_CHALLAN", "PARTY")
    # A source is fixed and matches the step.
    with pytest.raises(DBAPIError, match="cannot change"), conn.begin_nested():
        conn.execute(
            text("update public.gs_gate_documents set doc_source = 'TRANSPORT' where id = :id"),
            {"id": party_row},
        )
    with pytest.raises(IntegrityError, match="source_step_match"), conn.begin_nested():
        insert(other["id"], "INVOICE", "CARTON")


async def test_db_transport_needs_a_transporter_not_a_vehicle(
    client: AsyncClient, actors: Actors, masters: Masters, db_conn: Connection
) -> None:
    gs = (await _create(client, actors.gate, masters, _values("DIRECT_TRUCK"))).json()["goods_slip"]
    conn = as_admin(db_conn)
    row = fetch_all(conn, "select vehicle_no from public.goods_slips where id = :id", id=gs["id"])
    assert row == [{"vehicle_no": None}]
    with pytest.raises(IntegrityError, match="goods_slips_truck_fields"), conn.begin_nested():
        conn.execute(
            text(
                """update public.goods_slips set transporter_name = null, transporter_id = null
                    where id = :id"""
            ),
            {"id": gs["id"]},
        )
