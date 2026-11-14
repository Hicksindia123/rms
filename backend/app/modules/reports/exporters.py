"""Report export writers (prompt P4-02). Pure functions over row iterators; no database access.

* CSV: generated line by line (UTF-8 with BOM so Excel detects the encoding). Text cells that
  start with = + - @ are prefixed with an apostrophe (spreadsheet formula injection).
* XLSX: openpyxl in write-only mode (rows are flushed to a temporary file as they are appended, so
  memory stays flat however many rows), then the finished file is streamed in chunks and deleted.
  openpyxl is used because report users work in Excel: typed numbers and dates, a frozen header
  row, column widths and a second sheet listing the filters used.
"""

from __future__ import annotations

import csv
import io
import os
import tempfile
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from app.modules.reports.registry import Col

CHUNK = 64 * 1024
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
_NUMBER_FORMATS = {
    "int": "#,##0",
    "decimal": "#,##0.00",
    "money": "#,##0.00",
    "hours": "0.0",
    "days": "0.0",
    "percent": "0.0",
    "date": "dd-mm-yyyy",
    "datetime": "dd-mm-yyyy hh:mm",
}
_WIDTHS = {"date": 12, "datetime": 17, "bool": 9, "int": 11, "money": 14}


@dataclass(frozen=True, slots=True)
class ExportMeta:
    title: str
    generated_by: str
    generated_at: datetime
    timezone: str
    filters: Sequence[tuple[str, str]]


def _local(value: datetime, tz: ZoneInfo) -> datetime:
    return value.astimezone(tz) if value.tzinfo else value


def text_value(value: Any, col: Col, tz: ZoneInfo) -> str:
    """Human text for CSV and print (no locale-specific number grouping)."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, datetime):
        return _local(value, tz).strftime("%Y-%m-%d %H:%M")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, UUID):
        return str(value)
    out = str(value)
    if col.type in ("text", "code") and out.startswith(_FORMULA_PREFIXES):
        return "'" + out
    return out


def csv_stream(
    columns: Sequence[Col], rows: Iterable[Sequence[Any]], tz_name: str
) -> Iterator[bytes]:
    tz = ZoneInfo(tz_name)
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow([c.label for c in columns])
    yield ("﻿" + buf.getvalue()).encode("utf-8")
    pending = 0
    buf.seek(0)
    buf.truncate()
    for row in rows:
        writer.writerow([text_value(v, c, tz) for v, c in zip(row, columns, strict=True)])
        pending += 1
        if pending >= 500:
            yield buf.getvalue().encode("utf-8")
            buf.seek(0)
            buf.truncate()
            pending = 0
    if buf.tell():
        yield buf.getvalue().encode("utf-8")


def _xlsx_value(value: Any, col: Col, tz: ZoneInfo) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, datetime):
        # Excel has no time zones: write the business-timezone wall clock.
        return _local(value, tz).replace(tzinfo=None)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, UUID):
        return str(value)
    if (
        isinstance(value, str)
        and col.type in ("text", "code")
        and value.startswith(_FORMULA_PREFIXES)
    ):
        return "'" + value
    return value


def write_xlsx(
    path: str,
    columns: Sequence[Col],
    rows: Iterable[Sequence[Any]],
    meta: ExportMeta,
) -> int:
    """Write the workbook to `path` in write-only mode; returns the number of data rows."""
    tz = ZoneInfo(meta.timezone)
    wb = Workbook(write_only=True)
    ws = wb.create_sheet("Report")
    ws.freeze_panes = "A2"
    for i, c in enumerate(columns, start=1):
        ws.column_dimensions[get_column_letter(i)].width = max(
            _WIDTHS.get(c.type, 18), min(len(c.label) + 2, 40)
        )
    bold = Font(bold=True)
    header = []
    for c in columns:
        cell = WriteOnlyCell(ws, value=c.label)
        cell.font = bold
        header.append(cell)
    ws.append(header)

    formats = [_NUMBER_FORMATS.get(c.type) for c in columns]
    count = 0
    for row in rows:
        out: list[Any] = []
        for value, c, fmt in zip(row, columns, formats, strict=True):
            v = _xlsx_value(value, c, tz)
            if fmt and v is not None and not isinstance(v, str):
                cell = WriteOnlyCell(ws, value=v)
                cell.number_format = fmt
                out.append(cell)
            else:
                out.append(v)
        ws.append(out)
        count += 1

    about = wb.create_sheet("Filters")
    about.column_dimensions["A"].width = 28
    about.column_dimensions["B"].width = 60
    about.append([WriteOnlyCell(about, value=meta.title)])
    about.append(["Generated by", meta.generated_by])
    about.append(["Generated at", _local(meta.generated_at, tz).strftime("%Y-%m-%d %H:%M")])
    about.append(["Rows", count])
    for label, value in meta.filters:
        about.append([label, value])
    wb.save(path)
    return count


def xlsx_stream(
    columns: Sequence[Col], rows: Iterable[Sequence[Any]], meta: ExportMeta
) -> Iterator[bytes]:
    fd, path = tempfile.mkstemp(prefix="rms-report-", suffix=".xlsx")
    os.close(fd)
    try:
        write_xlsx(path, columns, rows, meta)
        with open(path, "rb") as fh:
            while chunk := fh.read(CHUNK):
                yield chunk
    finally:
        os.remove(path)
