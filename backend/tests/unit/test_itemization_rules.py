"""Pure rules of Step-3 itemisation / CSR approval (prompt P2-04; G-03, BR-07, BR-08, DEC-09)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.core.errors import Conflict, SystemGuardUnmet
from app.modules.goods_slips.service import assert_csr_decided
from app.modules.itemization.service import form_field_options, is_short, route_step
from app.shared.guards import g03_violation, guard_g03
from app.shared.workflow_engine import (
    InMemoryWorkflowEntity,
    SystemGuardViolation,
    TransitionNotAllowed,
    WorkflowEngine,
    WorkflowUser,
)

# The routing part of the seeded RMS_STANDARD v1 workflow (supabase/seed.sql).
WF: dict[str, Any] = {
    "steps": [
        {
            "code": "S1_ITEMIZE",
            "requires_approval": False,
            "assignments": [{"role_code": "INWARD_VERIFIER", "assignment_type": "PERFORM"}],
        },
        {
            "code": "S1_CSR_APPROVAL",
            "requires_approval": True,
            "assignments": [{"role_code": "REPLACEMENT_MANAGER", "assignment_type": "APPROVE"}],
        },
        {
            "code": "S1_INSPECT",
            "requires_approval": False,
            "assignments": [{"role_code": "INWARD_VERIFIER", "assignment_type": "PERFORM"}],
        },
        {
            "code": "S2_HANDOVER",
            "requires_approval": False,
            "assignments": [{"role_code": "INWARD_VERIFIER", "assignment_type": "PERFORM"}],
        },
    ],
    "transitions": [
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
        {
            "from_step_code": "S1_CSR_APPROVAL",
            "to_step_code": "S1_INSPECT",
            "condition": {"field": "csr_decision", "op": "eq", "value": "CSR_REJECTED_TO_RO"},
            "system_guards": [],
            "priority": 10,
        },
        {
            "from_step_code": "S1_CSR_APPROVAL",
            "to_step_code": "S2_HANDOVER",
            "condition": {"field": "csr_decision", "op": "eq", "value": "CSR_APPROVED"},
            "system_guards": ["G-03"],
            "priority": 20,
        },
    ],
}

AMAN = WorkflowUser(roles=["INWARD_VERIFIER"])
PRATHAM = WorkflowUser(roles=["REPLACEMENT_MANAGER"])


@pytest.mark.parametrize(
    ("ctx", "expected"),
    [
        ({"category_code": "RO", "original_category_code": "RO"}, None),
        ({"category_code": "CSR", "original_category_code": "CSR"}, "CSR_DECISION_MISSING"),
        (
            {"category_code": "CSR", "csr_decision": "CSR_APPROVED"},
            "CSR_DECISION_UNAUTHORIZED",
        ),
        (
            {
                "category_code": "CSR",
                "csr_decision": "CSR_APPROVED",
                "csr_decision_authorized": True,
            },
            None,
        ),
        (
            {
                "category_code": "RO",
                "original_category_code": "CSR",
                "csr_decision": "CSR_REJECTED_TO_RO",
                "csr_decision_authorized": True,
            },
            None,
        ),
        (
            {
                "category_code": "CSR",
                "csr_decision": "CSR_REJECTED_TO_RO",
                "csr_decision_authorized": True,
            },
            "CSR_DECISION_MISMATCH",
        ),
        ({"category_code": "RO", "original_category_code": "CSR"}, "CSR_DECISION_MISSING"),
    ],
)
def test_g03_violation(ctx: dict[str, Any], expected: str | None) -> None:
    assert g03_violation(ctx) == expected


def test_g03_engine_guard_cannot_be_bypassed_by_super_admin() -> None:
    engine = WorkflowEngine(WF)
    entity = InMemoryWorkflowEntity(
        current_step_code="S1_CSR_APPROVAL",
        status="CSR_APPROVAL_PENDING",
        context={"category_code": "CSR", "csr_decision": "CSR_APPROVED"},
    )
    admin = WorkflowUser(is_super_admin=True)
    with pytest.raises(SystemGuardViolation) as err:
        engine.assert_can_transition(entity, "S2_HANDOVER", admin)
    assert err.value.code == "G-03"
    entity.context["csr_decision_authorized"] = True
    assert guard_g03(entity, admin) is True
    engine.assert_can_transition(entity, "S2_HANDOVER", admin)


def test_actor_step_authorisation() -> None:
    """Aman routes a CSR into the RM's approval step; the RM routes it on to inspection."""
    engine = WorkflowEngine(WF)
    itemize = InMemoryWorkflowEntity(
        current_step_code="S1_ITEMIZE", context={"category_code": "CSR"}
    )
    # Default rule (target-step assignment) would wrongly require Aman to be an approver.
    with pytest.raises(TransitionNotAllowed):
        engine.assert_can_transition(itemize, "S1_CSR_APPROVAL", AMAN)
    engine.assert_can_transition(itemize, "S1_CSR_APPROVAL", AMAN, actor_step_code="S1_ITEMIZE")
    with pytest.raises(TransitionNotAllowed):
        engine.assert_can_transition(
            itemize, "S1_CSR_APPROVAL", PRATHAM, actor_step_code="S1_ITEMIZE"
        )

    decided = InMemoryWorkflowEntity(
        current_step_code="S1_CSR_APPROVAL", context={"csr_decision": "CSR_REJECTED_TO_RO"}
    )
    engine.assert_can_transition(
        decided,
        "S1_INSPECT",
        PRATHAM,
        actor_step_code="S1_CSR_APPROVAL",
        actor_assignment_type="APPROVE",
    )
    with pytest.raises(TransitionNotAllowed):
        engine.assert_can_transition(
            decided,
            "S1_INSPECT",
            AMAN,
            actor_step_code="S1_CSR_APPROVAL",
            actor_assignment_type="APPROVE",
        )


