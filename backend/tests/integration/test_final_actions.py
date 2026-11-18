"""Integration tests for change plan 2026-11-12 Phase 7 (AMD-16, AMD-17; DEC-41; G-20; G-21).

1. RM final actions: per item the qty available for action (counted - at departments) is split
   across the actions of the product's resolved ACTION profile; G-21 rejects any other total,
   actions outside the profile and finalising while pieces are at a department. Revisions are kept.
2. Finalise renders the server-side "Replacement Slip - A/c Actions" PDF, stores it as a
   GENERATED_PDF attachment (versioned slip row), notifies ACCOUNTS (rule-driven), is idempotent.
   Revising finalised actions needs a reason and supersedes the slip; re-print logs every print.
3. G-20 fix-forward: pieces back from a department that are actioned are not counted twice.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from app.core.db import get_session_factory
from app.core.errors import ServiceUnavailable
from app.core.middleware import limiter
from app.shared.storage import Bucket, get_storage
from tests.conftest import JwtFactory
from tests.integration.conftest import UserFactory, as_admin, build_test_app
from tests.integration.test_department_routing import (
    _dispatch,
    _plan,
    _seed_gs_held_at_intermediate_store,
)
from tests.integration.test_gate_inward import _auth
from tests.integration.test_unboxing import FakeStorage


@dataclass
class PdfStorage(FakeStorage):
    """FakeStorage plus server-side uploads (DEC-41 generated PDFs)."""

    uploads: dict[tuple[str, str], bytes] = field(default_factory=dict)
    fail_upload: bool = False

    def upload(self, bucket: Bucket, path: str, data: bytes, content_type: str) -> None:
        if self.fail_upload:
            raise ServiceUnavailable("File storage request failed", code="STORAGE_ERROR")
        self.uploads[(bucket.value, path)] = data
        self.put(bucket.value, path, len(data), content_type)


def _key() -> str:
    return f"test-ph7-{uuid.uuid4().hex}"


@pytest.fixture
def storage() -> PdfStorage:
    return PdfStorage()


@pytest.fixture
async def client(
    session_factory: sessionmaker[Session], storage: PdfStorage
) -> AsyncIterator[AsyncClient]:
    app = build_test_app()
    app.dependency_overrides[get_session_factory] = lambda: session_factory
    app.dependency_overrides[get_storage] = lambda: storage
    limiter.reset()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    limiter.reset()


@pytest.fixture
def actors(users: UserFactory, make_token: JwtFactory) -> dict[str, Any]:
    aman_id = users.create(roles=["INWARD_VERIFIER"], full_name="Aman")
    rm_id = users.create(roles=["REPLACEMENT_MANAGER"], full_name="Pratham")
    acc_id = users.create(roles=["ACCOUNTS"], full_name="Deepak")
    tech_id = users.create(roles=["TECHNICIAN"], full_name="Ramesh")
    store_id = users.create(roles=["INTERMEDIATE_STORE_MANAGER"], full_name="Sanjay")
    return {
        "aman": make_token(aman_id),
        "store": make_token(store_id),
        "rm": make_token(rm_id),
        "rm_id": str(rm_id),
        "accounts": make_token(acc_id),
        "accounts_id": str(acc_id),
        "tech": make_token(tech_id),
    }


def _url(gs_id: str, suffix: str = "") -> str:
    return f"/api/v1/gs/{gs_id}/final-actions{suffix}"


def _split(item_id: str, **qty: int) -> dict[str, Any]:
    return {
        "gs_item_id": item_id,
        "actions": [{"action_code": c, "qty": q} for c, q in qty.items()],
    }


async def _dispatch_and_receive(
    client: AsyncClient,
    actors: dict[str, Any],
    fx: dict[str, Any],
    *,
    sent: int,
    booked: dict[str, int],
) -> str:
    """Send `sent` pcs to REPAIR (RM plans, Store Manager issues; DEC-55) and book them back
    into the given outcome heads."""
    res = await _dispatch(client, actors, fx, sent, _key())
    assert res.status_code == 200, res.text
    routing = res.json()
    if booked:
        heads = (
            await client.get(
                "/api/v1/department-routing/outcome-heads", headers=_auth(actors["aman"])
            )
        ).json()
        head_id = {h["code"]: h["id"] for h in heads}
        rec = await client.post(
            f"/api/v1/department-routing/{routing['id']}/receive",
            headers=_auth(actors["aman"], _key()),
            json={
                "routing_id": routing["id"],
                "lines": [
                    {
                        "routing_line_id": routing["lines"][0]["id"],
                        "outcome_head_id": head_id[code],
                        "quantity": q,
                    }
                    for code, q in booked.items()
                ],
            },
        )
        assert rec.status_code == 200, rec.text
    return str(routing["id"])


# =================================================================================================


async def test_state_shows_available_qty_and_profile_actions(
    client: AsyncClient, db_conn: Connection, actors: dict[str, Any]
) -> None:
    fx = _seed_gs_held_at_intermediate_store(db_conn)
    res = await client.get(_url(fx["gs_id"]), headers=_auth(actors["rm"]))
    assert res.status_code == 200, res.text
    state = res.json()
    assert state["on_final_action_flow"] is True
    assert state["can_edit"] is True
    assert state["can_finalise"] is False
    assert "No final actions have been saved yet." in state["finalise_blockers"]
    line = state["lines"][0]
    assert (line["counted_qty"], line["at_departments_qty"], line["available_qty"]) == (10, 0, 10)
    codes = {a["code"] for a in line["allowed_actions"]}
    assert {"SEND_NEW", "SEND_REPAIRED", "ISSUE_CN", "NOT_ALLOWED"} <= codes
    cn = next(a for a in line["allowed_actions"] if a["code"] == "ISSUE_CN")
    assert cn["requires_cn"] is True  # AMD-18 flag carried for Phase 8

    # Accounts can read; a technician cannot.
    assert (
        await client.get(_url(fx["gs_id"]), headers=_auth(actors["accounts"]))
    ).status_code == 200
    assert (await client.get(_url(fx["gs_id"]), headers=_auth(actors["tech"]))).status_code == 403


async def test_g21_split_must_equal_available_qty(
    client: AsyncClient, db_conn: Connection, actors: dict[str, Any]
) -> None:
    """AMD-16 / G-21: 10 pcs -> 6 Send New, 3 Send Repaired, 1 Issue CN; 9 or 11 are rejected."""
    fx = _seed_gs_held_at_intermediate_store(db_conn)
    for bad in ({"SEND_NEW": 6, "SEND_REPAIRED": 3}, {"SEND_NEW": 8, "ISSUE_CN": 3}):
        res = await client.put(
            _url(fx["gs_id"]),
            headers=_auth(actors["rm"], _key()),
            json={"lines": [_split(fx["item_id"], **bad)]},
        )
        assert res.status_code == 409, res.text
        assert res.json()["error"]["code"] == "G-21"

    # Idempotency-Key is mandatory (G-16) and Accounts may not edit.
    no_key = await client.put(
        _url(fx["gs_id"]),
        headers=_auth(actors["rm"]),
        json={"lines": [_split(fx["item_id"], SEND_NEW=10)]},
    )
    assert no_key.status_code in (400, 422), no_key.text
    forbidden = await client.put(
        _url(fx["gs_id"]),
        headers=_auth(actors["accounts"], _key()),
        json={"lines": [_split(fx["item_id"], SEND_NEW=10)]},
    )
    assert forbidden.status_code == 403

    ok = await client.put(
        _url(fx["gs_id"]),
        headers=_auth(actors["rm"], _key()),
        json={"lines": [_split(fx["item_id"], SEND_NEW=6, SEND_REPAIRED=3, ISSUE_CN=1)]},
    )
    assert ok.status_code == 200, ok.text
    state = ok.json()
    assert state["current_revision_no"] == 1
    assert state["lines"][0]["is_balanced"] is True
    assert {a["action_code"]: a["qty"] for a in state["lines"][0]["current_actions"]} == {
        "SEND_NEW": 6,
        "SEND_REPAIRED": 3,
        "ISSUE_CN": 1,
    }
    assert state["can_finalise"] is True

    # A second, different split is a new revision; history keeps both (AMD-16 "revisions kept").
    ok2 = await client.put(
        _url(fx["gs_id"]),
        headers=_auth(actors["rm"], _key()),
        json={"lines": [_split(fx["item_id"], SEND_NEW=7, ISSUE_CN=3)]},
    )
    assert ok2.status_code == 200, ok2.text
    assert [r["revision_no"] for r in ok2.json()["revisions"]] == [2, 1]

    # G-20 panel: all 10 actioned, nothing counted twice.
    recon = (
        await client.get(
            f"/api/v1/department-routing/gs/{fx['gs_id']}/reconciliation",
            headers=_auth(actors["rm"]),
        )
    ).json()
    assert recon["is_fully_reconciled"] is True
    assert (recon["total_in_store"], recon["total_actioned"]) == (0, 10)


async def test_g21_action_outside_resolved_profile_rejected(
    client: AsyncClient, db_conn: Connection, actors: dict[str, Any]
) -> None:
    """AMD-10/16: a PRODUCT-scope ACTION profile with only Send New wins over the category."""
    fx = _seed_gs_held_at_intermediate_store(db_conn)
    c = as_admin(db_conn)
    c.execute(
        text(
            """
            insert into public.item_field_assignments
                   (field_id, field_group, scope_type, product_id, is_included)
            select id, 'ACTION', 'PRODUCT', cast(:pid as uuid), true
              from public.item_field_library where field_group = 'ACTION' and code = 'SEND_NEW'
            """
        ),
        {"pid": fx["product_id"]},
    )
    state = (await client.get(_url(fx["gs_id"]), headers=_auth(actors["rm"]))).json()
    assert [a["code"] for a in state["lines"][0]["allowed_actions"]] == ["SEND_NEW"]

    res = await client.put(
        _url(fx["gs_id"]),
        headers=_auth(actors["rm"], _key()),
        json={"lines": [_split(fx["item_id"], SEND_NEW=9, ISSUE_CN=1)]},
    )
    assert res.status_code == 409, res.text
    assert res.json()["error"]["code"] == "G-21"
    assert "not allowed" in res.json()["error"]["message"]


async def test_department_round_trip_then_finalise_generates_pdf_and_alerts_accounts(
    client: AsyncClient, db_conn: Connection, actors: dict[str, Any], storage: PdfStorage
) -> None:
    fx = _seed_gs_held_at_intermediate_store(db_conn)
    gs_id, item_id = fx["gs_id"], fx["item_id"]
    routing_id = await _dispatch_and_receive(client, actors, fx, sent=5, booked={})

    # 5 at REPAIR: only 5 are available for action (G-21) ...
    state = (await client.get(_url(gs_id), headers=_auth(actors["rm"]))).json()
    assert state["lines"][0]["available_qty"] == 5
    full = await client.put(
        _url(gs_id),
        headers=_auth(actors["rm"], _key()),
        json={"lines": [_split(item_id, SEND_NEW=10)]},
    )
    assert full.status_code == 409 and full.json()["error"]["code"] == "G-21"
    part = await client.put(
        _url(gs_id),
        headers=_auth(actors["rm"], _key()),
        json={"lines": [_split(item_id, SEND_NEW=5)]},
    )
    assert part.status_code == 200, part.text

    # ... and finalising is blocked while pieces are at a department.
    blocked = await client.post(
        _url(gs_id, "/finalise"), headers=_auth(actors["rm"], _key()), json={}
    )
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "G-21"
    assert "at a department" in blocked.json()["error"]["message"]

    # Department returns 4 Repaired + 1 Wastage (DEC-43).
    heads = (
        await client.get("/api/v1/department-routing/outcome-heads", headers=_auth(actors["aman"]))
    ).json()
    head_id = {h["code"]: h["id"] for h in heads}
    routing = (
        await client.get(f"/api/v1/department-routing/{routing_id}", headers=_auth(actors["aman"]))
    ).json()
    rec = await client.post(
        f"/api/v1/department-routing/{routing_id}/receive",
        headers=_auth(actors["aman"], _key()),
        json={
            "routing_id": routing_id,
            "lines": [
                {
                    "routing_line_id": routing["lines"][0]["id"],
                    "outcome_head_id": head_id[h],
                    "quantity": q,
                }
                for h, q in (("REPAIRED", 4), ("WASTAGE", 1))
            ],
        },
    )
    assert rec.status_code == 200, rec.text

    # G-20 fix-forward: 5 outcome pcs + 5 actioned pcs of 10 counted is conserved (no double count).
    recon = (
        await client.get(
            f"/api/v1/department-routing/gs/{gs_id}/reconciliation", headers=_auth(actors["rm"])
        )
    ).json()
    assert recon["is_fully_reconciled"] is True
    assert recon["total_counted"] == 10

    state = (await client.get(_url(gs_id), headers=_auth(actors["rm"]))).json()
    line = state["lines"][0]
    assert (line["available_qty"], line["actioned_qty"], line["is_balanced"]) == (10, 5, False)
    assert {o["outcome_code"]: o["qty"] for o in line["outcomes"]} == {"REPAIRED": 4, "WASTAGE": 1}

    save = await client.put(
        _url(gs_id),
        headers=_auth(actors["rm"], _key()),
        json={"lines": [_split(item_id, SEND_NEW=6, SEND_REPAIRED=3, ISSUE_CN=1)]},
    )
    assert save.status_code == 200, save.text
    recon2 = (
        await client.get(
            f"/api/v1/department-routing/gs/{gs_id}/reconciliation", headers=_auth(actors["rm"])
        )
    ).json()
    assert recon2["is_fully_reconciled"] is True
    assert (recon2["total_in_store"], recon2["total_outcomes"], recon2["total_actioned"]) == (
        0,
        0,
        10,
    )

    # Accounts may not finalise.
    assert (
        await client.post(
            _url(gs_id, "/finalise"), headers=_auth(actors["accounts"], _key()), json={}
        )
    ).status_code == 403

    key = _key()
    fin = await client.post(
        _url(gs_id, "/finalise"), headers=_auth(actors["rm"], key), json={"remarks": "All checked"}
    )
    assert fin.status_code == 200, fin.text
    state = fin.json()
    assert state["is_finalised"] is True
    slip = state["current_slip"]
    assert slip["slip_no"].startswith("RSA/") and slip["version_no"] == 1
    assert slip["total_qty"] == 10
    assert {t["action_code"]: t["qty"] for t in slip["action_totals"]} == {
        "SEND_NEW": 6,
        "SEND_REPAIRED": 3,
        "ISSUE_CN": 1,
    }
    assert state["can_edit"] is True and state["can_finalise"] is False

    # Server-side PDF stored once (DEC-41) and linked as a GENERATED_PDF attachment.
    assert len(storage.uploads) == 1
    (bucket, path), pdf = next(iter(storage.uploads.items()))
    assert bucket == "rms-documents" and path.startswith(f"gs/{gs_id}/generated_pdf/")
    assert pdf.startswith(b"%PDF-")
    c = as_admin(db_conn)
    row = (
        c.execute(
            text(
                """
                select a.kind, a.status, a.mime_type, s.status as slip_status, s.revision_no,
                       s.content ->> 'gs_no' as gs_no, jsonb_array_length(s.content -> 'lines') as n
                  from public.ac_action_slips s join public.attachments a on a.id = s.attachment_id
                 where s.gs_id = cast(:g as uuid)
                """
            ),
            {"g": gs_id},
        )
        .mappings()
        .one()
    )
    assert (row["kind"], row["status"], row["mime_type"]) == (
        "GENERATED_PDF",
        "CONFIRMED",
        "application/pdf",
    )
    assert (row["slip_status"], row["gs_no"], row["n"]) == ("CURRENT", fx["gs_no"], 3)

    # AMD-17: ACCOUNTS notified through the seeded rule.
    n = c.execute(
        text(
            "select count(*) from public.notifications"
            " where user_id = cast(:u as uuid) and type = 'AC_ACTIONS_SLIP_READY'"
        ),
        {"u": actors["accounts_id"]},
    ).scalar_one()
    assert n == 1

    # Idempotent replay: same key, same body, no second slip / upload (G-16).
    replay = await client.post(
        _url(gs_id, "/finalise"), headers=_auth(actors["rm"], key), json={"remarks": "All checked"}
    )
    assert replay.status_code == 200
    assert replay.json()["current_slip"]["id"] == slip["id"]
    assert len(storage.uploads) == 1
    again = await client.post(
        _url(gs_id, "/finalise"), headers=_auth(actors["rm"], _key()), json={}
    )
    assert again.status_code == 409 and again.json()["error"]["code"] == "ALREADY_FINALISED"


async def _finalised_gs(
    client: AsyncClient, db_conn: Connection, actors: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    fx = _seed_gs_held_at_intermediate_store(db_conn)
    save = await client.put(
        _url(fx["gs_id"]),
        headers=_auth(actors["rm"], _key()),
        json={"lines": [_split(fx["item_id"], SEND_NEW=6, SEND_REPAIRED=3, ISSUE_CN=1)]},
    )
    assert save.status_code == 200, save.text
    fin = await client.post(
        _url(fx["gs_id"], "/finalise"), headers=_auth(actors["rm"], _key()), json={}
    )
    assert fin.status_code == 200, fin.text
    return fx, fin.json()["current_slip"]


async def test_revision_after_finalise_needs_reason_and_supersedes_slip(
    client: AsyncClient, db_conn: Connection, actors: dict[str, Any], storage: PdfStorage
) -> None:
    fx, slip1 = await _finalised_gs(client, db_conn, actors)
    gs_id, item_id = fx["gs_id"], fx["item_id"]
    changed = {"lines": [_split(item_id, SEND_NEW=5, SEND_REPAIRED=4, ISSUE_CN=1)]}

    no_reason = await client.put(_url(gs_id), headers=_auth(actors["rm"], _key()), json=changed)
    assert no_reason.status_code == 422 and no_reason.json()["error"]["code"] == "REASON_REQUIRED"
    same = await client.put(
        _url(gs_id),
        headers=_auth(actors["rm"], _key()),
        json={"lines": [_split(item_id, SEND_NEW=6, SEND_REPAIRED=3, ISSUE_CN=1)], "reason": "x"},
    )
    assert same.status_code == 422 and same.json()["error"]["code"] == "NO_CHANGE"

    rev = await client.put(
        _url(gs_id),
        headers=_auth(actors["rm"], _key()),
        json={**changed, "reason": "One more piece repaired"},
    )
    assert rev.status_code == 200, rev.text
    state = rev.json()
    assert state["is_finalised"] is False
    old = next(s for s in state["slips"] if s["id"] == slip1["id"])
    assert old["status"] == "SUPERSEDED" and old["supersede_reason"] == "One more piece repaired"
    n = (
        as_admin(db_conn)
        .execute(
            text(
                "select count(*) from public.notifications"
                " where user_id = cast(:u as uuid) and type = 'AC_ACTIONS_SLIP_SUPERSEDED'"
            ),
            {"u": actors["accounts_id"]},
        )
        .scalar_one()
    )
    assert n == 1

    fin2 = await client.post(_url(gs_id, "/finalise"), headers=_auth(actors["rm"], _key()), json={})
    assert fin2.status_code == 200, fin2.text
    slip2 = fin2.json()["current_slip"]
    assert (slip2["slip_no"], slip2["version_no"], slip2["revision_no"]) == (slip1["slip_no"], 2, 2)
    assert len(storage.uploads) == 2


async def test_print_and_reprint_are_logged(
    client: AsyncClient, db_conn: Connection, actors: dict[str, Any], storage: PdfStorage
) -> None:
    fx, slip = await _finalised_gs(client, db_conn, actors)
    url = _url(fx["gs_id"], f"/slips/{slip['id']}/print")
    first = await client.post(url, headers=_auth(actors["accounts"]))
    assert first.status_code == 200, first.text
    assert first.json()["print_count"] == 1 and first.json()["url"].startswith(
        "http://storage.test/"
    )
    second = await client.post(url, headers=_auth(actors["rm"]))
    assert second.json()["print_count"] == 2
    assert (await client.post(url, headers=_auth(actors["tech"]))).status_code == 403
    missing = await client.post(
        _url(fx["gs_id"], f"/slips/{uuid.uuid4()}/print"), headers=_auth(actors["rm"])
    )
    assert missing.status_code == 404

    rows = (
        as_admin(db_conn)
        .execute(
            text(
                "select count(*), bool_or((metadata ->> 'is_reprint')::boolean)"
                " from public.print_logs"
                " where template_code = 'AC_ACTIONS_SLIP' and entity_id = cast(:s as uuid)"
            ),
            {"s": slip["id"]},
        )
        .one()
    )
    assert (rows[0], rows[1]) == (2, True)
    state = (await client.get(_url(fx["gs_id"]), headers=_auth(actors["rm"]))).json()
    assert state["current_slip"]["print_count"] == 2


async def test_storage_failure_and_db_failure_leave_no_slip_or_orphan(
    client: AsyncClient,
    db_conn: Connection,
    actors: dict[str, Any],
    storage: PdfStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fx = _seed_gs_held_at_intermediate_store(db_conn)
    await client.put(
        _url(fx["gs_id"]),
        headers=_auth(actors["rm"], _key()),
        json={"lines": [_split(fx["item_id"], SEND_NEW=10)]},
    )
    storage.fail_upload = True
    res = await client.post(
        _url(fx["gs_id"], "/finalise"), headers=_auth(actors["rm"], _key()), json={}
    )
    assert res.status_code == 503 and res.json()["error"]["code"] == "STORAGE_ERROR"
    storage.fail_upload = False

    # A DB failure after the upload removes the stored file again (no orphan, rule j: not silent).
    from app.modules.final_actions import repository

    def boom(*_a: Any, **_k: Any) -> None:
        raise ServiceUnavailable("simulated", code="SIMULATED")

    monkeypatch.setattr(repository, "insert_slip", boom)
    res2 = await client.post(
        _url(fx["gs_id"], "/finalise"), headers=_auth(actors["rm"], _key()), json={}
    )
    assert res2.status_code == 503
    assert len(storage.deleted) == 1 and not storage.objects
    count = (
        as_admin(db_conn)
        .execute(
            text("select count(*) from public.ac_action_slips where gs_id = cast(:g as uuid)"),
            {"g": fx["gs_id"]},
        )
        .scalar_one()
    )
    assert count == 0


async def test_legacy_rm_actions_endpoint_refuses_amd13_goods_slip(
    client: AsyncClient, db_conn: Connection, actors: dict[str, Any]
) -> None:
    fx = _seed_gs_held_at_intermediate_store(db_conn)
    res = await client.put(
        f"/api/v1/gs/{fx['gs_id']}/rm-actions",
        headers=_auth(actors["rm"]),
        json={"lines": [_split(fx["item_id"], SEND_NEW=10)]},
    )
    assert res.status_code == 409, res.text
    assert res.json()["error"]["code"] == "USE_FINAL_ACTIONS"


async def test_db_guards_reject_direct_writes(
    client: AsyncClient, db_conn: Connection, actors: dict[str, Any]
) -> None:
    """G-21 in the DB: no API path needed to be bypassed for these to hold."""
    fx, slip = await _finalised_gs(client, db_conn, actors)
    c = as_admin(db_conn)

    def rejected(sql: str, params: dict[str, Any]) -> str:
        sp = c.begin_nested()
        with pytest.raises(DBAPIError) as exc:
            c.execute(text(sql), params)
        sp.rollback()
        return str(exc.value)

    # Finalised: no action row may change until the slip is superseded.
    msg = rejected(
        """
        insert into public.rm_item_actions (gs_item_id, revision_no, action_code, qty, decided_by)
        values (cast(:i as uuid), 9, 'SEND_NEW', 1, cast(:u as uuid))
        """,
        {"i": fx["item_id"], "u": actors["rm_id"]},
    )
    assert "G-21" in msg and "finalised" in msg
    # The slip is immutable except CURRENT -> SUPERSEDED (with a reason) and never deleted.
    assert "G-21" in rejected(
        "update public.ac_action_slips set remarks = 'edited' where id = cast(:s as uuid)",
        {"s": slip["id"]},
    )
    assert "G-21" in rejected(
        "delete from public.ac_action_slips where id = cast(:s as uuid)", {"s": slip["id"]}
    )
    assert "ac_action_slips_superseded_fields" in rejected(
        """
        update public.ac_action_slips set status = 'SUPERSEDED', superseded_at = now(),
               superseded_by = cast(:u as uuid), supersede_reason = ' '
         where id = cast(:s as uuid)
        """,
        {"s": slip["id"], "u": actors["rm_id"]},
    )
    # G-21 sum check on an unbalanced GS (7 of 10 actioned) and a direct slip insert for it.
    fx2 = _seed_gs_held_at_intermediate_store(db_conn)
    c.execute(
        text(
            """
            insert into public.rm_item_actions
                   (gs_item_id, revision_no, action_code, qty, decided_by)
            values (cast(:i as uuid), 1, 'SEND_NEW', 7, cast(:u as uuid))
            """
        ),
        {"i": fx2["item_id"], "u": actors["rm_id"]},
    )
    assert "G-21" in rejected(
        "select rms_private.validate_final_action_split(cast(:g as uuid), false)",
        {"g": fx2["gs_id"]},
    )
    assert "G-21" in rejected(
        """
        insert into public.ac_action_slips
               (gs_id, slip_no, version_no, revision_no, attachment_id, template_version_no,
                content, totals, sha256, finalised_by)
        values (cast(:g as uuid), 'RSA/TEST/1', 1, 1, gen_random_uuid(), 1, '{}', '{}',
                repeat('a', 64), cast(:u as uuid))
        """,
        {"g": fx2["gs_id"], "u": actors["rm_id"]},
    )
    # The finalised, balanced GS passes the same check.
    c.execute(
        text("select rms_private.validate_final_action_split(cast(:g as uuid), true)"),
        {"g": fx["gs_id"]},
    )


async def test_g21_finalise_blocked_while_routing_is_planned_not_issued(
    client: AsyncClient, db_conn: Connection, actors: dict[str, Any]
) -> None:
    """DEC-55 / G-21: pieces planned for a department wait for the Store issue; finalising is
    blocked (state blocker + 409) until they are issued (and received) or the plan is cancelled."""
    fx = _seed_gs_held_at_intermediate_store(db_conn)
    gs_id, item_id = fx["gs_id"], fx["item_id"]

    # 2 pcs planned to REPAIR, not issued: the state shows the blocker ...
    plan_res = await _plan(client, actors["rm"], fx, 2)
    assert plan_res.status_code == 200, plan_res.text
    state = (await client.get(_url(gs_id), headers=_auth(actors["rm"]))).json()
    assert any("planned for a department" in b for b in state["finalise_blockers"])

    # ... and the planned pieces cannot be actioned away (G-20: planned <= in store).
    saved = await client.put(
        _url(gs_id),
        headers=_auth(actors["rm"], _key()),
        json={"lines": [_split(item_id, SEND_NEW=10)]},
    )
    assert saved.status_code == 409, saved.text
    assert saved.json()["error"]["code"] == "G-20"

    # Once the store issues them, the 2 pcs are at the department: 8 are available for action.
    plan_ids = [ln["id"] for ln in plan_res.json()["lines"]]
    issue = await client.post(
        "/api/v1/department-routing/issue",
        headers=_auth(actors["store"], _key()),
        json={
            "gs_id": gs_id,
            "department_field_id": fx["repair_dept_id"],
            "plan_line_ids": plan_ids,
        },
    )
    assert issue.status_code == 200, issue.text
    state = (await client.get(_url(gs_id), headers=_auth(actors["rm"]))).json()
    assert not any("planned for a department" in b for b in state["finalise_blockers"])
    assert state["lines"][0]["available_qty"] == 8


async def test_g21_plan_after_all_pieces_are_actioned_is_rejected(
    client: AsyncClient, db_conn: Connection, actors: dict[str, Any]
) -> None:
    """DEC-55 / G-20: routing is planned before final actions; once every piece is actioned
    nothing is left in the store to plan."""
    fx = _seed_gs_held_at_intermediate_store(db_conn)
    saved = await client.put(
        _url(fx["gs_id"]),
        headers=_auth(actors["rm"], _key()),
        json={"lines": [_split(fx["item_id"], SEND_NEW=10)]},
    )
    assert saved.status_code == 200, saved.text
    planned = await _plan(client, actors["rm"], fx, 2)
    assert planned.status_code == 409, planned.text
    assert "G-20" in planned.json()["error"]["message"]
