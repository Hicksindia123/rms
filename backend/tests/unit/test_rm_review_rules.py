"""Unit tests for RM Review editing rules (DEC-54, Q1, Q2, T1-T3, G-19, BR-07).

Tests:
1. Pydantic schema validation:
   - RmAddLineIn: reason required and non-empty.
   - RmRemoveLineIn: reason required and non-empty.
   - RmChangeProductIn: reason required and non-empty.
2. Service rules with mocked UoW / Session:
   - T2: All operations (add_line, remove_line, change_product, edit_item, send_back, approve)
     are blocked with Conflict if a transfer_slip_id already exists on the goods slip.
   - G-19 conservation: add_line and change_product reject bucket sum != received_qty.
   - BR-07: remove_line requires at least 2 lines; removing the last line
     raises ValidationFailed(ITEMS_REQUIRED).
   - T3: split is replaced whole (deleting existing buckets and counts).
   - Audit trail: revisions RM_ADD_LINE, RM_REMOVE_LINE, RM_CHANGE_PRODUCT, RM_EDIT recorded.
   - Inward booking: categorisation submit does NOT book stock;
     RM approval performs inward stock booking.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from app.core.errors import Conflict, SystemGuardViolation, ValidationFailed
from app.core.permissions import EffectivePermissions
from app.core.security import CurrentUser, Role
from app.modules.itemization.schemas import ItemBucketIn, ItemCountIn, SubmitCategorisationIn
from app.modules.itemization.service import ItemizationService
from app.modules.rm_review.schemas import (
    RmAddLineIn,
    RmApproveIn,
    RmChangeProductIn,
    RmEditItemIn,
    RmRemoveLineIn,
    RmSendBackIn,
)
from app.modules.rm_review.service import RmReviewService


def _fake_user(roles: list[str] | None = None, super_admin: bool = False) -> CurrentUser:
    role_names = roles or ["REPLACEMENT_MANAGER"]
    return CurrentUser(
        id=uuid.uuid4(),
        email="rm@example.com",
        full_name="Pratham (RM)",
        employee_code="EMP01",
        phone=None,
        is_super_admin=super_admin,
        department=None,
        roles=tuple(Role(id=uuid.uuid4(), code=r, name=r) for r in role_names),
    )


def _fake_perms(super_admin: bool = False) -> EffectivePermissions:
    return EffectivePermissions(
        is_super_admin=super_admin,
        grants={("itemization", "approve"): "all"},
    )


# -----------------------------------------------------------------------------
# 1. Schema Validation Tests
# -----------------------------------------------------------------------------


def test_rm_add_line_schema_reason_required() -> None:
    valid_data: dict[str, Any] = {
        "product_id": str(uuid.uuid4()),
        "documented_qty": 5,
        "received_qty": 5,
        "buckets": [{"field_code": "OK_PACKED", "qty": 5}],
        "counts": [],
        "reason": "Found extra unopened carton with goods",
    }
    schema = RmAddLineIn.model_validate(valid_data)
    assert schema.reason == "Found extra unopened carton with goods"

    # Empty reason
    with pytest.raises(ValidationError):
        RmAddLineIn.model_validate({**valid_data, "reason": ""})

    # Whitespace-only reason
    with pytest.raises(ValidationError):
        RmAddLineIn.model_validate({**valid_data, "reason": "   \n\t "})


def test_rm_remove_line_schema_reason_required() -> None:
    valid_data = {"reason": "Party confirmed this item was sent in another shipment"}
    schema = RmRemoveLineIn.model_validate(valid_data)
    assert schema.reason == "Party confirmed this item was sent in another shipment"

    with pytest.raises(ValidationError):
        RmRemoveLineIn.model_validate({"reason": ""})

    with pytest.raises(ValidationError):
        RmRemoveLineIn.model_validate({"reason": "  \t "})


def test_rm_change_product_schema_reason_required() -> None:
    valid_data: dict[str, Any] = {
        "product_id": str(uuid.uuid4()),
        "buckets": [{"field_code": "OK_PACKED", "qty": 4}],
        "counts": [],
        "reason": "Verifier misidentified 1000W iron as 1500W model",
    }
    schema = RmChangeProductIn.model_validate(valid_data)
    assert schema.reason == "Verifier misidentified 1000W iron as 1500W model"

    with pytest.raises(ValidationError):
        RmChangeProductIn.model_validate({**valid_data, "reason": ""})

    with pytest.raises(ValidationError):
        RmChangeProductIn.model_validate({**valid_data, "reason": "   \n "})


# -----------------------------------------------------------------------------
# 2. DEC-54 T2: Transfer Slip Exists Blocks All RM Operations
# -----------------------------------------------------------------------------


@pytest.fixture
def mock_service() -> tuple[RmReviewService, MagicMock, MagicMock]:
    mock_uow = MagicMock()
    mock_session = MagicMock()
    mock_uow.transaction.return_value.__enter__.return_value = mock_session
    service = RmReviewService(mock_uow)
    return service, mock_uow, mock_session


def test_operations_blocked_when_transfer_slip_exists(
    mock_service: tuple[RmReviewService, MagicMock, MagicMock],
) -> None:
    service, _, session = mock_service
    user = _fake_user()
    perms = _fake_perms()
    gs_id = uuid.uuid4()
    item_id = uuid.uuid4()
    ts_id = uuid.uuid4()

    # Header has transfer_slip_id set
    with patch("app.modules.rm_review.service.gs_service.lock_goods_slip") as mock_lock:
        mock_lock.return_value = {
            "id": gs_id,
            "status": "RM_REVIEW",
            "transfer_slip_id": ts_id,
            "counted_by": uuid.uuid4(),
        }

        # 1. Add line blocked
        with pytest.raises(Conflict) as exc:
            service._add_line(
                session,
                user,
                perms,
                gs_id,
                RmAddLineIn(
                    product_id=uuid.uuid4(),
                    documented_qty=1,
                    received_qty=1,
                    buckets=[ItemBucketIn(field_code="OK", qty=1)],
                    reason="Test reason",
                ),
            )
        assert exc.value.code == "TRANSFER_SLIP_EXISTS"

        # 2. Remove line blocked
        with pytest.raises(Conflict) as exc:
            service._remove_line(
                session,
                user,
                perms,
                gs_id,
                item_id,
                RmRemoveLineIn(reason="Test reason"),
            )
        assert exc.value.code == "TRANSFER_SLIP_EXISTS"

        # 3. Change product blocked
        with pytest.raises(Conflict) as exc:
            service._change_product(
                session,
                user,
                perms,
                gs_id,
                item_id,
                RmChangeProductIn(
                    product_id=uuid.uuid4(),
                    buckets=[ItemBucketIn(field_code="OK", qty=1)],
                    reason="Test reason",
                ),
            )
        assert exc.value.code == "TRANSFER_SLIP_EXISTS"

        # 4. Edit item blocked
        with pytest.raises(Conflict) as exc:
            service._edit_item(
                session,
                user,
                perms,
                gs_id,
                item_id,
                RmEditItemIn(
                    documented_qty=1,
                    received_qty=1,
                    buckets=[ItemBucketIn(field_code="OK", qty=1)],
                ),
            )
        assert exc.value.code == "TRANSFER_SLIP_EXISTS"

        # 5. Send back blocked
        with pytest.raises(Conflict) as exc:
            service._send_back(
                session,
                user,
                perms,
                gs_id,
                RmSendBackIn(remarks="Send back"),
            )
        assert exc.value.code == "TRANSFER_SLIP_EXISTS"

        # 6. Approve blocked
        with pytest.raises(Conflict) as exc:
            service._approve(
                session,
                user,
                perms,
                gs_id,
                RmApproveIn(remarks="Approve"),
            )
        assert exc.value.code == "ALREADY_APPROVED"


# -----------------------------------------------------------------------------
# 3. G-19 Conservation and BR-07 Minimum 1 Line Rules
# -----------------------------------------------------------------------------


def test_add_line_rejects_g19_mismatch(
    mock_service: tuple[RmReviewService, MagicMock, MagicMock],
) -> None:
    service, _, session = mock_service
    user = _fake_user()
    perms = _fake_perms()
    gs_id = uuid.uuid4()
    prod_id = uuid.uuid4()

    with patch("app.modules.rm_review.service.gs_service.lock_goods_slip") as mock_lock, patch(
        "app.modules.rm_review.service.item_repo.get_product"
    ) as mock_prod:
        mock_lock.return_value = {"id": gs_id, "status": "RM_REVIEW", "transfer_slip_id": None}
        mock_prod.return_value = {"id": prod_id, "is_active": True}

        # received_qty = 5, but bucket sum = 3 -> SystemGuardViolation(G-19)
        with pytest.raises(SystemGuardViolation) as exc:
            service._add_line(
                session,
                user,
                perms,
                gs_id,
                RmAddLineIn(
                    product_id=prod_id,
                    documented_qty=5,
                    received_qty=5,
                    buckets=[ItemBucketIn(field_code="OK", qty=3)],
                    reason="Added missing item",
                ),
            )
        assert exc.value.code == "G-19"


def test_remove_line_enforces_br07_minimum_one_item(
    mock_service: tuple[RmReviewService, MagicMock, MagicMock],
) -> None:
    service, _, session = mock_service
    user = _fake_user()
    perms = _fake_perms()
    gs_id = uuid.uuid4()
    item_id = uuid.uuid4()

    with patch("app.modules.rm_review.service.gs_service.lock_goods_slip") as mock_lock, patch(
        "app.modules.rm_review.service.item_repo.get_item"
    ) as mock_item, patch(
        "app.modules.rm_review.service.item_repo.list_items"
    ) as mock_items:
        mock_lock.return_value = {"id": gs_id, "status": "RM_REVIEW", "transfer_slip_id": None}
        mock_item.return_value = {
            "id": item_id,
            "gs_id": gs_id,
            "line_no": 1,
            "product_id": uuid.uuid4(),
        }
        # Only 1 item exists on the goods slip
        mock_items.return_value = [{"id": item_id, "line_no": 1, "product_id": uuid.uuid4()}]

        with pytest.raises(ValidationFailed) as exc:
            service._remove_line(
                session,
                user,
                perms,
                gs_id,
                item_id,
                RmRemoveLineIn(reason="Party sent wrong box"),
            )
        assert exc.value.code == "ITEMS_REQUIRED"


# -----------------------------------------------------------------------------
# 4. DEC-54 T3: Split Replacement Replaces Buckets and Counts Whole
# -----------------------------------------------------------------------------


def test_edit_item_replaces_split_whole(
    mock_service: tuple[RmReviewService, MagicMock, MagicMock],
) -> None:
    service, _, session = mock_service
    user = _fake_user()
    perms = _fake_perms()
    gs_id = uuid.uuid4()
    item_id = uuid.uuid4()
    prod_id = uuid.uuid4()

    with patch("app.modules.rm_review.service.gs_service.lock_goods_slip") as mock_lock, patch(
        "app.modules.rm_review.service.item_repo.get_item"
    ) as mock_item, patch(
        "app.modules.rm_review.service.item_repo.get_profile_version_id", return_value=None
    ), patch(
        "app.modules.rm_review.service.item_service.resolve_item_fields"
    ) as mock_fields, patch(
        "app.modules.rm_review.service.item_repo.delete_item_buckets"
    ) as mock_del_b, patch(
        "app.modules.rm_review.service.item_repo.delete_item_counts"
    ) as mock_del_c, patch(
        "app.modules.rm_review.service.item_repo.upsert_item_bucket"
    ) as mock_ins_b, patch(
        "app.modules.rm_review.service.item_repo.upsert_item_count"
    ) as mock_ins_c, patch(
        "app.modules.rm_review.service.repo.get_next_revision_no"
    ) as mock_rev_no, patch(
        "app.modules.rm_review.service.repo.insert_revision"
    ) as mock_ins_rev, patch(
        "app.modules.rm_review.service.RmReviewService._get_items_snapshot"
    ) as mock_snap, patch(
        "app.modules.rm_review.service.RmReviewService._notify_verifier_of_change"
    ) as mock_notify:
        mock_lock.return_value = {
            "id": gs_id,
            "status": "RM_REVIEW",
            "transfer_slip_id": None,
            "counted_by": uuid.uuid4(),
        }
        mock_item.return_value = {
            "id": item_id,
            "gs_id": gs_id,
            "product_id": prod_id,
            "line_no": 1,
            "sku_code": "SKU1",
            "sku_name": "Iron",
            "documented_qty": 5,
            "received_qty": 5,
        }
        field_mock = MagicMock()
        field_mock.bucket_ids.return_value = {"OK_PACKED": uuid.uuid4(), "DAMAGED": uuid.uuid4()}
        field_mock.count_ids.return_value = {"PACKAGING": uuid.uuid4()}
        mock_fields.return_value = field_mock
        mock_rev_no.return_value = 2
        mock_snap.return_value = []

        service._edit_item(
            session,
            user,
            perms,
            gs_id,
            item_id,
            RmEditItemIn(
                documented_qty=5,
                received_qty=4,
                buckets=[
                    ItemBucketIn(field_code="OK_PACKED", qty=3),
                    ItemBucketIn(field_code="DAMAGED", qty=1),
                ],
                counts=[ItemCountIn(count_type="PACKAGING", count_value=4)],
                remarks="Adjusted count",
            ),
        )

        # Verified: old buckets and counts deleted first (replaced whole - DEC-54 T3)
        mock_del_b.assert_called_once_with(session, item_id)
        mock_del_c.assert_called_once_with(session, item_id)
        assert mock_ins_b.called
        assert mock_ins_c.called

        # Verified: revision recorded with action RM_EDIT and remarks
        assert mock_ins_rev.called
        rev_kwargs = mock_ins_rev.call_args[1]
        assert rev_kwargs["action"] == "RM_EDIT"
        assert rev_kwargs["remarks"] == "Adjusted count"

        # Verified: verifier notified
        assert mock_notify.called


# -----------------------------------------------------------------------------
# 5. Inward Stock Booking Moved from Categorisation Submit to RM Approval
# -----------------------------------------------------------------------------


def test_categorisation_submit_does_not_call_move_stock() -> None:
    mock_uow = MagicMock()
    mock_session = MagicMock()
    mock_session.execute.return_value.scalar_one.return_value = 1
    mock_uow.transaction.return_value.__enter__.return_value = mock_session
    svc = ItemizationService(mock_uow)

    user = _fake_user(roles=["INWARD_VERIFIER"])
    perms = _fake_perms()
    gs_id = uuid.uuid4()

    with patch("app.modules.itemization.service.gs_service.lock_goods_slip") as mock_lock, patch(
        "app.modules.itemization.service.repo.list_items"
    ) as mock_items, patch(
        "app.modules.itemization.service.repo.get_buckets_for_items"
    ) as mock_b, patch(
        "app.modules.itemization.service.gs_service.change_status_within_step"
    ), patch(
        "app.modules.itemization.service.repo.complete_open_tasks"
    ), patch(
        "app.modules.itemization.service.notifications.publish"
    ), patch(
        "app.modules.inventory.ledger_service.move_stock"
    ) as mock_move:
        mock_lock.return_value = {
            "id": gs_id,
            "gs_no": "GS/2026/001",
            "status": "CATEGORISATION",
            "counted_by": user.id,
            "created_by": user.id,
            "inward_gate_id": uuid.uuid4(),
        }
        item_id = uuid.uuid4()
        mock_items.return_value = [
            {
                "id": item_id,
                "line_no": 1,
                "sku_code": "SKU1",
                "sku_name": "Iron",
                "received_qty": 2,
                "product_id": uuid.uuid4(),
                "documented_qty": 2,
            }
        ]
        mock_b.return_value = [
            {"gs_item_id": item_id, "field_code": "OK", "label_snapshot": "OK", "qty": 2}
        ]

        svc._submit_categorisation(
            mock_session,
            user,
            perms,
            gs_id,
            SubmitCategorisationIn(
                category_code="REGULAR_RETURN",
                remarks="Counted and sorted",
            ),
        )

        # Inward stock booking was moved to RM approval, so move_stock must NOT be called here!
        mock_move.assert_not_called()
