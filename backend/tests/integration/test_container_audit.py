"""Integration tests for Daily DMT Container Audit (P2-06, BR-18, DEC-08, DD r31)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Connection, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.db import get_session_factory
from app.core.middleware import limiter
from app.modules.container_audit import service as audit_service
from app.shared.storage import get_storage
from tests.conftest import JwtFactory
from tests.integration.conftest import UserFactory, as_admin, build_test_app
from tests.integration.test_gate_inward import Masters, _auth
from tests.integration.test_inspection import (
    TriProducts,
    inspection_ready_gs,
    key,
)
from tests.integration.test_unboxing import Actors, FakeStorage

TZ_KOLKATA = ZoneInfo("Asia/Kolkata")


@pytest.fixture
def storage() -> FakeStorage:
    return FakeStorage()


@pytest.fixture
def masters(db_conn: Connection) -> Masters:
    return Masters(db_conn)


@pytest.fixture
def tri_products(db_conn: Connection) -> TriProducts:
    c = as_admin(db_conn)
    tag = uuid.uuid4().hex[:6].upper()

    def make(category: str) -> str:
        return str(
            c.execute(
                text(
                    """insert into public.products (code, name, category_id)
                       select :code, :name, id from public.product_categories where code = :cat
                       returning id"""
                ),
                {"code": f"PRD-{category}-{tag}", "name": f"Product {category}", "cat": category},
            ).scalar_one()
        )

    return TriProducts(
        dmt=make("DMT"),
        prismatic=make("PRISMATIC"),
        eo=make("ENCLOSED_OVAL"),
    )


@pytest.fixture
def actors(users: UserFactory, make_token: JwtFactory) -> Actors:
    aman_id = users.create(roles=["INWARD_VERIFIER"], full_name="Aman")
    rm_id = users.create(roles=["REPLACEMENT_MANAGER"], full_name="Pratham")
    acc_id = users.create(roles=["ACCOUNTS"], full_name="Deepak")
    return Actors(
        gate=make_token(users.create(roles=["GATE_INWARD"], full_name="Anuj")),
        aman=make_token(aman_id),
        aman_id=aman_id,
        rm=make_token(rm_id),
        rm_id=rm_id,
        accounts=make_token(acc_id),
        accounts_id=acc_id,
        admin=make_token(users.create(super_admin=True, full_name="Admin")),
    )


@pytest.fixture
async def client(session_factory: sessionmaker[Session], storage: FakeStorage) -> Any:
    app = build_test_app()
    app.dependency_overrides[get_session_factory] = lambda: session_factory
    app.dependency_overrides[get_storage] = lambda: storage
    limiter.reset()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    limiter.reset()


@pytest.mark.asyncio
async def test_today_audit_lazy_creation_and_fields(
    client: AsyncClient,
    actors: Actors,
) -> None:
    """GET /container-audits/today creates today's record and returns all active DMT containers."""
    res = await client.get("/api/v1/container-audits/today", headers=_auth(actors.aman))
    assert res.status_code == 200, res.text
    data = res.json()

    assert data["day"]["status"] == "PENDING"
    assert data["day"]["confirmed"] is False
    assert data["can_edit"] is True
    assert data["can_confirm"] is True
    assert data["checkbox_label"] == "Containers Checked & Counted Daily"

    containers = data["containers"]
    assert len(containers) >= 4
    for c in containers:
        assert c["container_code"].startswith("DMT-")
        assert c["counted_qty"] == 0
        assert c["sellable_packaging_qty"] == 0


