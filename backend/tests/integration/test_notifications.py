"""Notification automation, escalations & email channel (prompt P4-03; §8.7, §10; BR-06, DEC-05,
DEC-25, DEC-30).

* Outbox: written with the business change (no phantom on rollback), dispatched inline, retried
  by the worker when inline dispatch fails, FAILED after the configured attempts.
* Every P4-03 event produces the configured notifications exactly once (dedupe + delivery unique).
* Rule evaluation: context recipients, roles, users, open-step assignees, priority, channels;
  disabling a rule stops new notifications.
* Preferences: email opt-out per event, mandatory events cannot be opted out, daily digest.
* Email: rendering, SMTP send / retry / FAILED, SMTP not configured → SKIPPED (never dropped).
* Escalations with frozen time: once per level; escalated_at stamped.
* Admin API (configure permission, config_change_log) and the user notification centre API.
"""

from __future__ import annotations

import smtplib
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import Connection, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.core.db import UnitOfWork
from app.modules.inventory import battery_service
from app.modules.notifications import email as email_mod
from app.modules.notifications import service as notif
from app.modules.notifications.email import OutgoingEmail, render
from tests.conftest import JwtFactory
from tests.integration.conftest import UserFactory, as_admin, fetch_all
from tests.integration.test_gate_inward import Masters, _payload, _values

API = "/api/v1"

P4_03_EVENTS = [
    "GS_CREATED",
    "MISSING_DOCUMENTS",
    "EVIDENCE_COMPLETED",
    "CSR_APPROVAL_REQUIRED",
    "CSR_DECIDED",
    "HAZARD_DETECTED",
    "REJECTION_RECORDED",
    "PENDENCY_OPENED",
    "PENDENCY_CLEARED",
    "TRANSFER_INITIATED",
    "TRANSFER_DISCREPANCY",
    "TECH_BATCH_ALLOTTED",
    "TECH_BATCH_RECEIVED",
    "BATTERY_LOW_STOCK",
    "PARTS_RECOVERED",
    "STORE_ISSUED",
    "DISPATCHED",
    "CN_DECISION_REQUIRED",
    "CN_ISSUED",
    "NOTIFICATION_PENDING",
    "GS_CLOSED",
    "DAILY_AUDIT_MISSED",
]


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def uow(session_factory: sessionmaker[Session]) -> UnitOfWork:
    return UnitOfWork(session_factory)


@pytest.fixture
def smtp_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Email channel ON (fake SMTP host); the sender itself is faked per test."""
    cfg = get_settings().model_copy(
        update={
            "smtp_host": "smtp.test.local",
            "smtp_from": "rms@test.local",
            "smtp_use_tls": False,
        }
    )
    monkeypatch.setattr(notif, "get_settings", lambda: cfg)
    return cfg


@pytest.fixture
def no_smtp(monkeypatch: pytest.MonkeyPatch) -> Settings:
    cfg = get_settings().model_copy(update={"smtp_host": None, "smtp_from": None})
    monkeypatch.setattr(notif, "get_settings", lambda: cfg)
    return cfg


class FakeSmtp:
    """Context-manager sender recording mails; `fail_with` makes every send raise."""

    def __init__(self) -> None:
        self.sent: list[OutgoingEmail] = []
        self.fail_with: Exception | None = None
        self.connect_error: Exception | None = None

    def factory(self, _settings: Settings) -> FakeSmtp:
        if self.connect_error:
            raise self.connect_error
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
def fake_smtp() -> Iterator[FakeSmtp]:
    yield FakeSmtp()


def only_rule(conn: Connection, event_type: str, **kw: Any) -> uuid.UUID:
    """Deactivate the event's seeded rules and add one test rule (rolled back with the test)."""
    c = as_admin(conn)
    c.execute(
        text("update public.notification_rules set is_active = false where event_type = :e"),
        {"e": event_type},
    )
    return add_rule(conn, event_type, **kw)


def add_rule(
    conn: Connection,
    event_type: str,
    *,
    users: list[uuid.UUID] | None = None,
    roles: list[str] | None = None,
    context: bool = False,
    step: bool = False,
    channels: tuple[str, ...] = ("IN_APP",),
    priority: str | None = None,
    active: bool = True,
) -> uuid.UUID:
    return uuid.UUID(
        str(
            as_admin(conn)
            .execute(
                text(
                    """
                    insert into public.notification_rules
                           (event_type, name, include_context_recipients, include_step_assignees,
                            recipient_role_codes, recipient_user_ids, channels, priority, is_active)
                    values (:e, 'test rule', :ctx, :step, cast(:roles as text[]),
                            cast(:users as uuid[]), cast(:ch as text[]), :prio, :active)
                    returning id
                    """
                ),
                {
                    "e": event_type,
                    "ctx": context,
                    "step": step,
                    "roles": roles or [],
                    "users": [str(u) for u in users or []],
                    "ch": list(channels),
                    "prio": priority,
                    "active": active,
                },
            )
            .scalar_one()
        )
    )


