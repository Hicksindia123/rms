"""Masters service: product categories, sub-categories (AMD-07) and products.

Business rules live here, one transaction per command. The DB enforces the same AMD-07 rules
(composite FK products(subcategory_id, category_id), immutable sub-category code/category); the
service checks them first so the client gets a clear 409/422 instead of a database error.
"""

from __future__ import annotations

from uuid import UUID

import structlog

from app.core.db import UnitOfWork
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.idempotency import IdempotencyKey, IdempotentResult, run_idempotent
from app.core.security import CurrentUser
from app.modules.masters import repository as repo
from app.modules.masters.product_import import (
    CODE_PATTERN,
    CsvFormatError,
    ImportPlan,
    code_from_name,
    parse_csv,
    plan_import,
)
from app.modules.masters.schemas import (
    CategoryOut,
    ImportCategoryOut,
    ImportExceptionOut,
    ImportProductOut,
    ImportSubCategoryOut,
    ImportUpdateOut,
    ProductImportIn,
    ProductImportOut,
    ProductOut,
    ProductUpdate,
    SubCategoryCreate,
    SubCategoryOut,
    SubCategoryUpdate,
)
from app.shared.pagination import Page

log = structlog.get_logger("rms.masters")


def build_plan(db: repo.Db, csv_text: str, *, create_categories: bool) -> ImportPlan:
    """Parse + plan against the current masters (shared by the API and the CLI script)."""
    try:
        rows = parse_csv(csv_text)
    except CsvFormatError as exc:
        raise ValidationFailed(str(exc), code="CSV_INVALID") from exc
    return plan_import(rows, repo.load_snapshot(db), create_categories=create_categories)


def plan_to_out(plan: ImportPlan, *, dry_run: bool, codes: list[str] | None) -> ProductImportOut:
    new_codes: list[str | None] = list(codes) if codes else [None] * len(plan.new_products)
    return ProductImportOut(
        dry_run=dry_run,
        rows_read=plan.rows_read,
        new_categories=[ImportCategoryOut(code=c.code, name=c.name) for c in plan.new_categories],
        new_subcategories=[
            ImportSubCategoryOut(category_code=s.category_code, code=s.code, name=s.name)
            for s in plan.new_subcategories
        ],
        new_products=[
            ImportProductOut(
                row_no=p.row_no,
                code=code,
                name=p.name,
                category_code=p.category_code,
                subcategory_code=p.subcategory_code,
            )
            for code, p in zip(new_codes, plan.new_products, strict=True)
        ],
        updates=[
            ImportUpdateOut(
                row_no=u.row_no,
                product_code=u.product_code,
                name=u.name,
                from_category=u.from_category,
                to_category=u.to_category,
                from_subcategory=u.from_subcategory,
                to_subcategory=u.to_subcategory,
            )
            for u in plan.updates
        ],
        category_changes=sum(1 for u in plan.updates if u.category_changed),
        unchanged=plan.unchanged,
        duplicates_in_file=plan.duplicates_in_file,
        exceptions=[
            ImportExceptionOut(
                row_no=e.row_no,
                item_name=e.item_name,
                category=e.category,
                sub_category=e.sub_category,
                reason=e.reason,
            )
            for e in plan.exceptions
        ],
    )