@pytest.mark.asyncio
async def test_save_lines_and_confirm_lifecycle(
    client: AsyncClient,
    actors: Actors,
    session_factory: sessionmaker[Session],
) -> None:
    """Enter counts for containers, attempt partial confirm (fails BR-18), then complete confirm."""
    # 1. Fetch today
    today_res = await client.get("/api/v1/container-audits/today", headers=_auth(actors.aman))
    today_data = today_res.json()
    today_str = today_data["day"]["audit_date"]
    containers = today_data["containers"]
    assert len(containers) >= 2

    # 2. Save only the first container's count
    first_c = containers[0]
    save_res = await client.put(
        f"/api/v1/container-audits/{today_str}/lines",
        json={
            "lines": [
                {
                    "container_id": first_c["container_id"],
                    "counted_qty": 15,
                    "sellable_packaging_qty": 5,
                    "remarks": "Partially counted bin 1",
                }
            ]
        },
        headers=_auth(actors.aman),
    )
    assert save_res.status_code == 200, save_res.text

    # 3. Attempt confirmation with incomplete active containers -> rejected (BR-18)
    bad_confirm = await client.post(
        f"/api/v1/container-audits/{today_str}/confirm",
        json={"confirmed": True},
        headers=_auth(actors.aman),
    )
    assert bad_confirm.status_code == 422
    assert "all active DMT containers must be counted" in bad_confirm.json()["error"]["message"]

    # 4. Supply lines for all remaining active containers
    all_lines = [
        {
            "container_id": c["container_id"],
            "counted_qty": 20,
            "sellable_packaging_qty": 4,
            "remarks": f"Bin {c['container_code']} verified",
        }
        for c in containers
    ]
    good_confirm = await client.post(
        f"/api/v1/container-audits/{today_str}/confirm",
        json={
            "confirmed": True,
            "remarks": "Daily audit complete for all DMT bins",
            "lines": all_lines,
        },
        headers=_auth(actors.aman),
    )
    assert good_confirm.status_code == 200, good_confirm.text
    conf_data = good_confirm.json()
    assert conf_data["day"]["status"] == "CONFIRMED"
    assert conf_data["day"]["confirmed"] is True
    assert conf_data["day"]["is_late"] is False
    assert conf_data["can_confirm"] is False

    # 5. Modifying lines after confirmation raises Conflict (409)
    blocked_edit = await client.put(
        f"/api/v1/container-audits/{today_str}/lines",
        json={"lines": all_lines},
        headers=_auth(actors.aman),
    )
    assert blocked_edit.status_code == 409


@pytest.mark.asyncio
async def test_late_entry_requires_reason(
    client: AsyncClient,
    actors: Actors,
    session_factory: sessionmaker[Session],
) -> None:
    """Confirming past audit requires late_reason and sets is_late=True (status=LATE)."""
    past_date = datetime.now(TZ_KOLKATA).date() - timedelta(days=2)
    past_str = past_date.isoformat()

    # Get active containers
    today_res = await client.get("/api/v1/container-audits/today", headers=_auth(actors.aman))
    containers = today_res.json()["containers"]
    all_lines = [
        {
            "container_id": c["container_id"],
            "counted_qty": 10,
            "sellable_packaging_qty": 2,
        }
        for c in containers
    ]

    # Past date confirm without late_reason -> 422
    no_reason_res = await client.post(
        f"/api/v1/container-audits/{past_str}/confirm",
        json={
            "confirmed": True,
            "lines": all_lines,
        },
        headers=_auth(actors.aman),
    )
    assert no_reason_res.status_code == 422
    err_msg = no_reason_res.json()["error"]["message"]
    assert "Late entry for a past date requires a reason" in err_msg

    # Past date confirm with late_reason -> 200, status=LATE, is_late=True
    late_res = await client.post(
        f"/api/v1/container-audits/{past_str}/confirm",
        json={
            "confirmed": True,
            "late_reason": "Auditor was absent; physical register transcribed today.",
            "lines": all_lines,
        },
        headers=_auth(actors.aman),
    )
    assert late_res.status_code == 200, late_res.text
    late_data = late_res.json()
    assert late_data["day"]["status"] == "LATE"
    assert late_data["day"]["is_late"] is True
    assert late_data["day"]["late_reason"] == (
        "Auditor was absent; physical register transcribed today."
    )