def publish(uow: UnitOfWork, event_type: str, **kw: Any) -> int:
    kw.setdefault("title", f"Test {event_type}")
    with uow.transaction() as s:
        return notif.publish(s, event_type, **kw)


def notifications_of(conn: Connection, user: uuid.UUID) -> list[dict[str, Any]]:
    return fetch_all(
        conn,
        "select n.*, e.event_type from public.notifications n "
        "left join public.notification_events e on e.id = n.event_id "
        "where n.user_id = :u order by n.created_at",
        u=user,
    )


def deliveries_of(conn: Connection, user: uuid.UUID) -> list[dict[str, Any]]:
    return fetch_all(
        conn,
        "select d.*, e.event_type from public.notification_deliveries d "
        "join public.notification_events e on e.id = d.event_id where d.user_id = :u "
        "order by d.created_at",
        u=user,
    )


# =============================================================================================
# Catalogue & seed
# =============================================================================================


def test_catalogue_and_seed(db_conn: Connection) -> None:
    types = {
        r["code"]: r for r in fetch_all(db_conn, "select * from public.notification_event_types")
    }
    assert set(P4_03_EVENTS) <= set(types)
    # every event has a published v1 email template
    templ = fetch_all(
        db_conn,
        "select event_type from public.notification_templates where status = 'PUBLISHED'",
    )
    assert {t["event_type"] for t in templ} == set(types)
    # mandatory: safety / compliance events
    assert {c for c, t in types.items() if t["is_mandatory"]} >= {
        "HAZARD_DETECTED",
        "MISSING_DOCUMENTS",
        "DAILY_AUDIT_MISSED",
        "SLA_ESCALATION",
    }
    # DEC-30: escalation rules are seeded disabled
    seeded = fetch_all(db_conn, "select is_active from public.escalation_rules")
    assert seeded and not any(
        r["is_active"]
        for r in fetch_all(
            db_conn,
            """select er.is_active from public.escalation_rules er
             join public.workflow_steps ws on ws.id = er.workflow_step_id
             join public.workflow_versions wv on wv.id = ws.workflow_version_id
             join public.workflow_definitions wd on wd.id = wv.workflow_definition_id
            where wd.code = 'RMS_STANDARD' and wv.version_no = 1""",
        )
    )
    # Events that notified before P4-03 have an active IN_APP context rule (behaviour preserved)
    rules = fetch_all(db_conn, "select * from public.notification_rules where is_active")
    active = {r["event_type"] for r in rules}
    assert {
        "EVIDENCE_COMPLETED",
        "MISSING_DOCUMENTS",
        "HAZARD_DETECTED",
        "GS_CLOSED",
        "DAILY_AUDIT_MISSED",
        "CN_ISSUED",
        "DISPATCHED",
        "BATTERY_LOW_STOCK",
    } <= active
    assert "GS_CREATED" not in active  # new events are seeded inactive


def test_event_codes_are_immutable(db_conn: Connection) -> None:
    c = as_admin(db_conn)
    with pytest.raises(Exception, match="immutable"), c.begin_nested():
        c.execute(
            text(
                "update public.notification_event_types set code = 'X_Y' where code = 'GS_CREATED'"
            )
        )


# =============================================================================================
# Outbox: no phantom, no lost, exactly once
# =============================================================================================


def test_publish_dispatches_inline_in_the_same_transaction(
    db_conn: Connection, users: UserFactory, uow: UnitOfWork
) -> None:
    u = users.create()
    only_rule(db_conn, "GS_CLOSED", context=True)
    assert publish(uow, "GS_CLOSED", user_ids=[u], body="b", priority="HIGH") == 1
    [n] = notifications_of(db_conn, u)
    assert (n["type"], n["title"], n["body"], n["priority"]) == (
        "GS_CLOSED",
        "Test GS_CLOSED",
        "b",
        "HIGH",
    )
    ev = fetch_all(
        db_conn, "select * from public.notification_events where id = :i", i=n["event_id"]
    )[0]
    assert ev["status"] == "DISPATCHED" and ev["dispatched_at"] is not None
    [d] = deliveries_of(db_conn, u)
    assert (d["channel"], d["status"], d["notification_id"]) == ("IN_APP", "SENT", n["id"])


def test_rolled_back_business_change_leaves_no_event(
    db_conn: Connection, users: UserFactory, uow: UnitOfWork
) -> None:
    u = users.create()
    only_rule(db_conn, "GS_CLOSED", context=True)
    key = f"phantom-{uuid.uuid4()}"
    with pytest.raises(RuntimeError), uow.transaction() as s:
        notif.publish(s, "GS_CLOSED", title="x", user_ids=[u], dedupe_key=key)
        raise RuntimeError("business command failed")
    assert not fetch_all(
        db_conn, "select 1 from public.notification_events where dedupe_key = :k", k=key
    )
    assert notifications_of(db_conn, u) == []


