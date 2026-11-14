"""Unit tests for workflow engine core (master plan §2, §4.2, §6.5, prompt P1-08)."""

import pytest

from app.shared.workflow_engine import (
    InMemoryWorkflowEntity,
    SystemGuardViolation,
    TransitionError,
    TransitionNotAllowed,
    WorkflowEngine,
    WorkflowUser,
    register_guard,
)

SAMPLE_WORKFLOW_SNAPSHOT = {
    "workflow_code": "RMS_STANDARD",
    "name": "RMS Standard Return Workflow",
    "version_no": 1,
    "stages": [
        {"code": "STAGE_1", "label": "Stage 1", "sort_order": 1},
        {"code": "STAGE_2", "label": "Stage 2", "sort_order": 2},
    ],
    "steps": [
        {
            "code": "S1_GATE",
            "label": "Step-1 GS creation",
            "requires_approval": False,
            "assignments": [{"role_code": "GATE_INWARD", "assignment_type": "PERFORM"}],
        },
        {
            "code": "S1_UNBOX",
            "label": "Step-2 Unboxing",
            "requires_approval": False,
            "assignments": [{"role_code": "INWARD_VERIFIER", "assignment_type": "PERFORM"}],
        },
        {
            "code": "S1_ITEMIZE",
            "label": "Step-3 Itemisation & categorisation",
            "requires_approval": False,
            "assignments": [{"role_code": "INWARD_VERIFIER", "assignment_type": "PERFORM"}],
        },
        {
            "code": "S1_CSR_APPROVAL",
            "label": "Step-3 CSR Approval",
            "requires_approval": True,
            "assignments": [{"role_code": "REPLACEMENT_MANAGER", "assignment_type": "APPROVE"}],
        },
        {
            "code": "S1_INSPECT",
            "label": "Step-3 Inspection",
            "requires_approval": False,
            "assignments": [{"role_code": "INWARD_VERIFIER", "assignment_type": "PERFORM"}],
        },
    ],
    "transitions": [
        {
            "from_step_code": "S1_GATE",
            "to_step_code": "S1_UNBOX",
            "condition": None,
            "system_guards": ["G-01"],
            "priority": 10,
        },
        {
            "from_step_code": "S1_UNBOX",
            "to_step_code": "S1_ITEMIZE",
            "condition": None,
            "system_guards": [],
            "priority": 10,
        },
        {
            "from_step_code": "S1_ITEMIZE",
            "to_step_code": "S1_CSR_APPROVAL",
            "condition": {"field": "category_code", "op": "eq", "value": "CSR"},
            "system_guards": [],
            "priority": 20,
        },
        {
            "from_step_code": "S1_ITEMIZE",
            "to_step_code": "S1_INSPECT",
            "condition": {"field": "category_code", "op": "eq", "value": "RO"},
            "system_guards": [],
            "priority": 10,
        },
    ],
}


def test_transition_unimplemented_guard_raises_not_implemented() -> None:
    """Unimplemented system guards must raise NotImplementedError in tests (G-xx requirement)."""
    engine = WorkflowEngine(SAMPLE_WORKFLOW_SNAPSHOT, guard_registry={})
    entity = InMemoryWorkflowEntity(current_step_code="S1_GATE")
    user = WorkflowUser(roles=["INWARD_VERIFIER"])

    with pytest.raises(NotImplementedError) as exc_info:
        engine.assert_can_transition(entity, "S1_UNBOX", user)
    assert "System guard 'G-01' is not implemented" in str(exc_info.value)


def test_transition_with_satisfied_guard_and_permissions() -> None:
    """When a guard is implemented and passes, transition is permitted."""
    fake_guards = {"G-01": lambda ent, usr: True}
    engine = WorkflowEngine(SAMPLE_WORKFLOW_SNAPSHOT, guard_registry=fake_guards)
    entity = InMemoryWorkflowEntity(current_step_code="S1_GATE")
    user = WorkflowUser(roles=["INWARD_VERIFIER"])

    tr = engine.assert_can_transition(entity, "S1_UNBOX", user)
    assert tr["to_step_code"] == "S1_UNBOX"


