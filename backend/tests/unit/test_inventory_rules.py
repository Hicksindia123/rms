"""P3-04 pure rules: DD r63-66 custody assignment validity, adjustment movements, CSV export."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.core.errors import SystemGuardViolation, ValidationFailed
from app.modules.inventory.service import (
    adjustment_movement,
    assignment_codes_for,
    check_assignment,
    to_csv,
)


@pytest.mark.parametrize(
    ("condition", "kind", "codes"),
    [
        ("FUNCTIONAL_GOOD", "FINISHED_GOOD", ["CUST_FUNCTIONAL_GOOD"]),
        ("FUNCTIONAL_REPAIRED", "FINISHED_GOOD", ["CUST_FUNCTIONAL_REPAIRED"]),
        ("NON_GOOD", "FINISHED_GOOD", ["CUST_NON_FUNCTIONAL"]),
        ("NON_SELLABLE", "FINISHED_GOOD", ["CUST_NON_FUNCTIONAL"]),
        ("NOT_ALLOWED", "FINISHED_GOOD", ["CUST_NON_FUNCTIONAL"]),
        ("SALVAGED", "SPARE_PART", ["CUST_SALVAGED_PARTS"]),
        ("AS_RECEIVED", "FINISHED_GOOD", []),
        ("HAZARD", "FINISHED_GOOD", []),
        ("SCRAP", "FINISHED_GOOD", []),
        ("FUNCTIONAL_GOOD", "BATTERY", []),
    ],
)
def test_assignment_codes_for(condition: str, kind: str, codes: list[str]) -> None:
    assert assignment_codes_for(condition, kind) == codes


@pytest.mark.parametrize(
    ("condition", "code", "guard"),
    [
        ("NON_GOOD", "CUST_FUNCTIONAL_GOOD", "G-04"),
        ("NON_SELLABLE", "CUST_FUNCTIONAL_REPAIRED", "G-04"),
        ("NOT_ALLOWED", "CUST_FUNCTIONAL_GOOD", "G-04"),
        ("SCRAP", "CUST_FUNCTIONAL_GOOD", "G-04"),
        ("SALVAGED", "CUST_FUNCTIONAL_GOOD", "G-12"),
        ("HAZARD", "CUST_NON_FUNCTIONAL", "G-05"),
        ("HAZARD", "CUST_FUNCTIONAL_GOOD", "G-05"),
    ],
)
def test_contradictions_are_guard_violations(condition: str, code: str, guard: str) -> None:
    kind = "SPARE_PART" if condition == "SALVAGED" else "FINISHED_GOOD"
    with pytest.raises(SystemGuardViolation) as exc:
        check_assignment(condition, kind, code)
    assert exc.value.guard == guard


@pytest.mark.parametrize(
    ("condition", "kind", "code", "error"),
    [
        (
            "FUNCTIONAL_GOOD",
            "FINISHED_GOOD",
            "CUST_FUNCTIONAL_REPAIRED",
            "CUSTODY_ASSIGNMENT_MISMATCH",
        ),
        ("FUNCTIONAL_GOOD", "FINISHED_GOOD", "CUST_NON_FUNCTIONAL", "CUSTODY_ASSIGNMENT_MISMATCH"),
        ("NON_GOOD", "FINISHED_GOOD", "CUST_SALVAGED_PARTS", "CUSTODY_ASSIGNMENT_MISMATCH"),
        (
            "AS_RECEIVED",
            "FINISHED_GOOD",
            "CUST_FUNCTIONAL_GOOD",
            "CUSTODY_ASSIGNMENT_NEEDS_CLASSIFICATION",
        ),
        ("FUNCTIONAL_GOOD", "BATTERY", "CUST_FUNCTIONAL_GOOD", "CUSTODY_ASSIGNMENT_NOT_APPLICABLE"),
        ("FUNCTIONAL_GOOD", "FINISHED_GOOD", "CUST_UNKNOWN", "CUSTODY_ASSIGNMENT_INVALID"),
    ],
)
def test_mismatches_are_validation_errors(condition: str, kind: str, code: str, error: str) -> None:
    with pytest.raises(ValidationFailed) as exc:
        check_assignment(condition, kind, code)
    assert exc.value.code == error


@pytest.mark.parametrize(
    ("condition", "kind", "code"),
    [
        ("FUNCTIONAL_GOOD", "FINISHED_GOOD", "CUST_FUNCTIONAL_GOOD"),
        ("FUNCTIONAL_REPAIRED", "FINISHED_GOOD", "CUST_FUNCTIONAL_REPAIRED"),
        ("NON_SELLABLE", "FINISHED_GOOD", "CUST_NON_FUNCTIONAL"),
        ("SALVAGED", "SPARE_PART", "CUST_SALVAGED_PARTS"),
    ],
)
def test_valid_assignments_pass(condition: str, kind: str, code: str) -> None:
    check_assignment(condition, kind, code)


def test_adjustment_movement_direction() -> None:
    loc = uuid.uuid4()
    assert adjustment_movement(loc, -3) == (loc, None, 3)
    assert adjustment_movement(loc, 2) == (None, loc, 2)
    with pytest.raises(ValidationFailed):
        adjustment_movement(loc, 0)


def test_csv_neutralises_formulas_and_formats_dates() -> None:
    out = to_csv(
        [
            {
                "gs_no": "GS/2026-27/00001",
                "product_name": "=HYPERLINK(evil)",
                "qty": 4,
                "received_at": datetime(2026, 11, 4, 10, 0, tzinfo=UTC),
            }
        ]
    )
    header, row = out.splitlines()
    assert header.startswith("GS No.,Line,Product code,Product")
    assert "'=HYPERLINK(evil)" in row
    assert "2026-11-04T10:00:00+00:00" in row
