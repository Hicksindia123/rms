"""Integration tests for goods slip lifecycle and transitions (prompt P2-01).

Guarantees workflow version pinning, gs_status_history logging,
and workflow_tasks open/complete lifecycle during status transitions.
"""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from app.modules.goods_slips import repository as repo
from app.modules.goods_slips import service as gs_service
from app.shared.workflow_engine import TransitionNotAllowed, WorkflowUser


def test_goods_slip_creation_and_transition_lifecycle(
    session_factory: sessionmaker[Session],
) -> None:
    """Test full goods slip creation, version pinning, history recording, and task management."""
    with session_factory() as s:
        from sqlalchemy import text

        profile_id = s.execute(text("select id from public.profiles limit 1")).scalar_one()

        # Create acting users
        gate_user = WorkflowUser(id=profile_id, roles=["GATE_INWARD"])
        verifier_user = WorkflowUser(id=profile_id, roles=["INWARD_VERIFIER"])

        # 1. Create goods slip
        gs = gs_service.create_goods_slip(
            s,
            delivery_mode_code="COURIER_PARCEL",
            courier_name="BlueDart Express",
            docket_no="BD-998877",
            box_count=2,
            user=gate_user,
        )

        gs_id = gs["id"]
        assert gs["status"] == "GATE_CREATED"
        assert gs["workflow_version_id"] is not None

        # Verify initial status history
        hist = repo.get_status_history_for_gs(s, gs_id)
        assert len(hist) == 1
        assert hist[0]["from_status"] is None
        assert hist[0]["to_status"] == "GATE_CREATED"
        assert hist[0]["step_code"] == "S1_GATE"

        # Verify initial open task for S1_GATE
        tasks = repo.get_open_tasks_for_gs(s, gs_id)
        assert len(tasks) == 1
        assert tasks[0]["step_code"] == "S1_GATE"
        assert tasks[0]["status"] == "OPEN"

        # 2. Transition from S1_GATE -> S1_UNBOX
        updated_gs = gs_service.transition_gs(
            s,
            gs_id=gs_id,
            to_status="UNBOXING",
            step_code="S1_UNBOX",
            user=verifier_user,
            reason="Boxes moved to unboxing station",
        )

        assert updated_gs["status"] == "UNBOXING"

        # Verify status history updated
        hist2 = repo.get_status_history_for_gs(s, gs_id)
        assert len(hist2) == 2
        assert hist2[1]["from_status"] == "GATE_CREATED"
        assert hist2[1]["to_status"] == "UNBOXING"
        assert hist2[1]["step_code"] == "S1_UNBOX"
        assert hist2[1]["reason"] == "Boxes moved to unboxing station"

        # Verify previous task is marked DONE and new task is OPEN
        open_tasks = repo.get_open_tasks_for_gs(s, gs_id)
        assert len(open_tasks) == 1
        assert open_tasks[0]["step_code"] == "S1_UNBOX"
        assert open_tasks[0]["status"] == "OPEN"

        # Check total tasks in db for this GS (1 DONE, 1 OPEN)
        from sqlalchemy import text

        all_tasks = (
            s.execute(
                text(
                    "select id, step_code, status from public.workflow_tasks "
                    "where gs_id = :id order by created_at"
                ),
                {"id": gs_id},
            )
            .mappings()
            .all()
        )
        assert len(all_tasks) == 2
        assert all_tasks[0]["step_code"] == "S1_GATE"
        assert all_tasks[0]["status"] == "DONE"
        assert all_tasks[1]["step_code"] == "S1_UNBOX"
        assert all_tasks[1]["status"] == "OPEN"


def test_transition_unauthorized_user_rejected(
    session_factory: sessionmaker[Session],
) -> None:
    """Acting user lacking required role on target step is rejected."""
    with session_factory() as s:
        from sqlalchemy import text

        profile_id = s.execute(text("select id from public.profiles limit 1")).scalar_one()

        gate_user = WorkflowUser(id=profile_id, roles=["GATE_INWARD"])
        unauthorized_user = WorkflowUser(id=profile_id, roles=["ACCOUNTANT"])

        gs = gs_service.create_goods_slip(
            s,
            delivery_mode_code="COURIER_PARCEL",
            courier_name="BlueDart",
            docket_no="BD-112233",
            box_count=1,
            user=gate_user,
        )

        # ACCOUNTANT attempting to perform S1_UNBOX should raise TransitionNotAllowed
        import pytest

        with pytest.raises(TransitionNotAllowed):
            gs_service.transition_gs(
                s,
                gs_id=gs["id"],
                to_status="UNBOXING",
                step_code="S1_UNBOX",
                user=unauthorized_user,
            )
