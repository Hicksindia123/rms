"""Product CSV import planner (change plan 2026-11-12 Phase 1, AMD-07, DEC-36).

Pure: no SQL, no I/O.

Used by the masters service (Admin UI import) and by `backend/scripts/import_products.py`, so a
dry run and the real import always follow the same rules.

CSV columns (header names, case-insensitive; extra columns are ignored):
    Item Name  (alias: Product Name)        required
    Category                                 required — matched by category code or name
    Sub-Category (aliases: Sub Category, Subcategory)  optional — blank = no sub-category
    UOM (default PCS), HSN (4-8 digits)      optional, used only for new products

Rules:
* Names are compared ignoring case and repeated spaces ("exact name match" otherwise).
* An unknown category is an exception unless `create_categories` is set. New categories get no
  behaviour flags (hazard, battery, full opening, dismantling), so the summary lists them for
  review.
* An unknown sub-category is created under its category (code derived from the name).
* A name that matches an existing product updates its category / sub-category when they differ.
  A name that matches more than one product is an exception (never guessed).
* The same item twice in the file with the same category/sub-category is skipped as a duplicate;
  with a different one it is an exception.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

HSN_PATTERN = re.compile(r"^[0-9]{4,8}$")  # products.hsn_code CHECK (masters migration)
CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")

_HEADER_ALIASES: Mapping[str, tuple[str, ...]] = {
    "item": ("item name", "product name"),
    "category": ("category",),
    "sub_category": ("sub-category", "sub category", "subcategory"),
    "uom": ("uom",),
    "hsn": ("hsn",),
}


def clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def norm(value: str | None) -> str:
    return clean(value).upper()


def code_from_name(name: str) -> str:
    """Stable code for a new category / sub-category.

    `Rectal (Blister Pack)` -> RECTAL_BLISTER_PACK.
    """
    code = re.sub(r"[^A-Z0-9]+", "_", norm(name)).strip("_")
    if not code:
        return ""
    if not code[0].isalpha():
        code = f"C_{code}"
    return code[:50]


# --- inputs -----------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class CsvRow:
    row_no: int
    item_name: str
    category: str
    sub_category: str
    uom: str
    hsn: str | None


@dataclass(frozen=True, slots=True)
class CategoryRef:
    code: str
    name: str
    is_active: bool


@dataclass(frozen=True, slots=True)
class SubCategoryRef:
    category_code: str
    code: str
    name: str
    is_active: bool


@dataclass(frozen=True, slots=True)
class ProductRef:
    id: str
    code: str
    name: str
    category_code: str
    subcategory_code: str | None


@dataclass(frozen=True, slots=True)
class MastersSnapshot:
    categories: list[CategoryRef]
    subcategories: list[SubCategoryRef]
    products: list[ProductRef]


# --- outputs ----------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class NewCategory:
    code: str
    name: str


@dataclass(frozen=True, slots=True)
class NewSubCategory:
    category_code: str
    code: str
    name: str


@dataclass(frozen=True, slots=True)
class NewProduct:
    row_no: int
    name: str
    category_code: str
    subcategory_code: str | None
    uom: str
    hsn: str | None


@dataclass(frozen=True, slots=True)
class ProductUpdate:
    row_no: int
    product_id: str
    product_code: str
    name: str
    from_category: str
    to_category: str
    from_subcategory: str | None
    to_subcategory: str | None

    @property
    def category_changed(self) -> bool:
        return self.from_category != self.to_category


@dataclass(frozen=True, slots=True)
class ImportException:
    row_no: int
    item_name: str
    category: str
    sub_category: str
    reason: str


@dataclass(slots=True)
class ImportPlan:
    rows_read: int = 0
    new_categories: list[NewCategory] = field(default_factory=list)
    new_subcategories: list[NewSubCategory] = field(default_factory=list)
    new_products: list[NewProduct] = field(default_factory=list)
    updates: list[ProductUpdate] = field(default_factory=list)
    unchanged: int = 0
    duplicates_in_file: int = 0
    exceptions: list[ImportException] = field(default_factory=list)


class CsvFormatError(ValueError):
    """The CSV cannot be read at all (missing required columns, empty file)."""


# --- parsing ----------------------------------------------------------------------------------
def parse_csv(text: str) -> list[CsvRow]:
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    headers = {clean(h).lower(): h for h in (reader.fieldnames or []) if h is not None}
    columns: dict[str, str] = {}
    for key, aliases in _HEADER_ALIASES.items():
        for alias in aliases:
            if alias in headers:
                columns[key] = headers[alias]
                break
    missing = [
        label
        for key, label in (("item", "Item Name"), ("category", "Category"))
        if key not in columns
    ]
    if missing:
        raise CsvFormatError(f"CSV is missing column(s): {', '.join(missing)}")

    def cell(row: Mapping[str, str | None], key: str) -> str:
        col = columns.get(key)
        return clean(row.get(col)) if col else ""

    rows: list[CsvRow] = []
    for row_no, raw in enumerate(reader, start=2):
        if not any(clean(v) for v in raw.values() if isinstance(v, str)):
            continue  # fully blank line
        rows.append(
            CsvRow(
                row_no=row_no,
                item_name=cell(raw, "item"),
                category=cell(raw, "category"),
                sub_category=cell(raw, "sub_category"),
                uom=cell(raw, "uom") or "PCS",
                hsn=cell(raw, "hsn") or None,
            )
        )
    return rows


# --- planning ---------------------------------------------------------------------------------
def plan_import(
    rows: Iterable[CsvRow], masters: MastersSnapshot, *, create_categories: bool
) -> ImportPlan:
    plan = ImportPlan()

    # Category lookup by code and by name.
    cat_by_key: dict[str, CategoryRef] = {}
    for c in masters.categories:
        cat_by_key.setdefault(norm(c.code), c)
        cat_by_key.setdefault(norm(c.name), c)
    new_cat_by_key: dict[str, NewCategory] = {}

    # Sub-category lookup per category code, by code and by name.
    sub_by_key: dict[tuple[str, str], SubCategoryRef] = {}
    for s in masters.subcategories:
        sub_by_key.setdefault((s.category_code, norm(s.code)), s)
        sub_by_key.setdefault((s.category_code, norm(s.name)), s)
    new_sub_by_key: dict[tuple[str, str], NewSubCategory] = {}

    products_by_name: dict[str, list[ProductRef]] = {}
    for p in masters.products:
        products_by_name.setdefault(norm(p.name), []).append(p)
    seen_in_file: dict[str, tuple[str, str | None]] = {}

    def fail(row: CsvRow, reason: str) -> None:
        plan.exceptions.append(
            ImportException(row.row_no, row.item_name, row.category, row.sub_category, reason)
        )

    for row in rows:
        plan.rows_read += 1
        if not row.item_name:
            fail(row, "Item Name is blank")
            continue
        if not row.category:
            fail(row, "Category is blank")
            continue

        # Category
        category_code: str
        existing_cat = cat_by_key.get(norm(row.category))
        pending_cat = new_cat_by_key.get(norm(row.category)) or new_cat_by_key.get(
            code_from_name(row.category)
        )
        if existing_cat is not None:
            if not existing_cat.is_active:
                fail(row, f"Category '{existing_cat.code}' is inactive")
                continue
            category_code = existing_cat.code
        elif pending_cat is not None:
            category_code = pending_cat.code
        elif create_categories:
            code = code_from_name(row.category)
            if not CODE_PATTERN.fullmatch(code):
                fail(row, f"Cannot derive a category code from '{row.category}'")
                continue
            clash = cat_by_key.get(code)
            if clash is not None:
                category_code = clash.code
            else:
                new_cat = NewCategory(code=code, name=row.category)
                plan.new_categories.append(new_cat)
                new_cat_by_key[norm(row.category)] = new_cat
                new_cat_by_key[code] = new_cat
                category_code = code
        else:
            fail(
                row,
                f"Category '{row.category}' not found (allow new categories to create it)",
            )
            continue

        # Sub-category
        subcategory_code: str | None = None
        if row.sub_category:
            key = (category_code, norm(row.sub_category))
            existing_sub = sub_by_key.get(key)
            derived = code_from_name(row.sub_category)
            if existing_sub is None:
                existing_sub = sub_by_key.get((category_code, derived))
            pending_sub = new_sub_by_key.get(key) or new_sub_by_key.get((category_code, derived))
            if existing_sub is not None:
                if not existing_sub.is_active:
                    fail(row, f"Sub-category '{existing_sub.code}' is inactive")
                    continue
                subcategory_code = existing_sub.code
            elif pending_sub is not None:
                subcategory_code = pending_sub.code
            else:
                if not CODE_PATTERN.fullmatch(derived):
                    fail(row, f"Cannot derive a sub-category code from '{row.sub_category}'")
                    continue
                new_sub = NewSubCategory(category_code, derived, row.sub_category)
                plan.new_subcategories.append(new_sub)
                new_sub_by_key[key] = new_sub
                new_sub_by_key[(category_code, derived)] = new_sub
                subcategory_code = derived

        # Duplicates within the file
        target = (category_code, subcategory_code)
        name_key = norm(row.item_name)
        if name_key in seen_in_file:
            if seen_in_file[name_key] == target:
                plan.duplicates_in_file += 1
            else:
                fail(row, "Item appears earlier in the file with a different category/sub-category")
            continue
        seen_in_file[name_key] = target

        # Existing product?
        matches = products_by_name.get(name_key, [])
        if len(matches) > 1:
            codes = ", ".join(sorted(m.code for m in matches))
            fail(row, f"Item name matches more than one product ({codes})")
            continue
        if matches:
            p = matches[0]
            if (p.category_code, p.subcategory_code) == target:
                plan.unchanged += 1
            else:
                plan.updates.append(
                    ProductUpdate(
                        row_no=row.row_no,
                        product_id=p.id,
                        product_code=p.code,
                        name=p.name,
                        from_category=p.category_code,
                        to_category=category_code,
                        from_subcategory=p.subcategory_code,
                        to_subcategory=subcategory_code,
                    )
                )
            continue

        if row.hsn is not None and not HSN_PATTERN.fullmatch(row.hsn):
            fail(row, f"HSN '{row.hsn}' must be 4-8 digits")
            continue
        plan.new_products.append(
            NewProduct(
                row_no=row.row_no,
                name=row.item_name,
                category_code=category_code,
                subcategory_code=subcategory_code,
                uom=row.uom,
                hsn=row.hsn,
            )
        )

    # Only create the sub-categories/categories that a surviving row actually uses.
    used_subs = {(p.category_code, p.subcategory_code) for p in plan.new_products} | {
        (u.to_category, u.to_subcategory) for u in plan.updates
    }
    plan.new_subcategories = [
        s for s in plan.new_subcategories if (s.category_code, s.code) in used_subs
    ]
    used_cats = {c for c, _ in used_subs} | {s.category_code for s in plan.new_subcategories}
    plan.new_categories = [c for c in plan.new_categories if c.code in used_cats]
    return plan
