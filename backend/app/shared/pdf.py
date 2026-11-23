"""Server-side slip PDFs (DEC-41: one server-side template per slip, stored and re-printable).

A slip is described by plain data (`SlipDocument`) built by the owning service from the published
print template (branding, titles, section titles, signature blocks, paper) and the business record.
This module only lays it out; it holds no business values (CLAUDE.md rule e).

Output is deterministic (reportlab `invariant`): the same document data gives the same bytes, so
the stored file's SHA-256 identifies its content.

DEC-65 / Q26: an optional PNG logo is drawn left of the title block when the template has
`show_logo` on (the owning service passes the bytes); a table can be printed greyed with
strike-through (`SlipTable.muted`, used for the "other stores" section of a Transfer Slip).

DEC-70 (Q17): an optional one-line approval stamp (`SlipDocument.stamp`, the text comes from the
owning service) is drawn in a framed box below the header sections.
"""

from __future__ import annotations

import io
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4, A5, landscape, portrait
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    Image,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

Align = Literal["left", "right", "center"]

_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_DEFAULT_COLOR = "#0f172a"


@dataclass(frozen=True, slots=True)
class SlipField:
    label: str
    value: str


@dataclass(frozen=True, slots=True)
class SlipSection:
    """A titled block of label / value pairs (header data)."""

    title: str
    fields: Sequence[SlipField]


@dataclass(frozen=True, slots=True)
class SlipColumn:
    header: str
    weight: float = 1.0
    align: Align = "left"


@dataclass(frozen=True, slots=True)
class SlipTable:
    title: str
    columns: Sequence[SlipColumn]
    rows: Sequence[Sequence[str]]
    total_row: Sequence[str] | None = None
    empty_text: str = "No lines"
    # DEC-65: greyed + strike-through rows (information only, e.g. another store's items).
    muted: bool = False


@dataclass(frozen=True, slots=True)
class SlipSignature:
    label: str
    role: str
    name: str | None = None


@dataclass(frozen=True, slots=True)
class SlipDocument:
    title: str
    subtitle: str | None
    document_ref: str
    sections: Sequence[SlipSection] = field(default_factory=tuple)
    tables: Sequence[SlipTable] = field(default_factory=tuple)
    signatures: Sequence[SlipSignature] = field(default_factory=tuple)
    footer_text: str | None = None
    generated_text: str | None = None
    brand_color: str = _DEFAULT_COLOR
    paper_size: str = "A4"
    orientation: str = "portrait"
    signatures_title: str = "Signatures"
    # DEC-65 / Q26: PNG / JPEG bytes of the logo (None = company name only).
    logo: bytes | None = None
    # DEC-70: "Digitally approved by Management — name, date time, ref …" (None = no stamp).
    stamp: str | None = None


def _color(value: str) -> colors.Color:
    return colors.HexColor(value if _HEX_COLOR.fullmatch(value or "") else _DEFAULT_COLOR)


def _page_size(paper: str, orientation: str) -> tuple[float, float]:
    base = A5 if paper.upper() == "A5" else A4
    w, h = landscape(base) if orientation.lower() == "landscape" else portrait(base)
    return float(w), float(h)


def _p(text: Any, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape("" if text is None else str(text)).replace("\n", "<br/>"), style)


def _logo_flowable(data: bytes, max_w: float, max_h: float) -> Image:
    """The logo scaled to fit max_w x max_h, keeping its aspect ratio."""
    reader = ImageReader(io.BytesIO(data))
    w, h = reader.getSize()
    scale = min(max_w / float(w), max_h / float(h))
    return Image(io.BytesIO(data), width=float(w) * scale, height=float(h) * scale)


