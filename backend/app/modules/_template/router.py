"""Router: HTTP only (auth + permission dependencies, Pydantic I/O). No SQL here."""

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.core.db import UowDep
from app.core.idempotency import IdempotencyKeyDep
from app.core.permissions import require
from app.core.security import CurrentUser
from app.modules._template.schemas import DepartmentCreate, DepartmentOut
from app.modules._template.service import TemplateService
from app.shared.pagination import Page, PageParamsDep

router = APIRouter(prefix="/template/departments", tags=["template"])


def get_service(uow: UowDep) -> TemplateService:
    return TemplateService(uow)


ServiceDep = Annotated[TemplateService, Depends(get_service)]


@router.get("", response_model=Page[DepartmentOut])
def list_items(
    user: Annotated[CurrentUser, Depends(require("masters", "view"))],
    params: PageParamsDep,
    service: ServiceDep,
) -> Page[DepartmentOut]:
    return service.list(user, params)


@router.post("", status_code=201, response_model=DepartmentOut)
def create_item(
    payload: DepartmentCreate,
    user: Annotated[CurrentUser, Depends(require("masters", "create"))],
    idem: IdempotencyKeyDep,
    service: ServiceDep,
) -> JSONResponse:
    return service.create(user, payload, idem).to_response()