class MastersService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    # ---------------------------------------------------------------- categories ----------------
    def list_categories(self, user: CurrentUser) -> list[CategoryOut]:
        with self._uow.transaction(user.id) as session:
            return [CategoryOut.model_validate(r) for r in repo.list_categories(session)]

    # ---------------------------------------------------------------- sub-categories ------------
    def list_subcategories(
        self, user: CurrentUser, category_id: UUID | None, include_inactive: bool
    ) -> list[SubCategoryOut]:
        with self._uow.transaction(user.id) as session:
            rows = repo.list_subcategories(session, category_id, include_inactive)
            return [SubCategoryOut.model_validate(r) for r in rows]

    def create_subcategory(
        self, user: CurrentUser, payload: SubCategoryCreate, idem: IdempotencyKey
    ) -> IdempotentResult:
        name = " ".join(payload.name.split())
        code = payload.code or code_from_name(name)
        if not CODE_PATTERN.fullmatch(code):
            raise ValidationFailed(
                "Cannot derive a code from this name; enter a code (A-Z, 0-9, _)",
                code="SUBCATEGORY_CODE_REQUIRED",
            )
        with self._uow.transaction(user.id) as session:

            def command() -> tuple[int, SubCategoryOut]:
                category = repo.get_category(session, payload.category_id)
                if category is None:
                    raise NotFound("Product category not found", code="CATEGORY_NOT_FOUND")
                if not category["is_active"]:
                    raise Conflict(
                        f"Category {category['code']} is inactive", code="CATEGORY_INACTIVE"
                    )
                clash = repo.subcategory_clash(session, payload.category_id, code, name)
                if clash is not None:
                    raise Conflict(
                        f"A sub-category with this {clash} already exists in {category['code']}",
                        code="DUPLICATE_SUBCATEGORY",
                        details={"field": clash},
                    )
                new_id = repo.insert_subcategory(session, payload.category_id, code, name)
                row = repo.get_subcategory(session, new_id)
                assert row is not None  # noqa: S101 - just inserted in this transaction
                log.info("subcategory_created", category=category["code"], code=code)
                return 201, SubCategoryOut.model_validate(row)

            return run_idempotent(session, idem, user.id, command)

    def update_subcategory(
        self, user: CurrentUser, subcategory_id: UUID, payload: SubCategoryUpdate
    ) -> SubCategoryOut:
        with self._uow.transaction(user.id) as session:
            current = repo.get_subcategory(session, subcategory_id)
            if current is None:
                raise NotFound("Sub-category not found", code="SUBCATEGORY_NOT_FOUND")
            name = " ".join(payload.name.split()) if payload.name is not None else current["name"]
            if name != current["name"] and repo.subcategory_name_used(
                session, subcategory_id, name
            ):
                raise Conflict(
                    "Another sub-category of this category already has this name",
                    code="DUPLICATE_SUBCATEGORY",
                    details={"field": "name"},
                )
            is_active = payload.is_active if payload.is_active is not None else current["is_active"]
            repo.update_subcategory(session, subcategory_id, name=name, is_active=is_active)
            row = repo.get_subcategory(session, subcategory_id)
            assert row is not None  # noqa: S101
            return SubCategoryOut.model_validate(row)

    # ---------------------------------------------------------------- products ------------------
    def list_products(
        self,
        user: CurrentUser,
        *,
        q: str | None,
        category_id: UUID | None,
        subcategory_id: UUID | None,
        without_subcategory: bool,
        include_inactive: bool,
        page: int,
        page_size: int,
    ) -> Page[ProductOut]:
        with self._uow.transaction(user.id) as session:
            rows, total = repo.list_products(
                session,
                q=(q or "").strip() or None,
                category_id=category_id,
                subcategory_id=subcategory_id,
                without_subcategory=without_subcategory,
                include_inactive=include_inactive,
                limit=page_size,
                offset=(page - 1) * page_size,
            )
        return Page[ProductOut](
            items=[ProductOut.model_validate(r) for r in rows],
            total=total,
            page=page,
            page_size=page_size,
        )

    def update_product(
        self, user: CurrentUser, product_id: UUID, payload: ProductUpdate
    ) -> ProductOut:
        sent = payload.model_fields_set
        with self._uow.transaction(user.id) as session:
            current = repo.get_product(session, product_id)
            if current is None:
                raise NotFound("Product not found", code="PRODUCT_NOT_FOUND")

            category_id: UUID = current["category_id"]
            if "category_id" in sent:
                if payload.category_id is None:
                    raise ValidationFailed("category_id cannot be empty", code="CATEGORY_REQUIRED")
                category = repo.get_category(session, payload.category_id)
                if category is None:
                    raise NotFound("Product category not found", code="CATEGORY_NOT_FOUND")
                if not category["is_active"] and payload.category_id != current["category_id"]:
                    raise Conflict(
                        f"Category {category['code']} is inactive", code="CATEGORY_INACTIVE"
                    )
                category_id = payload.category_id

            subcategory_id: UUID | None = current["subcategory_id"]
            if "subcategory_id" in sent:
                subcategory_id = payload.subcategory_id
            elif category_id != current["category_id"]:
                # Changing the category without naming a sub-category clears the old one.
                subcategory_id = None

            if subcategory_id is not None:
                sub = repo.get_subcategory(session, subcategory_id)
                if sub is None:
                    raise NotFound("Sub-category not found", code="SUBCATEGORY_NOT_FOUND")
                # AMD-07 (also DB-enforced by products_subcategory_in_category_fkey).
                if sub["category_id"] != category_id:
                    raise ValidationFailed(
                        "AMD-07: the sub-category must belong to the product's category",
                        code="SUBCATEGORY_CATEGORY_MISMATCH",
                        details={"subcategory_id": ["Not a sub-category of the chosen category"]},
                    )
                if not sub["is_active"] and subcategory_id != current["subcategory_id"]:
                    raise Conflict(
                        f"Sub-category {sub['code']} is inactive", code="SUBCATEGORY_INACTIVE"
                    )

            name = current["name"]
            if "name" in sent and payload.name is not None:
                name = " ".join(payload.name.split())
                if name.upper() != " ".join(current["name"].split()).upper() and (
                    repo.product_name_used(session, product_id, name)
                ):
                    raise Conflict(
                        "Another product already has this name",
                        code="DUPLICATE_PRODUCT_NAME",
                        details={"field": "name"},
                    )

            uom = current["uom"]
            if "uom" in sent:
                if payload.uom is None or not payload.uom.strip():
                    raise ValidationFailed("UOM cannot be empty", code="UOM_REQUIRED")
                uom = payload.uom.strip()
            hsn = payload.hsn_code if "hsn_code" in sent else current["hsn_code"]
            is_active = current["is_active"]
            if "is_active" in sent and payload.is_active is not None:
                is_active = payload.is_active

            repo.update_product(
                session,
                product_id,
                name=name,
                category_id=category_id,
                subcategory_id=subcategory_id,
                uom=uom,
                hsn_code=hsn,
                is_active=is_active,
            )
            row = repo.get_product(session, product_id)
            assert row is not None  # noqa: S101
            return ProductOut.model_validate(row)

    # ---------------------------------------------------------------- CSV import ----------------
    def preview_import(self, user: CurrentUser, payload: ProductImportIn) -> ProductImportOut:
        """Dry run: the full plan, nothing written."""
        with self._uow.transaction(user.id) as session:
            plan = build_plan(
                session, payload.csv_text, create_categories=payload.create_categories
            )
            return plan_to_out(plan, dry_run=True, codes=None)

    def run_import(
        self, user: CurrentUser, payload: ProductImportIn, idem: IdempotencyKey
    ) -> IdempotentResult:
        """Apply the import in one transaction (rule f); a replayed key returns the first result."""
        with self._uow.transaction(user.id) as session:

            def command() -> tuple[int, ProductImportOut]:
                repo.lock_product_import(session)
                plan = build_plan(
                    session, payload.csv_text, create_categories=payload.create_categories
                )
                codes = repo.apply_import(session, plan)
                log.info(
                    "product_import_applied",
                    new_categories=len(plan.new_categories),
                    new_subcategories=len(plan.new_subcategories),
                    new_products=len(plan.new_products),
                    updates=len(plan.updates),
                    exceptions=len(plan.exceptions),
                )
                return 200, plan_to_out(plan, dry_run=False, codes=codes)

            return run_idempotent(session, idem, user.id, command)