def render_slip_pdf(doc: SlipDocument) -> bytes:
    """Lay the slip out on A4/A5 pages and return the PDF bytes."""
    brand = _color(doc.brand_color)
    page_w, page_h = _page_size(doc.paper_size, doc.orientation)
    margin = 12 * mm
    usable_w = page_w - 2 * margin

    base = getSampleStyleSheet()
    s_title = ParagraphStyle(
        "slip_title", parent=base["Title"], fontSize=14, leading=17, textColor=brand, spaceAfter=1
    )
    s_sub = ParagraphStyle(
        "slip_sub", parent=base["Heading2"], fontSize=11.5, leading=14, alignment=TA_CENTER
    )
    s_ref = ParagraphStyle(
        "slip_ref", parent=base["Normal"], fontSize=8.5, leading=11, alignment=TA_CENTER
    )
    s_head = ParagraphStyle(
        "slip_head", parent=base["Heading4"], fontSize=9, leading=11, textColor=brand
    )
    s_label = ParagraphStyle(
        "slip_label", parent=base["Normal"], fontSize=8, leading=10, textColor=colors.grey
    )
    s_value = ParagraphStyle("slip_value", parent=base["Normal"], fontSize=8.5, leading=10.5)
    s_cell = ParagraphStyle("slip_cell", parent=base["Normal"], fontSize=8, leading=10)
    s_cell_r = ParagraphStyle("slip_cell_r", parent=s_cell, alignment=TA_RIGHT)
    s_cell_c = ParagraphStyle("slip_cell_c", parent=s_cell, alignment=TA_CENTER)
    s_th = ParagraphStyle(
        "slip_th", parent=s_cell, fontName="Helvetica-Bold", textColor=colors.white
    )
    cell_style = {"left": s_cell, "right": s_cell_r, "center": s_cell_c}

    s_muted = ParagraphStyle("slip_muted", parent=s_cell, textColor=colors.HexColor("#94a3b8"))
    s_muted_r = ParagraphStyle("slip_muted_r", parent=s_muted, alignment=TA_RIGHT)
    s_muted_c = ParagraphStyle("slip_muted_c", parent=s_muted, alignment=TA_CENTER)
    muted_style = {"left": s_muted, "right": s_muted_r, "center": s_muted_c}

    heading: list[Any] = [
        _p(doc.title, s_title),
        *([_p(doc.subtitle, s_sub)] if doc.subtitle else []),
        _p(doc.document_ref, s_ref),
    ]
    if doc.logo:
        logo_w = 38 * mm
        head = Table(
            [[_logo_flowable(doc.logo, logo_w, 16 * mm), heading]],
            colWidths=[logo_w + 3 * mm, usable_w - logo_w - 3 * mm],
        )
        head.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ]
            )
        )
        story: list[Any] = [head, Spacer(1, 4 * mm)]
    else:
        story = [*heading, Spacer(1, 4 * mm)]

    # Header sections, two per row.
    blocks: list[Table] = []
    col_w = (usable_w - 4 * mm) / 2
    for section in doc.sections:
        rows = [[_p(section.title, s_head), ""]] + [
            [_p(f.label, s_label), _p(f.value or "—", s_value)] for f in section.fields
        ]
        t = Table(rows, colWidths=[col_w * 0.38, col_w * 0.62])
        t.setStyle(
            TableStyle(
                [
                    ("SPAN", (0, 0), (1, 0)),
                    ("LINEBELOW", (0, 0), (1, 0), 0.6, brand),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BOX", (0, 0), (-1, -1), 0.4, colors.lightgrey),
                    ("TOPPADDING", (0, 0), (-1, -1), 2),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ]
            )
        )
        blocks.append(t)
    for i in range(0, len(blocks), 2):
        pair: list[Any] = blocks[i : i + 2]
        if len(pair) == 1:
            pair.append("")
        grid = Table([pair], colWidths=[col_w + 2 * mm, col_w + 2 * mm])
        grid.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
                ]
            )
        )
        story += [grid, Spacer(1, 3 * mm)]

    # DEC-70: the Management e-approval stamp.
    if doc.stamp:
        s_stamp = ParagraphStyle(
            "slip_stamp", parent=s_value, fontName="Helvetica-Bold", textColor=brand
        )
        box = Table([[_p(doc.stamp, s_stamp)]], colWidths=[usable_w])
        box.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 1.2, brand),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        story += [box, Spacer(1, 3 * mm)]

    # Line tables.
    for table in doc.tables:
        total_weight = sum(c.weight for c in table.columns) or 1.0
        widths = [usable_w * c.weight / total_weight for c in table.columns]
        data: list[list[Any]] = [[_p(c.header, s_th) for c in table.columns]]
        if table.rows:
            for row in table.rows:
                if table.muted:
                    data.append(
                        [
                            Paragraph(
                                f"<strike>{escape(str(value))}</strike>" if value else "",
                                muted_style[col.align],
                            )
                            for value, col in zip(row, table.columns, strict=True)
                        ]
                    )
                    continue
                data.append(
                    [
                        _p(value, cell_style[col.align])
                        for value, col in zip(row, table.columns, strict=True)
                    ]
                )
        else:
            data.append([_p(table.empty_text, s_cell)] + [""] * (len(table.columns) - 1))
        if table.total_row is not None:
            data.append(
                [
                    Paragraph(f"<b>{escape(str(v))}</b>", cell_style[col.align])
                    for v, col in zip(table.total_row, table.columns, strict=True)
                ]
            )
        t = Table(data, colWidths=widths, repeatRows=1)
        style: list[tuple[Any, ...]] = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#94a3b8") if table.muted else brand),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.lightgrey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ]
        if not table.rows:
            style.append(("SPAN", (0, 1), (-1, 1)))
        if table.total_row is not None:
            style += [
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#e2e8f0")),
                ("LINEABOVE", (0, -1), (-1, -1), 0.8, brand),
            ]
        t.setStyle(TableStyle(style))
        story += [_p(table.title, s_head), Spacer(1, 1 * mm), t, Spacer(1, 4 * mm)]

    # Signatures.
    if doc.signatures:
        n = len(doc.signatures)
        sig_w = usable_w / n
        cells = [
            [
                Spacer(1, 12 * mm),
                _p("_" * 28, s_cell_c),
                Paragraph(f"<b>{escape(s.label)}</b>", s_cell_c),
                _p(s.role, s_cell_c),
                _p(s.name or "\u00a0", s_cell_c),  # same height for every block
            ]
            for s in doc.signatures
        ]
        sig = Table([cells], colWidths=[sig_w] * n)
        sig.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "BOTTOM")]))
        story.append(KeepTogether([_p(doc.signatures_title, s_head), sig]))

    footer = doc.footer_text or ""
    generated = doc.generated_text or ""
    ref = doc.document_ref

    def _decorate(canvas: Any, pdf: Any) -> None:
        canvas.saveState()
        canvas.setStrokeColor(brand)
        canvas.setLineWidth(1.2)
        canvas.line(margin, page_h - margin + 3 * mm, page_w - margin, page_h - margin + 3 * mm)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.grey)
        if footer:
            canvas.drawString(margin, margin - 5 * mm, footer[:180])
        canvas.drawString(margin, margin - 8.5 * mm, f"{ref}  {generated}"[:180])
        canvas.drawRightString(page_w - margin, margin - 8.5 * mm, f"Page {pdf.page}")
        canvas.restoreState()

    buf = io.BytesIO()
    template = SimpleDocTemplate(
        buf,
        pagesize=(page_w, page_h),
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=margin + 4 * mm,
        title=f"{doc.title} \u2013 {doc.subtitle or ''} {doc.document_ref}".strip(),
        author="RMS",
        invariant=True,
    )
    template.build(story, onFirstPage=_decorate, onLaterPages=_decorate)
    # Sanity: the output must be a PDF (never store anything else as GENERATED_PDF).
    out = buf.getvalue()
    if not out.startswith(b"%PDF-"):
        raise RuntimeError("PDF renderer produced no PDF output")
    return out


__all__ = [
    "SlipColumn",
    "SlipDocument",
    "SlipField",
    "SlipSection",
    "SlipSignature",
    "SlipTable",
    "render_slip_pdf",
]
