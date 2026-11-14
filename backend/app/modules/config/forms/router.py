"""Router for versioned dynamic forms and form builder (master plan §8.3, §10, prompt P1-07)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from app.core.db import UowDep
from app.core.permissions import require
from app.core.security import CurrentUser, get_current_user
from app.modules.config.forms.schemas import (
    FormDefinitionOut,
    FormDiffOut,
    FormDraftUpdate,
    FormPublishRequest,
    FormValidateOut,
    FormVersionDetailOut,
    FormVersionOut,
    SubmissionValidationRequest,
    SubmissionValidationResponse,
)
from app.modules.config.forms.service import FormService

router = APIRouter(prefix="/config/forms", tags=["config-forms"])


def get_service(uow: UowDep) -> FormService:
    return FormService(uow)


ServiceDep = Annotated[FormService, Depends(get_service)]


@router.get("", response_model=list[FormDefinitionOut])
def list_forms(
    user: Annotated[CurrentUser, Depends(require("config", "view"))],
    service: ServiceDep,
) -> list[FormDefinitionOut]:
    return service.list_forms(user)


@router.get("/{form_code}", response_model=FormDefinitionOut)
def get_form(
    form_code: str,
    user: Annotated[CurrentUser, Depends(require("config", "view"))],
    service: ServiceDep,
) -> FormDefinitionOut:
    return service.get_form(user, form_code)


@router.get(
    "/{form_code}/published",
    response_model=dict[str, Any],
    dependencies=[Depends(get_current_user)],  # any active user (production audit 2026-11-14)
)
def get_published_snapshot(
    form_code: str,
    service: ServiceDep,
) -> dict[str, Any]:
    """Returns the snapshot used by operational screens."""
    return service.get_published_snapshot(form_code)


@router.get("/{form_code}/versions/{version_no}", response_model=FormVersionDetailOut)
def get_version(
    form_code: str,
    version_no: int,
    user: Annotated[CurrentUser, Depends(require("config", "view"))],
    service: ServiceDep,
) -> FormVersionDetailOut:
    return service.get_version(user, form_code, version_no)


@router.post("/{form_code}/draft", response_model=FormVersionDetailOut)
def create_draft(
    form_code: str,
    user: Annotated[CurrentUser, Depends(require("config", "configure"))],
    service: ServiceDep,
) -> FormVersionDetailOut:
    return service.create_draft(user, form_code)


@router.put("/{form_code}/draft/fields", response_model=FormVersionDetailOut)
def update_draft_fields(
    form_code: str,
    payload: FormDraftUpdate,
    user: Annotated[CurrentUser, Depends(require("config", "configure"))],
    service: ServiceDep,
) -> FormVersionDetailOut:
    return service.update_draft_fields(user, form_code, payload)


@router.post("/{form_code}/draft/validate", response_model=FormValidateOut)
def validate_draft(
    form_code: str,
    user: Annotated[CurrentUser, Depends(require("config", "configure"))],
    service: ServiceDep,
) -> FormValidateOut:
    return service.validate_draft(user, form_code)


@router.post("/{form_code}/draft/publish", response_model=FormVersionOut)
def publish_draft(
    form_code: str,
    payload: FormPublishRequest,
    user: Annotated[CurrentUser, Depends(require("config", "configure"))],
    service: ServiceDep,
) -> FormVersionOut:
    return service.publish_draft(user, form_code, version_notes=payload.version_notes)


@router.get("/{form_code}/diff", response_model=FormDiffOut)
def diff_versions(
    form_code: str,
    v1: Annotated[int, Query(description="Base version number")],
    v2: Annotated[int, Query(description="Target version number")],
    user: Annotated[CurrentUser, Depends(require("config", "view"))],
    service: ServiceDep,
) -> FormDiffOut:
    return service.diff_versions(user, form_code, v1, v2)


@router.post(
    "/{form_code}/validate-submission",
    response_model=SubmissionValidationResponse,
    dependencies=[Depends(get_current_user)],  # any active user (production audit 2026-11-14)
)
def validate_submission_endpoint(
    form_code: str,
    payload: SubmissionValidationRequest,
    service: ServiceDep,
) -> SubmissionValidationResponse:
    """Test and validate a submission against the published form snapshot."""
    return service.validate_submission_payload(form_code, payload.values, payload.context)
