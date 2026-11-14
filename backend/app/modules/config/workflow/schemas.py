"""Pydantic schemas for workflow configuration, versioning, and validation (prompt P1-08)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class StepAssignmentIn(BaseModel):
    role_id: UUID | None = None
    role_code: str | None = None
    user_id: UUID | None = None
    assignment_type: str = Field(..., pattern="^(PERFORM|APPROVE|VIEW)$")


class StepAssignmentOut(BaseModel):
    id: UUID | None = None
    role_id: UUID | None = None
    role_code: str | None = None
    user_id: UUID | None = None
    assignment_type: str


class WorkflowStageIn(BaseModel):
    id: UUID | None = None
    code: str = Field(..., pattern="^[A-Z][A-Z0-9_]*$")
    label: str = Field(..., min_length=1)
    sort_order: int = 0


class WorkflowStageOut(BaseModel):
    id: UUID
    workflow_version_id: UUID
    code: str
    label: str
    sort_order: int
    created_at: datetime
    updated_at: datetime


class WorkflowStepIn(BaseModel):
    id: UUID | None = None
    stage_id: UUID
    code: str = Field(
        ...,
        pattern="^(S1_GATE|S1_UNBOX|S1_ITEMIZE|S1_CSR_APPROVAL|S1_INSPECT|S1A_RM_ACTION|S2_HANDOVER|S3_TECHNICAL|S4_DISMANTLE|S5_SEGREGATE|S6_STORE_ISSUE|S6_CN_DECISION|S6_ACCOUNTS_CN|S6_NOTIFY|S6_CLOSE)$",
    )
    label: str = Field(..., min_length=1)
    form_definition_id: UUID | None = None
    sla_hours: float | None = None
    requires_approval: bool = False
    sort_order: int = 0
    is_active: bool = True
    assignments: list[StepAssignmentIn] = Field(default_factory=list)


class WorkflowStepOut(BaseModel):
    id: UUID
    workflow_version_id: UUID
    stage_id: UUID
    stage_code: str | None = None
    code: str
    label: str
    form_definition_id: UUID | None = None
    form_code: str | None = None
    sla_hours: float | None = None
    requires_approval: bool = False
    sort_order: int = 0
    is_active: bool = True
    assignments: list[StepAssignmentOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class WorkflowTransitionIn(BaseModel):
    id: UUID | None = None
    from_step_id: UUID
    to_step_id: UUID
    condition: dict[str, Any] | None = None
    system_guards: list[str] = Field(default_factory=list)
    priority: int = 0


class WorkflowTransitionOut(BaseModel):
    id: UUID
    workflow_version_id: UUID
    from_step_id: UUID
    from_step_code: str | None = None
    to_step_id: UUID
    to_step_code: str | None = None
    condition: dict[str, Any] | None = None
    system_guards: list[str] = Field(default_factory=list)
    priority: int = 0
    created_at: datetime
    updated_at: datetime


class WorkflowDraftUpdate(BaseModel):
    stages: list[WorkflowStageIn] | None = None
    steps: list[WorkflowStepIn] | None = None
    transitions: list[WorkflowTransitionIn] | None = None


class WorkflowPublishRequest(BaseModel):
    reason: str = Field(
        ..., min_length=3, description="Mandatory reason for publishing workflow version"
    )


class WorkflowValidateOut(BaseModel):
    is_valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class WorkflowVersionOut(BaseModel):
    id: UUID
    workflow_definition_id: UUID
    version_no: int
    status: str
    published_by: UUID | None = None
    published_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class WorkflowVersionDetailOut(WorkflowVersionOut):
    snapshot: dict[str, Any] | None = None
    stages: list[WorkflowStageOut] = Field(default_factory=list)
    steps: list[WorkflowStepOut] = Field(default_factory=list)
    transitions: list[WorkflowTransitionOut] = Field(default_factory=list)


class WorkflowDefinitionOut(BaseModel):
    id: UUID
    code: str
    name: str
    is_active: bool
    latest_published_version: int | None = None
    has_draft: bool = False
    draft_version_no: int | None = None
    created_at: datetime
    updated_at: datetime


class WorkflowDiffOut(BaseModel):
    v1: int
    v2: int
    stages_diff: dict[str, Any]
    steps_diff: dict[str, Any]
    transitions_diff: dict[str, Any]