def test_inline_failure_is_retried_by_the_worker(
    db_conn: Connection, users: UserFactory, uow: UnitOfWork, monkeypatch: pytest.MonkeyPatch
) -> None:
    u = users.create()
    only_rule(db_conn, "GS_CLOSED", context=True)
    real = notif.dispatch_event

    def broken(*a: Any, **k: Any) -> int:
        raise OperationalError("dispatch", {}, Exception("simulated outage"))

    monkeypatch.setattr(notif, "dispatch_event", broken)
    assert publish(uow, "GS_CLOSED", user_ids=[u], dedupe_key="retry-1") == 0
    [ev] = fetch_all(
        db_conn, "select * from public.notification_events where dedupe_key = 'retry-1'"
    )
    assert ev["status"] == "PENDING" and ev["attempts"] == 1 and "simulated" in ev["last_error"]
    assert notifications_of(db_conn, u) == []  # the business change committed; nothing lost

    monkeypatch.setattr(notif, "dispatch_event", real)
    assert notif.process_outbox(uow) >= 1
    assert len(notifications_of(db_conn, u)) == 1
    # a second worker pass does not deliver again
    notif.process_outbox(uow)
    assert len(notifications_of(db_conn, u)) == 1


def test_worker_marks_event_failed_after_max_attempts(
    db_conn: Connection, users: UserFactory, uow: UnitOfWork, monkeypatch: pytest.MonkeyPatch
) -> None:
    u = users.create()
    only_rule(db_conn, "GS_CLOSED", context=True)
    as_admin(db_conn).execute(
        text(
            "update public.system_settings set value = '2' where key = 'notification_max_attempts'"
        )
    )

    def broken(*a: Any, **k: Any) -> int:
        raise OperationalError("dispatch", {}, Exception("still down"))

    monkeypatch.setattr(notif, "dispatch_event", broken)
    publish(uow, "GS_CLOSED", user_ids=[u], dedupe_key="fail-1")  # attempt 1 (inline)
    as_admin(db_conn).execute(
        text(
            "update public.notification_events set next_attempt_at = now() "
            "where dedupe_key = 'fail-1'"
        )
    )
    notif.process_outbox(uow)  # attempt 2 → FAILED
    [ev] = fetch_all(
        db_conn, "select * from public.notification_events where dedupe_key = 'fail-1'"
    )
    assert (ev["status"], ev["attempts"]) == ("FAILED", 2)


@pytest.mark.parametrize("event_type", P4_03_EVENTS)
def test_every_event_produces_configured_notifications_exactly_once(
    event_type: str,
    db_conn: Connection,
    users: UserFactory,
    uow: UnitOfWork,
    smtp_settings: Settings,
) -> None:
    a, b = users.create(), users.create()
    only_rule(db_conn, event_type, users=[a, b], channels=("IN_APP", "EMAIL"))
    key = f"once-{event_type}-{uuid.uuid4()}"
    assert publish(uow, event_type, dedupe_key=key) == 2
    assert publish(uow, event_type, dedupe_key=key) == 0  # same occurrence published again
    notif.process_outbox(uow)  # worker pass: nothing left to deliver
    for u in (a, b):
        assert [n["event_type"] for n in notifications_of(db_conn, u)] == [event_type]
        assert sorted(d["channel"] for d in deliveries_of(db_conn, u)) == ["EMAIL", "IN_APP"]
    count = fetch_all(
        db_conn, "select count(*) as c from public.notification_events where dedupe_key = :k", k=key
    )
    assert count[0]["c"] == 1


# =============================================================================================
# Rule evaluation
# =============================================================================================


def test_rule_evaluation_merges_sources_and_dedupes_users(
    db_conn: Connection, users: UserFactory, uow: UnitOfWork
) -> None:
    ctx_user = users.create()
    role_user = users.create(roles=["DISPATCH"])
    inactive_role_user = users.create(roles=["DISPATCH"], active=False)
    named = users.create()
    only_rule(db_conn, "CN_ISSUED", context=True, priority="LOW")
    add_rule(db_conn, "CN_ISSUED", roles=["DISPATCH"], users=[named, ctx_user], priority="HIGH")
    publish(uow, "CN_ISSUED", user_ids=[ctx_user], priority="NORMAL")
    # context user matched by two rules → one notification, highest priority wins
    [n] = notifications_of(db_conn, ctx_user)
    assert n["priority"] == "HIGH"
    [d] = deliveries_of(db_conn, ctx_user)
    assert len(d["rule_ids"]) == 2
    assert len(notifications_of(db_conn, role_user)) == 1
    assert len(notifications_of(db_conn, named)) == 1
    assert notifications_of(db_conn, inactive_role_user) == []


def test_disabling_a_rule_stops_new_notifications(
    db_conn: Connection, users: UserFactory, uow: UnitOfWork
) -> None:
    u = users.create()
    rule = only_rule(db_conn, "DISPATCHED", users=[u])
    publish(uow, "DISPATCHED")
    as_admin(db_conn).execute(
        text("update public.notification_rules set is_active = false where id = :r"), {"r": rule}
    )
    publish(uow, "DISPATCHED")
    assert len(notifications_of(db_conn, u)) == 1


