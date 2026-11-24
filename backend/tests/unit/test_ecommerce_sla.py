"""DEC-73: SLA state of an E-Commerce platform ticket (2-hour window to raise it)."""

from datetime import UTC, datetime, timedelta

from app.modules.ecommerce_returns.service import _sla

DUE = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)


def test_unraised_before_due_is_on_time_with_minutes_left() -> None:
    assert _sla({"sla_due_at": DUE, "raised_at": None}, DUE - timedelta(minutes=45)) == (
        "ON_TIME",
        45,
    )


def test_unraised_after_due_is_overdue() -> None:
    state, minutes = _sla({"sla_due_at": DUE, "raised_at": None}, DUE + timedelta(minutes=10))
    assert state == "OVERDUE" and minutes is not None and minutes < 0


def test_raised_records_whether_it_was_late() -> None:
    now = DUE + timedelta(hours=5)
    assert _sla({"sla_due_at": DUE, "raised_at": DUE - timedelta(minutes=1)}, now) == (
        "RAISED_ON_TIME",
        None,
    )
    assert _sla({"sla_due_at": DUE, "raised_at": DUE + timedelta(minutes=1)}, now) == (
        "RAISED_LATE",
        None,
    )
