"""Schemas for versioned dynamic forms and form builder (master plan §8.3, §10, prompt P1-07)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ControlType = Literal[
    "text",
    "number",
    "date",
    "dropdown",
    "radio",
    "checkbox",
    "multiselect",
    "file",
    "textarea",
    "master_ref",
]

FormVersionStatus = Literal["DRAFT", "PUBLISHED", "RETIRED"]


class FormFieldBase(BaseModel):
    field_key: str = Field(..., pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(..., min_length=1)
    control_type: ControlType
    option_set_id: UUID | None = None
    master_ref_type: str | None = None
    is_required: bool = False
    visible_when: dict[str, Any] | None = None
    required_when: dict[str, Any] | None = None
    validation: dict[str, Any] | None = None
    default_value: Any = None
    sort_order: int = 0
    section: str | None = None
    help_text: str | None = None
    is_core: bool = False
    is_system_locked: bool = False


class FormFieldCreate(FormFieldBase):
    pass


class FormFieldUpdate(BaseModel):
    label: str | None = Field(None, min_length=1)
    control_type: ControlType | None = None
    option_set_id: UUID | None = None
    master_ref_type: str | None = None
    is_required: bool | None = None
    visible_when: dict[str, Any] | None = None
    required_when: dict[str, Any] | None = None
    validation: dict[str, Any] | None = None
    default_value: Any = None
    sort_order: int | None = None
    section: str | None = None
    help_text: str | None = None
    is_core: bool | None = None


class FormFieldOut(FormFieldBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    form_version_id: UUID
    option_set_code: str | None = None
    option_items: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class FormVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    form_definition_id: UUID
    version_no: int
    status: FormVersionStatus
    snapshot: dict[str, Any] | None = None
    published_by: UUID | None = None
    published_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    field_count: int = 0


class FormVersionDetailOut(FormVersionOut):
    fields: list[FormFieldOut] = Field(default_factory=list)


class FormDefinitionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    step_code: str | None = None
    name: str
    is_active: bool
    latest_published_version: int | None = None
    has_draft: bool = False
    draft_version_no: int | None = None
    created_at: datetime
    updated_at: datetime


class FormDraftUpdate(BaseModel):
    fields: list[FormFieldCreate]
    sections: list[str] | None = None


class FormPublishRequest(BaseModel):
    version_notes: str | None = None


class FormValidateOut(BaseModel):
    is_valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class FormDiffOut(BaseModel):
    form_code: str
    version_a: int
    version_b: int
    added_fields: list[dict[str, Any]] = Field(default_factory=list)
    removed_fields: list[dict[str, Any]] = Field(default_factory=list)
    modified_fields: list[dict[str, Any]] = Field(default_factory=list)


class SubmissionValidationRequest(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] | None = None


class SubmissionValidationResponse(BaseModel):
    is_valid: bool
    errors: dict[str, list[str]] = Field(default_factory=dict)
    sanitized_values: dict[str, Any] = Field(default_factory=dict)