async def test_step_assignee_rule_reaches_the_next_steps_assignees(
    client: AsyncClient, db_conn: Connection, users: UserFactory, make_token: JwtFactory
) -> None:
    """GS_CREATED with "assignee of next step": a fresh Inward Verifier gets it from a real gate
    inward through the API (the S1_UNBOX task is assigned to that role)."""
    masters = Masters(db_conn)
    verifier = users.create(roles=["INWARD_VERIFIER"])
    gate = make_token(users.create(roles=["GATE_INWARD"]))
    only_rule(db_conn, "GS_CREATED", step=True)
    res = await client.post(
        f"{API}/gs",
        json={"party_id": str(masters.party), **_payload(_values())},
        headers={**_h(gate), "Idempotency-Key": f"test-{uuid.uuid4()}"},
    )
    assert res.status_code == 201, res.text
    gs = res.json()["goods_slip"]
    mine = [n for n in notifications_of(db_conn, verifier) if n["event_type"] == "GS_CREATED"]
    assert len(mine) == 1
    assert mine[0]["entity_id"] == uuid.UUID(gs["id"]) and gs["gs_no"] in mine[0]["title"]


async def test_seeded_rules_reproduce_pre_p4_03_missing_document_alert(
    client: AsyncClient, db_conn: Connection, users: UserFactory, make_token: JwtFactory
) -> None:
    """DEC-05 behaviour unchanged: NO_DOCUMENT → HIGH GS_MISSING_DOCUMENTATION to Accounts + RM."""
    masters = Masters(db_conn)
    accounts = users.create(roles=["ACCOUNTS"])
    rm = users.create(roles=["REPLACEMENT_MANAGER"])
    gate = make_token(users.create(roles=["GATE_INWARD"]))
    res = await client.post(
        f"{API}/gs",
        json={"party_id": str(masters.party), **_payload(_values(doc="NO_DOCUMENT"))},
        headers={**_h(gate), "Idempotency-Key": f"test-{uuid.uuid4()}"},
    )
    assert res.status_code == 201, res.text
    for u in (accounts, rm):
        [n] = [x for x in notifications_of(db_conn, u) if x["type"] == "GS_MISSING_DOCUMENTATION"]
        assert n["priority"] == "HIGH" and n["event_type"] == "MISSING_DOCUMENTS"


# =============================================================================================
# Preferences, mandatory events, digest
# =============================================================================================


def test_email_opt_out_and_mandatory_events(
    db_conn: Connection, users: UserFactory, uow: UnitOfWork, smtp_settings: Settings
) -> None:
    u = users.create()
    for ev in ("DISPATCHED", "HAZARD_DETECTED"):
        only_rule(db_conn, ev, users=[u], channels=("IN_APP", "EMAIL"))
        as_admin(db_conn).execute(
            text("""insert into public.notification_preferences
                        (user_id, notification_type, channel, is_enabled)
                    values (:u, :e, 'EMAIL', false)"""),
            {"u": u, "e": ev},
        )
    publish(uow, "DISPATCHED")
    publish(uow, "HAZARD_DETECTED")  # mandatory: the stored opt-out is ignored
    emails = {d["event_type"]: d for d in deliveries_of(db_conn, u) if d["channel"] == "EMAIL"}
    assert (emails["DISPATCHED"]["status"], emails["DISPATCHED"]["skip_reason"]) == (
        "SKIPPED",
        "OPTED_OUT",
    )
    assert emails["HAZARD_DETECTED"]["status"] == "PENDING"
    # in-app is never opted out
    assert len(notifications_of(db_conn, u)) == 2


async def test_preferences_api(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory, smtp_settings: Settings
) -> None:
    token = make_token(users.create())
    res = await client.get(f"{API}/notifications/preferences", headers=_h(token))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["email_channel"]["enabled"] is True and "password" not in str(body).lower()
    items = {i["event_type"]: i for i in body["items"]}
    assert items["HAZARD_DETECTED"]["is_mandatory"] and items["HAZARD_DETECTED"]["email_enabled"]

    res = await client.put(
        f"{API}/notifications/preferences",
        json={"email_mode": "DAILY_DIGEST", "email": {"DISPATCHED": False}},
        headers=_h(token),
    )
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["email_mode"] == "DAILY_DIGEST"
    assert {i["event_type"]: i for i in out["items"]}["DISPATCHED"]["email_enabled"] is False

    res = await client.put(
        f"{API}/notifications/preferences",
        json={"email": {"HAZARD_DETECTED": False}},
        headers=_h(token),
    )
    assert res.status_code == 422 and res.json()["error"]["code"] == "MANDATORY_EVENT"
    res = await client.put(
        f"{API}/notifications/preferences", json={"email": {"NOPE": False}}, headers=_h(token)
    )
    assert res.status_code == 422


