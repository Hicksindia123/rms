"""Integration tests for change plan 2026-11-12 Phase 9 (AMD-20; BR-38, DD r79, DEC-25, DEC-48;
G-15, G-16, G-18).

1. The party email is built from the values Accounts entered on the completed A/c Actions slip
   (CN No./Date/Value, Challan No./Date) and the Dispatch Slip tracking data once dispatched.
2. Preview -> send -> log: a SENT email records PRIOR_INFO_SENT (EMAIL_SENT), which the closure
   checklist (G-15) needs; the send is idempotent (G-16); failures are retried, then FAILED.
3. Resend creates a new logged email. Content is frozen at insert (G-18); the log is never deleted.
4. Auto-send is OFF by default and only queues when party_email.delivery enables it.
5. Admin: template placeholders are validated; preview renders sample values.
"""

from __future__ import annotations

import json
import smtplib
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.core.db import UnitOfWork, get_session_factory
from app.core.middleware import limiter
from app.modules.notifications.email import OutgoingEmail
from app.modules.party_notifications import email_service
from app.modules.party_notifications.schemas import PartyEmailTemplate
from app.shared.storage import get_storage
from tests.conftest import JwtFactory
from tests.integration.conftest import UserFactory, as_admin, build_test_app
from tests.integration.test_ac_entry_dispatch import _complete, _fill_all, _finalise
from tests.integration.test_final_actions import PdfStorage
from tests.integration.test_gate_inward import _auth

TODAY = date.today()
PARTY_EMAIL = "party.ph9@example.com"


def _key() -> str:
    return f"test-ph9-{uuid.uuid4().hex}"


class FakeSmtp:
    """Context-manager sender recording mails; `fail_with` makes every send raise."""

    def __init__(self) -> None:
        self.sent: list[OutgoingEmail] = []
        self.fail_with: Exception | None = None

    def factory(self, _settings: Settings) -> FakeSmtp:
        return self

    def __enter__(self) -> FakeSmtp:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def send(self, mail: OutgoingEmail) -> None:
        if self.fail_with:
            raise self.fail_with
        self.sent.append(mail)


@pytest.fixture
def fake_smtp(monkeypatch: pytest.MonkeyPatch) -> FakeSmtp:
    """SMTP ON (fake host) for the party email service; the sender is faked (rule i)."""
    fake = FakeSmtp()
    cfg = get_settings().model_copy(
        update={
            "smtp_host": "smtp.test.local",
            "smtp_from": "rms@test.local",
            "smtp_use_tls": False,
        }
    )
    monkeypatch.setattr(email_service, "get_settings", lambda: cfg)
    monkeypatch.setattr(email_service, "SmtpSender", fake.factory)
    return fake


@pytest.fixture
def no_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = get_settings().model_copy(update={"smtp_host": None, "smtp_from": None})
    monkeypatch.setattr(email_service, "get_settings", lambda: cfg)


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
def uow(session_factory: sessionmaker[Session]) -> UnitOfWork:
    return UnitOfWork(session_factory)


@pytest.fixture
def actors(users: UserFactory, make_token: JwtFactory) -> dict[str, Any]:
    rm_id = users.create(roles=["REPLACEMENT_MANAGER"], full_name="Pratham")
    acc_id = users.create(roles=["ACCOUNTS"], full_name="Deepak")
    disp_id = users.create(roles=["DISPATCH"], full_name="Vikas")
    admin_id = users.create(super_admin=True, full_name="Admin")
    return {
        "rm": make_token(rm_id),
        "accounts": make_token(acc_id),
        "dispatch": make_token(disp_id),
        "admin": make_token(admin_id),
    }


def _attach_party(db_conn: Connection, gs_id: str, email: str | None = PARTY_EMAIL) -> None:
    """The Phase 6 seed has no party: give the GS one with the given e-mail address."""
    c = as_admin(db_conn)
    party_id = c.execute(
        text("select id from public.parties where is_active order by code limit 1")
    ).scalar_one()
    c.execute(
        text("update public.parties set email = :e where id = :p"), {"e": email, "p": party_id}
    )
    c.execute(text("set session_replication_role = 'replica'"))
    c.execute(
        text("update public.goods_slips set party_id = :p where id = cast(:g as uuid)"),
        {"p": party_id, "g": gs_id},
    )
    c.execute(text("set session_replication_role = 'origin'"))


