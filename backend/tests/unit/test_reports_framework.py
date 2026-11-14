"""Report framework units (prompt P4-02): SQL composition and export writers, no database."""

from __future__ import annotations

import io
import os
import tempfile
import tracemalloc
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from openpyxl import load_workbook

from app.modules.reports import exporters, query
from app.modules.reports.registry import REGISTRY, Col, Filt, ReportDef

UID = uuid.uuid4()
DEMO = ReportDef(
    code="R-00",
    requires=(),
    sql="select x.a, x.b from t x where {where}",
    columns=(Col("a", "A", "int"), Col("b", "B")),
    filters=(
        Filt("a_min", "A from", "date", expr="x.a", op="gte"),
        Filt("name", "Name", "text", expr="x.b", op="ilike"),
        Filt("b", "B", "text", mode="outer"),
        Filt("as_on", "As on", "date", mode="param"),
    ),
    default_sort=("a", "asc"),
    tiebreak="b",
    owner_expr="x.owner",
)


def test_values_are_bound_never_inlined() -> None:
    evil = "x'; drop table t; --"
    built = query.build(
        DEMO,
        {"a_min": date(2026, 1, 1), "name": evil, "b": evil, "as_on": None},
        scope="all",
        user_id=UID,
        timezone="Asia/Kolkata",
    )
    assert evil not in built.source
    assert "x.a >= :f_a_min" in built.source
    assert "x.b ilike :f_name escape" in built.source
    assert 'r."b" = :f_b' in built.source
    assert built.params["f_name"] == "%x'; drop table t; --%"
    assert built.params["p_as_on"] is None and "f_as_on" not in built.params


def test_like_wildcards_are_escaped() -> None:
    built = query.build(DEMO, {"name": "50%_off\\"}, scope="all", user_id=UID, timezone="UTC")
    assert built.params["f_name"] == "%50\\%\\_off\\\\%"


def test_scope_predicates() -> None:
    own = query.build(DEMO, {}, scope="own", user_id=UID, timezone="UTC")
    assert "(x.owner = :scope_uid)" in own.source and own.params["scope_uid"] == UID
    dept = query.build(DEMO, {}, scope="department", user_id=UID, timezone="UTC")
    assert "department_id is not distinct from" in dept.source
    everyone = query.build(DEMO, {}, scope="all", user_id=UID, timezone="UTC")
    assert "scope_uid" not in everyone.params and "where true" in everyone.source
    for defn in REGISTRY.values():
        if defn.owner_expr is None:
            assert query.scope_predicate(defn, "own") == "false"  # fail closed


def test_totals_and_order() -> None:
    built = query.build(DEMO, {}, scope="all", user_id=UID, timezone="UTC")
    assert query.order_by(DEMO, "a", "desc") == 'order by r."a" desc nulls last, r."b" asc'
    assert query.order_by(DEMO, "b", "asc") == 'order by r."b" asc nulls last'
    r10 = REGISTRY["R-10"]
    sql = query.totals_sql(query.build(r10, {}, scope="all", user_id=UID, timezone="UTC"), r10)
    assert 'sum(r."batteries_installed") / nullif(sum(r."pieces_checked"), 0)' in sql
    # A SUM total over an empty filtered set is 0, not NULL (parity with dashboard formulas).
    r08 = REGISTRY["R-08"]
    sql08 = query.totals_sql(query.build(r08, {}, scope="all", user_id=UID, timezone="UTC"), r08)
    assert 'coalesce(sum(r."qty"), 0) as "qty"' in sql08
    assert query.export_sql(built, DEMO, ["b"], "a", "asc").startswith('select r."b" from (')


def test_csv_guards_formulas_and_formats() -> None:
    cols = [
        Col("a", "A"),
        Col("n", "N", "int"),
        Col("d", "When", "datetime"),
        Col("f", "F", "bool"),
    ]
    rows = [
        ("=HYPERLINK(1)", -5, datetime(2026, 11, 6, 0, 30, tzinfo=UTC), True),
        ("@cmd", 3, None, False),
    ]
    out = b"".join(exporters.csv_stream(cols, iter(rows), "Asia/Kolkata")).decode("utf-8")
    lines = out.lstrip("﻿").splitlines()
    assert lines[0] == "A,N,When,F"
    assert lines[1] == "'=HYPERLINK(1),-5,2026-11-06 06:00,Yes"  # numbers are not prefixed
    assert lines[2] == "'@cmd,3,,No"


def _many(n: int) -> Iterator[tuple[Any, ...]]:
    for i in range(n):
        yield (i, f"row {i}", Decimal(i) / 4, datetime(2026, 1, 1, tzinfo=UTC), date(2026, 1, 2))


def test_xlsx_write_only_keeps_memory_flat() -> None:
    cols = [
        Col("n", "No.", "int"),
        Col("t", "Text"),
        Col("m", "Money", "money"),
        Col("at", "At", "datetime"),
        Col("d", "Day", "date"),
    ]
    meta = exporters.ExportMeta(
        title="R-00 Test",
        generated_by="Unit",
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
        timezone="Asia/Kolkata",
        filters=[("Status", "CLOSED")],
    )
    fd, path = tempfile.mkstemp(suffix=".xlsx")
    os.close(fd)
    try:
        tracemalloc.start()
        count = exporters.write_xlsx(path, cols, _many(50_000), meta)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        assert count == 50_000
        # write-only mode: rows go to a temp file as they are appended.
        assert peak < 25 * 1024 * 1024, f"peak {peak / 1e6:.1f} MB"
        with open(path, "rb") as fh:
            wb = load_workbook(io.BytesIO(fh.read()), read_only=True)
        ws = wb["Report"]
        header = next(ws.iter_rows(max_row=1, values_only=True))
        first = next(ws.iter_rows(min_row=2, max_row=2, values_only=True))
        assert header == ("No.", "Text", "Money", "At", "Day")
        assert first[0] == 0 and first[3] == datetime(2026, 1, 1, 5, 30)
        about = list(wb["Filters"].iter_rows(values_only=True))
        assert ("Status", "CLOSED") in about and ("Rows", 50_000) in about
    finally:
        os.remove(path)