def test_transition_fails_on_guard_violation() -> None:
    """When a guard is implemented and fails, SystemGuardViolation is raised."""
    fake_guards = {"G-01": lambda ent, usr: False}
    engine = WorkflowEngine(SAMPLE_WORKFLOW_SNAPSHOT, guard_registry=fake_guards)
    entity = InMemoryWorkflowEntity(current_step_code="S1_GATE")
    user = WorkflowUser(roles=["INWARD_VERIFIER"])

    with pytest.raises(SystemGuardViolation):
        engine.assert_can_transition(entity, "S1_UNBOX", user)


def test_transition_unauthorized_role_rejected() -> None:
    """User without matching step assignment role is rejected with TransitionNotAllowed."""
    fake_guards = {"G-01": lambda ent, usr: True}
    engine = WorkflowEngine(SAMPLE_WORKFLOW_SNAPSHOT, guard_registry=fake_guards)
    entity = InMemoryWorkflowEntity(current_step_code="S1_GATE")
    # User only has GATE_INWARD, but S1_UNBOX requires INWARD_VERIFIER
    user = WorkflowUser(roles=["GATE_INWARD"])

    with pytest.raises(TransitionNotAllowed):
        engine.assert_can_transition(entity, "S1_UNBOX", user)


def test_super_admin_bypasses_role_assignment() -> None:
    """Super Admin bypasses step role assignments, but still evaluates conditions and guards."""
    fake_guards = {"G-01": lambda ent, usr: True}
    engine = WorkflowEngine(SAMPLE_WORKFLOW_SNAPSHOT, guard_registry=fake_guards)
    entity = InMemoryWorkflowEntity(current_step_code="S1_GATE")
    user = WorkflowUser(roles=[], is_super_admin=True)

    tr = engine.assert_can_transition(entity, "S1_UNBOX", user)
    assert tr["to_step_code"] == "S1_UNBOX"


def test_conditional_transitions_evaluation() -> None:
    """Transitions with condition rules evaluate against entity.context."""
    engine = WorkflowEngine(SAMPLE_WORKFLOW_SNAPSHOT, guard_registry={})
    user = WorkflowUser(roles=["REPLACEMENT_MANAGER", "INWARD_VERIFIER"])

    # Context category_code = CSR
    entity_csr = InMemoryWorkflowEntity(
        current_step_code="S1_ITEMIZE",
        context={"category_code": "CSR"},
    )
    tr_csr = engine.assert_can_transition(entity_csr, "S1_CSR_APPROVAL", user)
    assert tr_csr["to_step_code"] == "S1_CSR_APPROVAL"

    # Context category_code = RO
    entity_ro = InMemoryWorkflowEntity(
        current_step_code="S1_ITEMIZE",
        context={"category_code": "RO"},
    )
    tr_ro = engine.assert_can_transition(entity_ro, "S1_INSPECT", user)
    assert tr_ro["to_step_code"] == "S1_INSPECT"

    # Trying S1_CSR_APPROVAL on RO entity fails condition
    with pytest.raises(TransitionError):
        engine.assert_can_transition(entity_ro, "S1_CSR_APPROVAL", user)


def test_available_transitions_filtering() -> None:
    """available_transitions returns only transitions matching conditions and user roles."""
    engine = WorkflowEngine(SAMPLE_WORKFLOW_SNAPSHOT, guard_registry={})

    # Inward verifier on S1_ITEMIZE with RO category
    user_inward = WorkflowUser(roles=["INWARD_VERIFIER"])
    entity_ro = InMemoryWorkflowEntity(
        current_step_code="S1_ITEMIZE",
        context={"category_code": "RO"},
    )
    avail = engine.available_transitions(entity_ro, user_inward)
    assert len(avail) == 1
    assert avail[0]["to_step_code"] == "S1_INSPECT"

    # Replacement Manager on S1_ITEMIZE with CSR category
    user_rm = WorkflowUser(roles=["REPLACEMENT_MANAGER"])
    entity_csr = InMemoryWorkflowEntity(
        current_step_code="S1_ITEMIZE",
        context={"category_code": "CSR"},
    )
    avail_rm = engine.available_transitions(entity_csr, user_rm)
    assert len(avail_rm) == 1
    assert avail_rm[0]["to_step_code"] == "S1_CSR_APPROVAL"


