"""Masters Pydantic I/O. Request models forbid unknown fields; responses are explicit."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CategoryOut(BaseModel):
    id: UUID
    code: str
    name: str
    is_active: bool
    requires_full_opening: bool
    supports_battery: bool
    supports_dismantling: bool
    hazard_capable: bool
    subcategory_count: int
    product_count: int


class SubCategoryOut(BaseModel):
    id: UUID
    category_id: UUID
    category_code: str
    category_name: str
    code: str
    name: str
    is_active: bool
    product_count: int
    created_at: datetime
    updated_at: datetime


class SubCategoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category_id: UUID
    # AMD-07: immutable once created. Optional: derived from the name when omitted.
    code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]*$", max_length=50)
    name: str = Field(min_length=1, max_length=200)


class SubCategoryUpdate(BaseModel):
    """Name and active flag only: code and category are immutable (AMD-07)."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    is_active: bool | None = None


class ProductOut(BaseModel):
    id: UUID
    code: str
    name: str
    uom: str
    hsn_code: str | None
    is_active: bool
    category_id: UUID
    category_code: str
    category_name: str
    subcategory_id: UUID | None
    subcategory_code: str | None
    subcategory_name: str | None
    updated_at: datetime


class ProductUpdate(BaseModel):
    """Partial update. Send `subcategory_id: null` to clear the sub-category."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    category_id: UUID | None = None
    subcategory_id: UUID | None = None
    uom: str | None = Field(default=None, min_length=1, max_length=20)
    hsn_code: str | None = Field(default=None, pattern=r"^[0-9]{4,8}$")
    is_active: bool | None = None


class ProductImportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    csv_text: str = Field(min_length=1, max_length=2_000_000)
    # New categories carry no behaviour flags (G-05/G-06/DEC-15/DEC-18), so creating them is opt-in.
    create_categories: bool = False


class ImportCategoryOut(BaseModel):
    code: str
    name: str


class ImportSubCategoryOut(BaseModel):
    category_code: str
    code: str
    name: str


class ImportProductOut(BaseModel):
    row_no: int
    code: str | None
    name: str
    category_code: str
    subcategory_code: str | None


class ImportUpdateOut(BaseModel):
    row_no: int
    product_code: str
    name: str
    from_category: str
    to_category: str
    from_subcategory: str | None
    to_subcategory: str | None


class ImportExceptionOut(BaseModel):
    row_no: int
    item_name: str
    category: str
    sub_category: str
    reason: str


class ProductImportOut(BaseModel):
    dry_run: bool
    rows_read: int
    new_categories: list[ImportCategoryOut]
    new_subcategories: list[ImportSubCategoryOut]
    new_products: list[ImportProductOut]
    updates: list[ImportUpdateOut]
    category_changes: int
    unchanged: int
    duplicates_in_file: int
    exceptions: list[ImportExceptionOut]
