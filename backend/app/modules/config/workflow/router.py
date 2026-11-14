"""FastAPI router for workflow configuration and version management (prompt P1-08)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from app.core.db import UowDep
from app.core.permissions import require
from app.core.security import CurrentUser, get_current_user
from app.modules.config.workflow.schemas import (
    WorkflowDefinitionOut,
    WorkflowDiffOut,
    WorkflowPublishRequest,
    WorkflowTransitionIn,
    WorkflowValidateOut,
    WorkflowVersionDetailOut,
    WorkflowVersionOut,
)
from app.modules.config.workflow.service import WorkflowService

router = APIRouter(prefix="/config/workflow", tags=["config-workflow"])


def get_service(uow: UowDep) -> WorkflowService:
    return WorkflowService(uow)


ServiceDep = Annotated[WorkflowService, Depends(get_service)]


@router.get("", response_model=list[WorkflowDefinitionOut])
def list_workflows(
    user: Annotated[CurrentUser, Depends(require("config", "view"))],
    service: ServiceDep,
) -> list[WorkflowDefinitionOut]:
    return service.list_workflows(user)


@router.get("/{code}", response_model=WorkflowDefinitionOut)
def get_workflow(
    code: str,
    user: Annotated[CurrentUser, Depends(require("config", "view"))],
    service: ServiceDep,
) -> WorkflowDefinitionOut:
    return service.get_workflow(user, code)


@router.get(
    "/{code}/published",
    response_model=dict[str, Any],
    dependencies=[Depends(get_current_user)],  # any active user (production audit 2026-11-14)
)
def get_published_snapshot(
    code: str,
    service: ServiceDep,
) -> dict[str, Any]:
    """Returns the published snapshot used by operational transitions."""
    return service.get_published_snapshot(code)


@router.get("/{code}/versions/{version_no}", response_model=WorkflowVersionDetailOut)
def get_version(
    code: str,
    version_no: int,
    user: Annotated[CurrentUser, Depends(require("config", "view"))],
    service: ServiceDep,
) -> WorkflowVersionDetailOut:
    return service.get_version(user, code, version_no)


@router.post("/{code}/draft", response_model=WorkflowVersionDetailOut)
def create_draft(
    code: str,
    user: Annotated[CurrentUser, Depends(require("config", "configure"))],
    service: ServiceDep,
) -> WorkflowVersionDetailOut:
    return service.create_draft(user, code)


@router.put("/{code}/draft/step-label", response_model=WorkflowVersionDetailOut)
def update_step_label(
    code: str,
    step_code: str,
    new_label: str,
    user: Annotated[CurrentUser, Depends(require("config", "configure"))],
    service: ServiceDep,
) -> WorkflowVersionDetailOut:
    return service.update_draft_step_label(user, code, step_code, new_label)


@router.put("/{code}/draft/transitions", response_model=WorkflowVersionDetailOut)
def update_draft_transitions(
    code: str,
    transitions: list[WorkflowTransitionIn],
    user: Annotated[CurrentUser, Depends(require("config", "configure"))],
    service: ServiceDep,
) -> WorkflowVersionDetailOut:
    return service.update_draft_transitions(user, code, transitions)


@router.post("/{code}/draft/validate", response_model=WorkflowValidateOut)
def validate_draft(
    code: str,
    user: Annotated[CurrentUser, Depends(require("config", "configure"))],
    service: ServiceDep,
) -> WorkflowValidateOut:
    return service.validate_draft(user, code)


@router.post("/{code}/draft/publish", response_model=WorkflowVersionOut)
def publish_draft(
    code: str,
    payload: WorkflowPublishRequest,
    user: Annotated[CurrentUser, Depends(require("config", "configure"))],
    service: ServiceDep,
) -> WorkflowVersionOut:
    return service.publish_draft(user, code, reason=payload.reason)


@router.get("/{code}/diff", response_model=WorkflowDiffOut)
def diff_versions(
    code: str,
    v1: Annotated[int, Query(description="Base version number")],
    v2: Annotated[int, Query(description="Target version number")],
    user: Annotated[CurrentUser, Depends(require("config", "view"))],
    service: ServiceDep,
) -> WorkflowDiffOut:
    return service.diff_versions(user, code, v1, v2)
