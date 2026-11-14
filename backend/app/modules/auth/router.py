from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.db import UowDep
from app.core.permissions import EffectivePermissionsDep
from app.core.security import CurrentUserDep
from app.modules.auth.schemas import MeResponse
from app.modules.auth.service import AuthService

router = APIRouter(tags=["auth"])


def get_auth_service(uow: UowDep) -> AuthService:
    return AuthService(uow)


@router.get("/me", response_model=MeResponse)
def get_me(
    user: CurrentUserDep,
    perms: EffectivePermissionsDep,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> MeResponse:
    """The signed-in user's profile, roles, effective permissions and performable step codes."""
    return service.get_me(user, perms)
