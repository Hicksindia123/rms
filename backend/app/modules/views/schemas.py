"""Schemas for Saved Views (P4-04)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.shared.advanced_filters import FilterClause


class SavedViewIn(BaseModel):
    view_code: str | None = Field(
        default=None,
        max_length=60,
        description="Endpoint or view identifier e.g. gs_list, audit_log",
    )
    resource_code: str | None = Field(
        default=None, max_length=60, description="Alias for view_code"
    )
    name: str = Field(..., max_length=120, description="Display name for preset")
    filters: list[Any] = Field(default_factory=list, description="Filter clauses")
    columns: list[str] = Field(default_factory=list, description="Ordered visible column keys")
    sort_by: str | None = Field(default=None, max_length=60)
    sort_dir: Literal["asc", "desc"] | None = None
    is_default: bool = False

    def model_post_init(self, __context: Any) -> None:
        if not self.view_code and self.resource_code:
            self.view_code = self.resource_code
        if not self.view_code:
            self.view_code = "default"


class SavedViewUpdateIn(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    filters: list[FilterClause] | None = None
    columns: list[str] | None = None
    sort_by: str | None = None
    sort_dir: Literal["asc", "desc"] | None = None
    is_default: bool | None = None


class SavedViewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    view_code: str
    name: str
    filters: list[dict[str, Any]]
    columns: list[str]
    sort_by: str | None
    sort_dir: str | None
    is_default: bool
    created_at: datetime
    updated_at: datetime