async def _completed(
    client: AsyncClient,
    db_conn: Connection,
    actors: dict[str, Any],
    *,
    email: str | None = PARTY_EMAIL,
    **split: int,
) -> dict[str, Any]:
    """Phase 7 + 8: finalised (default 6 Send New / 3 Send Repaired / 1 Issue CN), Accounts
    entered every value (CN No. per GS) and completed."""
    fx = await _finalise(client, db_conn, actors, **split)
    _attach_party(db_conn, fx["gs_id"], email)
    fx["cn_no"] = f"CN-PH9-{uuid.uuid4().hex[:6]}"
    await _fill_all(client, actors, fx, fx["cn_no"])
    done = await _complete(client, actors, fx)
    assert done.status_code == 200, done.text
    fx["dispatch_slip"] = done.json()["dispatch_slip"]
    return fx


async def _state(client: AsyncClient, token: str, gs_id: str) -> dict[str, Any]:
    res = await client.get(f"/api/v1/gs/{gs_id}/party-notifications", headers=_auth(token))
    assert res.status_code == 200, res.text
    return dict(res.json())


async def _send(
    client: AsyncClient, token: str, gs_id: str, key: str | None = None, **body: Any
) -> Any:
    return await client.post(
        f"/api/v1/gs/{gs_id}/party-emails",
        headers=_auth(token, key or _key()),
        json={"to": PARTY_EMAIL} | body,
    )


def _checklist_item(db_conn: Connection, gs_id: str, code: str) -> dict[str, Any]:
    row = (
        as_admin(db_conn)
        .execute(
            text(
                "select applicable, passed from rms_private.gs_closure_checklist(cast(:g as uuid))"
                " where code = :c"
            ),
            {"g": gs_id, "c": code},
        )
        .mappings()
        .one()
    )
    return dict(row)


def _set_delivery(db_conn: Connection, value: dict[str, Any]) -> None:
    as_admin(db_conn).execute(
        text("update public.system_settings set value = cast(:v as jsonb) where key = :k"),
        {"v": json.dumps(value), "k": "party_email.delivery"},
    )


# =================================================================================================


def test_render_uses_accounts_values_and_drops_empty_lines() -> None:
    """AMD-20 / DEC-48: line templates per CN / challan; a body line whose placeholders are all
    empty is left out (no CN on the slip -> no CN heading)."""
    tpl = PartyEmailTemplate(
        subject="GS {gs_no}",
        body="Dear {party_name},\nCN:{cn_lines}\nTotal: {cn_total_value}\nChallan:{challan_lines}",
        cn_line="- {cn_no} {cn_date} {cn_value}",
        challan_line="- {challan_no} {challan_date} x{qty}",
        dispatch_line="- {dispatch_slip_no}",
    )
    snap = dict(email_service.SAMPLE_SNAPSHOT)
    subject, body = email_service.render_email(tpl, snap, "%d-%m-%Y")
    assert subject == "GS GS/2026-27/00042"
    assert "- CN-1234 14-11-2026 1,250.50" in body
    assert "- CH-5678 14-11-2026 x3" in body
    assert "Total: 1,250.50" in body

    no_cn = snap | {"cn_lines": [], "cn_total_value": None}
    _, body2 = email_service.render_email(tpl, no_cn, "%d-%m-%Y")
    assert "CN:" not in body2 and "Total:" not in body2 and "Challan:" in body2
    # A dropped section leaves at most one blank line.
    gap = tpl.model_copy(update={"body": "A\n\nX:{dispatch_details}\n\nB"})
    _, body3 = email_service.render_email(gap, no_cn | {"dispatch": None}, "%d-%m-%Y")
    assert body3 == "A\n\nB"


def test_template_validation_rejects_unknown_placeholders() -> None:
    bad = PartyEmailTemplate(
        subject="{gs_no} {cn_no}",  # cn_no belongs to the line template only
        body="{party_name} {",
        cn_line="{cn_no}",
        challan_line="{challan_no}",
        dispatch_line="{docket_no}",
    )
    with pytest.raises(email_service.ValidationFailed) as exc:
        email_service.validate_template(bad)
    assert exc.value.code == "TEMPLATE_INVALID"
    assert set(exc.value.details or {}) == {"subject", "body"}


