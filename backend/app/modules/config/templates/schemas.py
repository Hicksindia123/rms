"""Pydantic schemas for print templates configuration, preview, and versioning (prompt P1-08)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class PrintTemplateLayoutSection(BaseModel):
    id: str
    title: str
    fields: list[str] = Field(default_factory=list)


class PrintTemplateSignatureBlock(BaseModel):
    label: str
    role: str


class PrintTemplateLayout(BaseModel):
    paper_size: str = Field("A4", pattern="^(A4|A5|LABEL)$")
    orientation: str = Field("portrait", pattern="^(portrait|landscape)$")
    show_logo: bool = True
    header_title: str
    header_subtitle: str | None = None
    footer_text: str | None = None
    sections: list[dict[str, Any]] = Field(default_factory=list)
    signature_blocks: list[PrintTemplateSignatureBlock] = Field(default_factory=list)


class PrintTemplateUpdate(BaseModel):
    name: str | None = None
    layout: dict[str, Any]
    reason: str | None = None


class PrintTemplatePublishRequest(BaseModel):
    reason: str = Field(..., min_length=3, description="Mandatory reason for publishing template")


class PrintTemplateOut(BaseModel):
    id: UUID
    code: str
    name: str
    version_no: int
    status: str
    layout: dict[str, Any]
    snapshot: dict[str, Any] | None = None
    published_by: UUID | None = None
    published_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class PrintTemplateSampleDataOut(BaseModel):
    code: str
    sample_data: dict[str, Any]
    data_dictionary: list[dict[str, str]]
