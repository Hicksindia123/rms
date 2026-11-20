"""Intermediate Stores I/O models (Phase P1, DEC-61)."""

from __future__ import annotations

import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

# Same rule as the DB CHECK on intermediate_stores.code (the role / location codes get "ISTORE_").
_STORE_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,19}$")


class RoleRef(BaseModel):
    id: UUID
    code: str
    name: str


class LocationRef(BaseModel):
    id: UUID
    code: str
    name: str


class StoreUser(BaseModel):
    id: UUID
    full_name: str
    email: str | None
    is_active: bool


class StoreOut(BaseModel):
    id: UUID
    code: str
    name: str
    is_default: bool
    is_active: bool
    sort_order: int
    role: RoleRef
    location: LocationRef
    category_count: int
    subcategory_count: int
    users: list[StoreUser]
    created_at: datetime
    updated_at: datetime


class StoreBrief(BaseModel):
    id: UUID
    code: str
    name: str
    is_default: bool
    location_code: str


def _clean_name(value: str) -> str:
    value = " ".join(value.split())
    if not value:
        raise ValueError("Name is required")
    return value


class StoreCreate(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=120)
    sort_order: int = Field(default=100, ge=0, le=100000)
    is_default: bool = False
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("code")
    @classmethod
    def _code(cls, value: str) -> str:
        value = value.strip().upper()
        if not _STORE_CODE.fullmatch(value):
            raise ValueError("Code must start with a letter and use A-Z, 0-9 and _ (max 20)")
        return value

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return _clean_name(value)


class StoreUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    sort_order: int | None = Field(default=None, ge=0, le=100000)
    is_active: bool | None = None
    # Only `true` is meaningful: it moves the default flag to this store (DEC-61, exactly one).
    is_default: bool | None = None
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        return None if value is None else _clean_name(value)


class StoreRef(BaseModel):
    id: UUID
    code: str
    name: str
    is_active: bool


class MappingSubcategory(BaseModel):
    id: UUID
    code: str
    name: str
    is_active: bool
    store: StoreRef | None


class MappingCategory(BaseModel):
    id: UUID
    code: str
    name: str
    is_active: bool
    store: StoreRef | None
    subcategories: list[MappingSubcategory]


class StoreMappingOut(BaseModel):
    store: StoreRef
    default_store: StoreRef | None
    category_ids: list[UUID]
    subcategory_ids: list[UUID]
    tree: list[MappingCategory]


class StoreMappingIn(BaseModel):
    category_ids: list[UUID] = Field(default_factory=list, max_length=500)
    subcategory_ids: list[UUID] = Field(default_factory=list, max_length=2000)
    # A (sub-)category mapped to another store is a conflict; true moves it to this store.
    reassign: bool = False
    reason: str | None = Field(default=None, max_length=500)