def test_route_step_follows_workflow_conditions() -> None:
    assert route_step(WF, "S1_ITEMIZE", {"category_code": "CSR"}) == "S1_CSR_APPROVAL"
    assert route_step(WF, "S1_ITEMIZE", {"category_code": "RO"}) == "S1_INSPECT"
    assert route_step(WF, "S1_CSR_APPROVAL", {"csr_decision": "CSR_APPROVED"}) == "S2_HANDOVER"
    assert route_step(WF, "S1_CSR_APPROVAL", {"csr_decision": "CSR_REJECTED_TO_RO"}) == "S1_INSPECT"
    with pytest.raises(Conflict):
        route_step(WF, "S1_ITEMIZE", {"category_code": "MIXED"})


def test_dec09_short_flag() -> None:
    dmt, prs = uuid.uuid4(), uuid.uuid4()
    short_dmt = {"short_qty": 2, "category_id": dmt}
    short_prs = {"short_qty": 2, "category_id": prs}
    assert is_short(short_prs, all_categories=True, short_categories=set())
    assert is_short(short_dmt, all_categories=False, short_categories={dmt})
    assert not is_short(short_prs, all_categories=False, short_categories={dmt})
    assert not is_short(
        {"short_qty": 0, "category_id": dmt}, all_categories=True, short_categories=set()
    )


def test_form_field_options_skip_inactive() -> None:
    snapshot = {
        "fields": [
            {
                "field_key": "return_category",
                "option_items": [
                    {
                        "code": "CSR",
                        "label": "Complete Sales Return",
                        "allowed_status": "CONDITIONAL",
                    },
                    {"code": "RO", "label": "Replacement Only", "is_active": False},
                ],
            }
        ]
    }
    opts = form_field_options(snapshot, "return_category")
    assert [(o.code, o.allowed_status) for o in opts] == [("CSR", "CONDITIONAL")]
    assert form_field_options(snapshot, "missing") == []


def test_assert_csr_decided_raises_422_g03() -> None:
    gs = {"category_code": "CSR", "original_category_code": "CSR", "status": "CSR_APPROVAL_PENDING"}
    with pytest.raises(SystemGuardUnmet) as err:
        assert_csr_decided(gs, None)
    assert err.value.code == "G-03" and err.value.status_code == 422
    assert_csr_decided(gs, {"decision_code": "CSR_APPROVED"})
    assert_csr_decided({"category_code": "RO", "original_category_code": "RO"}, None)