async def test_send_builds_from_accounts_values_records_prior_info_and_is_idempotent(
    client: AsyncClient, db_conn: Connection, actors: dict[str, Any], fake_smtp: FakeSmtp
) -> None:
    fx = await _completed(client, db_conn, actors)
    gs_id = fx["gs_id"]

    state = await _state(client, actors["accounts"], gs_id)
    panel = state["party_email"]
    assert panel["ready"] is True and panel["can_send"] is True
    assert panel["auto_send"] == "OFF" and panel["emails"] == []  # AMD-20: no auto-send by default
    assert panel["to"] == PARTY_EMAIL
    assert fx["cn_no"] in panel["body"] and "Challan CH-SEND_NEW" in panel["body"]
    assert "Dispatch Slip" not in panel["body"]  # not dispatched yet: no tracking data
    assert [ln["cn_no"] for ln in panel["snapshot"]["cn_lines"]] == [fx["cn_no"]]
    assert {ln["action_code"] for ln in panel["snapshot"]["challan_lines"]} == {
        "SEND_NEW",
        "SEND_REPAIRED",
    }
    # The manual-record draft on this flow comes from the same Accounts values.
    assert state["drafts"][0]["source"] == "AC_ACTIONS"
    assert state["drafts"][0]["voucher_no"] == fx["cn_no"]
    assert _checklist_item(db_conn, gs_id, "PRIOR_NOTIFICATION") == {
        "applicable": True,
        "passed": False,
    }

    key = _key()
    res = await _send(client, actors["accounts"], gs_id, key, cc=["accounts.copy@example.com"])
    assert res.status_code == 201, res.text
    mail = res.json()
    assert (mail["status"], mail["trigger_code"], mail["attempts"]) == ("SENT", "MANUAL", 1)
    assert mail["party_notification_id"] is not None
    assert len(fake_smtp.sent) == 1
    sent = fake_smtp.sent[0]
    assert sent.to == PARTY_EMAIL and sent.cc == ("accounts.copy@example.com",)
    assert fx["cn_no"] in sent.body and sent.subject == panel["subject"]

    # BR-38 / G-15: the SENT email is the PRIOR_INFO_SENT record of the goods slip.
    note = (
        as_admin(db_conn)
        .execute(
            text(
                "select delivery_mode, channel_code, recipient, party_email_id"
                " from public.party_notifications where gs_id = cast(:g as uuid)"
            ),
            {"g": gs_id},
        )
        .mappings()
        .one()
    )
    assert (note["delivery_mode"], note["channel_code"], note["recipient"]) == (
        "EMAIL_SENT",
        "EMAIL",
        PARTY_EMAIL,
    )
    assert str(note["party_email_id"]) == mail["id"]
    assert _checklist_item(db_conn, gs_id, "PRIOR_NOTIFICATION")["passed"] is True

    # G-16: the same Idempotency-Key returns the same email and sends nothing new.
    replay = await _send(client, actors["accounts"], gs_id, key, cc=["accounts.copy@example.com"])
    assert replay.status_code == 201 and replay.json()["id"] == mail["id"]
    assert replay.headers.get("Idempotency-Replayed") == "true"
    assert len(fake_smtp.sent) == 1

    # Edited subject / body are sent as written; the snapshot stays server-built (G-18).
    edited = await _send(client, actors["accounts"], gs_id, subject="Custom", body="Custom text")
    assert edited.status_code == 201, edited.text
    assert (fake_smtp.sent[-1].subject, fake_smtp.sent[-1].body) == ("Custom", "Custom text")
    log = (await _state(client, actors["accounts"], gs_id))["party_email"]["emails"]
    assert len(log) == 2


