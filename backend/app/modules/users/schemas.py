"""User administration I/O models (master plan prompt P1-05)."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_DEPT_CODE = re.compile(r"^[A-Z][A-Z0-9_]*$")

# P1-05 / DEC-50 password policy (enforced by the backend for admin-set and self-set passwords).
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 72  # bcrypt limit used by Supabase Auth


def check_password_policy(value: str) -> str:
    if len(value) < PASSWORD_MIN_LENGTH or len(value) > PASSWORD_MAX_LENGTH:
        raise ValueError(
            f"Password must be {PASSWORD_MIN_LENGTH}-{PASSWORD_MAX_LENGTH} characters long"
        )
    if not re.search(r"[A-Za-z]", value) or not re.search(r"\d", value):
        raise ValueError("Password must contain at least one letter and one digit")
    return value


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


class DepartmentRef(BaseModel):
    id: UUID
    code: str
    name: str


class RoleRef(BaseModel):
    id: UUID
    code: str
    name: str


class UserOut(BaseModel):
    id: UUID
    email: str | None
    full_name: str
    employee_code: str | None
    phone: str | None
    department: DepartmentRef | None
    is_active: bool
    is_super_admin: bool
    must_change_password: bool
    roles: list[RoleRef]
    created_at: datetime
    updated_at: datetime


class UserCreate(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    full_name: str = Field(min_length=1, max_length=200)
    employee_code: str | None = Field(default=None, max_length=50)
    phone: str | None = Field(default=None, max_length=30)
    department_id: UUID | None = None
    role_codes: list[str] = Field(default_factory=list, max_length=20)
    is_super_admin: bool = False
    initial_password: str
    must_change_password: bool = True

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        value = value.strip().lower()
        if not _EMAIL.fullmatch(value):
            raise ValueError("Enter a valid email address")
        return value

    @field_validator("full_name")
    @classmethod
    def _name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Full name is required")
        return value

    @field_validator("employee_code", "phone")
    @classmethod
    def _optional(cls, value: str | None) -> str | None:
        return _clean_optional(value)

    @field_validator("initial_password")
    @classmethod
    def _password(cls, value: str) -> str:
        return check_password_policy(value)


class UserUpdate(BaseModel):
    """PATCH: only the fields sent are changed (`department_id: null` clears the department)."""

    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    employee_code: str | None = Field(default=None, max_length=50)
    phone: str | None = Field(default=None, max_length=30)
    department_id: UUID | None = None
    role_codes: list[str] | None = Field(default=None, max_length=20)
    is_super_admin: bool | None = None
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("full_name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Full name cannot be empty")
        return value.strip() if value else value

    @field_validator("employee_code", "phone")
    @classmethod
    def _optional(cls, value: str | None) -> str | None:
        return _clean_optional(value)


class ReasonIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class ResetPasswordIn(BaseModel):
    temporary_password: str
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("temporary_password")
    @classmethod
    def _password(cls, value: str) -> str:
        return check_password_policy(value)


class ChangeOwnPasswordIn(BaseModel):
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _password(cls, value: str) -> str:
        return check_password_policy(value)


class OverrideIn(BaseModel):
    module_code: str = Field(min_length=1, max_length=60)
    action: str = Field(min_length=1, max_length=20)
    effect: Literal["grant", "deny"]
    reason: str = Field(min_length=3, max_length=500)
    expires_at: datetime | None = None


class OverridesReplaceIn(BaseModel):
    overrides: list[OverrideIn] = Field(max_length=200)


class OverrideOut(BaseModel):
    id: UUID
    module_code: str
    action: str
    effect: Literal["grant", "deny"]
    reason: str
    expires_at: datetime | None
    is_expired: bool
    created_at: datetime


class EffectivePermissionOut(BaseModel):
    module_code: str
    action: str
    scope: str


class EffectivePermissionsOut(BaseModel):
    user_id: UUID
    is_super_admin: bool
    permissions: list[EffectivePermissionOut]


class DepartmentOut(BaseModel):
    id: UUID
    code: str
    name: str
    is_active: bool
    user_count: int


class DepartmentCreate(BaseModel):
    code: str = Field(min_length=2, max_length=40)
    name: str = Field(min_length=1, max_length=120)

    @field_validator("code")
    @classmethod
    def _code(cls, value: str) -> str:
        value = value.strip().upper()
        if not _DEPT_CODE.fullmatch(value):
            raise ValueError("Code must start with a letter and use A-Z, 0-9 and _")
        return value

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name is required")
        return value


class DepartmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    is_active: bool | None = None
