"""Reports & MIS service (prompt P4-02, master plan §8.3 report_column_prefs, §10 "Report columns").

* Catalogue: only reports the caller may run (reports.view + the report's module permissions, and
  scope `all` for facility-wide reports without a per-row owner).
* Data: validated filters → registry SQL with the data-scope predicate → one page (server-side
  sort + pagination) and SQL totals over the whole filtered set.
* Export (reports.export): CSV / XLSX streamed through a server-side cursor; refused above
  `report_export_max_rows` instead of being silently truncated.
* Print: the same data for the A4-landscape print layout with branding and the filters used.
* Columns: user choice → admin default of the user's earliest-assigned role (provisional "primary
  role", as P4-01) → registry defaults. Admin defaults write config_change_log.
* Saved filters [IMP]: per user and report, at most one default.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal, cast
from urllib.parse import quote
from uuid import UUID

import structlog

from app.core.config import get_settings
from app.core.db import UnitOfWork
from app.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from app.core.permissions import EffectivePermissions
from app.core.security import CurrentUser
from app.modules.reports import exporters, query
from app.modules.reports import repository as repo
from app.modules.reports.registry import REGISTRY, RESERVED_PARAMS, Col, Filt, ReportDef
from app.modules.reports.schemas import (
    Branding,
    ColumnOut,
    ColumnPrefOut,
    ColumnsIn,
    FilterChoice,
    FilterOut,
    FilterUsed,
    ReportDataOut,
    ReportDefinitionOut,
    ReportGroupOut,
    ReportPrintOut,
    ReportSummary,
    RoleColumnsIn,
    RoleColumnsOut,
    RoleRef,
    SavedFilterIn,
    SavedFilterOut,
    SortOut,
)

log = structlog.get_logger("rms.reports")

Scope = Literal["all", "department", "own"]
ExportFormat = Literal["csv", "xlsx"]
MAX_PAGE_SIZE = 500
MAX_TEXT_FILTER = 100
MAX_SAVED_FILTERS = 50
DEFAULT_EXPORT_MAX = 100_000
DEFAULT_PRINT_MAX = 2_000
DEFAULT_WINDOW_DAYS = 30
_PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]*)\}")
_TRUE = {"true", "1", "yes"}
_FALSE = {"false", "0", "no"}

MEDIA_TYPES: dict[str, str] = {
    "csv": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def _int_setting(value: Any, default: int, lo: int, hi: int) -> int:
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and lo <= value <= hi
        else default
    )


def _jsonable(value: Any) -> Any:
    """Screen/print values: Decimal → JSON number (exports keep the exact Decimal)."""
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    return value


class ReportExport:
    """A validated export: filename, media type and the byte stream (runs after the response
    headers are sent, in its own read transaction)."""

    def __init__(self, filename: str, media_type: str, body: Iterator[bytes]) -> None:
        self.filename = filename
        self.media_type = media_type
        self.body = body


class _Run:
    """A validated report request."""

    def __init__(
        self,
        defn: ReportDef,
        meta: dict[str, Any],
        scope: Scope,
        values: dict[str, Any],
        timezone: str,
        sort: str,
        direction: Literal["asc", "desc"],
    ) -> None:
        self.defn = defn
        self.meta = meta
        self.scope = scope
        self.values = values
        self.timezone = timezone
        self.sort = sort
        self.direction = direction

    def labels(self) -> dict[str, str]:
        overrides = self.meta.get("column_labels") or {}
        return {
            c.key: str(overrides[c.key]) if isinstance(overrides.get(c.key), str) else c.label
            for c in self.defn.columns
        }


class ReportService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    # --- access ---------------------------------------------------------------------------------
    @staticmethod
    def _scope(perms: EffectivePermissions) -> Scope:
        scope = perms.scope("reports", "view")
        return cast(Scope, scope) if scope in ("all", "department", "own") else "own"

    @classmethod
    def _allowed(cls, perms: EffectivePermissions, defn: ReportDef) -> bool:
        if not perms.allows("reports", "view"):
            return False
        if not all(perms.allows(m, a) for m, a in defn.requires):
            return False
        return defn.owner_expr is not None or cls._scope(perms) == "all"

    def _report(
        self, session: Any, perms: EffectivePermissions, code: str
    ) -> tuple[ReportDef, dict[str, Any]]:
        defn = REGISTRY.get(code)
        meta = repo.definition(session, code) if defn else None
        if defn is None or meta is None or not meta["is_active"]:
            raise NotFound(f"Unknown report {code}", code="REPORT_NOT_FOUND")
        if not self._allowed(perms, defn):
            needs = ["reports.view", *(f"{m}.{a}" for m, a in defn.requires)]
            raise PermissionDenied(
                f"You may not run report {code}",
                code="REPORT_FORBIDDEN",
                details={
                    "requires": needs,
                    "scope_required": "all" if defn.owner_expr is None else None,
                },
            )
        return defn, meta

    # --- catalogue & definition -----------------------------------------------------------------
    def catalogue(self, user: CurrentUser, perms: EffectivePermissions) -> list[ReportGroupOut]:
        with self._uow.transaction(user.id) as session:
            rows = repo.catalogue(session)
        can_export = perms.allows("reports", "export")
        groups: dict[str, ReportGroupOut] = {}
        for r in rows:
            defn = REGISTRY.get(r["code"])
            if defn is None:
                log.error("report_without_registry_entry", report=r["code"])
                continue
            if not r["is_active"] or not self._allowed(perms, defn):
                continue
            group = groups.setdefault(
                r["group_code"],
                ReportGroupOut(code=r["group_code"], title=r["group_title"], reports=[]),
            )
            group.reports.append(
                ReportSummary(
                    code=r["code"],
                    title=r["title"],
                    description=r["description"],
                    can_export=can_export,
                )
            )
        return list(groups.values())

    def definition(
        self, user: CurrentUser, perms: EffectivePermissions, code: str
    ) -> ReportDefinitionOut:
        with self._uow.transaction(user.id) as session:
            defn, meta = self._report(session, perms, code)
            filters = [self._filter_out(session, f) for f in defn.filters]
            visible, source, source_role = self._effective_columns(session, user.id, defn)
            saved = [SavedFilterOut(**s) for s in repo.saved_filters(session, user.id, code)]
            page_size = _int_setting(repo.get_setting(session, "page_size"), 25, 5, MAX_PAGE_SIZE)
        labels = _Run(defn, meta, "all", {}, "", "", "asc").labels()
        return ReportDefinitionOut(
            code=defn.code,
            group_code=meta["group_code"],
            group_title=meta["group_title"],
            title=meta["title"],
            description=meta["description"],
            columns=[self._column_out(c, labels) for c in defn.columns],
            filters=filters,
            default_sort=SortOut(key=defn.default_sort[0], dir=defn.default_sort[1]),
            visible_columns=visible,
            column_source=source,
            column_source_role=source_role,
            saved_filters=saved,
            can_export=perms.allows("reports", "export"),
            scope=self._scope(perms),
            page_size=page_size,
        )

    @staticmethod
    def _column_out(c: Col, labels: dict[str, str]) -> ColumnOut:
        return ColumnOut(
            key=c.key,
            label=labels.get(c.key, c.label),
            type=c.type,
            default=c.default,
            total=c.total.kind if c.total else None,
            has_link=c.link is not None,
            card=c.card,
            sortable=c.sortable,
        )

    def _choices(self, session: Any, f: Filt) -> list[FilterChoice]:
        if f.option_set:
            return [FilterChoice(**r) for r in repo.option_labels(session, f.option_set)]
        if f.lookup:
            return [FilterChoice(**r) for r in repo.lookup(session, f.lookup)]
        return [FilterChoice(value=c, label=c) for c in f.choices]

    def _filter_out(self, session: Any, f: Filt) -> FilterOut:
        default = None
        if f.default is not None:
            default = self._default_value(session, f)
        return FilterOut(
            key=f.key,
            label=f.label,
            type=f.type,
            choices=self._choices(session, f) if f.type in ("enum", "uuid") else [],
            default=default.isoformat()
            if isinstance(default, date)
            else (str(default).lower() if isinstance(default, bool) else None),
            required=f.mode == "param" and f.default in ("window_start", "today"),
        )

    # --- parameter validation -------------------------------------------------------------------
    def _timezone(self, session: Any) -> str:
        tz = repo.get_setting(session, "timezone")
        return tz if isinstance(tz, str) and tz else get_settings().tz

    def _default_value(self, session: Any, f: Filt) -> Any:
        if f.default == "true":
            return True
        if f.default == "false":
            return False
        today = repo.today_in(session, self._timezone(session))
        today = today if isinstance(today, date) else date.fromisoformat(str(today))
        if f.default == "today":
            return today
        days = _int_setting(
            repo.get_setting(session, "report_default_window_days"), DEFAULT_WINDOW_DAYS, 1, 366
        )
        return today - timedelta(days=days - 1)

    def _parse_value(self, session: Any, f: Filt, raw: str) -> Any:
        raw = raw.strip()
        if raw == "":
            return None
        if f.type == "date":
            return date.fromisoformat(raw)
        if f.type == "bool":
            low = raw.lower()
            if low in _TRUE:
                return True
            if low in _FALSE:
                return False
            raise ValueError("expected true or false")
        if f.type == "uuid":
            value = UUID(raw)
            return value
        if f.type == "enum":
            allowed = {c.value for c in self._choices(session, f)}
            if raw not in allowed:
                raise ValueError(f"not one of the allowed values ({len(allowed)} choices)")
            return raw
        if len(raw) > MAX_TEXT_FILTER:
            raise ValueError(f"at most {MAX_TEXT_FILTER} characters")
        return raw

    def _values(self, session: Any, defn: ReportDef, raw: dict[str, str]) -> dict[str, Any]:
        errors: list[dict[str, Any]] = []
        values: dict[str, Any] = {}
        known = {f.key for f in defn.filters}
        for key in raw:
            if key not in known and key not in RESERVED_PARAMS:
                errors.append({"loc": [key], "msg": "unknown parameter"})
        for f in defn.filters:
            if f.key in raw:
                try:
                    values[f.key] = self._parse_value(session, f, raw[f.key])
                except ValueError as exc:
                    errors.append({"loc": [f.key], "msg": str(exc) or "invalid value"})
                    continue
                required = f.mode == "param" and f.default in ("window_start", "today")
                if values[f.key] is None and required:
                    values[f.key] = self._default_value(session, f)
            elif f.default is not None:
                values[f.key] = self._default_value(session, f)
            else:
                values[f.key] = None
        d_from, d_to = values.get("date_from"), values.get("date_to")
        if isinstance(d_from, date) and isinstance(d_to, date):
            if d_from > d_to:
                errors.append({"loc": ["date_from"], "msg": "must not be after date_to"})
            elif defn.max_span_days is not None and (d_to - d_from).days > defn.max_span_days:
                errors.append(
                    {
                        "loc": ["date_to"],
                        "msg": f"at most {defn.max_span_days} days after date_from",
                    }
                )
        if errors:
            raise ValidationFailed(
                f"Invalid parameters for report {defn.code}",
                code="INVALID_REPORT_PARAMS",
                details=errors,
            )
        return values

    @staticmethod
    def _sort(defn: ReportDef, raw: dict[str, str]) -> tuple[str, Literal["asc", "desc"]]:
        sort = raw.get("sort") or defn.default_sort[0]
        col = defn.column(sort)
        if col is None or not col.sortable:
            raise ValidationFailed(
                f"Cannot sort report {defn.code} by {sort}",
                code="INVALID_REPORT_PARAMS",
                details=[{"loc": ["sort"], "msg": "unknown or unsortable column"}],
            )
        direction = raw.get("dir") or (
            defn.default_sort[1] if sort == defn.default_sort[0] else "asc"
        )
        if direction not in ("asc", "desc"):
            raise ValidationFailed(
                "dir must be asc or desc",
                code="INVALID_REPORT_PARAMS",
                details=[{"loc": ["dir"], "msg": "must be asc or desc"}],
            )
        return sort, cast(Literal["asc", "desc"], direction)

    def _prepare(
        self, session: Any, perms: EffectivePermissions, code: str, raw: dict[str, str]
    ) -> _Run:
        defn, meta = self._report(session, perms, code)
        values = self._values(session, defn, raw)
        sort, direction = self._sort(defn, raw)
        return _Run(
            defn, meta, self._scope(perms), values, self._timezone(session), sort, direction
        )

    @staticmethod
    def _built(run: _Run, user: CurrentUser) -> query.BuiltQuery:
        return query.build(
            run.defn, run.values, scope=run.scope, user_id=user.id, timezone=run.timezone
        )

    @staticmethod
    def _applied(run: _Run) -> dict[str, Any]:
        return {
            k: (v.isoformat() if isinstance(v, date) else _jsonable(v))
            for k, v in run.values.items()
            if v is not None
        }

    # --- rows -----------------------------------------------------------------------------------
    @staticmethod
    def _shape_row(defn: ReportDef, row: dict[str, Any]) -> dict[str, Any]:
        out = {c.key: _jsonable(row.get(c.key)) for c in defn.columns}
        links: dict[str, str] = {}
        for c in defn.columns:
            if c.link is None:
                continue
            keys = _PLACEHOLDER.findall(c.link)
            if any(row.get(k) is None for k in keys):
                continue
            links[c.key] = _PLACEHOLDER.sub(lambda m: quote(str(row[m.group(1)]), safe=""), c.link)
        out["_links"] = links
        return out

    @staticmethod
    def _totals(row: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        count = int(row.pop("_count") or 0)
        return count, {k: _jsonable(v) for k, v in row.items()}

    def data(
        self,
        user: CurrentUser,
        perms: EffectivePermissions,
        code: str,
        raw: dict[str, str],
    ) -> ReportDataOut:
        try:
            page = max(1, int(raw.get("page") or 1))
            page_size_raw = raw.get("page_size")
        except ValueError as exc:
            raise ValidationFailed(
                "page must be a number",
                code="INVALID_REPORT_PARAMS",
                details=[{"loc": ["page"], "msg": "must be a number"}],
            ) from exc
        with self._uow.transaction(user.id) as session:
            run = self._prepare(session, perms, code, raw)
            default_size = _int_setting(
                repo.get_setting(session, "page_size"), 25, 5, MAX_PAGE_SIZE
            )
            try:
                page_size = int(page_size_raw) if page_size_raw else default_size
            except ValueError as exc:
                raise ValidationFailed(
                    "page_size must be a number",
                    code="INVALID_REPORT_PARAMS",
                    details=[{"loc": ["page_size"], "msg": "must be a number"}],
                ) from exc
            if not 1 <= page_size <= MAX_PAGE_SIZE:
                raise ValidationFailed(
                    f"page_size must be between 1 and {MAX_PAGE_SIZE}",
                    code="INVALID_REPORT_PARAMS",
                    details=[{"loc": ["page_size"], "msg": f"1..{MAX_PAGE_SIZE}"}],
                )
            built = self._built(run, user)
            total, totals = self._totals(
                repo.fetch_one(session, query.totals_sql(built, run.defn), built.params)
            )
            rows = repo.fetch_all(
                session,
                query.page_sql(built, run.defn, run.sort, run.direction),
                {**built.params, "_limit": page_size, "_offset": (page - 1) * page_size},
            )
        return ReportDataOut(
            code=code,
            page=page,
            page_size=page_size,
            total=total,
            sort=SortOut(key=run.sort, dir=run.direction),
            applied=self._applied(run),
            rows=[self._shape_row(run.defn, r) for r in rows],
            totals=totals,
            generated_at=datetime.now(UTC),
        )

    # --- columns --------------------------------------------------------------------------------
    @staticmethod
    def _valid_keys(defn: ReportDef, keys: list[str]) -> list[str]:
        known = {c.key for c in defn.columns}
        return [k for k in keys if k in known]

    def _effective_columns(
        self, session: Any, user_id: UUID, defn: ReportDef
    ) -> tuple[list[str], Literal["user", "role", "default"], str | None]:
        mine = repo.user_columns(session, user_id, defn.code)
        if mine is not None and self._valid_keys(defn, mine):
            return self._valid_keys(defn, mine), "user", None
        role = repo.role_columns_for_user(session, user_id, defn.code)
        if role is not None and self._valid_keys(defn, role[1]):
            return self._valid_keys(defn, role[1]), "role", role[0]
        return defn.default_columns, "default", None

    def _requested_columns(
        self, session: Any, user_id: UUID, defn: ReportDef, raw: dict[str, str]
    ) -> list[str]:
        requested = raw.get("columns")
        if not requested:
            return self._effective_columns(session, user_id, defn)[0]
        keys = [k.strip() for k in requested.split(",") if k.strip()]
        unknown = [k for k in keys if defn.column(k) is None]
        if unknown or not keys or len(set(keys)) != len(keys):
            raise ValidationFailed(
                f"Invalid columns for report {defn.code}",
                code="INVALID_REPORT_PARAMS",
                details=[{"loc": ["columns"], "msg": f"unknown or repeated: {unknown or keys}"}],
            )
        return keys

    def _check_columns(self, defn: ReportDef, columns: list[str]) -> None:
        unknown = [k for k in columns if defn.column(k) is None]
        if unknown:
            raise ValidationFailed(
                f"Unknown columns for report {defn.code}",
                code="UNKNOWN_REPORT_COLUMN",
                details={"columns": unknown},
            )

    def set_my_columns(
        self, user: CurrentUser, perms: EffectivePermissions, code: str, payload: ColumnsIn
    ) -> ColumnPrefOut:
        with self._uow.transaction(user.id) as session:
            defn, _ = self._report(session, perms, code)
            self._check_columns(defn, payload.columns)
            repo.upsert_user_columns(session, user.id, code, json.dumps(payload.columns))
            visible, source, role = self._effective_columns(session, user.id, defn)
        return ColumnPrefOut(
            report_code=code, visible_columns=visible, column_source=source, column_source_role=role
        )

    def reset_my_columns(
        self, user: CurrentUser, perms: EffectivePermissions, code: str
    ) -> ColumnPrefOut:
        with self._uow.transaction(user.id) as session:
            defn, _ = self._report(session, perms, code)
            repo.delete_user_columns(session, user.id, code)
            visible, source, role = self._effective_columns(session, user.id, defn)
        return ColumnPrefOut(
            report_code=code, visible_columns=visible, column_source=source, column_source_role=role
        )

    # --- export & print -------------------------------------------------------------------------
    def _filters_used(self, session: Any, run: _Run) -> list[FilterUsed]:
        out: list[FilterUsed] = []
        for f in run.defn.filters:
            value = run.values.get(f.key)
            if value is None:
                continue
            if isinstance(value, bool):
                text = "Yes" if value else "No"
            elif isinstance(value, date):
                text = value.isoformat()
            elif f.type in ("enum", "uuid"):
                labels = {c.value: c.label for c in self._choices(session, f)}
                text = labels.get(str(value), str(value))
            else:
                text = str(value)
            out.append(FilterUsed(label=f.label, value=text))
        return out

    def export(
        self,
        user: CurrentUser,
        perms: EffectivePermissions,
        code: str,
        fmt: ExportFormat,
        raw: dict[str, str],
    ) -> ReportExport:
        with self._uow.transaction(user.id) as session:
            run = self._prepare(session, perms, code, raw)
            keys = self._requested_columns(session, user.id, run.defn, raw)
            built = self._built(run, user)
            total, _ = self._totals(
                repo.fetch_one(session, query.totals_sql(built, run.defn), built.params)
            )
            limit = _int_setting(
                repo.get_setting(session, "report_export_max_rows"),
                DEFAULT_EXPORT_MAX,
                1,
                1_000_000,
            )
            if total > limit:
                raise ValidationFailed(
                    f"The export has {total} rows; the limit is {limit}. Narrow the filters.",
                    code="EXPORT_TOO_LARGE",
                    details={"rows": total, "limit": limit},
                )
            filters_used = self._filters_used(session, run)
        labels = run.labels()
        columns = [self._with_label(run.defn.column(k), labels) for k in keys]
        sql_text = query.export_sql(built, run.defn, keys, run.sort, run.direction)
        params = built.params
        uow, uid = self._uow, user.id

        def rows() -> Iterator[tuple[Any, ...]]:
            with uow.transaction(uid) as stream_session:
                yield from repo.stream(stream_session, sql_text, params)

        stamp = datetime.now(UTC)
        log.info("report_export", report=code, format=fmt, rows=total, columns=len(keys))
        if fmt == "csv":
            body = exporters.csv_stream(columns, rows(), run.timezone)
        else:
            meta = exporters.ExportMeta(
                title=f"{code} {run.meta['title']}",
                generated_by=user.full_name,
                generated_at=stamp,
                timezone=run.timezone,
                filters=[(f.label, f.value) for f in filters_used],
            )
            body = exporters.xlsx_stream(columns, rows(), meta)
        filename = f"{code}-{stamp.strftime('%Y%m%d-%H%M')}.{fmt}"
        return ReportExport(filename, MEDIA_TYPES[fmt], body)

    @staticmethod
    def _with_label(col: Col | None, labels: dict[str, str]) -> Col:
        if col is None:  # keys were validated against the registry before this point
            raise ValueError("unknown report column")
        label = labels.get(col.key, col.label)
        if label == col.label:
            return col
        return Col(
            col.key, label, col.type, col.default, col.total, col.link, col.card, col.sortable
        )

    def print_data(
        self,
        user: CurrentUser,
        perms: EffectivePermissions,
        code: str,
        raw: dict[str, str],
    ) -> ReportPrintOut:
        with self._uow.transaction(user.id) as session:
            run = self._prepare(session, perms, code, raw)
            keys = self._requested_columns(session, user.id, run.defn, raw)
            built = self._built(run, user)
            total, totals = self._totals(
                repo.fetch_one(session, query.totals_sql(built, run.defn), built.params)
            )
            limit = _int_setting(
                repo.get_setting(session, "report_print_max_rows"), DEFAULT_PRINT_MAX, 1, 20_000
            )
            rows = repo.fetch_all(
                session,
                query.page_sql(built, run.defn, run.sort, run.direction),
                {**built.params, "_limit": limit, "_offset": 0},
            )
            filters_used = self._filters_used(session, run)
            brand = repo.branding(session)
        labels = run.labels()
        cols = [self._column_out(cast(Col, run.defn.column(k)), labels) for k in keys]
        shaped = [self._shape_row(run.defn, r) for r in rows]
        app_name = brand.get("app_name")
        logo = brand.get("branding_logo_url")
        color = brand.get("branding_primary_color")
        return ReportPrintOut(
            code=code,
            title=run.meta["title"],
            description=run.meta["description"],
            branding=Branding(
                app_name=app_name if isinstance(app_name, str) else "RMS",
                logo_url=logo if isinstance(logo, str) else None,
                primary_color=color if isinstance(color, str) else None,
            ),
            filters_used=filters_used,
            generated_by=user.full_name,
            generated_at=datetime.now(UTC),
            timezone=run.timezone,
            columns=cols,
            rows=[{k: r[k] for k in keys} for r in shaped],
            totals={k: v for k, v in totals.items() if k in keys},
            total_rows=total,
            printed_rows=len(shaped),
            truncated=total > len(shaped),
        )

    # --- saved filters --------------------------------------------------------------------------
    def create_saved_filter(
        self, user: CurrentUser, perms: EffectivePermissions, code: str, payload: SavedFilterIn
    ) -> SavedFilterOut:
        raw = {
            k: ("true" if v is True else "false" if v is False else (v or ""))
            for k, v in payload.params.items()
        }
        with self._uow.transaction(user.id) as session:
            defn, _ = self._report(session, perms, code)
            reserved = sorted(k for k in raw if k in RESERVED_PARAMS)
            if reserved:
                raise ValidationFailed(
                    "Saved filters hold filter values only",
                    code="INVALID_REPORT_PARAMS",
                    details=[{"loc": [k], "msg": "not a filter"} for k in reserved],
                )
            self._values(session, defn, raw)  # same validation as a run
            if repo.saved_filter_name_taken(session, user.id, code, payload.name):
                raise Conflict(
                    f"You already have a saved filter named {payload.name!r}",
                    code="SAVED_FILTER_EXISTS",
                )
            if len(repo.saved_filters(session, user.id, code)) >= MAX_SAVED_FILTERS:
                raise ValidationFailed(
                    f"At most {MAX_SAVED_FILTERS} saved filters per report",
                    code="TOO_MANY_SAVED_FILTERS",
                )
            if payload.is_default:
                repo.clear_default_filter(session, user.id, code)
            row = repo.insert_saved_filter(
                session,
                user_id=user.id,
                report_code=code,
                name=payload.name,
                params_json=json.dumps({k: v for k, v in raw.items() if v != ""}),
                is_default=payload.is_default,
            )
        return SavedFilterOut(**row)

    def delete_saved_filter(
        self, user: CurrentUser, perms: EffectivePermissions, code: str, filter_id: UUID
    ) -> None:
        with self._uow.transaction(user.id) as session:
            self._report(session, perms, code)
            if not repo.delete_saved_filter(session, user.id, code, filter_id):
                raise NotFound("Saved filter not found", code="SAVED_FILTER_NOT_FOUND")

    # --- admin: role column defaults --------------------------------------------------------------
    def list_role_columns(self, user: CurrentUser) -> list[RoleColumnsOut]:
        with self._uow.transaction(user.id) as session:
            titles = {r["code"]: r["title"] for r in repo.catalogue(session)}
            rows = repo.all_role_columns(session)
        return [
            RoleColumnsOut(
                report_code=r["report_code"],
                report_title=titles.get(r["report_code"], r["report_code"]),
                role_code=r["role_code"],
                role_name=r["role_name"],
                columns=list(r["columns"]),
                updated_at=r["updated_at"],
            )
            for r in rows
        ]

    def roles(self, user: CurrentUser) -> list[RoleRef]:
        with self._uow.transaction(user.id) as session:
            return [RoleRef(code=r["code"], name=r["name"]) for r in repo.list_roles(session)]

    def _admin_target(
        self, session: Any, code: str, role_code: str
    ) -> tuple[ReportDef, dict[str, Any], dict[str, Any]]:
        defn = REGISTRY.get(code)
        meta = repo.definition(session, code) if defn else None
        if defn is None or meta is None:
            raise NotFound(f"Unknown report {code}", code="REPORT_NOT_FOUND")
        role = repo.role_by_code(session, role_code)
        if role is None:
            raise NotFound(f"Unknown role {role_code}", code="ROLE_NOT_FOUND")
        return defn, meta, role

    def put_role_columns(
        self, user: CurrentUser, code: str, role_code: str, payload: RoleColumnsIn
    ) -> RoleColumnsOut:
        with self._uow.transaction(user.id) as session:
            defn, meta, role = self._admin_target(session, code, role_code)
            self._check_columns(defn, payload.columns)
            before = repo.role_columns(session, role["id"], code)
            after = json.dumps(payload.columns)
            repo.upsert_role_columns(session, role["id"], code, after)
            repo.insert_config_change(
                session,
                entity_type="report_column_defaults",
                entity_id=f"{code}:{role['code']}",
                action="UPDATE" if before is not None else "CREATE",
                before_json=json.dumps(before) if before is not None else None,
                after_json=after,
                reason=payload.reason.strip()
                if payload.reason and payload.reason.strip()
                else None,
            )
            log.info("report_column_defaults_saved", report=code, role=role["code"])
        return RoleColumnsOut(
            report_code=code,
            report_title=meta["title"],
            role_code=role["code"],
            role_name=role["name"],
            columns=payload.columns,
            updated_at=datetime.now(UTC),
        )

    def delete_role_columns(
        self, user: CurrentUser, code: str, role_code: str, reason: str | None
    ) -> None:
        with self._uow.transaction(user.id) as session:
            _, _, role = self._admin_target(session, code, role_code)
            before = repo.role_columns(session, role["id"], code)
            if before is None:
                raise NotFound(
                    f"Role {role_code} has no default columns for {code}",
                    code="COLUMN_DEFAULTS_NOT_FOUND",
                )
            repo.delete_role_columns(session, role["id"], code)
            repo.insert_config_change(
                session,
                entity_type="report_column_defaults",
                entity_id=f"{code}:{role['code']}",
                action="DELETE",
                before_json=json.dumps(before),
                after_json=None,
                reason=reason.strip() if reason and reason.strip() else None,
            )