def test_version_pinning_immutability() -> None:
    """Verify that an entity pinned to v1 snapshot is unaffected by v2 snapshot modifications."""
    v1_snapshot = {
        "version_no": 1,
        "steps": [
            {
                "code": "S1_GATE",
                "assignments": [{"role_code": "GATE_INWARD", "assignment_type": "PERFORM"}],
            },
            {
                "code": "S1_UNBOX",
                "assignments": [{"role_code": "INWARD_VERIFIER", "assignment_type": "PERFORM"}],
            },
        ],
        "transitions": [
            {"from_step_code": "S1_GATE", "to_step_code": "S1_UNBOX", "system_guards": []},
        ],
    }

    v2_snapshot = {
        "version_no": 2,
        "steps": [
            {
                "code": "S1_GATE",
                "assignments": [{"role_code": "SUPER_ADMIN", "assignment_type": "PERFORM"}],
            },
            {
                "code": "S1_UNBOX",
                "assignments": [{"role_code": "STORE_MANAGER", "assignment_type": "PERFORM"}],
            },
        ],
        "transitions": [
            {"from_step_code": "S1_GATE", "to_step_code": "S1_UNBOX", "system_guards": []},
        ],
    }

    engine_v1 = WorkflowEngine(v1_snapshot)
    engine_v2 = WorkflowEngine(v2_snapshot)

    user_inward = WorkflowUser(roles=["INWARD_VERIFIER"])
    entity = InMemoryWorkflowEntity(current_step_code="S1_GATE")

    # Under v1, INWARD_VERIFIER is authorized for S1_UNBOX
    tr1 = engine_v1.assert_can_transition(entity, "S1_UNBOX", user_inward)
    assert tr1 is not None

    # Under v2, INWARD_VERIFIER is NOT authorized (requires STORE_MANAGER)
    with pytest.raises(TransitionNotAllowed):
        engine_v2.assert_can_transition(entity, "S1_UNBOX", user_inward)


def test_workflow_engine_additional_coverage() -> None:
    """Test guard registration, from_version, user assignment, and session record."""

    # 1. register_guard decorator
    @register_guard("G-TEST-CUSTOM")
    def custom_guard(entity, user):
        return True

    engine = WorkflowEngine.from_version(SAMPLE_WORKFLOW_SNAPSHOT)
    assert engine.guard_registry.get("G-TEST-CUSTOM") is not None

    # 2. is_user_assigned_to_step edge cases
    # Non-existent step
    sa_user = WorkflowUser(roles=["SUPER_ADMIN"], is_super_admin=True)
    tech_user = WorkflowUser(roles=["TECHNICIAN"])
    assert engine.is_user_assigned_to_step("NON_EXISTENT_STEP", sa_user) is True
    assert engine.is_user_assigned_to_step("NON_EXISTENT_STEP", tech_user) is False

    # Specific user ID match
    uid = "00000000-0000-0000-0000-000000000001"
    snap_user_assigned = {
        "steps": [
            {
                "code": "STEP_USER",
                "assignments": [{"user_id": uid, "assignment_type": "PERFORM"}],
            }
        ],
        "transitions": [],
    }
    eng_u = WorkflowEngine(snap_user_assigned)
    assert eng_u.is_user_assigned_to_step("STEP_USER", WorkflowUser(id=uid, roles=[])) is True
    assert (
        eng_u.is_user_assigned_to_step("STEP_USER", WorkflowUser(id="other-id", roles=[])) is False
    )

    # 3. record_transition with session mock
    class MockSession:
        def __init__(self) -> None:
            self.executed: list[tuple[str, dict]] = []

        def execute(self, statement, params=None):
            self.executed.append((str(statement), params or {}))

    mock_session = MockSession()
    ent = InMemoryWorkflowEntity(current_step_code="S1_GATE", status="GATE_REGISTERED")
    user = WorkflowUser(roles=["GATE_INWARD"])
    engine.record_transition(
        ent, "S1_UNBOX", user, reason="Testing session write", session=mock_session
    )
    assert ent.current_step_code == "S1_UNBOX"
    assert len(mock_session.executed) == 1  # status_history insert
