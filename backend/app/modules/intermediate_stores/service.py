"""Intermediate Stores service (Phase P1, DEC-60 / DEC-61).

Rules:
 * A store has an immutable code, its own role (ISTORE_<code>) and its own FUNCTIONAL stock location
   (ISTORE_<code>). Creating a store creates all three in one transaction; the new role copies the
   permission grants and menu of the current default store's role, so it works like the others.
 * Exactly one active default store takes every product no mapping covers. The default cannot be
   switched off or deactivated; it moves by setting another active store as default. The DB
   repeats these rules (partial unique index, CHECK, deferred trigger).
 * Stores are never deleted; they are deactivated (their mappings are then skipped).
 * A category / sub-category belongs to at most one store. Saving a mapping that takes one from
   another store is a conflict unless the admin confirms the move (reassign).
 * Guard STORE_MAPPING_MISSING: `require_stores_for_products` is called by transfer-slip generation
   (P5) inside its transaction; it checks in the service and then runs the DB guard.
 * Every change is written to config_change_log with before / after.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy.orm import Session

from app.core.db import UnitOfWork
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.security import CurrentUser
from app.modules.intermediate_stores import repository as repo
from app.modules.intermediate_stores.schemas import (
    LocationRef,
    MappingCategory,
    MappingSubcategory,
    RoleRef,
    StoreBrief,
    StoreCreate,
    StoreMappingIn,
    StoreMappingOut,
    StoreOut,
    StoreRef,
    StoreUpdate,
    StoreUser,
)
from app.shared.change_log import log_change

log = structlog.get_logger("rms.intermediate_stores")

ROLE_PREFIX = "ISTORE_"
# Department of every Intermediate Store location (same as the legacy INTERMEDIATE_STORE location).
STORE_DEPARTMENT_CODE = "INTERMEDIATE_STORE"


def _reason(value: str | None) -> str | None:
    return (value or "").strip() or None


def _store_out(row: dict[str, Any], users: list[dict[str, Any]]) -> StoreOut:
    return StoreOut(
        id=row["id"],
        code=row["code"],
        name=row["name"],
        is_default=row["is_default"],
        is_active=row["is_active"],
        sort_order=row["sort_order"],
        role=RoleRef(id=row["role_id"], code=row["role_code"], name=row["role_name"]),
        location=LocationRef(
            id=row["location_id"], code=row["location_code"], name=row["location_name"]
        ),
        category_count=row["category_count"],
        subcategory_count=row["subcategory_count"],
        users=[
            StoreUser(
                id=u["id"], full_name=u["full_name"], email=u["email"], is_active=u["is_active"]
            )
            for u in users
            if u["store_id"] == row["id"]
        ],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _snapshot(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": row["code"],
        "name": row["name"],
        "is_default": row["is_default"],
        "is_active": row["is_active"],
        "sort_order": row["sort_order"],
    }


def _ref(row: dict[str, Any]) -> StoreRef:
    return StoreRef(id=row["id"], code=row["code"], name=row["name"], is_active=row["is_active"])


def require_stores_for_products(session: Session, product_ids: Sequence[UUID]) -> dict[UUID, UUID]:
    """Guard STORE_MAPPING_MISSING (DEC-61): the store of every product, or a 409.

    Runs inside the caller's transaction (transfer-slip generation, P5). The service check gives a
    clear error; the DB guard runs as well so the rule holds even if this check is bypassed.
    """
    rows = repo.resolve_products(session, product_ids)
    unknown = {str(p) for p in product_ids} - {str(r["product_id"]) for r in rows}
    if unknown:
        raise NotFound(
            "Product not found",
            code="PRODUCT_NOT_FOUND",
            details={"product_ids": sorted(unknown)},
        )
    missing = [r["product_code"] for r in rows if r["store_id"] is None]
    if missing:
        log.warning("store_mapping_missing", products=missing)
        raise Conflict(
            "No Intermediate Store is mapped for these products and there is no default store",
            code="STORE_MAPPING_MISSING",
            details={"product_codes": missing},
        )
    repo.assert_store_for_products(session, product_ids)
    return {r["product_id"]: r["store_id"] for r in rows}


class IntermediateStoreService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    # --- read ---------------------------------------------------------------------------------

    def list_stores(self, actor: CurrentUser) -> list[StoreOut]:
        with self._uow.transaction(actor.id) as session:
            users = repo.store_users(session)
            return [_store_out(r, users) for r in repo.list_stores(session)]

    def my_stores(self, actor: CurrentUser) -> list[StoreBrief]:
        with self._uow.transaction(actor.id) as session:
            return [StoreBrief(**r) for r in repo.user_stores(session, actor.id)]

    def get_mapping(self, actor: CurrentUser, store_id: UUID) -> StoreMappingOut:
        with self._uow.transaction(actor.id) as session:
            return self._mapping_out(session, store_id)

    # --- write --------------------------------------------------------------------------------

    def create_store(self, actor: CurrentUser, payload: StoreCreate) -> StoreOut:
        role_code = f"{ROLE_PREFIX}{payload.code}"
        with self._uow.transaction(actor.id) as session:
            repo.lock_stores(session)
            if repo.store_code_taken(session, payload.code):
                raise Conflict("A store with this code exists", code="STORE_CODE_TAKEN")
            if repo.role_code_taken(session, role_code) or repo.location_code_taken(
                session, role_code
            ):
                raise Conflict(
                    f"The role or location code {role_code} is already used",
                    code="STORE_CODE_TAKEN",
                    details={"role_code": role_code},
                )
            if repo.store_name_taken(session, payload.name):
                raise Conflict("A store with this name exists", code="STORE_NAME_TAKEN")

            template = repo.default_store(session)
            role_id = repo.insert_role(
                session,
                role_code,
                payload.name,
                f"DEC-61: users of {payload.name}",
            )
            if template is not None:
                repo.copy_role_setup(session, template["role_id"], role_id)
            location_id = repo.insert_location(
                session, role_code, payload.name, role_id, STORE_DEPARTMENT_CODE
            )
            store_id = repo.insert_store(
                session,
                code=payload.code,
                name=payload.name,
                role_id=role_id,
                location_id=location_id,
                sort_order=payload.sort_order,
            )
            # The first store ever is the default (DEC-61: exactly one while any store exists).
            if payload.is_default or template is None:
                repo.clear_default(session)
                repo.update_store(session, store_id, {"is_default": True})
            row = repo.get_store(session, store_id)
            assert row is not None  # noqa: S101 - inserted in this transaction
            log_change(
                session,
                entity_type="intermediate_store",
                entity_id=store_id,
                action="INTERMEDIATE_STORE_CREATED",
                before=None,
                after={
                    **_snapshot(row),
                    "role_code": role_code,
                    "location_code": role_code,
                    "role_template": template["role_code"] if template else None,
                },
                reason=_reason(payload.reason),
            )
            users = repo.store_users(session)
        log.info("intermediate_store_created", code=payload.code, by=str(actor.id))
        return _store_out(row, users)

    def update_store(self, actor: CurrentUser, store_id: UUID, payload: StoreUpdate) -> StoreOut:
        sent = payload.model_fields_set
        with self._uow.transaction(actor.id) as session:
            repo.lock_stores(session)
            before = repo.get_store(session, store_id, for_update=True)
            if before is None:
                raise NotFound("Intermediate Store not found", code="STORE_NOT_FOUND")

            fields: dict[str, Any] = {}
            if "name" in sent and payload.name is not None and payload.name != before["name"]:
                if repo.store_name_taken(session, payload.name, exclude_id=store_id):
                    raise Conflict("A store with this name exists", code="STORE_NAME_TAKEN")
                fields["name"] = payload.name
            if "sort_order" in sent and payload.sort_order is not None:
                fields["sort_order"] = payload.sort_order

            is_active = before["is_active"]
            if "is_active" in sent and payload.is_active is not None:
                is_active = payload.is_active
                fields["is_active"] = is_active

            make_default = "is_default" in sent and payload.is_default is not None
            if make_default and payload.is_default is False and before["is_default"]:
                raise ValidationFailed(
                    "Set another store as the default instead; one default store is required",
                    code="STORE_DEFAULT_REQUIRED",
                )
            becomes_default = bool(make_default and payload.is_default and not before["is_default"])
            if (before["is_default"] or becomes_default) and not is_active:
                raise Conflict(
                    "The default store cannot be deactivated; make another store the default first",
                    code="STORE_IS_DEFAULT",
                )

            if becomes_default:
                repo.clear_default(session)
                fields["is_default"] = True
            repo.update_store(session, store_id, fields)
            if "name" in fields:
                # The store's role and location carry the store name.
                repo.rename_role(session, before["role_id"], fields["name"])
                repo.rename_location(session, before["location_id"], fields["name"])

            after = repo.get_store(session, store_id)
            assert after is not None  # noqa: S101
            if fields:
                log_change(
                    session,
                    entity_type="intermediate_store",
                    entity_id=store_id,
                    action="INTERMEDIATE_STORE_UPDATED",
                    before=_snapshot(before),
                    after=_snapshot(after),
                    reason=_reason(payload.reason),
                )
            users = repo.store_users(session)
        return _store_out(after, users)

    def replace_mapping(
        self, actor: CurrentUser, store_id: UUID, payload: StoreMappingIn
    ) -> StoreMappingOut:
        cats = list(dict.fromkeys(payload.category_ids))
        subs = list(dict.fromkeys(payload.subcategory_ids))
        with self._uow.transaction(actor.id) as session:
            repo.lock_stores(session)
            store = repo.get_store(session, store_id, for_update=True)
            if store is None:
                raise NotFound("Intermediate Store not found", code="STORE_NOT_FOUND")
            unknown_c = {str(c) for c in cats} - {
                str(c) for c in repo.existing_category_ids(session, cats)
            }
            unknown_s = {str(s) for s in subs} - {
                str(s) for s in repo.existing_subcategory_ids(session, subs)
            }
            if unknown_c or unknown_s:
                raise ValidationFailed(
                    "Unknown category or sub-category",
                    code="UNKNOWN_CATEGORY",
                    details={
                        "category_ids": sorted(unknown_c),
                        "subcategory_ids": sorted(unknown_s),
                    },
                )
            conflicts = repo.mapped_elsewhere(session, store_id, cats, subs)
            if conflicts and not payload.reassign:
                raise Conflict(
                    "Some categories are mapped to another store",
                    code="STORE_MAPPING_CONFLICT",
                    details={
                        "conflicts": [
                            {
                                "kind": c["kind"],
                                "id": str(c["id"]),
                                "code": c["code"],
                                "name": c["name"],
                                "store_code": c["store_code"],
                                "store_name": c["store_name"],
                            }
                            for c in conflicts
                        ]
                    },
                )
            before_c, before_s = repo.store_mapping(session, store_id)
            repo.replace_store_mapping(session, store_id, cats, subs)
            after_c, after_s = repo.store_mapping(session, store_id)
            if (before_c, before_s) != (after_c, after_s) or conflicts:
                log_change(
                    session,
                    entity_type="intermediate_store_mapping",
                    entity_id=store_id,
                    action="INTERMEDIATE_STORE_MAPPING_REPLACED",
                    before={
                        "store": store["code"],
                        "category_ids": [str(c) for c in before_c],
                        "subcategory_ids": [str(s) for s in before_s],
                    },
                    after={
                        "store": store["code"],
                        "category_ids": [str(c) for c in after_c],
                        "subcategory_ids": [str(s) for s in after_s],
                        "moved_from_other_stores": [
                            f"{c['code']}@{c['store_code']}" for c in conflicts
                        ],
                    },
                    reason=_reason(payload.reason),
                )
            out = self._mapping_out(session, store_id)
        log.info("intermediate_store_mapping_replaced", store=store["code"], by=str(actor.id))
        return out

    # --- helpers ------------------------------------------------------------------------------

    def _mapping_out(self, session: Session, store_id: UUID) -> StoreMappingOut:
        store = repo.get_store(session, store_id)
        if store is None:
            raise NotFound("Intermediate Store not found", code="STORE_NOT_FOUND")
        default = repo.default_store(session)
        cats, subs = repo.store_mapping(session, store_id)

        def store_ref(r: dict[str, Any]) -> StoreRef | None:
            if r["store_id"] is None:
                return None
            return StoreRef(
                id=r["store_id"],
                code=r["store_code"],
                name=r["store_name"],
                is_active=r["store_is_active"],
            )

        rows = repo.mapping_tree(session)
        subs_by_cat: dict[UUID, list[MappingSubcategory]] = {}
        for r in rows:
            if r["kind"] == "S":
                subs_by_cat.setdefault(r["category_id"], []).append(
                    MappingSubcategory(
                        id=r["id"],
                        code=r["code"],
                        name=r["name"],
                        is_active=r["is_active"],
                        store=store_ref(r),
                    )
                )
        tree = [
            MappingCategory(
                id=r["id"],
                code=r["code"],
                name=r["name"],
                is_active=r["is_active"],
                store=store_ref(r),
                subcategories=subs_by_cat.get(r["id"], []),
            )
            for r in rows
            if r["kind"] == "C"
        ]
        return StoreMappingOut(
            store=_ref(store),
            default_store=_ref(default) if default else None,
            category_ids=cats,
            subcategory_ids=subs,
            tree=tree,
        )
