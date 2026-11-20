"""Unit tests (no DB): file allow-list (§9.6), G-02 evidence rule, DD r12-r15 classification."""

from __future__ import annotations

from typing import Any

import pytest

from app.core.errors import ValidationFailed
from app.modules.attachments.allowlist import (
    FileRejectedError,
    check_file,
    check_size,
    normalise_mime,
)
from app.modules.unboxing.service import classification_snapshot, resolve_document
from app.shared.guards import g02_missing_evidence, guard_g02
from app.shared.storage import Bucket
from app.shared.workflow_engine import InMemoryWorkflowEntity, WorkflowUser


# --- allow-list ----------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("kind", "mime", "name", "ext", "bucket"),
    [
        ("UNBOXING_VIDEO", "video/mp4", "a.mp4", "mp4", Bucket.VIDEOS),
        ("UNBOXING_VIDEO", "video/quicktime", "a.mov", "mov", Bucket.VIDEOS),
        ("UNBOXING_VIDEO", "Video/MP4; codecs=avc1", None, "mp4", Bucket.VIDEOS),
        ("DOC_PHOTO", "image/jpeg", "a.JPG", "jpg", Bucket.DOCUMENTS),
        ("DOC_PHOTO", "image/jpeg", "a.jpeg", "jpg", Bucket.DOCUMENTS),
        ("DOC_PHOTO", "image/png", "a.png", "png", Bucket.DOCUMENTS),
        ("DOC_PHOTO", "image/heic", "a.heic", "heic", Bucket.DOCUMENTS),
        ("DOC_PHOTO", "application/pdf", "a.pdf", "pdf", Bucket.DOCUMENTS),
        ("PARCEL_PHOTO", "image/png", "a.png", "png", Bucket.DOCUMENTS),
    ],
)
def test_allow_list_accepts(
    kind: str, mime: str, name: str | None, ext: str, bucket: Bucket
) -> None:
    allowed = check_file(kind, mime, name)
    assert allowed.ext == ext and allowed.bucket is bucket
    assert allowed.mime_type == normalise_mime(mime)


@pytest.mark.parametrize(
    ("kind", "mime", "name", "field"),
    [
        ("OTHER", "image/png", None, "kind"),
        # P3-07: proofs are allowed (images / PDF), but never videos (DEC-25).
        ("NOTIFICATION_PROOF", "video/mp4", None, "mime_type"),
        ("UNBOXING_VIDEO", "video/webm", None, "mime_type"),
        ("UNBOXING_VIDEO", "image/jpeg", None, "mime_type"),
        ("DOC_PHOTO", "image/svg+xml", None, "mime_type"),
        ("DOC_PHOTO", "application/octet-stream", None, "mime_type"),
        ("PARCEL_PHOTO", "application/pdf", None, "mime_type"),
        ("DOC_PHOTO", "image/png", "photo.jpg", "file_name"),
        ("DOC_PHOTO", "image/png", "photo.png.exe", "file_name"),
        ("UNBOXING_VIDEO", "video/mp4", "noext", "file_name"),
    ],
)
def test_allow_list_rejects(kind: str, mime: str, name: str | None, field: str) -> None:
    with pytest.raises(FileRejectedError) as exc:
        check_file(kind, mime, name)
    assert exc.value.field == field


def test_size_limits() -> None:
    check_size(1, 10)
    check_size(10, 10)
    for bad in (0, -1, 11):
        with pytest.raises(FileRejectedError):
            check_size(bad, 10)


# --- G-02 ----------------------------------------------------------------------------------------
BASE = {
    "video_count": 1,
    "doc_photo_count": 1,
    "classified_doc_photo_count": 1,
    "missing_documentation": False,
    "approved_exception": False,
}


@pytest.mark.parametrize(
    ("override", "missing"),
    [
        ({}, []),
        ({"video_count": 0}, ["UNBOXING_VIDEO"]),
        ({"boxes_missing_video": [2]}, ["VIDEO_PER_CARTON"]),
        ({"video_count": 0, "boxes_missing_video": [1, 2]}, ["UNBOXING_VIDEO", "VIDEO_PER_CARTON"]),
        # DEC-63 (Q25): no document photo, and unclassified photos do not block.
        ({"doc_photo_count": 0, "classified_doc_photo_count": 0}, []),
        ({"doc_photo_count": 2}, []),
        # DEC-63 (Q8): a GS flagged missing documentation needs no exception, for all GSs.
        (
            {"missing_documentation": True, "doc_photo_count": 0, "classified_doc_photo_count": 0},
            [],
        ),
        ({"missing_documentation": True, "video_count": 0}, ["UNBOXING_VIDEO"]),
    ],
)
def test_g02_missing_evidence(override: dict[str, Any], missing: list[str]) -> None:
    assert g02_missing_evidence({**BASE, **override}) == missing


