"""Reports API schemas (prompt P4-02)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

COLUMN_KEY = r"^[a-z][a-z0-9_]{0,59}$"


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ReportSummary(_Out):
    code: str
    title: str
    description: str | None
    can_export: bool


class ReportGroupOut(_Out):
    code: str
    title: str
    reports: list[ReportSummary]


class FilterChoice(_Out):
    value: str
    label: str


class FilterOut(_Out):
    key: str
    label: str
    type: Literal["date", "text", "enum", "uuid", "bool"]
    choices: list[FilterChoice] = []
    default: str | None = None
    required: bool = False


class ColumnOut(_Out):
    key: str
    label: str
    type: str
    default: bool
    total: str | None
    has_link: bool
    card: int
    sortable: bool


class SortOut(_Out):
    key: str
    dir: Literal["asc", "desc"]


class SavedFilterOut(_Out):
    id: UUID
    name: str
    params: dict[str, Any]
    is_default: bool
    created_at: datetime


class ReportDefinitionOut(_Out):
    code: str
    group_code: str
    group_title: str
    title: str
    description: str | None
    columns: list[ColumnOut]
    filters: list[FilterOut]
    default_sort: SortOut
    visible_columns: list[str]
    column_source: Literal["user", "role", "default"]
    column_source_role: str | None
    saved_filters: list[SavedFilterOut]
    can_export: bool
    scope: Literal["all", "department", "own"]
    page_size: int


class ReportDataOut(_Out):
    code: str
    page: int
    page_size: int
    total: int
    sort: SortOut
    applied: dict[str, Any]
    rows: list[dict[str, Any]]
    totals: dict[str, Any]
    generated_at: datetime


class Branding(_Out):
    app_name: str
    logo_url: str | None
    primary_color: str | None


class FilterUsed(_Out):
    label: str
    value: str


class ReportPrintOut(_Out):
    code: str
    title: str
    description: str | None
    branding: Branding
    filters_used: list[FilterUsed]
    generated_by: str
    generated_at: datetime
    timezone: str
    columns: list[ColumnOut]
    rows: list[dict[str, Any]]
    totals: dict[str, Any]
    total_rows: int
    printed_rows: int
    truncated: bool


class ColumnsIn(BaseModel):
    columns: list[str] = Field(min_length=1, max_length=100)

    @field_validator("columns")
    @classmethod
    def _keys(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("a column can be chosen only once")
        return value


class RoleColumnsIn(ColumnsIn):
    reason: str | None = Field(default=None, max_length=500)


class ColumnPrefOut(_Out):
    report_code: str
    visible_columns: list[str]
    column_source: Literal["user", "role", "default"]
    column_source_role: str | None


class RoleColumnsOut(_Out):
    report_code: str
    report_title: str
    role_code: str
    role_name: str
    columns: list[str]
    updated_at: datetime | None


class RoleRef(_Out):
    code: str
    name: str


class SavedFilterIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    params: dict[str, str | bool | None] = Field(default_factory=dict)
    is_default: bool = False

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value
