from uuid import UUID

from pydantic import BaseModel


class DepartmentOut(BaseModel):
    id: UUID
    code: str
    name: str


class ProfileOut(BaseModel):
    id: UUID
    email: str | None
    full_name: str
    employee_code: str | None
    phone: str | None
    is_super_admin: bool
    department: DepartmentOut | None
    # P1-05 / DEC-50: the user must set a new password before using the app.
    must_change_password: bool = False


class RoleOut(BaseModel):
    code: str
    name: str


class PermissionOut(BaseModel):
    module_code: str
    action: str
    scope: str


class MeResponse(BaseModel):
    profile: ProfileOut
    roles: list[RoleOut]
    permissions: list[PermissionOut]
    step_codes: list[str]
