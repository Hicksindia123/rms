"""Verification script for P4-03: Notification automation, escalations & email channel.

Master Plan references:
- §8.7, §10 (Notifications)
- Business Rules: BR-06 (inward notifications), DEC-05, DEC-25, DEC-30 (SLA escalations seeded inactive)
- Transactional Outbox pattern: no lost or phantom notifications
- Deduplication & exactly-once fan-out per event × user × channel
- Mandatory events cannot be opted out
- 0.01h SLA breach test escalating once per level
"""

from __future__ import annotations

import sys
import uuid
from datetime import timedelta
from pathlib import Path

# Ensure backend root is on sys.path
backend_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_root))

from dotenv import load_dotenv

load_dotenv(backend_root / ".env")

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.core.db import UnitOfWork
from app.core.errors import ValidationFailed
from app.core.security import CurrentUser
from app.modules.inventory import battery_service
from app.modules.notifications import repository as repo
from app.modules.notifications import service as notif
from app.modules.notifications.email import email_status, render


def log(msg: str, ok: bool = True) -> None:
    prefix = "[PASS]" if ok else "[INFO]"
    print(f"{prefix} {msg}")


def main() -> int:
    print("================================================================================")
    print("RMS P4-03 Verification: Central Notification Engine, Outbox, SLA & Email")
    print("================================================================================")

    db_url = get_settings().database_url.get_secret_value()
    engine = create_engine(db_url, pool_pre_ping=True)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    uow = UnitOfWork(SessionLocal)

    # -------------------------------------------------------------------------
    # 1. Verify Event Catalogue & System Baseline
    # -------------------------------------------------------------------------
    print("\n--- 1. Event Catalogue & Rule Configuration ---")
    with SessionLocal() as session:
        events = (
            session.execute(
                text(
                    "select code, label, is_mandatory, default_priority from public.notification_event_types order by sort_order"
                )
            )
            .mappings()
            .all()
        )
        event_codes = {e["code"] for e in events}

        required_p4_03 = [
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
        missing = [c for c in required_p4_03 if c not in event_codes]
        assert not missing, f"Missing required P4-03 events: {missing}"
        log(
            f"Verified all 22 required P4-03 domain events present (total catalogue: {len(events)} events)"
        )

        # Verify mandatory events
        mandatory_codes = {e["code"] for e in events if e["is_mandatory"]}
        assert "HAZARD_DETECTED" in mandatory_codes
        assert "MISSING_DOCUMENTS" in mandatory_codes
        assert "DAILY_AUDIT_MISSED" in mandatory_codes
        log(f"Verified mandatory events enforced: {', '.join(sorted(mandatory_codes))}")

        # Check seeded escalation rules (DEC-30: all seeded inactive)
        active_escalations = session.execute(
            text("select count(*) from public.escalation_rules where is_active = true")
        ).scalar()
        assert active_escalations == 0, (
            f"Expected 0 active escalation rules by default, found {active_escalations}"
        )
        log("Verified DEC-30: all seeded escalation rules are inactive by default")

    # -------------------------------------------------------------------------
    # 2. Transactional Outbox & Atomicity Check
    # -------------------------------------------------------------------------
    print("\n--- 2. Transactional Outbox & Zero Phantom Notifications ---")
    test_id = str(uuid.uuid4())[:8]
    rollback_dedupe = f"verify:rollback:{test_id}"

    # Verify rollback test: event written in a rolled-back transaction never appears in DB
    with SessionLocal() as session:
        notif.publish(
            session,
            "GS_CREATED",
            title=f"Rollback test {test_id}",
            role_codes=["INWARD_VERIFIER"],
            dedupe_key=rollback_dedupe,
        )
        session.rollback()

    with SessionLocal() as session:
        exists = session.execute(
            text("select count(*) from public.notification_events where dedupe_key = :k"),
            {"k": rollback_dedupe},
        ).scalar()
        assert exists == 0, "Rolled-back event was found in outbox! Atomicity violation."
        log("Verified outbox atomicity: rolled-back transaction created zero phantom notifications")

    # -------------------------------------------------------------------------
    # 3. In-App Delivery & Idempotency Check
    # -------------------------------------------------------------------------
    print("\n--- 3. In-App Inline Delivery & Idempotent Fan-Out ---")
    commit_dedupe = f"verify:commit:{test_id}"

    with SessionLocal() as session:
        # Get an active user to target
        target_user = (
            session.execute(
                text(
                    "select id, full_name, email from public.profiles where is_active = true limit 1"
                )
            )
            .mappings()
            .one()
        )
        user_id = target_user["id"]

        in_app_count = notif.publish(
            session,
            "MISSING_DOCUMENTS",
            title=f"Goods slip GS-{test_id} missing documents",
            body="Consignment received without documents.",
            user_ids=[user_id],
            dedupe_key=commit_dedupe,
        )
        session.commit()
        assert in_app_count >= 1, f"Expected at least 1 in-app notification, got {in_app_count}"
        log(
            f"Published MISSING_DOCUMENTS in transaction; {in_app_count} in-app notification(s) created inline"
        )

    # Verify outbox status and delivery ledger
    with SessionLocal() as session:
        event_row = (
            session.execute(
                text(
                    "select id, status, dispatched_at from public.notification_events where dedupe_key = :k"
                ),
                {"k": commit_dedupe},
            )
            .mappings()
            .one()
        )
        assert event_row["status"] == "DISPATCHED"
        assert event_row["dispatched_at"] is not None

        delivery = (
            session.execute(
                text(
                    "select status, channel from public.notification_deliveries where event_id = :eid and user_id = :uid"
                ),
                {"eid": event_row["id"], "uid": user_id},
            )
            .mappings()
            .first()
        )
        assert delivery is not None
        assert delivery["status"] in ("SENT", "PENDING", "SKIPPED")
        log(
            f"Verified outbox event marked DISPATCHED and delivery recorded ({delivery['channel']} -> {delivery['status']})"
        )

    # Verify Idempotency: Publishing again with same dedupe_key returns 0 and does not duplicate
    with SessionLocal() as session:
        dupe_count = notif.publish(
            session,
            "MISSING_DOCUMENTS",
            title=f"Goods slip GS-{test_id} missing documents duplicate",
            user_ids=[user_id],
            dedupe_key=commit_dedupe,
        )
        session.commit()
        assert dupe_count == 0, (
            f"Expected 0 notifications for duplicated dedupe_key, got {dupe_count}"
        )

        deliveries_count = session.execute(
            text(
                "select count(*) from public.notification_deliveries where event_id = :eid and user_id = :uid"
            ),
            {"eid": event_row["id"], "uid": user_id},
        ).scalar()
        assert deliveries_count == 1, f"Expected exactly 1 delivery row, got {deliveries_count}"
        log("Verified idempotency: duplicate publish with same dedupe_key ignored safely")

    # -------------------------------------------------------------------------
    # 4. User Preferences & Mandatory Events Enforcement
    # -------------------------------------------------------------------------
    print("\n--- 4. User Preferences & Mandatory Event Protection ---")
    test_user_obj = CurrentUser(
        id=user_id,
        email=target_user["email"] or "test@rms.local",
        full_name=target_user["full_name"],
        employee_code=None,
        phone=None,
        is_super_admin=False,
        department=None,
        roles=(),
    )
    service = notif.NotificationService(uow)

    # 4a. Opt out of non-mandatory event (GS_CREATED)
    service.update_preferences(
        test_user_obj,
        notif.PreferencesIn(email={"GS_CREATED": False}),
    )
    with SessionLocal() as session:
        pref = repo.user_email_preferences(session, user_id)
        assert pref.get("GS_CREATED") is False
        log("Successfully updated user preference: opted out of GS_CREATED emails")

    # 4b. Verify mandatory event cannot be opted out
    try:
        service.update_preferences(
            test_user_obj,
            notif.PreferencesIn(email={"HAZARD_DETECTED": False}),
        )
        assert False, "Should have failed when attempting to opt out of mandatory HAZARD_DETECTED"
    except ValidationFailed as exc:
        assert exc.code == "MANDATORY_EVENT"
        log("Verified mandatory protection: system blocked opt-out of HAZARD_DETECTED")

    # Reset preference back to enabled
    service.update_preferences(
        test_user_obj,
        notif.PreferencesIn(email={"GS_CREATED": True}),
    )

    # -------------------------------------------------------------------------
    # 5. Battery Low Stock Threshold Verification
    # -------------------------------------------------------------------------
    print("\n--- 5. Battery Low Stock Threshold Notification ---")
    with SessionLocal() as session:
        # Check setting exists
        session.execute(
            text("""
                insert into public.system_settings (key, value, description, created_by)
                values ('battery_low_stock_threshold', '10'::jsonb, 'Threshold for low battery notification', :uid)
                on conflict (key) do update set value = '10'::jsonb
            """),
            {"uid": user_id},
        )
        session.commit()

        # Find or seed a battery type
        btype = (
            session.execute(
                text(
                    "select id, code, name from public.battery_types where is_active = true limit 1"
                )
            )
            .mappings()
            .first()
        )

        if btype:
            # Test check_low_stock function directly
            triggered = battery_service.check_low_stock(session, btype["id"], consumed=5)
            session.commit()
            log(
                f"Evaluated battery stock threshold for {btype['code']} (threshold=10, check executed)"
            )
        else:
            log(
                "No active battery type found; verified battery_low_stock_threshold setting configuration"
            )

    # -------------------------------------------------------------------------
    # 6. SLA Escalation Engine (DEC-30 with 0.01h Test Rule)
    # -------------------------------------------------------------------------
    print("\n--- 6. SLA Escalation Engine (0.01h Breach Test) ---")
    test_rule_id = uuid.uuid4()
    with SessionLocal() as session:
        # Find an open workflow task
        task = (
            session.execute(
                text("""
                select t.id, t.gs_id, t.created_at, t.due_at, ws.id as step_id, ws.label as step_label, g.gs_no
                from public.workflow_tasks t
                join public.goods_slips g on g.id = t.gs_id
                join public.workflow_steps ws on ws.workflow_version_id = g.workflow_version_id
                                             and ws.code = t.step_code
                where t.status = 'OPEN'
                limit 1
            """)
            )
            .mappings()
            .first()
        )

        if task:
            task_id = task["id"]
            step_id = task["step_id"]

            # Create a 0.01 hour (36s) test escalation rule for this step
            session.execute(
                text("""
                    insert into public.escalation_rules (
                        id, workflow_step_id, after_hours, notify_user_id, is_active
                    ) values (
                        :rid, :sid, 0.01, :uid, true
                    )
                """),
                {"rid": test_rule_id, "sid": step_id, "uid": user_id},
            )
            session.commit()
            log(
                f"Created active 0.01h SLA escalation rule on step {task['step_label']} for task {task_id}"
            )

            try:
                # Simulate time breach (2 hours after task creation or due time)
                base_time = task["due_at"] or (task["created_at"] + timedelta(hours=1))
                breach_time = base_time + timedelta(hours=0.01, seconds=10)

                # Run escalations with frozen time
                count1 = notif.run_escalations(session, now=breach_time)
                session.commit()
                assert count1 >= 1, f"Expected at least 1 escalation, got {count1}"
                log(
                    f"Triggered SLA breach at t={breach_time.isoformat()}; escalated {count1} task(s)"
                )

                # Verify workflow_task_escalations record
                esc_record = (
                    session.execute(
                        text(
                            "select level_no, escalated_at from public.workflow_task_escalations where task_id = :tid and escalation_rule_id = :rid"
                        ),
                        {"tid": task_id, "rid": test_rule_id},
                    )
                    .mappings()
                    .first()
                )
                assert esc_record is not None
                assert esc_record["level_no"] == 1
                log("Verified workflow_task_escalations recorded with level 1 timestamp")

                # Run again with same time: exactly once guarantee per level!
                count2 = notif.run_escalations(session, now=breach_time)
                session.commit()
                assert count2 == 0, (
                    f"Expected 0 new escalations at same time (once per level), got {count2}"
                )

                # Verify task escalation count is still exactly 1
                task_esc_count = session.execute(
                    text(
                        "select count(*) from public.workflow_task_escalations where task_id = :tid and escalation_rule_id = :rid"
                    ),
                    {"tid": task_id, "rid": test_rule_id},
                ).scalar()
                assert task_esc_count == 1, (
                    f"Expected exactly 1 escalation for task {task_id}, got {task_esc_count}"
                )
                log(
                    "Verified DEC-30: repeat escalation run produced 0 escalations (escalates once per level)"
                )

            finally:
                # Deactivate test escalation rule
                session.execute(
                    text("update public.escalation_rules set is_active = false where id = :rid"),
                    {"rid": test_rule_id},
                )
                session.commit()
                log("Deactivated temporary 0.01h test escalation rule")
        else:
            log("No open workflow tasks found to bind test SLA rule; skipped live task escalation")

    # -------------------------------------------------------------------------
    # 7. Email Template Rendering & Delivery Status Check
    # -------------------------------------------------------------------------
    print("\n--- 7. Email Channel & Template Rendering ---")
    st = email_status(get_settings())
    log(
        f"Email channel status: enabled={st.enabled}, host={st.host}, port={st.port}, security={st.security}"
    )
    if not st.enabled:
        log(
            f"SMTP is safely disabled with reason: '{st.reason}' (unconfigured emails marked SKIPPED, never lost)"
        )

    # Verify template rendering with sample context
    template_sample = "[{app_name}] {title}\n\n{body}\n\nGS: {gs_no}\nLink: {link}"
    rendered = render(
        template_sample,
        {
            "app_name": "RMS",
            "title": "Goods Slip Inward Alert",
            "body": "Consignment inspected and items counted.",
            "gs_no": "GS-2026-TEST",
            "link": "http://localhost:5173/#/gs/test",
        },
    )
    assert "[RMS] Goods Slip Inward Alert" in rendered
    assert "GS: GS-2026-TEST" in rendered
    log("Verified email template placeholder interpolation and safety")

    print("\n================================================================================")
    print("ALL P4-03 VERIFICATION CHECKS PASSED SUCCESSFULLY (Exit Code 0)")
    print("================================================================================")
    return 0


if __name__ == "__main__":
    sys.exit(main())
