"""Pydantic I/O models. Request models forbid unknown fields; responses are explicit."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DepartmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$", max_length=50)
    name: str = Field(min_length=1, max_length=200)


class DepartmentOut(BaseModel):
    id: UUID
    code: str
    name: str
    is_active: bool
    created_at: datetime
    created_by: UUID | None