def test_daily_digest(
    db_conn: Connection,
    users: UserFactory,
    uow: UnitOfWork,
    smtp_settings: Settings,
    fake_smtp: FakeSmtp,
) -> None:
    u = users.create(full_name="Digest Reader")
    as_admin(db_conn).execute(
        text(
            "insert into public.notification_user_settings (user_id, email_mode) "
            "values (:u, 'DAILY_DIGEST')"
        ),
        {"u": u},
    )
    for ev in ("DISPATCHED", "CN_ISSUED", "HAZARD_DETECTED"):
        only_rule(db_conn, ev, users=[u], channels=("EMAIL",))
        publish(uow, ev, body=f"{ev} body")
    states = {d["event_type"]: d["status"] for d in deliveries_of(db_conn, u)}
    # mandatory events are never batched into the digest
    assert states == {"DISPATCHED": "DIGEST", "CN_ISSUED": "DIGEST", "HAZARD_DETECTED": "PENDING"}

    as_admin(db_conn).execute(
        text("update public.system_settings set value = '9' where key = 'notification_digest_hour'")
    )
    before_hour = datetime(2026, 11, 6, 2, 0, tzinfo=UTC)  # 07:30 IST
    after_hour = datetime(2026, 11, 6, 4, 0, tzinfo=UTC)  # 09:30 IST
    assert (
        notif.send_digests(
            uow, settings=smtp_settings, sender_factory=fake_smtp.factory, now=before_hour
        )
        == 0
    )
    sent = notif.send_digests(
        uow, settings=smtp_settings, sender_factory=fake_smtp.factory, now=after_hour
    )
    assert sent >= 1
    [mail] = [m for m in fake_smtp.sent if "Digest Reader" in m.body]
    assert "2 notification(s)" in mail.subject and "DISPATCHED body" in mail.body
    assert "CN_ISSUED body" in mail.body
    digest = [d for d in deliveries_of(db_conn, u) if d["event_type"] != "HAZARD_DETECTED"]
    assert all(d["status"] == "SENT" and d["digest_key"] == "DIGEST:2026-11-06" for d in digest)
    # once per day
    only_rule(db_conn, "STORE_ISSUED", users=[u], channels=("EMAIL",))
    publish(uow, "STORE_ISSUED")
    notif.send_digests(
        uow,
        settings=smtp_settings,
        sender_factory=fake_smtp.factory,
        now=after_hour + timedelta(hours=1),
    )
    assert len([m for m in fake_smtp.sent if "Digest Reader" in m.body]) == 1


# =============================================================================================
# Email rendering & delivery
# =============================================================================================


def test_render_keeps_unknown_placeholders_and_survives_bad_braces() -> None:
    ctx = {"title": "T", "gs_no": "GS-1"}
    assert render("{title} for {gs_no} by {unknown}", ctx) == "T for GS-1 by {unknown}"
    assert render("broken {title", ctx) == "broken {title"
    assert render("{{literal}} {title}", ctx) == "{literal} T"
    assert email_mod.entity_path("goods_slip", "x", None) == "/#/gs/x"
    assert email_mod.entity_path("custody_transfer", "t", None) == "/#/custody/transfers/t"
    assert email_mod.entity_path("credit_notes", "c", "g") == "/#/gs/g"


def test_email_sent_with_published_template(
    db_conn: Connection,
    users: UserFactory,
    uow: UnitOfWork,
    smtp_settings: Settings,
    fake_smtp: FakeSmtp,
) -> None:
    u = users.create(full_name="Mail Reader")
    only_rule(db_conn, "DISPATCHED", users=[u], channels=("EMAIL",))
    gs_id = uuid.uuid4()
    publish(
        uow,
        "DISPATCHED",
        title="Replacement Dispatched: DSP-1",
        body="via Test Transport",
        entity_type="goods_slip",
        entity_id=gs_id,
        data={"gs_no": "GS-TEST-1"},
    )
    assert notif.send_due_emails(uow, settings=smtp_settings, sender_factory=fake_smtp.factory) >= 1
    [mail] = [m for m in fake_smtp.sent if "Mail Reader" in m.body]
    assert mail.subject.endswith("Replacement Dispatched: DSP-1")
    assert "Hello Mail Reader" in mail.body and "via Test Transport" in mail.body
    assert f"/#/gs/{gs_id}" in mail.body
    [d] = deliveries_of(db_conn, u)
    assert (
        d["status"] == "SENT"
        and d["sent_at"] is not None
        and d["email_to"].endswith("@example.test")
    )


def test_email_retry_then_failed(
    db_conn: Connection,
    users: UserFactory,
    uow: UnitOfWork,
    smtp_settings: Settings,
    fake_smtp: FakeSmtp,
) -> None:
    u = users.create()
    as_admin(db_conn).execute(
        text(
            "update public.system_settings set value = '2' where key = 'notification_max_attempts'"
        )
    )
    only_rule(db_conn, "DISPATCHED", users=[u], channels=("EMAIL",))
    publish(uow, "DISPATCHED")
    fake_smtp.connect_error = smtplib.SMTPConnectError(421, b"busy")
    notif.send_due_emails(uow, settings=smtp_settings, sender_factory=fake_smtp.factory)
    [d] = deliveries_of(db_conn, u)
    assert (d["status"], d["attempts"]) == ("PENDING", 1) and "busy" in d["last_error"]
    assert d["next_attempt_at"] > datetime.now(UTC)  # backoff

    fake_smtp.connect_error = None
    fake_smtp.fail_with = smtplib.SMTPRecipientsRefused({"x": (550, b"no such user")})
    notif.send_due_emails(
        uow,
        settings=smtp_settings,
        sender_factory=fake_smtp.factory,
        now=datetime.now(UTC) + timedelta(hours=2),
    )
    [d] = deliveries_of(db_conn, u)
    assert (d["status"], d["attempts"]) == ("FAILED", 2)


