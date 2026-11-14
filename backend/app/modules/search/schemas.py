"""Schemas for Global Search (P4-04)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SearchResultItem(BaseModel):
    id: str
    type: str = Field(
        ...,
        description=(
            "Category code: goods_slip, party, document, credit_note, "
            "transfer, store_issue, dispatch, batch, container"
        ),
    )
    title: str
    subtitle: str | None = None
    badge: str | None = None
    badge_variant: str | None = "info"  # info, success, warning, neutral
    route: str = Field(..., description="Web app hash route e.g. /#/gs/{id}")
    details: dict[str, Any] = Field(default_factory=dict)


class SearchResultGroup(BaseModel):
    type: str
    label: str
    count: int
    items: list[SearchResultItem]


class SearchResponse(BaseModel):
    query: str
    total: int
    is_qr_match: bool = False
    direct_route: str | None = None
    groups: list[SearchResultGroup]
    took_ms: float