def test_g02_guard_cannot_be_bypassed_by_super_admin() -> None:
    entity = InMemoryWorkflowEntity(context={**BASE, "video_count": 0})
    assert guard_g02(entity, WorkflowUser(is_super_admin=True)) is False
    assert guard_g02(InMemoryWorkflowEntity(context=BASE), WorkflowUser()) is True


# --- classification (DD r12-r15) -----------------------------------------------------------------
def _field(key: str, control: str, cls: str | None = None, **extra: Any) -> dict[str, Any]:
    rule = {"field": "doc_classification", "op": "eq", "value": cls} if cls else None
    return {
        "field_key": key,
        "label": key,
        "control_type": control,
        "is_required": False,
        "visible_when": rule,
        "required_when": rule,
        **extra,
    }


SNAPSHOT: dict[str, Any] = {
    "fields": [
        {
            "field_key": "unboxing_video",
            "label": "Video",
            "control_type": "file",
            "is_required": True,
        },
        {
            **_field("doc_classification", "dropdown"),
            "is_required": True,
            "option_items": [
                {"code": c, "label": c.title()}
                for c in ("INVOICE", "DEBIT_NOTE", "DELIVERY_CHALLAN", "HANDWRITTEN_SLIP")
            ],
        },
        _field("invoice_no", "text", "INVOICE"),
        _field("invoice_date", "date", "INVOICE"),
        _field("buyer_gstin", "text", "INVOICE", validation={"regex": "^[0-9A-Z]{15}$"}),
        _field("seller_gstin", "text", "INVOICE", validation={"regex": "^[0-9A-Z]{15}$"}),
        _field("items_verified", "checkbox", "INVOICE"),
        _field("dn_number", "text", "DEBIT_NOTE"),
        _field("dn_amount", "number", "DEBIT_NOTE"),
        _field("challan_qty_matched", "checkbox", "DELIVERY_CHALLAN"),
        {
            **_field("challan_remarks", "textarea", "DELIVERY_CHALLAN"),
            "required_when": {
                "all": [
                    {"field": "doc_classification", "op": "eq", "value": "DELIVERY_CHALLAN"},
                    {"field": "challan_qty_matched", "op": "neq", "value": True},
                ]
            },
        },
        _field("party_claim_text", "textarea", "HANDWRITTEN_SLIP"),
    ]
}


def test_classification_snapshot_drops_file_fields() -> None:
    keys = [f["field_key"] for f in classification_snapshot(SNAPSHOT)["fields"]]
    assert "unboxing_video" not in keys and "doc_classification" in keys


def test_resolve_invoice_maps_columns_and_hides_other_fields() -> None:
    columns, values, labels = resolve_document(
        SNAPSHOT,
        {
            "doc_classification": "INVOICE",
            "invoice_no": " INV-9 ",
            "invoice_date": "2026-10-01",
            "buyer_gstin": "09aaach7409r1zz",
            "seller_gstin": "07 AAACB1234C1Z5",
            "items_verified": True,
            "dn_amount": 99,  # not visible for an invoice → pruned
        },
    )
    assert columns["classification_code"] == "INVOICE"
    assert columns["doc_no"] == "INV-9" and str(columns["doc_date"]) == "2026-10-01"
    assert columns["buyer_gstin"] == "09AAACH7409R1ZZ"
    assert columns["seller_gstin"] == "07AAACB1234C1Z5"
    assert "amount" not in columns and "dn_amount" not in values
    assert labels["doc_classification"]["value_label"] == "Invoice"


@pytest.mark.parametrize(
    ("values", "field"),
    [
        (
            {
                "doc_classification": "INVOICE",
                "invoice_no": "1",
                "invoice_date": "2026-10-01",
                "buyer_gstin": "09AAACH7409R1ZZ",
                "seller_gstin": "07AAACB1234C1Z5",
                "items_verified": False,
            },
            "items_verified",
        ),
        ({"doc_classification": "DEBIT_NOTE", "dn_number": "D1", "dn_amount": -5}, "dn_amount"),
        (
            {"doc_classification": "DELIVERY_CHALLAN", "challan_qty_matched": False},
            "challan_remarks",
        ),
        ({"doc_classification": "HANDWRITTEN_SLIP"}, "party_claim_text"),
        ({}, "doc_classification"),
    ],
)
def test_resolve_rejects(values: dict[str, Any], field: str) -> None:
    with pytest.raises(ValidationFailed) as exc:
        resolve_document(SNAPSHOT, values)
    assert exc.value.code == "FORM_VALIDATION_FAILED"
    assert isinstance(exc.value.details, dict) and field in exc.value.details


def test_resolve_challan_matched_needs_no_remarks() -> None:
    columns, _, _ = resolve_document(
        SNAPSHOT, {"doc_classification": "DELIVERY_CHALLAN", "challan_qty_matched": True}
    )
    assert columns["qty_matched"] is True and columns.get("remarks") is None