def test_email_disabled_without_smtp_is_recorded_not_dropped(
    db_conn: Connection, users: UserFactory, uow: UnitOfWork, no_smtp: Settings
) -> None:
    u = users.create()
    only_rule(db_conn, "DISPATCHED", users=[u], channels=("IN_APP", "EMAIL"))
    publish(uow, "DISPATCHED")
    by_channel = {d["channel"]: d for d in deliveries_of(db_conn, u)}
    assert by_channel["IN_APP"]["status"] == "SENT"
    assert (by_channel["EMAIL"]["status"], by_channel["EMAIL"]["skip_reason"]) == (
        "SKIPPED",
        "SMTP_NOT_CONFIGURED",
    )


# =============================================================================================
# Escalations (DEC-30) with frozen time
# =============================================================================================


async def test_sla_breach_escalates_once_per_level(
    client: AsyncClient,
    db_conn: Connection,
    users: UserFactory,
    make_token: JwtFactory,
    uow: UnitOfWork,
) -> None:
    masters = Masters(db_conn)
    gate = make_token(users.create(roles=["GATE_INWARD"]))
    res = await client.post(
        f"{API}/gs",
        json={"party_id": str(masters.party), **_payload(_values())},
        headers={**_h(gate), "Idempotency-Key": f"test-{uuid.uuid4()}"},
    )
    assert res.status_code == 201, res.text
    gs_id = res.json()["goods_slip"]["id"]
    [task] = fetch_all(
        db_conn,
        """select t.*, ws.id as step_id, ws.sla_hours from public.workflow_tasks t
             join public.goods_slips g on g.id = t.gs_id
             join public.workflow_steps ws on ws.workflow_version_id = g.workflow_version_id
                                          and ws.code = t.step_code
            where t.gs_id = :g and t.status = 'OPEN'""",
        g=gs_id,
    )
    # A 0.01 h test SLA: due 36 s after the task opened (G-18 keeps the published step as is,
    # so the task's due time is set directly).
    due = task["created_at"] + timedelta(hours=0.01)
    as_admin(db_conn).execute(
        text("update public.workflow_tasks set due_at = :d where id = :t"),
        {"d": due, "t": task["id"]},
    )
    lvl1_user, lvl2_user = users.create(), users.create()
    c = as_admin(db_conn)
    c.execute(
        text("update public.escalation_rules set is_active = false where workflow_step_id = :s"),
        {"s": task["step_id"]},
    )
    for after, target in ((0.01, lvl1_user), (1.0, lvl2_user)):
        c.execute(
            text("""insert into public.escalation_rules
                        (workflow_step_id, after_hours, notify_user_id, is_active)
                    values (:s, :a, :u, true)"""),
            {"s": task["step_id"], "a": after, "u": target},
        )

    def run(at: datetime) -> list[dict[str, Any]]:
        with uow.transaction() as s:
            notif.run_escalations(s, now=at)
        return fetch_all(
            db_conn,
            "select * from public.workflow_task_escalations where task_id = :t order by level_no",
            t=task["id"],
        )

    assert run(due) == []  # SLA due but the first level fires 0.01 h after the breach
    [e1] = run(due + timedelta(hours=0.01, seconds=1))
    assert e1["level_no"] == 1
    assert len(run(due + timedelta(minutes=30))) == 1  # same level never fires twice
    [n1] = [n for n in notifications_of(db_conn, lvl1_user) if n["event_type"] == "SLA_ESCALATION"]
    assert "escalation level 1" in n1["title"] and n1["priority"] == "HIGH"
    levels = run(due + timedelta(hours=1, minutes=1))
    assert [e["level_no"] for e in levels] == [1, 2]
    assert (
        len(
            [n for n in notifications_of(db_conn, lvl2_user) if n["event_type"] == "SLA_ESCALATION"]
        )
        == 1
    )
    assert (
        len(
            [n for n in notifications_of(db_conn, lvl1_user) if n["event_type"] == "SLA_ESCALATION"]
        )
        == 1
    )
    [t] = fetch_all(
        db_conn, "select escalated_at from public.workflow_tasks where id = :t", t=task["id"]
    )
    assert t["escalated_at"] is not None
    # a closed task is no longer escalated
    as_admin(db_conn).execute(
        text("update public.workflow_tasks set status = 'DONE' where id = :t"), {"t": task["id"]}
    )
    c.execute(
        text("""insert into public.escalation_rules (workflow_step_id, after_hours, notify_user_id,
                                                     is_active) values (:s, 2, :u, true)"""),
        {"s": task["step_id"], "u": lvl2_user},
    )
    assert len(run(due + timedelta(hours=5))) == 2


