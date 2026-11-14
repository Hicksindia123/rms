"""Item field profiles — admin-configurable Categorisation / Department / Action / Item-count
fields per Category -> Sub-Category -> Product (change plan 2026-11-12 Phase 4).

AMD-10: most specific scope with an assignment for a group wins (PRODUCT > SUBCATEGORY >
CATEGORY). The rule lives in the DB function `rms_private.resolve_item_field_profile_for_scope`;
this service only calls it. AMD-11: Packaging / Container / User Manual are the ITEM_COUNT group.
AMD-16: the ACTION group is the action catalogue for rm_item_actions.
G-18: codes and groups are immutable; every committed change creates a profile version (DB).
G-05: the hazard behaviour of a field is locked (DB trigger; the API never edits system_behavior).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog

from app.core.db import UnitOfWork
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.idempotency import IdempotencyKey, IdempotentResult, run_idempotent
from app.core.security import CurrentUser
from app.modules.config.field_profiles import repository as repo
from app.modules.config.field_profiles.schemas import (
    FIELD_GROUPS,
    AssignmentOut,
    FieldCreate,
    FieldFlags,
    FieldOut,
    FieldUpdate,
    GroupProfileOut,
    OverrideIn,
    ResolvedField,
    ResolvedProfileOut,
    ScopeIn,
    ScopeProfileOut,
    ScopeRef,
    VersionOut,
)
from app.modules.masters.product_import import CODE_PATTERN, code_from_name

log = structlog.get_logger(__name__)

# Which flags a group may carry (mirrors the CHECK constraints of item_field_library).
_ALLOWED_FLAGS: dict[str, set[str]] = {
    "CATEGORISATION": {"is_wastage", "returns_to_routing"},
    "DEPARTMENT": {"is_wastage", "returns_to_routing"},
    "ACTION": {"requires_cn", "requires_challan"},
    "ITEM_COUNT": set(),
}
_FLAG_NAMES = ("is_wastage", "returns_to_routing", "requires_cn", "requires_challan")


def _check_flags(field_group: str, flags: FieldFlags) -> None:
    allowed = _ALLOWED_FLAGS[field_group]
    for name in _FLAG_NAMES:
        value = getattr(flags, name)
        if value and name not in allowed:
            raise ValidationFailed(
                f"Flag {name} does not apply to {field_group} fields",
                code="FLAG_NOT_ALLOWED",
                details={"flag": name, "field_group": field_group},
            )


def _resolved(row: dict[str, Any]) -> ResolvedField:
    return ResolvedField.model_validate(row)


class _Scope:
    """A validated scope chain: category [-> sub-category] [-> product]."""

    def __init__(
        self,
        category: dict[str, Any],
        subcategory: dict[str, Any] | None,
        product: dict[str, Any] | None,
    ) -> None:
        self.category = category
        self.subcategory = subcategory
        self.product = product

    @property
    def scope_type(self) -> str:
        if self.product is not None:
            return "PRODUCT"
        if self.subcategory is not None:
            return "SUBCATEGORY"
        return "CATEGORY"

    @property
    def scope_id(self) -> UUID:
        row = self.product or self.subcategory or self.category
        return UUID(str(row["id"]))

    @property
    def subcategory_id(self) -> UUID | None:
        return UUID(str(self.subcategory["id"])) if self.subcategory else None

    @property
    def product_id(self) -> UUID | None:
        return UUID(str(self.product["id"])) if self.product else None

    @property
    def category_id(self) -> UUID:
        return UUID(str(self.category["id"]))

    def refs(self) -> list[ScopeRef]:
        out = [_ref("CATEGORY", self.category)]
        if self.subcategory:
            out.append(_ref("SUBCATEGORY", self.subcategory))
        if self.product:
            out.append(_ref("PRODUCT", self.product))
        return out

    def parent(self) -> tuple[UUID, UUID | None, UUID | None] | None:
        """The scope chain one level up (None at CATEGORY scope)."""
        if self.product is not None:
            return self.category_id, self.subcategory_id, None
        if self.subcategory is not None:
            return self.category_id, None, None
        return None


def _ref(scope_type: str, row: dict[str, Any]) -> ScopeRef:
    return ScopeRef.model_validate(
        {"scope_type": scope_type, "scope_id": row["id"], "code": row["code"], "name": row["name"]}
    )


class FieldProfileService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    # --- library -----------------------------------------------------------------------------
    def list_fields(
        self, user: CurrentUser, field_group: str | None, include_inactive: bool
    ) -> list[FieldOut]:
        with self._uow.transaction(user.id) as session:
            rows = repo.list_fields(session, field_group, include_inactive)
            return [FieldOut.model_validate(r) for r in rows]

    def create_field(
        self, user: CurrentUser, payload: FieldCreate, idem: IdempotencyKey
    ) -> IdempotentResult:
        label = " ".join(payload.label.split())
        code = payload.code or code_from_name(label)
        if not CODE_PATTERN.fullmatch(code):
            raise ValidationFailed(
                "Cannot derive a code from this label; enter a code (A-Z, 0-9, _)",
                code="FIELD_CODE_REQUIRED",
            )
        _check_flags(payload.field_group, payload)

        with self._uow.transaction(user.id) as session:

            def command() -> tuple[int, FieldOut]:
                if repo.field_code_exists(session, payload.field_group, code):
                    raise Conflict(
                        f"A {payload.field_group} field with code {code} already exists",
                        code="DUPLICATE_CODE",
                        details={"code": code},
                    )
                sort_order = (
                    payload.sort_order
                    if payload.sort_order is not None
                    else repo.next_sort_order(session, payload.field_group)
                )
                new_id = repo.insert_field(
                    session,
                    {
                        "field_group": payload.field_group,
                        "code": code,
                        "label": label,
                        "description": payload.description,
                        "sort_order": sort_order,
                        "is_wastage": bool(payload.is_wastage),
                        "returns_to_routing": bool(payload.returns_to_routing),
                        "requires_cn": bool(payload.requires_cn),
                        "requires_challan": bool(payload.requires_challan),
                    },
                )
                row = repo.get_field(session, new_id)
                if row is None:
                    raise NotFound("Item field not found after insert")
                repo.log_config_change(
                    session,
                    entity_type="item_field",
                    entity_id=str(new_id),
                    action="ITEM_FIELD_CREATE",
                    before=None,
                    after=row,
                    reason="Created item field (AMD-10)",
                )
                log.info("item_field_created", field_group=payload.field_group, code=code)
                return 201, FieldOut.model_validate(row)

            return run_idempotent(session, idem, user.id, command)

    def update_field(self, user: CurrentUser, field_id: UUID, payload: FieldUpdate) -> FieldOut:
        with self._uow.transaction(user.id) as session:
            current = repo.get_field(session, field_id)
            if current is None:
                raise NotFound("Item field not found", code="FIELD_NOT_FOUND")
            _check_flags(current["field_group"], payload)
            data = payload.model_dump(exclude_unset=True, exclude={"reason"})
            if "label" in data and data["label"] is not None:
                data["label"] = " ".join(data["label"].split())
            for key in ("label", "sort_order", "is_active", *_FLAG_NAMES):
                if key in data and data[key] is None:
                    del data[key]
            if not data:
                return FieldOut.model_validate(current)
            repo.update_field(session, field_id, data)
            row = repo.get_field(session, field_id)
            if row is None:
                raise NotFound("Item field not found", code="FIELD_NOT_FOUND")
            repo.log_config_change(
                session,
                entity_type="item_field",
                entity_id=str(field_id),
                action="ITEM_FIELD_UPDATE",
                before=current,
                after=row,
                reason=payload.reason or "Item field updated",
            )
            return FieldOut.model_validate(row)

    # --- scope profiles ----------------------------------------------------------------------
    def _load_scope(self, session: Any, scope: ScopeIn) -> _Scope:
        category = repo.get_category(session, scope.category_id)
        if category is None:
            raise NotFound("Product category not found", code="CATEGORY_NOT_FOUND")
        subcategory = None
        product = None
        if scope.product_id is not None:
            product = repo.get_product(session, scope.product_id)
            if product is None:
                raise NotFound("Product not found", code="PRODUCT_NOT_FOUND")
            if product["category_id"] != category["id"]:
                raise ValidationFailed(
                    "The product does not belong to the selected category", code="SCOPE_MISMATCH"
                )
            if (
                scope.subcategory_id is not None
                and product["subcategory_id"] != scope.subcategory_id
            ):
                raise ValidationFailed(
                    "The product does not belong to the selected sub-category",
                    code="SCOPE_MISMATCH",
                )
            # The product's own sub-category is always part of its chain (AMD-07 hierarchy).
            if product["subcategory_id"] is not None:
                subcategory = repo.get_subcategory(session, product["subcategory_id"])
        elif scope.subcategory_id is not None:
            subcategory = repo.get_subcategory(session, scope.subcategory_id)
            if subcategory is None:
                raise NotFound("Product sub-category not found", code="SUBCATEGORY_NOT_FOUND")
            if subcategory["category_id"] != category["id"]:
                raise ValidationFailed(
                    "The sub-category does not belong to the selected category",
                    code="SCOPE_MISMATCH",
                )
        return _Scope(category, subcategory, product)

    def _scope_profile(self, session: Any, scope: _Scope) -> ScopeProfileOut:
        effective = repo.resolve_scope(
            session, scope.category_id, scope.subcategory_id, scope.product_id
        )
        parent = scope.parent()
        inherited = repo.resolve_scope(session, *parent) if parent else []
        own = repo.list_scope_assignments(session, scope.scope_type, scope.scope_id)
        version = repo.latest_version(session)

        names = {r.scope_id: r for r in scope.refs()}
        groups: list[GroupProfileOut] = []
        for group in FIELD_GROUPS:
            own_rows = [r for r in own if r["field_group"] == group]
            inh_rows = [r for r in inherited if r["field_group"] == group]
            eff_rows = [r for r in effective if r["field_group"] == group]
            source = names.get(inh_rows[0]["source_scope_id"]) if inh_rows else None
            groups.append(
                GroupProfileOut(
                    field_group=group,
                    overridden=bool(own_rows),
                    own=[AssignmentOut.model_validate(r) for r in own_rows],
                    inherited_from=source,
                    inherited=[_resolved(r) for r in inh_rows],
                    effective=[_resolved(r) for r in eff_rows],
                )
            )
        return ScopeProfileOut(
            scope=scope.refs()[-1],
            chain=scope.refs(),
            version_id=version["id"] if version else None,
            version_no=version["version_no"] if version else None,
            groups=groups,
        )

    def get_scope_profile(self, user: CurrentUser, scope_in: ScopeIn) -> ScopeProfileOut:
        with self._uow.transaction(user.id) as session:
            scope = self._load_scope(session, scope_in)
            return self._scope_profile(session, scope)

    def set_override(
        self, user: CurrentUser, field_group: str, payload: OverrideIn
    ) -> ScopeProfileOut:
        """Replace this scope's assignments for one group (AMD-10). An empty list removes the
        override (the scope inherits again). Unchanged rows are left alone, so a repeated PUT
        writes nothing and creates no new version (idempotent by content)."""
        with self._uow.transaction(user.id) as session:
            scope = self._load_scope(session, payload)
            fields = repo.get_fields(session, [f.field_id for f in payload.fields])
            for f in payload.fields:
                lib = fields.get(f.field_id)
                if lib is None:
                    raise NotFound(
                        "Item field not found",
                        code="FIELD_NOT_FOUND",
                        details={"field_id": str(f.field_id)},
                    )
                if lib["field_group"] != field_group:
                    raise ValidationFailed(
                        f"{lib['code']} is a {lib['field_group']} field, not {field_group}",
                        code="FIELD_GROUP_MISMATCH",
                    )
                if f.is_included and not lib["is_active"]:
                    raise ValidationFailed(
                        f"{lib['code']} is inactive; activate it in the library first",
                        code="FIELD_INACTIVE",
                    )

            existing = {
                r["field_id"]: r
                for r in repo.list_scope_assignments(
                    session, scope.scope_type, scope.scope_id, field_group
                )
            }
            wanted = {f.field_id: f for f in payload.fields}
            removed = [r["id"] for fid, r in existing.items() if fid not in wanted]
            repo.delete_assignments(session, removed)
            changed = bool(removed)
            for fid, f in wanted.items():
                cur = existing.get(fid)
                if cur is None:
                    repo.insert_assignment(
                        session,
                        field_id=fid,
                        field_group=field_group,
                        scope_type=scope.scope_type,
                        scope_id=scope.scope_id,
                        is_included=f.is_included,
                        sort_order=f.sort_order,
                    )
                    changed = True
                elif (cur["is_included"], cur["sort_order"]) != (f.is_included, f.sort_order):
                    repo.update_assignment(session, cur["id"], f.is_included, f.sort_order)
                    changed = True
            if changed:
                repo.log_config_change(
                    session,
                    entity_type="item_field_profile",
                    entity_id=f"{scope.scope_type}:{scope.scope_id}:{field_group}",
                    action="ITEM_FIELD_PROFILE_OVERRIDE"
                    if wanted
                    else "ITEM_FIELD_PROFILE_INHERIT",
                    before=[
                        {
                            "code": r["code"],
                            "is_included": r["is_included"],
                            "sort": r["sort_order"],
                        }
                        for r in existing.values()
                    ],
                    after=[
                        {
                            "code": fields[f.field_id]["code"],
                            "is_included": f.is_included,
                            "sort": f.sort_order,
                        }
                        for f in payload.fields
                    ],
                    reason=payload.reason or "Item field profile changed (AMD-10)",
                )
                log.info(
                    "item_field_profile_changed",
                    scope_type=scope.scope_type,
                    field_group=field_group,
                    fields=len(wanted),
                )
        # The new version is created at commit (deferred DB trigger): read it back afterwards.
        with self._uow.transaction(user.id) as session:
            return self._scope_profile(session, self._load_scope(session, payload))

    # --- resolution & history ----------------------------------------------------------------
    def resolve_product(
        self, user: CurrentUser, product_id: UUID, version_id: UUID | None
    ) -> ResolvedProfileOut:
        with self._uow.transaction(user.id) as session:
            product = repo.get_product(session, product_id)
            if product is None:
                raise NotFound("Product not found", code="PRODUCT_NOT_FOUND")
            if version_id is not None and not repo.version_exists(session, version_id):
                raise NotFound("Profile version not found", code="PROFILE_VERSION_NOT_FOUND")
            rows = repo.resolve_product(session, product_id, version_id)
            version_id_out: UUID | None
            version_no_out: int | None
            if rows:
                version_id_out = rows[0]["profile_version_id"]
                version_no_out = rows[0]["profile_version_no"]
            elif version_id is not None:
                version_id_out, version_no_out = version_id, repo.version_no(session, version_id)
            else:
                latest = repo.latest_version(session)
                version_id_out = latest["id"] if latest else None
                version_no_out = latest["version_no"] if latest else None
            groups: dict[str, list[ResolvedField]] = {g: [] for g in FIELD_GROUPS}
            for r in rows:
                groups[r["field_group"]].append(_resolved(r))
            return ResolvedProfileOut(
                product_id=product["id"],
                product_code=product["code"],
                product_name=product["name"],
                version_id=version_id_out,
                version_no=version_no_out,
                groups=groups,
            )

    def list_versions(self, user: CurrentUser, limit: int) -> list[VersionOut]:
        with self._uow.transaction(user.id) as session:
            return [VersionOut.model_validate(r) for r in repo.list_versions(session, limit)]
