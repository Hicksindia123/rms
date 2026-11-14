"""Item field profile I/O (change plan 2026-11-12 Phase 4; AMD-10, AMD-11, AMD-16; G-18).

Request models forbid unknown fields. Codes and field groups are immutable after create, so the
update model has neither.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

FieldGroup = Literal["CATEGORISATION", "DEPARTMENT", "ACTION", "ITEM_COUNT"]
ScopeType = Literal["CATEGORY", "SUBCATEGORY", "PRODUCT"]

FIELD_GROUPS: tuple[FieldGroup, ...] = ("CATEGORISATION", "DEPARTMENT", "ACTION", "ITEM_COUNT")


class FieldOut(BaseModel):
    id: UUID
    field_group: FieldGroup
    code: str
    label: str
    description: str | None
    sort_order: int
    is_active: bool
    is_system: bool
    is_wastage: bool
    returns_to_routing: bool
    requires_cn: bool
    requires_challan: bool
    system_behavior: str | None
    source_ref: str | None
    assignment_count: int
    updated_at: datetime


class FieldFlags(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_wastage: bool | None = None
    returns_to_routing: bool | None = None
    requires_cn: bool | None = None
    requires_challan: bool | None = None


class FieldCreate(FieldFlags):
    field_group: FieldGroup
    label: str = Field(min_length=1, max_length=120)
    # Immutable once created. Optional: derived from the label when omitted.
    code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]*$", max_length=50)
    description: str | None = Field(default=None, max_length=500)
    sort_order: int | None = Field(default=None, ge=0, le=100000)


class FieldUpdate(FieldFlags):
    """Label, description, sort, active and flags. Code and group are immutable (G-18)."""

    label: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    sort_order: int | None = Field(default=None, ge=0, le=100000)
    is_active: bool | None = None
    reason: str | None = Field(default=None, max_length=500)


class ScopeRef(BaseModel):
    scope_type: ScopeType
    scope_id: UUID
    code: str
    name: str


class ResolvedField(BaseModel):
    field_id: UUID
    code: str
    label: str
    sort_order: int
    source_scope_type: ScopeType
    source_scope_id: UUID
    is_wastage: bool
    returns_to_routing: bool
    requires_cn: bool
    requires_challan: bool
    system_behavior: str | None


class AssignmentOut(BaseModel):
    field_id: UUID
    code: str
    label: str
    is_included: bool
    sort_order: int
    field_is_active: bool


class GroupProfileOut(BaseModel):
    field_group: FieldGroup
    # True when this scope has its own assignment rows for the group (it overrides its parents).
    overridden: bool
    own: list[AssignmentOut]
    # What this scope would get from its parents (empty at CATEGORY scope).
    inherited_from: ScopeRef | None
    inherited: list[ResolvedField]
    # The effective fields at this scope (AMD-10 resolution rule, DB function).
    effective: list[ResolvedField]


class ScopeProfileOut(BaseModel):
    scope: ScopeRef
    chain: list[ScopeRef]
    version_id: UUID | None
    version_no: int | None
    groups: list[GroupProfileOut]


class AssignmentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_id: UUID
    is_included: bool = True
    sort_order: int = Field(default=0, ge=0, le=100000)


class ScopeIn(BaseModel):
    """The scope chain: category, optionally a sub-category, optionally a product."""

    model_config = ConfigDict(extra="forbid")

    category_id: UUID
    subcategory_id: UUID | None = None
    product_id: UUID | None = None


class OverrideIn(ScopeIn):
    fields: list[AssignmentIn] = Field(max_length=200)
    reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _unique_fields(self) -> OverrideIn:
        ids = [f.field_id for f in self.fields]
        if len(ids) != len(set(ids)):
            raise ValueError("A field can be listed only once per scope")
        return self


class ResolvedProfileOut(BaseModel):
    product_id: UUID
    product_code: str
    product_name: str
    version_id: UUID | None
    version_no: int | None
    groups: dict[str, list[ResolvedField]]


class VersionOut(BaseModel):
    id: UUID
    version_no: int
    created_at: datetime
    created_by_name: str | None
    library_count: int
    assignment_count: int
