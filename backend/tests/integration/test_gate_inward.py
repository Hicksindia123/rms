"""Step-1 gate inward & GS creation (prompt P2-02; BR-01..BR-03, DEC-01/02/05, G-01, G-16, G-17).

Every delivery mode x gate document combination is created through the API (valid), and each
conditional field is removed in turn to prove the backend rejects it without the UI (invalid).

Since change plan 2026-11-12 Phase 2 the published gate form is v2 (AMD-01..AMD-04): return type,
gate entry date / number (Offline), carton count and document rows. `_values()` builds a v2
submission; `_create()` / `_payload()` add the matching `documents` rows. Phase 2 specific tests
live in test_gate_entry_phase2.py.
"""

from __future__ import annotations

import re
import secrets
import uuid
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from tests.conftest import JwtFactory
from tests.integration.conftest import (
    Override,
    UserFactory,
    as_admin,
    fetch_all,
    force_gs_status,
)

GS_NO = re.compile(r"^GS/\d{4}-\d{2}/\d{5}$")  # seeded DEC-01 placeholder GS/{FY}/{SEQ:5}

MODE_VALUES: dict[str, dict[str, Any]] = {
    "COURIER_PARCEL": {"courier_name": "BlueDart", "docket_no": "BD-1001"},
    "DIRECT_TRUCK": {"vehicle_no": "UP80 AB 1234", "transporter_name": "Agra Roadways"},
    "SELF_PARTY_REP": {"rep_name": "Ramesh", "rep_contact": "9876543210"},
}
# AMD-04: one document row per type (NO_DOCUMENT is the GS-level flag, not a row).
DOC_VALUES: dict[str, dict[str, Any]] = {
    "INVOICE": {"doc_no": "INV-77", "doc_date": "2026-10-30"},
    "DEBIT_NOTE": {"doc_no": "DN-12", "doc_date": "2026-10-29"},
    "DELIVERY_CHALLAN": {"doc_no": "DC-5", "doc_date": "2026-10-28"},
    "HANDWRITTEN_SLIP": {"remarks": "Party note: 3 thermometers broken"},
    "COURIER_SLIP": {"doc_no": "CS-9"},
    "NO_DOCUMENT": {},
}


def business_today() -> date:
    """Business date (seeded `timezone` setting, Asia/Kolkata), as the DB guards use."""
    return datetime.now(ZoneInfo("Asia/Kolkata")).date()


def gate_entry_no() -> int:
    """AMD-02 / DEC-38: gate entry numbers are unique per FY; tests use random large numbers."""
    return 10**9 + secrets.randbelow(10**12)


class GateValues(dict[str, Any]):
    """v2 form values that remember their document rows (sent as `documents`, AMD-04)."""

    documents: list[dict[str, Any]]