@pytest.mark.asyncio
async def test_calendar_endpoint(
    client: AsyncClient,
    actors: Actors,
) -> None:
    """GET /container-audits?from=...&to=... returns aggregated compliance data."""
    today = datetime.now(TZ_KOLKATA).date()
    from_date = (today - timedelta(days=7)).isoformat()
    to_date = today.isoformat()

    res = await client.get(
        f"/api/v1/container-audits?from={from_date}&to={to_date}",
        headers=_auth(actors.aman),
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert "days" in data
    assert "today_status" in data


@pytest.mark.asyncio
async def test_worker_evening_alert_and_morning_missed(
    session_factory: sessionmaker[Session],
) -> None:
    """Test background worker functions for evening reminder and morning missed transition."""
    # 1. Past date left unconfirmed
    past_date = datetime.now(TZ_KOLKATA).date() - timedelta(days=3)
    with session_factory() as session:
        session.execute(
            text(
                """
                insert into public.container_audit_days (audit_date, status, confirmed)
                values (:dt, 'PENDING', false)
                on conflict (audit_date) do update set status = 'PENDING', confirmed = false
                """
            ),
            {"dt": past_date},
        )
        session.commit()

        # Morning missed transition runs
        missed_count = audit_service.run_morning_missed_transition(session)
        assert missed_count >= 1

        # Check status updated to MISSED
        row = session.execute(
            text("select status from public.container_audit_days where audit_date = :dt"),
            {"dt": past_date},
        ).scalar_one()
        assert row == "MISSED"

        # Today unconfirmed -> Evening alert runs
        today = datetime.now(TZ_KOLKATA).date()
        # Reset today to unconfirmed if confirmed by earlier tests
        session.execute(
            text(
                "update public.container_audit_days "
                "set confirmed = false, status = 'PENDING' where audit_date = :dt"
            ),
            {"dt": today},
        )
        session.commit()

        alert_count = audit_service.run_evening_alert(session)
        assert alert_count >= 1


@pytest.mark.asyncio
async def test_register_for_a_chosen_date(client: AsyncClient, actors: Actors) -> None:
    """P2-08 fix: the register for a past date is that day's, not today's; no future dates."""
    today = datetime.now(TZ_KOLKATA).date()
    past = today - timedelta(days=5)
    res = await client.get(f"/api/v1/container-audits/{past}", headers=_auth(actors.aman))
    assert res.status_code == 200, res.text
    assert res.json()["day"]["audit_date"] == str(past)
    assert res.json()["containers"]
    res = await client.get(
        f"/api/v1/container-audits/{today + timedelta(days=1)}", headers=_auth(actors.aman)
    )
    assert res.status_code == 422, res.text
    res = await client.get(f"/api/v1/container-audits/{past}", headers=_auth(actors.gate))
    assert res.status_code == 403, res.text


@pytest.mark.asyncio
async def test_morning_missed_flags_days_nobody_opened(
    session_factory: sessionmaker[Session],
) -> None:
    """BR-18 / DEC-08 (P2-08 fix): a skipped day has no row at all and must still be flagged."""
    today = datetime.now(TZ_KOLKATA).date()
    first = today - timedelta(days=40)
    gap = [first + timedelta(days=1), first + timedelta(days=2)]
    with session_factory() as session:
        session.execute(
            text("delete from public.container_audit_days where audit_date >= :d"), {"d": first}
        )
        session.execute(
            text(
                """insert into public.container_audit_days (audit_date, status, confirmed)
                   values (:d, 'CONFIRMED', true)"""
            ),
            {"d": first},
        )
        session.commit()

        assert audit_service.run_morning_missed_transition(session) >= len(gap)
        rows = dict(
            session.execute(
                text(
                    """select audit_date, status from public.container_audit_days
                        where audit_date between :a and :b"""
                ),
                {"a": first, "b": today},
            ).all()
        )
        assert rows[first] == "CONFIRMED"
        assert all(rows[d] == "MISSED" for d in gap)
        assert today not in rows  # today is still open, not missed
        # Re-running is a no-op for those days.
        audit_service.run_morning_missed_transition(session)
        again = session.execute(
            text("select count(*) from public.container_audit_days where audit_date = any(:d)"),
            {"d": gap},
        ).scalar_one()
        assert again == len(gap)


@pytest.mark.asyncio
async def test_daily_audit_blocks_inspection_toggle(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    tri_products: TriProducts,
    session_factory: sessionmaker[Session],
) -> None:
    """Verify daily_audit_blocks_inspection toggle (DEC-08): false allows, true blocks."""
    today = datetime.now(TZ_KOLKATA).date()
    today_str = today.isoformat()

    # Create a DMT goods slip ready for inspection
    gs_id = await inspection_ready_gs(
        client,
        storage,
        actors,
        masters,
        [(tri_products.dmt, 10, 10)],
    )
    insp_res = await client.get(f"/api/v1/gs/{gs_id}/inspection", headers=_auth(actors.aman))
    gs_item_id = insp_res.json()["lines"][0]["gs_item_id"]

    # Draft inspection
    await client.put(
        f"/api/v1/gs-items/{gs_item_id}/inspection",
        json={
            "allocations": [{"condition_code": "DMT_OK_PACKED", "qty": 10}],
            "extraction": {
                "primary_type": "PACKAGING_EXTRACTED",
                "packaging_qty": 10,
                "container_qty": 0,
            },
        },
        headers=_auth(actors.aman),
    )

    # 1. Unconfirm today's container audit
    with session_factory() as session:
        session.execute(
            text(
                "update public.container_audit_days "
                "set confirmed = false, status = 'PENDING' where audit_date = :dt"
            ),
            {"dt": today},
        )
        # Ensure setting is FALSE (default)
        session.execute(
            text(
                "update public.system_settings "
                "set value = 'false'::jsonb where key = 'daily_audit_blocks_inspection'"
            )
        )
        session.commit()

    # 2. When toggle is false -> finalise succeeds even if audit pending
    # Toggle to TRUE
    with session_factory() as session:
        session.execute(
            text(
                "update public.system_settings "
                "set value = 'true'::jsonb where key = 'daily_audit_blocks_inspection'"
            )
        )
        session.commit()

    # 3. When toggle is true and audit unconfirmed -> 422 error
    blocked_fin = await client.post(
        f"/api/v1/gs-items/{gs_item_id}/inspection/finalise",
        headers=_auth(actors.aman, key()),
    )
    assert blocked_fin.status_code == 422
    assert (
        f"Daily container audit pending for {today_str}" in (blocked_fin.json()["error"]["message"])
    )

    # 4. Confirm today's audit
    today_res = await client.get("/api/v1/container-audits/today", headers=_auth(actors.aman))
    containers = today_res.json()["containers"]
    all_lines = [
        {"container_id": c["container_id"], "counted_qty": 5, "sellable_packaging_qty": 1}
        for c in containers
    ]
    conf_res = await client.post(
        f"/api/v1/container-audits/{today_str}/confirm",
        json={"confirmed": True, "lines": all_lines},
        headers=_auth(actors.aman),
    )
    assert conf_res.status_code == 200

    # 5. Now finalise succeeds!
    ok_fin = await client.post(
        f"/api/v1/gs-items/{gs_item_id}/inspection/finalise",
        headers=_auth(actors.aman, key()),
    )
    assert ok_fin.status_code == 200, ok_fin.text
    assert ok_fin.json()["status"] == "FINAL"

    # Reset toggle to false for cleanliness
    with session_factory() as session:
        session.execute(
            text(
                "update public.system_settings "
                "set value = 'false'::jsonb where key = 'daily_audit_blocks_inspection'"
            )
        )
        session.commit()
