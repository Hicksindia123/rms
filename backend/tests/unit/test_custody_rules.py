"""Pure rules of the custody engine (prompt P3-01; BR-21, G-09, DEC-14)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.core.errors import SystemGuardUnmet, ValidationFailed
from app.modules.custody import service
from app.modules.custody.schemas import ReconcileIn, TransferLineIn

LOT_A, LOT_B = uuid.uuid4(), uuid.uuid4()


def lines(*counts: tuple[int, int]) -> list[dict[str, Any]]:
    return [
        {"lot_id": lot, "qty_sent": sent, "qty_counted": counted}
        for lot, (sent, counted) in zip((LOT_A, LOT_B), counts, strict=False)
    ]


@pytest.mark.parametrize(
    ("code", "disposition", "counts", "expected"),
    [
        ("ACCEPT_COUNTED_WITH_ADJUSTMENT", "RETURN_TO_SOURCE", [(5, 4)], False),
        ("ACCEPT_COUNTED_WITH_ADJUSTMENT", "WRITE_OFF_LOSS", [(5, 4)], True),
        ("ACCEPT_COUNTED_WITH_ADJUSTMENT", "RETURN_TO_SOURCE", [(5, 6)], True),  # excess
        ("CANCEL_RETURN", None, [(5, 4)], False),
        ("RESEND_CORRECTED", None, [(5, 6)], False),
    ],
)
def test_rm_approval_needed_only_for_stock_adjustments(
    code: str, disposition: str | None, counts: list[tuple[int, int]], expected: bool
) -> None:
    assert service._requires_rm_approval(code, disposition, lines(*counts)) is expected


def test_accept_counted_requires_a_disposition_for_shortages() -> None:
    payload = ReconcileIn(resolution_code="ACCEPT_COUNTED_WITH_ADJUSTMENT", notes="n")
    with pytest.raises(ValidationFailed) as exc:
        service._validate_resolution(payload, lines((5, 4)))
    assert exc.value.details == {"difference_disposition": ["Required"]}
    # Excess only: nothing to dispose of → defaults to RETURN_TO_SOURCE.
    assert service._validate_resolution(payload, lines((5, 6))) == ("RETURN_TO_SOURCE", [])


def test_resend_defaults_to_counted_quantities_and_rejects_foreign_lots() -> None:
    payload = ReconcileIn(resolution_code="RESEND_CORRECTED", notes="n")
    disposition, resend = service._validate_resolution(payload, lines((5, 4), (3, 0)))
    assert disposition is None and resend == [{"lot_id": str(LOT_A), "qty": 4}]
    foreign = ReconcileIn(
        resolution_code="RESEND_CORRECTED",
        notes="n",
        resend_lines=[TransferLineIn(lot_id=uuid.uuid4(), qty=1)],
    )
    with pytest.raises(ValidationFailed):
        service._validate_resolution(foreign, lines((5, 4)))
    nothing = ReconcileIn(resolution_code="RESEND_CORRECTED", notes="n")
    with pytest.raises(ValidationFailed):
        service._validate_resolution(nothing, lines((5, 0)))
    misplaced = ReconcileIn(
        resolution_code="CANCEL_RETURN",
        notes="n",
        resend_lines=[TransferLineIn(lot_id=LOT_A, qty=1)],
    )
    with pytest.raises(ValidationFailed):
        service._validate_resolution(misplaced, lines((5, 4)))


def test_same_proposal_ignores_order_and_types() -> None:
    current = {
        "resolution_code": "RESEND_CORRECTED",
        "difference_disposition": None,
        "resend_lines": [{"lot_id": str(LOT_B), "qty": 2}, {"lot_id": str(LOT_A), "qty": "1"}],
    }
    resend = sorted(
        [{"lot_id": str(LOT_A), "qty": 1}, {"lot_id": str(LOT_B), "qty": 2}],
        key=lambda x: str(x["lot_id"]),
    )
    assert service._same_proposal(current, "RESEND_CORRECTED", None, resend)
    assert not service._same_proposal(current, "CANCEL_RETURN", None, [])


@pytest.mark.parametrize(
    ("lot", "enabled", "step"),
    [
        (
            {"condition_class": "AS_RECEIVED", "routing_hint": "SELLABLE"},
            True,
            "DIRECT_CLASSIFICATION",
        ),
        (
            {"condition_class": "AS_RECEIVED", "routing_hint": "SELLABLE"},
            False,
            "AWAITING_TECHNICIAN",
        ),
        (
            {"condition_class": "AS_RECEIVED", "routing_hint": "REPACK_OR_TECH"},
            True,
            "AWAITING_TECHNICIAN",
        ),
        (
            {"condition_class": "AS_RECEIVED", "routing_hint": "TO_TECHNICIAN"},
            True,
            "AWAITING_TECHNICIAN",
        ),
        (
            {
                "condition_class": "AS_RECEIVED",
                "routing_hint": "SELLABLE",
                "requires_evaluation": True,
            },
            True,
            "AWAITING_TECHNICIAN",
        ),
        ({"condition_class": "FUNCTIONAL_GOOD", "routing_hint": "SELLABLE"}, True, "CLASSIFIED"),
        ({"condition_class": "AS_RECEIVED", "routing_hint": None}, True, "AWAITING_TECHNICIAN"),
    ],
)
def test_dec14_routing_in_the_intermediate_store(
    lot: dict[str, Any], enabled: bool, step: str
) -> None:
    assert service._next_step(lot, enabled) == step


@pytest.mark.parametrize(
    ("lot", "target_class", "guard"),
    [
        ({"condition_class": "AS_RECEIVED", "is_pending": True}, "FUNCTIONAL", "G-08"),
        ({"condition_class": "HAZARD", "is_pending": False}, "NON_FUNCTIONAL", "G-05"),
        ({"condition_class": "NOT_ALLOWED", "is_pending": False}, "FUNCTIONAL", "G-04"),
        ({"condition_class": "SALVAGED", "is_pending": False}, "FUNCTIONAL", "G-12"),
    ],
)
def test_location_guards_refuse_before_any_stock_moves(
    lot: dict[str, Any], target_class: str, guard: str
) -> None:
    lot = {"id": LOT_A, "source_condition_code": None, **lot}
    transit = {"location_class": "TRANSIT"}
    target = {"location_class": target_class, "name": "Target", "code": "T"}
    with pytest.raises(SystemGuardUnmet) as exc:
        service._assert_lot_may_move(lot, transit, target)
    assert exc.value.code == guard and exc.value.status_code == 422


def test_allowed_lot_passes_location_guards() -> None:
    lot = {
        "id": LOT_A,
        "condition_class": "AS_RECEIVED",
        "is_pending": False,
        "source_condition_code": None,
    }
    service._assert_lot_may_move(
        lot,
        {"location_class": "TRANSIT"},
        {"location_class": "FUNCTIONAL", "name": "S", "code": "S"},
    )