def _auth(token: str, key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if key is not None:
        headers["Idempotency-Key"] = key
    return headers


def _values(
    mode: str = "COURIER_PARCEL",
    doc: str = "INVOICE",
    *,
    doc_row: dict[str, Any] | None = None,
    **extra: Any,
) -> GateValues:
    no_doc = doc == "NO_DOCUMENT"
    values = GateValues(
        {
            "return_type": "OFFLINE_RETURN",
            "gate_entry_date": (business_today() - timedelta(days=1)).isoformat(),
            "gate_entry_no": gate_entry_no(),
            "carton_count": 3,
            "delivery_mode": mode,
            **MODE_VALUES[mode],
            "no_document": no_doc,  # DEC-52: no separate acknowledgement
            "gs_creation_format": "AUTO_STANDARD",
            **extra,
        }
    )
    values.documents = (
        [] if no_doc else [{"doc_type_code": doc, **DOC_VALUES[doc], **(doc_row or {})}]
    )
    return values


def _payload(values: dict[str, Any]) -> dict[str, Any]:
    """`values` + the document rows a GateValues carries (AMD-04)."""
    return {"values": values, "documents": list(getattr(values, "documents", []))}


class Masters:
    def __init__(self, conn: Connection) -> None:
        c = as_admin(conn)
        tag = uuid.uuid4().hex[:6].upper()
        self.state_a = c.execute(
            text("insert into public.states (name) values (:n) returning id"),
            {"n": f"Test State A {tag}"},
        ).scalar_one()
        self.state_b = c.execute(
            text("insert into public.states (name) values (:n) returning id"),
            {"n": f"Test State B {tag}"},
        ).scalar_one()
        self.station_a = c.execute(
            text("insert into public.stations (state_id, name) values (:s, 'Stn A') returning id"),
            {"s": self.state_a},
        ).scalar_one()
        self.station_b = c.execute(
            text("insert into public.stations (state_id, name) values (:s, 'Stn B') returning id"),
            {"s": self.state_b},
        ).scalar_one()
        self.party = c.execute(
            text(
                """insert into public.parties (code, name, state_id, station_id)
                   values (:c, :n, :s, :st) returning id"""
            ),
            {"c": f"TP-{tag}", "n": f"Test Party {tag}", "s": self.state_a, "st": self.station_a},
        ).scalar_one()
        self.party_name = f"Test Party {tag}"
        self.transporter = c.execute(
            text("insert into public.transporters (name) values (:n) returning id"),
            {"n": f"Test Transporter {tag}"},
        ).scalar_one()


@pytest.fixture
def masters(db_conn: Connection) -> Masters:
    return Masters(db_conn)


@pytest.fixture
def gate_token(users: UserFactory, make_token: JwtFactory) -> Callable[[], tuple[uuid.UUID, str]]:
    def factory() -> tuple[uuid.UUID, str]:
        uid = users.create(roles=["GATE_INWARD"], full_name="Gate User")
        return uid, make_token(uid)

    return factory


async def _create(
    client: AsyncClient,
    token: str,
    masters: Masters,
    values: dict[str, Any],
    *,
    key: str | None = None,
    **body: Any,
) -> Any:
    payload: dict[str, Any] = {"party_id": str(masters.party), **_payload(values), **body}
    return await client.post(
        "/api/v1/gs", json=payload, headers=_auth(token, key or f"test-{uuid.uuid4()}")
    )


# --- valid: every delivery mode x gate document --------------------------------------------------
@pytest.mark.parametrize("doc", list(DOC_VALUES))
@pytest.mark.parametrize("mode", list(MODE_VALUES))
async def test_create_valid_combinations(
    client: AsyncClient,
    db_conn: Connection,
    masters: Masters,
    gate_token: Callable[[], tuple[uuid.UUID, str]],
    mode: str,
    doc: str,
) -> None:
    uid, token = gate_token()
    res = await _create(client, token, masters, _values(mode, doc))
    assert res.status_code == 201, res.text
    body = res.json()
    gs = body["goods_slip"]
    assert GS_NO.fullmatch(gs["gs_no"]), gs["gs_no"]
    assert gs["status"] == "GATE_CREATED"
    assert gs["delivery_mode_code"] == mode
    assert gs["gate_document_code"] is None  # AMD-04: replaced by document rows
    assert [d["doc_type_code"] for d in gs["documents"]] == ([] if doc == "NO_DOCUMENT" else [doc])
    assert gs["return_type_code"] == "OFFLINE_RETURN" and gs["carton_count"] == 3
    assert gs["party_name"] == masters.party_name
    assert gs["state_id"] == str(masters.state_a)  # DEC-02 auto-fill
    assert gs["state_station_overridden"] is False
    assert gs["missing_documentation"] is (doc == "NO_DOCUMENT")
    assert [w["code"] for w in body["warnings"]] == (
        ["MISSING_DOCUMENTATION"] if doc == "NO_DOCUMENT" else []
    )
    assert gs["created_by"] == str(uid)

    rows = fetch_all(
        db_conn,
        """select t.step_code, r.code as role, t.status, t.due_at is not null as has_due
             from public.workflow_tasks t join public.roles r on r.id = t.assigned_role_id
            where t.gs_id = :id""",
        id=gs["id"],
    )
    assert rows == [
        {"step_code": "S1_UNBOX", "role": "INWARD_VERIFIER", "status": "OPEN", "has_due": True}
    ]
    hist = fetch_all(
        db_conn,
        "select from_status, to_status, step_code from public.gs_status_history where gs_id = :id",
        id=gs["id"],
    )
    assert hist == [{"from_status": None, "to_status": "GATE_CREATED", "step_code": "S1_GATE"}]
    resp = fetch_all(
        db_conn,
        """select r.labels_snapshot, v.status from public.form_responses r
             join public.form_versions v on v.id = r.form_version_id
            where r.entity_type = 'goods_slip' and r.entity_id = :id""",
        id=gs["id"],
    )
    assert len(resp) == 1 and resp[0]["status"] == "PUBLISHED"
    labels = resp[0]["labels_snapshot"]
    assert labels["delivery_mode"]["value"] == mode
    assert labels["delivery_mode"]["value_label"]  # option label snapshot (G-18)
    assert labels["party_name"]["value"] == masters.party_name


# --- invalid: each conditional field is enforced by the backend ----------------------------------
INVALID_CASES = [
    ("COURIER_PARCEL", "INVOICE", {"courier_name": None}, "courier_name"),
    ("COURIER_PARCEL", "INVOICE", {"docket_no": "  "}, "docket_no"),
    ("DIRECT_TRUCK", "INVOICE", {"vehicle_no": None}, "vehicle_no"),
    ("DIRECT_TRUCK", "INVOICE", {"transporter_name": None}, "transporter_name"),
    ("SELF_PARTY_REP", "INVOICE", {"rep_name": None}, "rep_name"),
    ("SELF_PARTY_REP", "INVOICE", {"rep_contact": None}, "rep_contact"),
    ("SELF_PARTY_REP", "INVOICE", {"rep_contact": "12345"}, "rep_contact"),
    ("COURIER_PARCEL", "INVOICE", {"doc_row": {"doc_no": None}}, "documents.0.doc_no"),
    ("COURIER_PARCEL", "DEBIT_NOTE", {"doc_row": {"doc_date": None}}, "documents.0.doc_date"),
    (
        "COURIER_PARCEL",
        "DELIVERY_CHALLAN",
        {"doc_row": {"doc_date": "2999-01-01"}},
        "documents.0.doc_date",
    ),
    ("COURIER_PARCEL", "HANDWRITTEN_SLIP", {"doc_row": {"remarks": ""}}, "documents.0.remarks"),
    (
        "COURIER_PARCEL",
        "INVOICE",
        {"doc_row": {"doc_type_code": "NO_DOCUMENT"}},
        "documents.0.doc_type_code",
    ),
    (
        "COURIER_PARCEL",
        "INVOICE",
        {"doc_row": {"doc_type_code": "BOGUS"}},
        "documents.0.doc_type_code",
    ),
    ("COURIER_PARCEL", "INVOICE", {"carton_count": 0}, "carton_count"),  # AMD-03
    ("COURIER_PARCEL", "INVOICE", {"carton_count": None}, "carton_count"),
    ("COURIER_PARCEL", "INVOICE", {"delivery_mode": "DIRECT_VEHICLE"}, "delivery_mode"),
    ("COURIER_PARCEL", "INVOICE", {"gs_creation_format": "MANUAL"}, "gs_creation_format"),
    ("COURIER_PARCEL", "INVOICE", {"return_type": None}, "return_type"),  # AMD-01
    ("COURIER_PARCEL", "INVOICE", {"return_type": "WALK_IN"}, "return_type"),
    ("COURIER_PARCEL", "INVOICE", {"gate_entry_date": None}, "gate_entry_date"),  # AMD-02
    ("COURIER_PARCEL", "INVOICE", {"gate_entry_no": None}, "gate_entry_no"),
    ("COURIER_PARCEL", "INVOICE", {"gate_entry_no": 0}, "gate_entry_no"),
    ("COURIER_PARCEL", "INVOICE", {"gate_entry_date": "2999-01-01"}, "gate_entry_date"),
]


@pytest.mark.parametrize(("mode", "doc", "change", "field"), INVALID_CASES)
async def test_create_rejects_missing_conditional_fields(
    client: AsyncClient,
    db_conn: Connection,
    masters: Masters,
    gate_token: Callable[[], tuple[uuid.UUID, str]],
    mode: str,
    doc: str,
    change: dict[str, Any],
    field: str,
) -> None:
    _, token = gate_token()
    before = fetch_all(db_conn, "select count(*) as n from public.goods_slips")[0]["n"]
    res = await _create(client, token, masters, _values(mode, doc, **change))
    assert res.status_code == 422, res.text
    err = res.json()["error"]
    assert err["code"] == "FORM_VALIDATION_FAILED"
    assert field in err["details"], err
    after = fetch_all(db_conn, "select count(*) as n from public.goods_slips")[0]["n"]
    assert after == before


async def test_party_is_required(
    client: AsyncClient, masters: Masters, gate_token: Callable[[], tuple[uuid.UUID, str]]
) -> None:
    _, token = gate_token()
    res = await client.post(
        "/api/v1/gs", json=_payload(_values()), headers=_auth(token, f"k-{uuid.uuid4()}")
    )
    assert res.status_code == 422
    assert "party_name" in res.json()["error"]["details"]


# --- BR-03 / DEC-05 ------------------------------------------------------------------------------
async def test_no_document_flags_and_notifies_accounts_and_rm(
    client: AsyncClient,
    db_conn: Connection,
    users: UserFactory,
    masters: Masters,
    gate_token: Callable[[], tuple[uuid.UUID, str]],
) -> None:
    accounts = users.create(roles=["ACCOUNTS"])
    rm = users.create(roles=["REPLACEMENT_MANAGER"])
    verifier = users.create(roles=["INWARD_VERIFIER"])
    gate_uid, token = gate_token()
    res = await _create(client, token, masters, _values(doc="NO_DOCUMENT"))
    assert res.status_code == 201
    body = res.json()
    assert body["goods_slip"]["missing_documentation"] is True
    assert body["warnings"][0]["code"] == "MISSING_DOCUMENTATION"
    assert "No Document Attached" in body["warnings"][0]["message"]  # configured label
    rows = fetch_all(
        db_conn,
        """select user_id, priority, type from public.notifications
            where entity_id = :id and type = 'GS_MISSING_DOCUMENTATION'""",
        id=body["goods_slip"]["id"],
    )
    recipients = {r["user_id"] for r in rows}
    assert {accounts, rm} <= recipients
    assert gate_uid not in recipients and verifier not in recipients
    assert {r["priority"] for r in rows} == {"HIGH"}


# --- G-16: idempotency ---------------------------------------------------------------------------
async def test_double_submit_same_key_creates_one_gs(
    client: AsyncClient,
    db_conn: Connection,
    masters: Masters,
    gate_token: Callable[[], tuple[uuid.UUID, str]],
) -> None:
    _, token = gate_token()
    key = f"double-tap-{uuid.uuid4()}"
    before = fetch_all(db_conn, "select count(*) as n from public.goods_slips")[0]["n"]
    values = _values()  # one payload: the same key with another payload is a 409 (G-16)
    first = await _create(client, token, masters, values, key=key)
    second = await _create(client, token, masters, values, key=key)
    assert first.status_code == second.status_code == 201
    assert second.headers.get("Idempotency-Replayed") == "true"
    assert first.json() == second.json()
    after = fetch_all(db_conn, "select count(*) as n from public.goods_slips")[0]["n"]
    assert after == before + 1


async def test_idempotency_key_is_required(
    client: AsyncClient, masters: Masters, gate_token: Callable[[], tuple[uuid.UUID, str]]
) -> None:
    _, token = gate_token()
    res = await client.post(
        "/api/v1/gs",
        json={"party_id": str(masters.party), **_payload(_values())},
        headers=_auth(token),
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"


# --- security ------------------------------------------------------------------------------------
async def test_only_s1_gate_performers_can_create(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory, masters: Masters
) -> None:
    verifier = make_token(users.create(roles=["INWARD_VERIFIER"]))
    res = await _create(client, verifier, masters, _values())
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "PERMISSION_DENIED"

    # Permission granted by override, but not assigned to perform S1_GATE.
    not_actor = make_token(users.create(overrides=[Override("goods_slips", "create", "grant")]))
    res = await _create(client, not_actor, masters, _values())
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "NOT_STEP_ACTOR"


# --- DEC-02 --------------------------------------------------------------------------------------
async def test_provisional_party_created_and_admins_notified(
    client: AsyncClient,
    db_conn: Connection,
    users: UserFactory,
    masters: Masters,
    gate_token: Callable[[], tuple[uuid.UUID, str]],
) -> None:
    admin = users.create(super_admin=True)
    _, token = gate_token()
    res = await client.post(
        "/api/v1/gs",
        json={
            "provisional_party": {
                "name": "Walk-in Chemist",
                "state_id": str(masters.state_b),
                "station_id": str(masters.station_b),
            },
            **_payload(_values()),
        },
        headers=_auth(token, f"prov-{uuid.uuid4()}"),
    )
    assert res.status_code == 201, res.text
    gs = res.json()["goods_slip"]
    assert gs["party_name"] == "Walk-in Chemist"
    assert gs["party_is_provisional"] is True
    assert gs["state_id"] == str(masters.state_b)
    party = fetch_all(
        db_conn,
        "select is_provisional, code from public.parties where id = :id",
        id=gs["party_id"],
    )[0]
    assert party["is_provisional"] is True and party["code"].startswith("PROV-")
    notes = fetch_all(
        db_conn,
        "select user_id from public.notifications where type = 'PROVISIONAL_PARTY_CREATED' "
        "and entity_id = :id",
        id=gs["party_id"],
    )
    assert admin in {n["user_id"] for n in notes}


async def test_provisional_party_station_must_match_state(
    client: AsyncClient, masters: Masters, gate_token: Callable[[], tuple[uuid.UUID, str]]
) -> None:
    _, token = gate_token()
    res = await client.post(
        "/api/v1/gs",
        json={
            "provisional_party": {
                "name": "Bad",
                "state_id": str(masters.state_a),
                "station_id": str(masters.station_b),
            },
            **_payload(_values()),
        },
        headers=_auth(token, f"prov-{uuid.uuid4()}"),
    )
    assert res.status_code == 422
    assert "station" in res.json()["error"]["details"]


async def test_state_station_override_is_flagged_and_audited(
    client: AsyncClient,
    db_conn: Connection,
    masters: Masters,
    gate_token: Callable[[], tuple[uuid.UUID, str]],
) -> None:
    _, token = gate_token()
    res = await _create(
        client,
        token,
        masters,
        _values(),
        state_id=str(masters.state_b),
        station_id=str(masters.station_b),
    )
    assert res.status_code == 201, res.text
    gs = res.json()["goods_slip"]
    assert gs["state_station_overridden"] is True
    audit = fetch_all(
        db_conn,
        "select action, reason from public.audit_log where table_name = 'public.goods_slips' "
        "and row_id = :id",
        id=gs["id"],
    )
    assert audit[0]["action"] == "INSERT"
    assert "DEC-02" in audit[0]["reason"]


async def test_transporter_from_master(
    client: AsyncClient, masters: Masters, gate_token: Callable[[], tuple[uuid.UUID, str]]
) -> None:
    _, token = gate_token()
    values = _values("DIRECT_TRUCK")
    values.pop("transporter_name")
    res = await _create(client, token, masters, values, transporter_id=str(masters.transporter))
    assert res.status_code == 201, res.text
    gs = res.json()["goods_slip"]
    assert gs["transporter_id"] == str(masters.transporter)
    assert gs["transporter_name"].startswith("Test Transporter")


# --- reads: list, detail, tag, tasks -------------------------------------------------------------
async def test_list_detail_tag_and_verifier_task(
    client: AsyncClient,
    users: UserFactory,
    make_token: JwtFactory,
    masters: Masters,
    gate_token: Callable[[], tuple[uuid.UUID, str]],
) -> None:
    _, token = gate_token()
    created = (await _create(client, token, masters, _values(doc="NO_DOCUMENT"))).json()
    gs = created["goods_slip"]

    listed = await client.get(
        "/api/v1/gs",
        params={"q": gs["gs_no"], "flag": "missing_documentation", "status": "GATE_CREATED"},
        headers=_auth(token),
    )
    assert listed.status_code == 200, listed.text
    assert [i["id"] for i in listed.json()["items"]] == [gs["id"]]
    bad = await client.get("/api/v1/gs", params={"flag": "nope"}, headers=_auth(token))
    assert bad.status_code == 422

    detail = await client.get(f"/api/v1/gs/{gs['id']}", headers=_auth(token))
    assert detail.status_code == 200
    d = detail.json()
    assert d["timeline"][0]["to_status"] == "GATE_CREATED"
    assert d["tasks"][0]["step_code"] == "S1_UNBOX"
    assert d["can_edit_gate"] is True and d["can_cancel"] is False
    assert d["form_values"]["delivery_mode"] == "COURIER_PARCEL"

    tag = await client.get(f"/api/v1/gs/{gs['id']}/tag", headers=_auth(token))
    assert tag.status_code == 200
    t = tag.json()
    assert t["template_code"] == "GS_TAG"
    assert t["qr_payload"] == f"{gs['gs_no']}|{gs['id']}"
    assert [lbl["caption"] for lbl in t["labels"]] == [  # AMD-03
        "Carton 1 of 3",
        "Carton 2 of 3",
        "Carton 3 of 3",
    ]
    fields = {f["key"]: f for sec in t["sections"] for f in sec["fields"]}
    assert fields["gs_no"]["value"] == gs["gs_no"]
    assert fields["party_name"]["label"] == "Distributor / Party"  # S1_GATE_INWARD v2 label
    assert fields["party_name"]["value"] == masters.party_name
    assert fields["carton_count"]["value"] == "3"
    assert fields["carton_count"]["label"] == "Carton No."
    assert fields["state_station"]["label"] == "State / Station"

    verifier = make_token(users.create(roles=["INWARD_VERIFIER"]))
    tasks = await client.get(
        "/api/v1/tasks/mine", params={"step_code": "S1_UNBOX"}, headers=_auth(verifier)
    )
    assert tasks.status_code == 200
    assert gs["id"] in {i["gs_id"] for i in tasks.json()["items"]}
    accounts = make_token(users.create(roles=["ACCOUNTS"]))
    other = await client.get("/api/v1/tasks/mine", headers=_auth(accounts))
    assert gs["id"] not in {i["gs_id"] for i in other.json()["items"]}


async def test_lookups(
    client: AsyncClient, masters: Masters, gate_token: Callable[[], tuple[uuid.UUID, str]]
) -> None:
    _, token = gate_token()
    parties = await client.get(
        "/api/v1/gs/lookups/parties", params={"q": masters.party_name}, headers=_auth(token)
    )
    assert parties.status_code == 200
    assert parties.json()[0]["state_id"] == str(masters.state_a)
    stations = await client.get(
        "/api/v1/gs/lookups/stations",
        params={"state_id": str(masters.state_b)},
        headers=_auth(token),
    )
    assert [s["id"] for s in stations.json()] == [str(masters.station_b)]
    form = await client.get("/api/v1/gs/gate-form", headers=_auth(token))
    assert form.status_code == 200
    assert form.json()["snapshot"]["form_code"] == "S1_GATE_INWARD"
    assert form.json()["contact_phone_pattern"]
    # DEC-52: the published gate form has no separate missing-documentation acknowledgement.
    keys = {f["field_key"] for f in form.json()["snapshot"]["fields"]}
    assert "no_document" in keys and "missing_doc_warning_acknowledged" not in keys


# --- PATCH /gate and cancel ----------------------------------------------------------------------
async def test_edit_gate_by_creator_with_reason(
    client: AsyncClient,
    db_conn: Connection,
    masters: Masters,
    gate_token: Callable[[], tuple[uuid.UUID, str]],
) -> None:
    _, token = gate_token()
    gs = (await _create(client, token, masters, _values())).json()["goods_slip"]
    patch = {
        "party_id": str(masters.party),
        **_payload(_values(carton_count=5)),
        "reason": "Recounted boxes at gate",
    }
    res = await client.patch(f"/api/v1/gs/{gs['id']}/gate", json=patch, headers=_auth(token))
    assert res.status_code == 200, res.text
    assert res.json()["goods_slip"]["carton_count"] == 5
    assert res.json()["goods_slip"]["box_count"] == 5  # deprecated mirror (AMD-03)
    assert any(e["title"] == "Gate details edited" for e in res.json()["timeline"])
    audit = fetch_all(
        db_conn,
        "select reason, changed_fields from public.audit_log where table_name = "
        "'public.goods_slips' and row_id = :id and action = 'UPDATE'",
        id=gs["id"],
    )
    assert audit[-1]["reason"] == "Recounted boxes at gate"
    assert "box_count" in audit[-1]["changed_fields"]

    # DEC-51: another gate user (not the creator) may edit too (no task-ownership lock).
    _, other = gate_token()
    detail = await client.get(f"/api/v1/gs/{gs['id']}", headers=_auth(other))
    assert detail.json()["can_edit_gate"] is True
    res = await client.patch(f"/api/v1/gs/{gs['id']}/gate", json=patch, headers=_auth(other))
    assert res.status_code == 200, res.text

    # Once unboxing has started the gate details are frozen.
    as_admin(db_conn).execute(
        text("update public.goods_slips set status = 'UNBOXING' where id = :id"), {"id": gs["id"]}
    )
    res = await client.patch(f"/api/v1/gs/{gs['id']}/gate", json=patch, headers=_auth(token))
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "GS_NOT_EDITABLE"


async def test_edit_gate_requires_reason(
    client: AsyncClient, masters: Masters, gate_token: Callable[[], tuple[uuid.UUID, str]]
) -> None:
    _, token = gate_token()
    gs = (await _create(client, token, masters, _values())).json()["goods_slip"]
    res = await client.patch(
        f"/api/v1/gs/{gs['id']}/gate",
        json={"party_id": str(masters.party), **_payload(_values())},
        headers=_auth(token),
    )
    assert res.status_code == 422


async def test_cancel_admin_only_before_unboxing_completes(
    client: AsyncClient,
    db_conn: Connection,
    users: UserFactory,
    make_token: JwtFactory,
    masters: Masters,
    gate_token: Callable[[], tuple[uuid.UUID, str]],
) -> None:
    _, token = gate_token()
    gs = (await _create(client, token, masters, _values())).json()["goods_slip"]
    res = await client.post(
        f"/api/v1/gs/{gs['id']}/cancel", json={"reason": "Wrong party"}, headers=_auth(token)
    )
    assert res.status_code == 403

    admin = make_token(users.create(super_admin=True))
    res = await client.post(f"/api/v1/gs/{gs['id']}/cancel", json={}, headers=_auth(admin))
    assert res.status_code == 422  # reason mandatory
    res = await client.post(
        f"/api/v1/gs/{gs['id']}/cancel", json={"reason": "Duplicate entry"}, headers=_auth(admin)
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["goods_slip"]["status"] == "CANCELLED"
    assert body["goods_slip"]["cancel_reason"] == "Duplicate entry"
    assert {t["status"] for t in body["tasks"]} == {"CANCELLED"}
    assert body["timeline"][-1]["to_status"] == "CANCELLED"

    gs2 = (await _create(client, token, masters, _values())).json()["goods_slip"]
    force_gs_status(db_conn, gs2["id"], "ITEMIZATION")
    res = await client.post(
        f"/api/v1/gs/{gs2['id']}/cancel", json={"reason": "Too late"}, headers=_auth(admin)
    )
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "GS_NOT_CANCELLABLE"


# --- DEC-01: numbering ---------------------------------------------------------------------------
async def test_pattern_change_affects_only_subsequent_gs(
    client: AsyncClient,
    db_conn: Connection,
    users: UserFactory,
    make_token: JwtFactory,
    masters: Masters,
    gate_token: Callable[[], tuple[uuid.UUID, str]],
) -> None:
    _, token = gate_token()
    first = (await _create(client, token, masters, _values())).json()["goods_slip"]
    admin = make_token(users.create(super_admin=True))
    used = fetch_all(
        db_conn,
        """select coalesce(max(c.last_value), 0) as n from public.number_series_counters c
             join public.number_series s on s.id = c.series_id where s.code = 'GS'""",
    )[0]["n"]
    res = await client.put(
        "/api/v1/config/numbering/GS",
        json={
            "prefix": "GS",
            "pattern": "HX-{FY}-{SEQ:6}",
            "reset_policy": "YEARLY_FY",
            "fy_start_month": 4,
            "fy_format": "LONG",
            "start_value": max(int(used), 1),
            "reason": "P2-02 test",
        },
        headers=_auth(admin),
    )
    assert res.status_code == 200, res.text
    second = (await _create(client, token, masters, _values())).json()["goods_slip"]
    assert re.fullmatch(r"HX-\d{4}-\d{2}-\d{6}", second["gs_no"]), second["gs_no"]
    reread = (await client.get(f"/api/v1/gs/{first['id']}", headers=_auth(token))).json()
    assert reread["goods_slip"]["gs_no"] == first["gs_no"]
    assert GS_NO.fullmatch(first["gs_no"])


# --- DB layer: G-01 and the conditional CHECKs hold without the service --------------------------
def test_g01_gs_items_need_an_existing_gs(db_conn: Connection) -> None:
    conn = as_admin(db_conn)
    tag = uuid.uuid4().hex[:6].upper()
    cat = conn.execute(
        text("insert into public.product_categories (code, name) values (:c, :c) returning id"),
        {"c": f"G01_{tag}"},
    ).scalar_one()
    product = conn.execute(
        text(
            "insert into public.products (category_id, code, name) values (:cat, :c, :c) "
            "returning id"
        ),
        {"cat": cat, "c": f"G01P_{tag}"},
    ).scalar_one()
    with pytest.raises(IntegrityError, match="gs_items_gs_id_fkey"), conn.begin_nested():
        conn.execute(
            text(
                """insert into public.gs_items
                          (gs_id, line_no, product_id, category_id, documented_qty, received_qty)
                   values (:id, 1, :product, :cat, 1, 1)"""
            ),
            {"id": uuid.uuid4(), "product": product, "cat": cat},
        )


def _raw_gs(conn: Connection, **cols: Any) -> None:
    wv = conn.execute(
        text(
            """select v.id from public.workflow_versions v
                 join public.workflow_definitions d on d.id = v.workflow_definition_id
                where d.code = 'RMS_STANDARD' and v.status = 'PUBLISHED'"""
        )
    ).scalar_one()
    base = {"gs_no": f"RAW-{uuid.uuid4().hex[:8]}", "workflow_version_id": wv, "box_count": 1}
    base.update(cols)
    names = ", ".join(base)
    binds = ", ".join(f":{k}" for k in base)
    conn.execute(text(f"insert into public.goods_slips ({names}) values ({binds})"), base)  # noqa: S608


@pytest.mark.parametrize(
    ("cols", "constraint"),
    [
        ({"delivery_mode_code": "DIRECT_TRUCK", "vehicle_no": "X"}, "goods_slips_truck_fields"),
        ({"delivery_mode_code": "SELF_PARTY_REP", "rep_name": "A"}, "goods_slips_rep_fields"),
        (
            {
                "delivery_mode_code": "COURIER_PARCEL",
                "courier_name": "A",
                "docket_no": "1",
                "gate_document_code": "INVOICE",
                "gate_doc_no": "1",
            },
            "goods_slips_formal_doc_fields",
        ),
        (
            {
                "delivery_mode_code": "COURIER_PARCEL",
                "courier_name": "A",
                "docket_no": "1",
                "gate_document_code": "NO_DOCUMENT",
            },
            "goods_slips_no_document_flag",
        ),
    ],
)
def test_db_checks_reject_incomplete_rows(
    db_conn: Connection, cols: dict[str, Any], constraint: str
) -> None:
    conn = as_admin(db_conn)
    with pytest.raises(IntegrityError, match=constraint), conn.begin_nested():
        _raw_gs(conn, **cols)


def test_db_rejects_unknown_codes_and_gs_no_change(db_conn: Connection) -> None:
    conn = as_admin(db_conn)
    with pytest.raises(DBAPIError, match="Unknown or inactive delivery mode"), conn.begin_nested():
        _raw_gs(conn, delivery_mode_code="DIRECT_VEHICLE", vehicle_no="X")
    with conn.begin_nested():
        _raw_gs(
            conn,
            gs_no="RAW-IMMUTABLE-1",
            delivery_mode_code="COURIER_PARCEL",
            courier_name="A",
            docket_no="1",
        )
    with pytest.raises(DBAPIError, match="G-01"), conn.begin_nested():
        conn.execute(
            text("update public.goods_slips set gs_no = 'RAW-X' where gs_no = 'RAW-IMMUTABLE-1'")
        )