async def test_send_rejected_before_completion_without_smtp_or_permission(
    client: AsyncClient,
    db_conn: Connection,
    actors: dict[str, Any],
    fake_smtp: FakeSmtp,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fx = await _finalise(client, db_conn, actors)
    _attach_party(db_conn, fx["gs_id"])
    panel = (await _state(client, actors["accounts"], fx["gs_id"]))["party_email"]
    assert panel["ready"] is False and "not completed" in panel["blocker"]
    early = await _send(client, actors["accounts"], fx["gs_id"])
    assert early.status_code == 409 and early.json()["error"]["code"] == "PARTY_EMAIL_NOT_READY"

    cn_no = f"CN-PH9-{uuid.uuid4().hex[:6]}"
    await _fill_all(client, actors, fx, cn_no)
    assert (await _complete(client, actors, fx)).status_code == 200

    # Not the Accounts role / step performer.
    denied = await _send(client, actors["dispatch"], fx["gs_id"])
    assert denied.status_code == 403
    bad = await _send(client, actors["accounts"], fx["gs_id"], to="not-an-email")
    assert bad.status_code == 422
    bad_cc = await _send(client, actors["accounts"], fx["gs_id"], cc=["x@"])
    assert bad_cc.status_code == 422

    # Without SMTP the send is refused (never silently dropped) ...
    cfg = get_settings().model_copy(update={"smtp_host": None, "smtp_from": None})
    monkeypatch.setattr(email_service, "get_settings", lambda: cfg)
    off = await _send(client, actors["accounts"], fx["gs_id"])
    assert off.status_code == 409 and off.json()["error"]["code"] == "EMAIL_NOT_CONFIGURED"
    assert fake_smtp.sent == []

    # ... and Accounts records the notification manually from the same Accounts values (DEC-25).
    manual = await client.post(
        f"/api/v1/gs/{fx['gs_id']}/party-notifications",
        headers=_auth(actors["accounts"], _key()),
        json={"channel": "WHATSAPP", "recipient": "+91 98765 43210"},
    )
    assert manual.status_code == 201, manual.text
    body = manual.json()
    assert body["delivery_mode"] == "RECORDED_MANUALLY"
    assert cn_no in body["message"]
    assert body["message_snapshot"]["cn_lines"][0]["cn_no"] == cn_no
    assert _checklist_item(db_conn, fx["gs_id"], "PRIOR_NOTIFICATION")["passed"] is True


async def test_failed_send_is_retried_then_resend_logs_a_new_email(
    client: AsyncClient,
    db_conn: Connection,
    actors: dict[str, Any],
    fake_smtp: FakeSmtp,
    uow: UnitOfWork,
) -> None:
    fx = await _completed(client, db_conn, actors)
    gs_id = fx["gs_id"]

    fake_smtp.fail_with = smtplib.SMTPServerDisconnected("connection lost")
    res = await _send(client, actors["accounts"], gs_id)
    assert res.status_code == 201, res.text
    first = res.json()
    assert (first["status"], first["attempts"]) == ("QUEUED", 1)
    assert "connection lost" in first["last_error"]
    assert first["party_notification_id"] is None
    assert _checklist_item(db_conn, gs_id, "PRIOR_NOTIFICATION")["passed"] is False

    # Resend of an email that is still being retried is refused.
    busy = await client.post(
        f"/api/v1/gs/{gs_id}/party-emails/{first['id']}/resend",
        headers=_auth(actors["accounts"], _key()),
    )
    assert busy.status_code == 409 and busy.json()["error"]["code"] == "PARTY_EMAIL_IN_PROGRESS"

    # The worker retries once the backoff has passed.
    fake_smtp.fail_with = None
    later = datetime.now(UTC) + timedelta(hours=2)
    assert email_service.deliver_due(uow, now=later) >= 1
    panel = (await _state(client, actors["accounts"], gs_id))["party_email"]
    retried = next(e for e in panel["emails"] if e["id"] == first["id"])
    assert (retried["status"], retried["attempts"]) == ("SENT", 2)
    assert len(fake_smtp.sent) == 1

    again = await client.post(
        f"/api/v1/gs/{gs_id}/party-emails/{first['id']}/resend",
        headers=_auth(actors["accounts"], _key()),
    )
    assert again.status_code == 201, again.text
    resent = again.json()
    assert (resent["trigger_code"], resent["resend_of_id"], resent["status"]) == (
        "RESEND",
        first["id"],
        "SENT",
    )
    assert resent["body"] == retried["body"]
    assert len(fake_smtp.sent) == 2

    # An email of another goods slip cannot be re-sent through this one.
    other = await _completed(client, db_conn, actors)
    cross = await client.post(
        f"/api/v1/gs/{other['gs_id']}/party-emails/{first['id']}/resend",
        headers=_auth(actors["accounts"], _key()),
    )
    assert cross.status_code == 404

    # Retries exhausted -> FAILED, never dropped.
    fake_smtp.fail_with = smtplib.SMTPException("mailbox unavailable")
    as_admin(db_conn).execute(
        text(
            "update public.system_settings set value = '1' where key = 'notification_max_attempts'"
        )
    )
    failed = (await _send(client, actors["accounts"], gs_id)).json()
    assert (failed["status"], failed["attempts"]) == ("FAILED", 1)


async def test_auto_send_only_when_enabled_includes_dispatch_details(
    client: AsyncClient,
    db_conn: Connection,
    actors: dict[str, Any],
    fake_smtp: FakeSmtp,
    uow: UnitOfWork,
) -> None:
    # Default OFF (AMD-20): completion and dispatch queue nothing.
    off = await _completed(client, db_conn, actors)
    dispatched = await client.post(
        f"/api/v1/dispatch-slips/{off['dispatch_slip']['id']}/dispatch",
        headers=_auth(actors["dispatch"], _key()),
        json={
            "dispatch_date": TODAY.isoformat(),
            "transporter": "Blue Dart",
            "docket_no": "DKT-PH9-1",
        },
    )
    assert dispatched.status_code == 200, dispatched.text
    assert (await _state(client, actors["accounts"], off["gs_id"]))["party_email"]["emails"] == []

    # ON_DISPATCH: nothing at completion (goods ship), then queued AUTO when dispatched.
    _set_delivery(db_conn, {"auto_send": "ON_DISPATCH", "cc": []})
    fx = await _completed(client, db_conn, actors)
    assert (await _state(client, actors["accounts"], fx["gs_id"]))["party_email"]["emails"] == []
    res = await client.post(
        f"/api/v1/dispatch-slips/{fx['dispatch_slip']['id']}/dispatch",
        headers=_auth(actors["dispatch"], _key()),
        json={
            "dispatch_date": TODAY.isoformat(),
            "transporter": "Blue Dart",
            "docket_no": "DKT-PH9-2",
        },
    )
    assert res.status_code == 200, res.text
    emails = (await _state(client, actors["accounts"], fx["gs_id"]))["party_email"]["emails"]
    assert [(e["trigger_code"], e["status"]) for e in emails] == [("AUTO", "QUEUED")]
    assert "DKT-PH9-2" in emails[0]["body"] and fx["cn_no"] in emails[0]["body"]
    assert email_service.deliver_due(uow) >= 1
    assert any("DKT-PH9-2" in m.body for m in fake_smtp.sent)
    assert _checklist_item(db_conn, fx["gs_id"], "PRIOR_NOTIFICATION")["passed"] is True

    # ON_AC_COMPLETION: queued at completion; a party without an address is logged SKIPPED.
    _set_delivery(db_conn, {"auto_send": "ON_AC_COMPLETION", "cc": []})
    no_addr = await _completed(client, db_conn, actors, email=None)
    emails = (await _state(client, actors["accounts"], no_addr["gs_id"]))["party_email"]["emails"]
    assert [(e["trigger_code"], e["status"], e["skip_reason"]) for e in emails] == [
        ("AUTO", "SKIPPED", "NO_EMAIL_ADDRESS")
    ]

    # ON_DISPATCH with nothing to ship: queued at completion.
    _set_delivery(db_conn, {"auto_send": "ON_DISPATCH", "cc": []})
    cn_only = await _completed(client, db_conn, actors, ISSUE_CN=10)
    assert cn_only["dispatch_slip"] is None
    emails = (await _state(client, actors["accounts"], cn_only["gs_id"]))["party_email"]["emails"]
    assert [(e["trigger_code"], e["status"]) for e in emails] == [("AUTO", "QUEUED")]


async def test_db_guard_party_email_log_is_frozen_and_source_checked(
    client: AsyncClient, db_conn: Connection, actors: dict[str, Any], fake_smtp: FakeSmtp
) -> None:
    """AMD-20 / G-18 in the DB: no delete, frozen content, final status, completed source only,
    and an EMAIL_SENT notification needs a SENT email of the same GS."""
    fx = await _completed(client, db_conn, actors)
    sent = (await _send(client, actors["accounts"], fx["gs_id"])).json()
    c = as_admin(db_conn)

    def rejects(sql: str, params: dict[str, Any], match: str) -> None:
        sp = c.begin_nested()
        with pytest.raises(DBAPIError, match=match):
            c.execute(text(sql), params)
        sp.rollback()

    rejects(
        "delete from public.party_emails where id = cast(:i as uuid)",
        {"i": sent["id"]},
        "never deleted",
    )
    rejects(
        "update public.party_emails set body = 'changed' where id = cast(:i as uuid)",
        {"i": sent["id"]},
        "frozen",
    )
    rejects(
        "update public.party_emails set last_error = 'x' where id = cast(:i as uuid)",
        {"i": sent["id"]},
        "is final",
    )
    # A slip Accounts has not completed cannot be the source of a party email.
    open_fx = await _finalise(client, db_conn, actors)
    rejects(
        """
        insert into public.party_emails (gs_id, ac_action_slip_id, trigger_code, email_to, subject,
          body, snapshot, template_snapshot, requested_by)
        select s.gs_id, s.id, 'MANUAL', 'a@b.co', 's', 'b', '{}', '{}', s.finalised_by
          from public.ac_action_slips s where s.id = cast(:s as uuid)
        """,
        {"s": open_fx["ac_slip_id"]},
        "completed Accounts entry",
    )
    # EMAIL_SENT without a SENT email of this GS.
    rejects(
        """
        insert into public.party_notifications (gs_id, channel_code, recipient, message,
          message_snapshot, delivery_mode, party_email_id, sent_by)
        select cast(:g as uuid), 'EMAIL', :to, 'm', '{}', 'EMAIL_SENT', cast(:i as uuid),
               requested_by
          from public.party_emails where id = cast(:i as uuid)
        """,
        {"g": open_fx["gs_id"], "to": PARTY_EMAIL, "i": sent["id"]},
        "SENT party email of this GS",
    )
    rejects(
        """
        insert into public.party_notifications (gs_id, channel_code, recipient, message,
          message_snapshot, delivery_mode, sent_by)
        select cast(:g as uuid), 'EMAIL', :to, 'm', '{}', 'EMAIL_SENT', requested_by
          from public.party_emails where id = cast(:i as uuid)
        """,
        {"g": fx["gs_id"], "to": PARTY_EMAIL, "i": sent["id"]},
        "party_notifications_email_link",
    )


async def test_admin_settings_validate_placeholders_and_preview(
    client: AsyncClient, actors: dict[str, Any], db_conn: Connection
) -> None:
    got = await client.get("/api/v1/party-email/settings", headers=_auth(actors["admin"]))
    assert got.status_code == 200, got.text
    cfg = got.json()
    assert cfg["delivery"] == {"auto_send": "OFF", "cc": []}
    assert cfg["auto_send_modes"] == ["OFF", "ON_AC_COMPLETION", "ON_DISPATCH"]
    assert "cn_no" in cfg["placeholders"]["cn_line"]

    bad = cfg["template"] | {"subject": "{gs_no} {unknown_thing}"}
    res = await client.put(
        "/api/v1/party-email/settings",
        headers=_auth(actors["admin"]),
        json={"template": bad, "delivery": cfg["delivery"]},
    )
    assert res.status_code == 422 and res.json()["error"]["code"] == "TEMPLATE_INVALID"

    # Accounts cannot change the configuration.
    denied = await client.put(
        "/api/v1/party-email/settings",
        headers=_auth(actors["accounts"]),
        json={"template": cfg["template"], "delivery": cfg["delivery"]},
    )
    assert denied.status_code == 403

    tpl = cfg["template"] | {"subject": "Return {gs_no}"}
    ok = await client.put(
        "/api/v1/party-email/settings",
        headers=_auth(actors["admin"]),
        json={
            "template": tpl,
            "delivery": {"auto_send": "ON_DISPATCH", "cc": [" copy@example.com "]},
            "reason": "Phase 9 test",
        },
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["template"]["subject"] == "Return {gs_no}"
    assert ok.json()["delivery"] == {"auto_send": "ON_DISPATCH", "cc": ["copy@example.com"]}
    history = as_admin(db_conn).execute(
        text(
            "select count(*) from public.config_change_log"
            " where entity_type = 'system_setting' and entity_id like 'party_email.%'"
        )
    )
    assert int(history.scalar_one()) >= 2

    preview = await client.post(
        "/api/v1/party-email/settings/preview",
        headers=_auth(actors["admin"]),
        json={"template": tpl},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["subject"] == "Return GS/2026-27/00042"
    assert "CN-1234" in preview.json()["body"]
