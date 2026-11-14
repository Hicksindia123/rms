"""FastAPI router for print templates and live sample previews (prompt P1-08)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.db import UowDep
from app.core.permissions import require
from app.core.security import CurrentUser, get_current_user
from app.modules.config.templates.schemas import (
    PrintTemplateOut,
    PrintTemplatePublishRequest,
    PrintTemplateSampleDataOut,
    PrintTemplateUpdate,
)
from app.modules.config.templates.service import PrintTemplatesService

router = APIRouter(prefix="/config/templates", tags=["config-templates"])


def get_service(uow: UowDep) -> PrintTemplatesService:
    return PrintTemplatesService(uow)


ServiceDep = Annotated[PrintTemplatesService, Depends(get_service)]


@router.get("", response_model=list[PrintTemplateOut])
def list_templates(
    user: Annotated[CurrentUser, Depends(require("config", "view"))],
    service: ServiceDep,
) -> list[PrintTemplateOut]:
    return service.list_templates(user)


@router.get(
    "/{code}/published",
    response_model=PrintTemplateOut,
    dependencies=[Depends(get_current_user)],  # any active user (production audit 2026-11-14)
)
def get_published_template(
    code: str,
    service: ServiceDep,
) -> PrintTemplateOut:
    return service.get_published_template(code)


@router.get("/{code}/versions/{version_no}", response_model=PrintTemplateOut)
def get_template_version(
    code: str,
    version_no: int,
    user: Annotated[CurrentUser, Depends(require("config", "view"))],
    service: ServiceDep,
) -> PrintTemplateOut:
    return service.get_template_version(user, code, version_no)


@router.post("/{code}/draft", response_model=PrintTemplateOut)
def create_draft(
    code: str,
    user: Annotated[CurrentUser, Depends(require("config", "configure"))],
    service: ServiceDep,
) -> PrintTemplateOut:
    return service.create_draft(user, code)


@router.put("/{code}/draft", response_model=PrintTemplateOut)
def update_draft(
    code: str,
    payload: PrintTemplateUpdate,
    user: Annotated[CurrentUser, Depends(require("config", "configure"))],
    service: ServiceDep,
) -> PrintTemplateOut:
    return service.update_draft(user, code, payload)


@router.post("/{code}/draft/publish", response_model=PrintTemplateOut)
def publish_draft(
    code: str,
    payload: PrintTemplatePublishRequest,
    user: Annotated[CurrentUser, Depends(require("config", "configure"))],
    service: ServiceDep,
) -> PrintTemplateOut:
    return service.publish_draft(user, code, payload)


@router.get("/{code}/sample-data", response_model=PrintTemplateSampleDataOut)
def get_sample_data(
    code: str,
    user: Annotated[CurrentUser, Depends(require("config", "view"))],
    service: ServiceDep,
) -> PrintTemplateSampleDataOut:
    """Returns sample preview data clearly flagged with 'SAMPLE PREVIEW'
    for live preview in the designer.
    """
    return service.get_sample_data(code)
