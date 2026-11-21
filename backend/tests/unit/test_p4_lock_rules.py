"""Phase P4 unit tests (no DB): DEC-64 input rules for the popup, the lock and the edits after the
lock (reason required, extra fields refused). Replaces the retired RM-edit schema tests (DEC-54,
retired by DEC-64 / Q9)."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.modules.itemization.schemas import (
    LockedAddLineIn,
    LockedLineIn,
    LockedRemoveIn,
    LockIn,
    ReturnChoiceIn,
)


def test_return_choice_needs_a_code_and_nothing_else() -> None:
    assert ReturnChoiceIn.model_validate({"category_code": "RO"}).category_code == "RO"
    with pytest.raises(ValidationError):
        ReturnChoiceIn.model_validate({"category_code": ""})
    with pytest.raises(ValidationError):
        ReturnChoiceIn.model_validate({"category_code": "RO", "remarks": "x"})


def test_lock_takes_optional_remarks_only() -> None:
    assert LockIn.model_validate({}).remarks is None
    with pytest.raises(ValidationError):
        LockIn.model_validate({"category_code": "RO"})


@pytest.mark.parametrize("reason", ["", "  ", "ab"])
def test_locked_edits_need_a_reason(reason: str) -> None:
    with pytest.raises(ValidationError):
        LockedLineIn.model_validate({"received_qty": 3, "reason": reason})
    with pytest.raises(ValidationError):
        LockedRemoveIn.model_validate({"reason": reason})
    with pytest.raises(ValidationError):
        LockedAddLineIn.model_validate(
            {"product_id": str(uuid.uuid4()), "received_qty": 1, "reason": reason}
        )


def test_locked_line_refuses_unknown_fields_and_negative_qty() -> None:
    with pytest.raises(ValidationError):
        LockedLineIn.model_validate({"remarks": "x", "reason": "fix count"})
    with pytest.raises(ValidationError):
        LockedLineIn.model_validate({"received_qty": -1, "reason": "fix count"})
    ok = LockedLineIn.model_validate(
        {"received_qty": 3, "buckets": [{"field_code": "OK", "qty": 3}], "reason": "fix count"}
    )
    assert ok.buckets is not None and ok.buckets[0].qty == 3