def test_task_escalations_are_insert_only(db_conn: Connection) -> None:
    with pytest.raises(Exception, match="permission denied"):
        c = db_conn
        with c.begin_nested():
            c.execute(text("set local role rms_api"))
            c.execute(text("delete from public.workflow_task_escalations"))
    as_admin(db_conn)


# =============================================================================================
# Battery low stock (item 6)
# =============================================================================================


def test_battery_low_stock_fires_once_per_crossing(
    db_conn: Connection, users: UserFactory, uow: UnitOfWork, monkeypatch: pytest.MonkeyPatch
) -> None:
    u = users.create()
    only_rule(db_conn, "BATTERY_LOW_STOCK", users=[u])
    as_admin(db_conn).execute(
        text(
            "update public.system_settings set value = '10' "
            "where key = 'battery_low_stock_threshold'"
        )
    )
    bt = uuid.uuid4()
    balance = {"v": 12}
    monkeypatch.setattr(
        battery_service,
        "battery_store_balance",
        lambda _s, _id: {"id": bt, "code": "CR2032", "name": "Coin cell", "balance": balance["v"]},
    )
    with uow.transaction() as s:
        assert battery_service.check_low_stock(s, bt, consumed=2) is False  # 14 → 12: above
        balance["v"] = 9
        assert battery_service.check_low_stock(s, bt, consumed=3) is True  # 12 → 9: crossed
        balance["v"] = 7
        assert battery_service.check_low_stock(s, bt, consumed=2) is False  # already below
    [n] = notifications_of(db_conn, u)
    assert n["event_type"] == "BATTERY_LOW_STOCK" and "9 left" in n["title"]
    as_admin(db_conn).execute(
        text(
            "update public.system_settings set value = '0' "
            "where key = 'battery_low_stock_threshold'"
        )
    )
    balance["v"] = 0
    with uow.transaction() as s:
        assert battery_service.check_low_stock(s, bt, consumed=50) is False  # 0 disables


# =============================================================================================
# Admin API
# =============================================================================================


@pytest.fixture
def admin_token(users: UserFactory, make_token: JwtFactory) -> str:
    return make_token(users.create(super_admin=True, full_name="Notif Admin"))


