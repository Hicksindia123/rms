"""Role & permission administration I/O models (master plan prompt P1-05)."""

from __future__ import annotations

import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

_ROLE_CODE = re.compile(r"^[A-Z][A-Z0-9_]*$")

Scope = Literal["own", "department", "all"]


class RoleOut(BaseModel):
    id: UUID
    code: str
    name: str
    description: str | None
    is_system: bool
    user_count: int
    permission_count: int


class RoleCreate(BaseModel):
    code: str = Field(min_length=2, max_length=60)
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)

    @field_validator("code")
    @classmethod
    def _code(cls, value: str) -> str:
        value = value.strip().upper()
        if not _ROLE_CODE.fullmatch(value):
            raise ValueError("Code must start with a letter and use A-Z, 0-9 and _")
        return value

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name is required")
        return value


class RoleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)


class PermissionCatalogueOut(BaseModel):
    module_code: str
    action: str
    description: str | None


class RolePermissionIn(BaseModel):
    module_code: str = Field(min_length=1, max_length=60)
    action: str = Field(min_length=1, max_length=20)
    scope: Scope = "all"


class RolePermissionsReplaceIn(BaseModel):
    permissions: list[RolePermissionIn] = Field(max_length=500)
    reason: str | None = Field(default=None, max_length=500)


class RolePermissionOut(BaseModel):
    module_code: str
    action: str
    scope: Scope
