"""Dashboards service (prompt P4-01, master plan §10 "Dashboard widgets", §11).

* GET /dashboard: the layout of the caller's primary role (or `?role=` for multi-role users), with
  every widget the caller lacks a permission for removed (never returned, not even its title).
* GET /dashboard/widgets/{code}: the widget's data. 403 when the caller lacks its permission.
  Aggregate widgets are cached per user for `dashboard_cache_seconds` (0-60 s); live widgets
  (My tasks) are never cached.
* Admin layout CRUD (dashboards.configure); every change writes config_change_log.

Primary role [provisional, docs/DECISIONS.md P4-01]: there is no "primary role" column; the primary
role is the user's earliest-assigned role (user_roles.created_at, then code). A Super Admin's
primary dashboard is the SUPER_ADMIN layout. Any held role can be chosen with `?role=`.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog
from pydantic import ValidationError

from app.core.db import UnitOfWork
from app.core.errors import NotFound, PermissionDenied, ValidationFailed
from app.core.permissions import EffectivePermissions
from app.core.security import CurrentUser
from app.modules.dashboards import repository as repo
from app.modules.dashboards.registry import REGISTRY, WidgetContext, WidgetDef
from app.modules.dashboards.schemas import (
    DashboardOut,
    LayoutEntryOut,
    LayoutIn,
    LayoutWidgetOut,
    PermissionRef,
    RoleLayoutOut,
    RoleRef,
    WidgetCatalogueItem,
    WidgetDataOut,
)

log = structlog.get_logger("rms.dashboards")

SUPER_ADMIN_ROLE = "SUPER_ADMIN"
DEFAULT_POLL_SECONDS = 60
DEFAULT_CACHE_SECONDS = 30
MAX_CACHE_SECONDS = 60
MAX_CACHE_ENTRIES = 5000


# --- short server-side cache (per user + widget + params) ---------------------------------------
@dataclass(frozen=True, slots=True)
class _Entry:
    expires: float
    generated_at: datetime
    title: str
    data: dict[str, Any]


_cache: dict[tuple[str, str, str], _Entry] = {}
_cache_lock = threading.Lock()


def clear_widget_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _cache_get(key: tuple[str, str, str]) -> _Entry | None:
    now = time.monotonic()
    with _cache_lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        if entry.expires <= now:
            _cache.pop(key, None)
            return None
        return entry


def _cache_put(key: tuple[str, str, str], entry: _Entry) -> None:
    now = time.monotonic()
    with _cache_lock:
        if len(_cache) >= MAX_CACHE_ENTRIES:
            for k in [k for k, e in _cache.items() if e.expires <= now]:
                del _cache[k]
            if len(_cache) >= MAX_CACHE_ENTRIES:
                _cache.clear()
        _cache[key] = entry


def _int_setting(value: Any, default: int, lo: int, hi: int) -> int:
    return value if isinstance(value, int) and lo <= value <= hi else default


def _perm_refs(perms: list[tuple[str, str]] | tuple[tuple[str, str], ...]) -> list[PermissionRef]:
    return [PermissionRef(module=m, action=a) for m, a in perms]


class DashboardService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    # --- user dashboard -------------------------------------------------------------------------
    def dashboard(
        self, user: CurrentUser, perms: EffectivePermissions, role_code: str | None
    ) -> DashboardOut:
        with self._uow.transaction(user.id) as session:
            roles = repo.user_roles_in_order(session, user.id)
            if user.is_super_admin and not any(r["code"] == SUPER_ADMIN_ROLE for r in roles):
                sa = repo.role_by_code(session, SUPER_ADMIN_ROLE)
                if sa:
                    roles.insert(0, sa)
            elif user.is_super_admin:
                roles.sort(key=lambda r: r["code"] != SUPER_ADMIN_ROLE)
            available = [RoleRef(code=r["code"], name=r["name"]) for r in roles]
            poll = _int_setting(
                repo.get_setting(session, "dashboard_poll_seconds"), DEFAULT_POLL_SECONDS, 15, 600
            )
            if not roles:
                return DashboardOut(
                    role=None,
                    available_roles=[],
                    widgets=[],
                    hidden_widget_count=0,
                    poll_seconds=poll,
                )
            if role_code is None:
                selected = roles[0]
            else:
                match = [r for r in roles if r["code"] == role_code]
                if not match:
                    raise PermissionDenied(
                        f"You do not hold the role {role_code}",
                        code="ROLE_NOT_HELD",
                        details={"role": role_code},
                    )
                selected = match[0]
            layout = repo.layout_for_role(session, selected["id"])
            catalogue = {w["code"]: w for w in repo.widget_catalogue(session)}

        widgets: list[LayoutWidgetOut] = []
        hidden = 0
        for entry in (layout or {}).get("widgets") or []:
            code = entry.get("code")
            definition = REGISTRY.get(code) if isinstance(code, str) else None
            meta = catalogue.get(code) if isinstance(code, str) else None
            if definition is None or meta is None or not meta["is_active"]:
                continue
            if not definition.allowed(perms):
                hidden += 1
                continue
            widgets.append(
                LayoutWidgetOut(
                    code=definition.code,
                    title=meta["title"],
                    description=meta["description"],
                    size=entry.get("size") or meta["default_size"],
                    priority=definition.priority,
                    live=definition.live,
                )
            )
        return DashboardOut(
            role=RoleRef(code=selected["code"], name=selected["name"]),
            available_roles=available,
            widgets=widgets,
            hidden_widget_count=hidden,
            poll_seconds=poll,
        )

    def widget_data(
        self,
        user: CurrentUser,
        perms: EffectivePermissions,
        code: str,
        raw_params: dict[str, str],
    ) -> WidgetDataOut:
        definition = REGISTRY.get(code)
        if definition is None:
            raise NotFound(f"Unknown widget {code}", code="WIDGET_NOT_FOUND")
        if not definition.allowed(perms):
            raise PermissionDenied(
                f"You lack the permission for widget {code}",
                code="WIDGET_FORBIDDEN",
                details={"requires": [f"{m}.{a}" for m, a in definition.requires]},
            )
        try:
            params = definition.params.model_validate(raw_params)
        except ValidationError as exc:
            raise ValidationFailed(
                f"Invalid parameters for widget {code}",
                code="INVALID_WIDGET_PARAMS",
                details=[
                    {"loc": list(e.get("loc", ())), "msg": e.get("msg", "")} for e in exc.errors()
                ],
            ) from exc

        key = (code, str(user.id), params.model_dump_json())
        if not definition.live:
            hit = _cache_get(key)
            if hit is not None:
                return WidgetDataOut(
                    code=code,
                    title=hit.title,
                    generated_at=hit.generated_at,
                    cached=True,
                    data=hit.data,
                )

        with self._uow.transaction(user.id) as session:
            meta = {w["code"]: w for w in repo.widget_catalogue(session)}.get(code)
            ttl = _int_setting(
                repo.get_setting(session, "dashboard_cache_seconds"),
                DEFAULT_CACHE_SECONDS,
                0,
                MAX_CACHE_SECONDS,
            )
        if meta is None or not meta["is_active"]:
            raise NotFound(f"Widget {code} is not active", code="WIDGET_NOT_FOUND")

        started = time.monotonic()
        result = definition.query(WidgetContext(self._uow, user, perms), params)
        data = result.model_dump(mode="json")
        generated_at = datetime.now(UTC)
        log.debug("widget_computed", widget=code, ms=round((time.monotonic() - started) * 1000))
        if not definition.live and ttl > 0:
            _cache_put(key, _Entry(time.monotonic() + ttl, generated_at, meta["title"], data))
        return WidgetDataOut(
            code=code, title=meta["title"], generated_at=generated_at, cached=False, data=data
        )

    # --- admin ----------------------------------------------------------------------------------
    def catalogue(self, user: CurrentUser) -> list[WidgetCatalogueItem]:
        with self._uow.transaction(user.id) as session:
            rows = repo.widget_catalogue(session)
        out: list[WidgetCatalogueItem] = []
        for r in rows:
            definition = REGISTRY.get(r["code"])
            if definition is None:
                # A catalogue row without a query function is a deployment mismatch: report it.
                log.error("widget_without_registry_entry", widget=r["code"])
                continue
            out.append(
                WidgetCatalogueItem(
                    code=r["code"],
                    title=r["title"],
                    description=r["description"],
                    default_size=r["default_size"],
                    priority=definition.priority,
                    is_active=r["is_active"],
                    requires=_perm_refs(definition.requires),
                    params_schema=definition.params.model_json_schema(),
                )
            )
        return out

    def list_layouts(self, user: CurrentUser) -> list[RoleLayoutOut]:
        with self._uow.transaction(user.id) as session:
            return [self._role_layout(session, role) for role in repo.list_roles(session)]

    def get_layout(self, user: CurrentUser, role_code: str) -> RoleLayoutOut:
        with self._uow.transaction(user.id) as session:
            return self._role_layout(session, self._role(session, role_code))

    def put_layout(self, user: CurrentUser, role_code: str, payload: LayoutIn) -> RoleLayoutOut:
        codes = [w.code for w in payload.widgets]
        duplicates = sorted({c for c in codes if codes.count(c) > 1})
        if duplicates:
            raise ValidationFailed(
                "A widget can appear only once in a layout",
                code="DUPLICATE_WIDGET",
                details={"codes": duplicates},
            )
        with self._uow.transaction(user.id) as session:
            role = self._role(session, role_code)
            catalogue = {w["code"]: w for w in repo.widget_catalogue(session)}
            unknown = sorted(c for c in codes if c not in REGISTRY or c not in catalogue)
            if unknown:
                raise ValidationFailed(
                    "Unknown widget codes", code="UNKNOWN_WIDGET", details={"codes": unknown}
                )
            before = repo.layout_for_update(session, role["id"])
            after = [{"code": w.code, "size": w.size} for w in payload.widgets]
            after_json = json.dumps(after)
            repo.upsert_layout(session, role["id"], after_json)
            repo.insert_config_change(
                session,
                entity_type="role_dashboard_layout",
                entity_id=role["code"],
                action="UPDATE" if before else "CREATE",
                before_json=json.dumps(before["widgets"]) if before else None,
                after_json=after_json,
                reason=payload.reason.strip()
                if payload.reason and payload.reason.strip()
                else None,
            )
            log.info("dashboard_layout_saved", role=role["code"], widgets=len(after))
            return self._role_layout(session, role)

    def delete_layout(self, user: CurrentUser, role_code: str, reason: str | None) -> None:
        with self._uow.transaction(user.id) as session:
            role = self._role(session, role_code)
            before = repo.layout_for_update(session, role["id"])
            if before is None:
                raise NotFound(f"Role {role_code} has no dashboard layout", code="LAYOUT_NOT_FOUND")
            repo.delete_layout(session, role["id"])
            repo.insert_config_change(
                session,
                entity_type="role_dashboard_layout",
                entity_id=role["code"],
                action="DELETE",
                before_json=json.dumps(before["widgets"]),
                after_json=None,
                reason=reason.strip() if reason and reason.strip() else None,
            )
            log.info("dashboard_layout_deleted", role=role["code"])

    # --- helpers --------------------------------------------------------------------------------
    @staticmethod
    def _role(session: Any, role_code: str) -> dict[str, Any]:
        role = repo.role_by_code(session, role_code)
        if role is None:
            raise NotFound(f"Unknown role {role_code}", code="ROLE_NOT_FOUND")
        return role

    @staticmethod
    def _role_layout(session: Any, role: dict[str, Any]) -> RoleLayoutOut:
        layout = repo.layout_for_role(session, role["id"])
        catalogue = {w["code"]: w for w in repo.widget_catalogue(session)}
        grants = repo.role_permission_keys(session, role["id"])
        entries: list[LayoutEntryOut] = []
        for e in (layout or {}).get("widgets") or []:
            definition: WidgetDef | None = REGISTRY.get(e.get("code"))
            meta = catalogue.get(e.get("code"))
            if definition is None or meta is None:
                continue
            missing = definition.missing(grants)
            entries.append(
                LayoutEntryOut(
                    code=definition.code,
                    title=meta["title"],
                    size=e.get("size") or meta["default_size"],
                    allowed_for_role=not missing,
                    missing=_perm_refs(missing),
                )
            )
        return RoleLayoutOut(
            role=RoleRef(code=role["code"], name=role["name"]),
            has_layout=layout is not None,
            widgets=entries,
            role_permissions=_perm_refs(sorted(grants)),
            updated_at=layout["updated_at"] if layout else None,
            updated_by_name=layout["updated_by_name"] if layout else None,
        )
