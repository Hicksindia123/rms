"""Compose a report's SQL from its registry definition (prompt P4-02). Pure functions, no I/O.

Only registry-declared expressions and column keys ever reach the SQL text; every user-supplied
value is a bind parameter. The data-scope predicate is placed in the base query's ``{where}`` slot
together with the inner filters, so aggregate reports are scoped before grouping.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from app.modules.reports.registry import Col, Filt, ReportDef

Scope = Literal["all", "department", "own"]


@dataclass(frozen=True, slots=True)
class BuiltQuery:
    """`source` = ``(<base>) r where <outer filters>``; select from it with any projection."""

    source: str
    params: dict[str, Any]


def _ident(key: str) -> str:
    # Keys come from the registry (validated identifiers); quoting keeps reserved words safe.
    return f'r."{key}"'


def _predicate(expr: str, f: Filt) -> str:
    name = f":f_{f.key}"
    if f.op == "gte":
        return f"{expr} >= {name}"
    if f.op == "lte":
        return f"{expr} <= {name}"
    if f.op == "ilike":
        return f"{expr} ilike {name} escape '\\'"
    return f"{expr} = {name}"


def _like(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def scope_predicate(defn: ReportDef, scope: Scope) -> str | None:
    if scope == "all":
        return None
    if defn.owner_expr is None:
        # The service never runs an owner-less report with a narrower scope; fail closed.
        return "false"
    if scope == "own":
        return f"{defn.owner_expr} = :scope_uid"
    return (
        f"{defn.owner_expr} in (select sp.id from public.profiles sp "  # noqa: S608
        "where sp.department_id is not distinct from "
        "(select me.department_id from public.profiles me where me.id = :scope_uid))"
    )


def build(
    defn: ReportDef,
    values: dict[str, Any],
    *,
    scope: Scope,
    user_id: UUID,
    timezone: str,
) -> BuiltQuery:
    """`values` are validated filter values (params included, None = not set)."""
    params: dict[str, Any] = {"tz": timezone}
    inner: list[str] = []
    outer: list[str] = []
    for f in defn.filters:
        value = values.get(f.key)
        if f.mode == "param":
            params[f"p_{f.key}"] = value
            continue
        if value is None:
            continue
        params[f"f_{f.key}"] = _like(value) if f.op == "ilike" else value
        if f.mode == "inner":
            inner.append(_predicate(f.expr, f))
        else:
            outer.append(_predicate(_ident(f.expr or f.key), f))
    scope_sql = scope_predicate(defn, scope)
    if scope_sql is not None:
        inner.append(scope_sql)
        if ":scope_uid" in scope_sql:
            params["scope_uid"] = user_id
    base = defn.sql.replace("{where}", " and ".join(f"({p})" for p in inner) or "true")
    where = " and ".join(outer) or "true"
    return BuiltQuery(source=f"({base}) r where {where}", params=params)


def order_by(defn: ReportDef, sort: str, direction: str) -> str:
    tiebreak = f", {_ident(defn.tiebreak)} asc" if defn.tiebreak != sort else ""
    return (
        f"order by {_ident(sort)} {'desc' if direction == 'desc' else 'asc'} nulls last{tiebreak}"
    )


def page_sql(q: BuiltQuery, defn: ReportDef, sort: str, direction: str) -> str:
    order = order_by(defn, sort, direction)
    return f"select r.* from {q.source} {order} limit :_limit offset :_offset"  # noqa: S608


def _total_expr(c: Col) -> str | None:
    t = c.total
    if t is None:
        return None
    col = _ident(c.key)
    if t.kind == "sum":
        # An empty filtered set totals 0, not NULL, matching the dashboard formulas (P4-02).
        return f"coalesce(sum({col}), 0)"
    if t.kind == "avg":
        return f"round(avg({col})::numeric, 2)"
    if t.kind == "max":
        return f"max({col})"
    if t.kind == "count_true":
        return f"count(*) filter (where {col})"
    # ratio: weighted rate over the filtered rows
    num, den = _ident(t.numerator or ""), _ident(t.denominator or "")
    return f"round(100.0 * sum({num}) / nullif(sum({den}), 0), 1)"


def totals_sql(q: BuiltQuery, defn: ReportDef) -> str:
    parts = ['count(*)::bigint as "_count"']
    for c in defn.columns:
        expr = _total_expr(c)
        if expr is not None:
            parts.append(f'{expr} as "{c.key}"')
    return f"select {', '.join(parts)} from {q.source}"  # noqa: S608 - registry keys only


def export_sql(
    q: BuiltQuery, defn: ReportDef, columns: list[str], sort: str, direction: str
) -> str:
    projection = ", ".join(_ident(k) for k in columns)
    order = order_by(defn, sort, direction)
    return f"select {projection} from {q.source} {order}"  # noqa: S608 - registry keys only
