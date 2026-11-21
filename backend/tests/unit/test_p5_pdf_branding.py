"""Phase P5 (DEC-65 / Q26): slip PDF logo + greyed table, print-logo setting, {STORE} numbers."""

from __future__ import annotations

from datetime import date
from typing import Any

from app.modules.config.numbering.service import render_number_pattern
from app.shared import branding
from app.shared.pdf import SlipColumn, SlipDocument, SlipTable, render_slip_pdf


def _doc(**kw: Any) -> SlipDocument:
    return SlipDocument(
        title="HICKS",
        subtitle="Transfer Slip",
        document_ref="TRF/OP/2026-27/0001",
        tables=[
            SlipTable(
                "Items for this store", [SlipColumn("Product"), SlipColumn("Qty")], [["A", "1"]]
            ),
            SlipTable(
                "Other items", [SlipColumn("Product"), SlipColumn("Qty")], [["B", "2"]], muted=True
            ),
        ],
        **kw,
    )


def test_logo_is_drawn_and_output_is_deterministic() -> None:
    logo = (branding.ASSETS_DIR / "hicks-logo.png").read_bytes()
    with_logo = render_slip_pdf(_doc(logo=logo))
    without = render_slip_pdf(_doc())
    assert with_logo.startswith(b"%PDF-") and without.startswith(b"%PDF-")
    assert b"/Subtype /Image" in with_logo
    assert b"/Subtype /Image" not in without
    assert render_slip_pdf(_doc(logo=logo)) == with_logo


class _Session:
    def __init__(self, value: Any) -> None:
        self.value = value

    def execute(self, *_: Any, **__: Any) -> _Session:
        return self

    def scalar(self) -> Any:
        return self.value


def test_print_logo_setting() -> None:
    assert branding.print_logo(_Session("hicks-logo.png"))  # type: ignore[arg-type]
    assert branding.print_logo(_Session("")) is None  # type: ignore[arg-type]
    # Only a bare file name inside the assets folder: no path traversal, no unknown file.
    assert branding.print_logo(_Session("../../.env")) is None  # type: ignore[arg-type]
    assert branding.print_logo(_Session("missing-logo.png")) is None  # type: ignore[arg-type]
    assert branding.template_logo(_Session("hicks-logo.png"), {"show_logo": False}) is None  # type: ignore[arg-type]


def test_store_token_has_its_own_counter() -> None:
    no, fy, period = render_number_pattern(
        "{PREFIX}/{STORE}/{FY}/{SEQ:4}", "TRF", 7, date(2026, 11, 21), scope="OP"
    )
    assert (no, fy, period) == ("TRF/OP/2026-27/0007", "2026-27", "FY2026:OP")
    plain, _, period = render_number_pattern("{PREFIX}/{FY}/{SEQ:5}", "TRF", 7, date(2026, 11, 21))
    assert (plain, period) == ("TRF/2026-27/00007", "FY2026")