async def test_admin_requires_configure(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    token = make_token(users.create(roles=["REPLACEMENT_MANAGER"]))
    for path in (
        "/admin/notifications/rules",
        "/admin/notifications/email-status",
        "/admin/notifications/escalation-rules",
        "/admin/notifications/templates",
    ):
        res = await client.get(f"{API}{path}", headers=_h(token))
        assert res.status_code == 403, path


async def test_admin_rule_crud_writes_config_log(
    client: AsyncClient, db_conn: Connection, admin_token: str, users: UserFactory
) -> None:
    u = users.create()
    body = {
        "event_type": "GS_CREATED",
        "name": "Test rule",
        "recipient_role_codes": ["ACCOUNTS"],
        "recipient_user_ids": [str(u)],
        "channels": ["IN_APP", "EMAIL"],
        "priority": "HIGH",
        "is_active": True,
        "reason": "test",
    }
    res = await client.post(f"{API}/admin/notifications/rules", json=body, headers=_h(admin_token))
    assert res.status_code == 201, res.text
    rule = res.json()
    assert rule["channels"] == ["IN_APP", "EMAIL"] and rule["event_label"]
    res = await client.put(
        f"{API}/admin/notifications/rules/{rule['id']}",
        json={**body, "is_active": False, "reason": "pause"},
        headers=_h(admin_token),
    )
    assert res.status_code == 200 and res.json()["is_active"] is False
    for bad, code in (
        ({**body, "recipient_role_codes": ["NOPE"]}, "UNKNOWN_ROLE"),
        ({**body, "recipient_role_codes": [], "recipient_user_ids": []}, "RULE_WITHOUT_RECIPIENTS"),
        ({**body, "event_type": "NOT_AN_EVENT"}, "UNKNOWN_EVENT_TYPE"),
    ):
        res = await client.post(
            f"{API}/admin/notifications/rules", json=bad, headers=_h(admin_token)
        )
        assert res.status_code == 422 and res.json()["error"]["code"] == code, res.text
    res = await client.request(
        "DELETE",
        f"{API}/admin/notifications/rules/{rule['id']}",
        json={"reason": "cleanup"},
        headers=_h(admin_token),
    )
    assert res.status_code == 204
    log = fetch_all(
        db_conn,
        "select action, reason from public.config_change_log "
        "where entity_type = 'notification_rule' and entity_id = :i order by changed_at",
        i=rule["id"],
    )
    assert [r["action"] for r in log] == ["CREATE", "UPDATE", "DELETE"]


async def test_admin_event_type_and_templates(
    client: AsyncClient, db_conn: Connection, admin_token: str
) -> None:
    res = await client.put(
        f"{API}/admin/notifications/event-types/DISPATCHED",
        json={
            "label": "Dispatched (relabelled)",
            "default_priority": "HIGH",
            "is_mandatory": True,
            "description": "d",
            "reason": "test",
        },
        headers=_h(admin_token),
    )
    assert res.status_code == 200 and res.json()["label"] == "Dispatched (relabelled)"

    res = await client.post(
        f"{API}/admin/notifications/templates/preview",
        json={
            "event_type": "DISPATCHED",
            "subject": "[{app_name}] {title}",
            "body": "Hi {recipient_name}: {body} {oops}",
        },
        headers=_h(admin_token),
    )
    assert res.status_code == 200, res.text
    prev = res.json()
    assert prev["subject"].endswith("sample notification title") and prev[
        "unknown_placeholders"
    ] == ["oops"]

    res = await client.put(
        f"{API}/admin/notifications/templates/DISPATCHED",
        json={"subject": "{title}", "body": "{oops}"},
        headers=_h(admin_token),
    )
    assert res.status_code == 422 and res.json()["error"]["code"] == "TEMPLATE_PLACEHOLDER"
    res = await client.put(
        f"{API}/admin/notifications/templates/DISPATCHED",
        json={"subject": "Dispatch: {title}", "body": "{body}\n{link}", "reason": "v2"},
        headers=_h(admin_token),
    )
    assert res.status_code == 200 and res.json()["version_no"] == 2
    versions = (
        await client.get(
            f"{API}/admin/notifications/templates/DISPATCHED/versions", headers=_h(admin_token)
        )
    ).json()
    assert [(v["version_no"], v["status"]) for v in versions] == [(2, "PUBLISHED"), (1, "RETIRED")]
    # retired versions are immutable in the database
    with pytest.raises(Exception, match="immutable"):
        c = as_admin(db_conn)
        with c.begin_nested():
            c.execute(
                text(
                    "update public.notification_templates set subject = 'x' "
                    "where event_type = 'DISPATCHED' and version_no = 1"
                )
            )


async def test_admin_escalation_rules_and_status(
    client: AsyncClient, db_conn: Connection, admin_token: str
) -> None:
    res = await client.get(f"{API}/admin/notifications/escalation-rules", headers=_h(admin_token))
    assert res.status_code == 200
    seeded = res.json()
    assert seeded and all(
        not r["is_active"] for r in seeded if r["workflow_code"] == "RMS_STANDARD"
    )
    step_id = seeded[0]["workflow_step_id"]
    res = await client.post(
        f"{API}/admin/notifications/escalation-rules",
        json={
            "workflow_step_id": step_id,
            "after_hours": 2,
            "notify_role_code": "REPLACEMENT_MANAGER",
            "is_active": True,
            "reason": "test",
        },
        headers=_h(admin_token),
    )
    assert res.status_code == 201, res.text
    created = res.json()
    assert created["level_no"] == 1 and created["notify_role_code"] == "REPLACEMENT_MANAGER"
    res = await client.post(
        f"{API}/admin/notifications/escalation-rules",
        json={"workflow_step_id": step_id, "after_hours": 2},
        headers=_h(admin_token),
    )
    assert res.status_code == 422 and res.json()["error"]["code"] == "ESCALATION_TARGET"
    res = await client.request(
        "DELETE",
        f"{API}/admin/notifications/escalation-rules/{created['id']}",
        headers=_h(admin_token),
    )
    assert res.status_code == 204

    res = await client.get(f"{API}/admin/notifications/email-status", headers=_h(admin_token))
    assert res.status_code == 200 and set(res.json()) == {
        "enabled",
        "host",
        "port",
        "sender",
        "security",
        "reason",
    }
    res = await client.get(
        f"{API}/admin/notifications/deliveries",
        headers=_h(admin_token),
        params={"channel": "EMAIL"},
    )
    assert res.status_code == 200 and "outbox" in res.json()


# =============================================================================================
# Notification centre API
# =============================================================================================


async def test_notification_centre_filters_and_read(
    client: AsyncClient,
    db_conn: Connection,
    users: UserFactory,
    make_token: JwtFactory,
    uow: UnitOfWork,
) -> None:
    u = users.create()
    token = make_token(u)
    only_rule(db_conn, "DISPATCHED", users=[u])
    only_rule(db_conn, "CN_ISSUED", users=[u], priority="HIGH")
    for _ in range(3):
        publish(uow, "DISPATCHED")
    publish(uow, "CN_ISSUED")
    res = await client.get(
        f"{API}/notifications/mine",
        headers=_h(token),
        params={"event_type": "DISPATCHED", "limit": 2},
    )
    body = res.json()
    assert res.status_code == 200 and body["total"] == 3 and len(body["items"]) == 2
    assert body["unread_count"] == 4
    res = await client.get(
        f"{API}/notifications/mine", headers=_h(token), params={"priority": "HIGH"}
    )
    [high] = res.json()["items"]
    assert high["event_type"] == "CN_ISSUED"
    await client.post(f"{API}/notifications/{high['id']}/read", headers=_h(token))
    res = await client.get(
        f"{API}/notifications/mine", headers=_h(token), params={"unread_only": True}
    )
    assert res.json()["total"] == 3
    await client.post(f"{API}/notifications/read-all", headers=_h(token))
    assert (await client.get(f"{API}/notifications/mine", headers=_h(token))).json()[
        "unread_count"
    ] == 0
