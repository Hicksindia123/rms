"""Service for print templates configuration, versioning, and sample data (prompt P1-08)."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from app.core.context import get_request_id
from app.core.db import UnitOfWork
from app.core.errors import NotFound, ValidationFailed
from app.core.security import CurrentUser
from app.modules.config.options import repository as options_repo
from app.modules.config.templates.schemas import (
    PrintTemplateOut,
    PrintTemplatePublishRequest,
    PrintTemplateSampleDataOut,
    PrintTemplateUpdate,
)

SAMPLE_DATA_REGISTRY: dict[str, dict[str, Any]] = {
    "REPLACEMENT_SLIP": {
        "sample_data": {
            "is_sample_preview": True,
            "gs_no": "GS/2026-27/00042",
            "party_name": "Acme Healthcare Diagnostics (SAMPLE PREVIEW)",
            "date": "15-Apr-2026",
            "box_count": 3,
            "delivery_mode": "Courier / Parcel",
            "items": [
                {
                    "line_no": 1,
                    "product_name": "Digital Clinical Thermometer (DMT-01)",
                    "received_qty": 50,
                    "action_code": "SEND_NEW",
                    "remarks": "Clean batch replacement authorised",
                },
                {
                    "line_no": 2,
                    "product_name": "Prismatic Clinical Thermometer",
                    "received_qty": 20,
                    "action_code": "ISSUE_CN",
                    "remarks": "Discontinued model credit note",
                },
            ],
            "prepared_by": "Aman (Inward Verifier)",
            "replacement_manager_sign": "Pratham Pratap Singh (RM)",
        },
        "data_dictionary": [
            {"field": "gs_no", "description": "Goods Slip Number"},
            {"field": "party_name", "description": "Returning customer or distributor name"},
            {"field": "date", "description": "Consignment creation date"},
            {"field": "box_count", "description": "Total boxes received"},
            {"field": "delivery_mode", "description": "Transport mode at gate inward"},
            {"field": "items", "description": "Array of item actions decided by RM"},
            {"field": "prepared_by", "description": "Name of unboxing verifier"},
            {
                "field": "replacement_manager_sign",
                "description": "Signature line of Replacement Manager",
            },
        ],
    },
    # Change plan Phase 7 (AMD-17, DEC-41): server-side PDF; these are the fields it prints.
    "AC_ACTIONS_SLIP": {
        "sample_data": {
            "is_sample_preview": True,
            "slip_no": "RSA/2026-27/00001",
            "version_no": 1,
            "gs_no": "GS/2026-27/00042",
            "gs_date": "15-04-2026",
            "return_type": "Offline Return",
            "carton_count": 3,
            "party_name": "Acme Healthcare Diagnostics (SAMPLE PREVIEW)",
            "party_code": "P-0042",
            "state_station": "Uttar Pradesh / Agra",
            "gate_entry_no": "1042",
            "gate_entry_date": "14-04-2026",
            "gate_documents": ["Invoice INV-778 14-04-2026", "Courier Slip CS-91"],
            "lines": [
                {
                    "line_no": 1,
                    "product_code": "DMT-01",
                    "product_name": "Digital Clinical Thermometer",
                    "counted_qty": 10,
                    "action_label": "Send New",
                    "qty": 6,
                },
                {
                    "line_no": 1,
                    "product_code": "DMT-01",
                    "product_name": "Digital Clinical Thermometer",
                    "counted_qty": 10,
                    "action_label": "Send Repaired",
                    "qty": 3,
                },
                {
                    "line_no": 1,
                    "product_code": "DMT-01",
                    "product_name": "Digital Clinical Thermometer",
                    "counted_qty": 10,
                    "action_label": "Issue CN",
                    "qty": 1,
                },
            ],
            "totals": {"total_qty": 10},
            "prepared_by": "Pratham Pratap Singh (RM)",
        },
        "data_dictionary": [
            {"field": "slip_no", "description": "A/c Actions slip number (series AC_ACTION_SLIP)"},
            {"field": "version_no", "description": "Slip version; a revision supersedes it"},
            {"field": "gs_no", "description": "Goods Slip Number"},
            {"field": "gs_date", "description": "Goods slip creation date"},
            {"field": "return_type", "description": "Offline / E-Commerce return (AMD-01)"},
            {"field": "carton_count", "description": "Cartons received (AMD-03)"},
            {"field": "party_name", "description": "Party (distributor) name"},
            {"field": "state_station", "description": "State and station"},
            {"field": "gate_entry_no", "description": "Gate entry number (Offline, AMD-02)"},
            {"field": "gate_entry_date", "description": "Gate entry date (Offline, AMD-02)"},
            {"field": "gate_documents", "description": "Gate / carton-opening documents"},
            {"field": "lines", "description": "Item x action x qty rows (AMD-16)"},
            {"field": "totals", "description": "Totals by action"},
            {"field": "prepared_by", "description": "Replacement Manager who finalised"},
        ],
    },
    # Change plan Phase 8 (AMD-19, DEC-41): server-side PDF; these are the fields it prints.
    "DISPATCH_SLIP": {
        "sample_data": {
            "is_sample_preview": True,
            "slip_no": "DS/2026-27/00001",
            "gs_no": "GS/2026-27/00042",
            "ac_slip_no": "RSA/2026-27/00001",
            "ac_version_no": 1,
            "party_name": "Acme Healthcare Diagnostics (SAMPLE PREVIEW)",
            "party_code": "P-0042",
            "state_station": "Uttar Pradesh / Agra",
            "generated_at": "16-04-2026 11:30",
            "lines": [
                {
                    "line_no": 1,
                    "product_code": "DMT-01",
                    "product_name": "Digital Clinical Thermometer",
                    "action_label": "Send New",
                    "qty": 6,
                    "challan_no": "CH-2041",
                    "challan_date": "16-04-2026",
                },
                {
                    "line_no": 1,
                    "product_code": "DMT-01",
                    "product_name": "Digital Clinical Thermometer",
                    "action_label": "Send Repaired",
                    "qty": 3,
                    "challan_no": "CH-2041",
                    "challan_date": "16-04-2026",
                },
            ],
            "total_qty": 9,
            "prepared_by": "Accounts (SAMPLE PREVIEW)",
        },
        "data_dictionary": [
            {"field": "slip_no", "description": "Dispatch Slip number (series DISPATCH_SLIP)"},
            {"field": "gs_no", "description": "Goods Slip Number"},
            {"field": "ac_slip_no", "description": "A/c Actions slip the entry was made on"},
            {"field": "party_name", "description": "Party (ship to)"},
            {"field": "state_station", "description": "State and station"},
            {"field": "generated_at", "description": "When Accounts completed the entry"},
            {"field": "lines", "description": "Goods-shipping action lines with challan (AMD-19)"},
            {"field": "total_qty", "description": "Total pieces to ship"},
            {"field": "prepared_by", "description": "Accounts user who completed the entry"},
        ],
    },
    "GS_TAG": {
        "sample_data": {
            "is_sample_preview": True,
            "gs_no": "GS/2026-27/00042",
            "qr_code": "RMS:GS/2026-27/00042:DEMO",
            "party_name": "Acme Healthcare Diagnostics",
            "state_station": "Uttar Pradesh / Agra",
            "carton_count": 3,
            "return_type": "Offline Return",
            "gate_entry_no": "1042",
            "received_date": "15-Apr-2026",
            "transporter": "SafeXpress (Docket: SFX99182)",
        },
        "data_dictionary": [
            {"field": "gs_no", "description": "Goods Slip identification code"},
            {"field": "qr_code", "description": "Scannable QR payload for mobile verification"},
            {"field": "party_name", "description": "Party master name"},
            {"field": "state_station", "description": "State and station location"},
            {"field": "carton_count", "description": "Number of cartons received (AMD-03)"},
            {"field": "return_type", "description": "Offline / E-Commerce return (AMD-01)"},
            {"field": "gate_entry_no", "description": "Gate entry number, Offline only (AMD-02)"},
            {"field": "received_date", "description": "Date received at gate"},
            {"field": "transporter", "description": "Courier or transporter info"},
        ],
    },
    # Phase P5 (DEC-65): server-side PDF of the Intermediate Store transfer slip.
    "TRANSFER_SLIP": {
        "sample_data": {
            "is_sample_preview": True,
            "slip_no": "TRF/OP/2026-27/0001",
            "store_name": "Intermediate Store OP",
            "generated_at": "21-11-2026 11:30",
            "generated_by": "Replacement Manager (SAMPLE PREVIEW)",
            "goods_slips": [
                {
                    "gs_no": "GS/2026-27/00042",
                    "party_name": "Acme Healthcare Diagnostics (SAMPLE PREVIEW)",
                    "station_name": "Agra",
                    "state_name": "Uttar Pradesh",
                    "cartons": 3,
                    "received_date": "18-11-2026",
                }
            ],
            "relevant": [
                {
                    "line_no": 1,
                    "product_code": "EO-01",
                    "product_name": "Enclosed Oval Thermometer",
                    "condition": "Broken body",
                    "qty": 4,
                }
            ],
            "others": [
                {
                    "line_no": 2,
                    "product_name": "Digital Thermometer",
                    "condition": "Not working",
                    "qty": 2,
                    "store_name": "Intermediate Store DT",
                }
            ],
            "relevant_qty": 4,
            "grand_total_qty": 6,
        },
        "data_dictionary": [
            {"field": "slip_no", "description": "Transfer Slip number (series TRANSFER_SLIP)"},
            {"field": "store_name", "description": "Intermediate Store the slip is addressed to"},
            {"field": "generated_at", "description": "When the RM generated the slip"},
            {"field": "generated_by", "description": "Replacement Manager who generated it"},
            {"field": "goods_slips", "description": "GS block per goods slip on the slip"},
            {"field": "relevant", "description": "Items for this store, per GS (with subtotal)"},
            {"field": "others", "description": "Other items of these GSs (greyed, other store)"},
            {"field": "relevant_qty", "description": "Total relevant qty (this store)"},
            {"field": "grand_total_qty", "description": "All items of the included GSs"},
        ],
    },
    "TRANSFER_NOTE": {
        "sample_data": {
            "is_sample_preview": True,
            "transfer_no": "TRF/2026-27/00018",
            "date": "15-Apr-2026",
            "from_location": "Gate Inward Unboxing Bay",
            "to_location": "Intermediate Store Bay-02",
            "mode": "Physical Movement & Digital Transfer",
            "lines": [
                {
                    "lot_id": "LOT-2026-00101",
                    "product_name": "Digital Thermometer DMT",
                    "condition": "VISUALLY OKAY and PACKED",
                    "qty_sent": 50,
                    "qty_counted": 50,
                }
            ],
            "status": "ACCEPTED_VERIFIED",
            "discrepancy_notes": "None - physical and digital counts match",
        },
        "data_dictionary": [
            {"field": "transfer_no", "description": "Custody transfer document reference"},
            {"field": "date", "description": "Transfer initiation date"},
            {"field": "from_location", "description": "Originating location bay"},
            {"field": "to_location", "description": "Destination store bay"},
            {"field": "mode", "description": "Custody transfer mode code"},
            {"field": "lines", "description": "Allocated inventory lots and counts"},
            {"field": "status", "description": "Accepted or Discrepancy status"},
            {
                "field": "discrepancy_notes",
                "description": "Reconciliation remarks if count mismatch",
            },
        ],
    },
    "STORE_ISSUE": {
        "sample_data": {
            "is_sample_preview": True,
            "issue_no": "SI/2026-27/00007",
            "date": "16-Apr-2026",
            "from_store": "Intermediate Store (Sahil)",
            "to_store": "Main Store (Sahil / Main Store In-charge)",
            "issued_by": "Sahil",
            "lots": [
                {
                    "line_no": 1,
                    "product_name": "Digital Thermometer DMT",
                    "lot_code": "LOT-FG-0091",
                    "condition_class": "FUNCTIONAL_GOOD",
                    "quantity": 50,
                }
            ],
            "receipt": {
                "acknowledged_by": "Sahil",
                "acknowledged_at": "16-Apr-2026 14:30",
                "notes": "Goods received in full with sellable packaging",
            },
        },
        "data_dictionary": [
            {"field": "issue_no", "description": "Store issue number"},
            {"field": "date", "description": "Store issue timestamp"},
            {"field": "from_store", "description": "Intermediate store originating lot"},
            {"field": "to_store", "description": "Main store receiving location"},
            {"field": "issued_by", "description": "Issuer profile"},
            {"field": "lots", "description": "Stock lots issued"},
            {"field": "receipt", "description": "Main store inward acknowledgement details"},
        ],
    },
    "CN_SUMMARY": {
        "sample_data": {
            "is_sample_preview": True,
            "gs_no": "GS/2026-27/00042",
            "party_name": "Acme Healthcare Diagnostics",
            "party_gstin": "09AAACH7409R1ZZ",
            "party_doc_no": "DN/2026/0411",
            "party_doc_date": "10-Apr-2026",
            "gst_portal_status": "Return Reflected on GST Portal (GSTR-2B)",
            "return_period": "March 2026",
            "verified_rate": "145.50 INR",
            "rate_ref_doc": "INV-2025-9981 dated 12-Nov-2025",
            "cn_type": "GST CREDIT NOTE",
            "cn_no": "CN/2026-27/0012",
            "cn_date": "16-Apr-2026",
            "jv_no": "JV/2026-27/0091",
            "taxable_value": 7275.00,
            "tax_breakup": "CGST 6%: 436.50, SGST 6%: 436.50",
            "total_amount": 8148.00,
            "prior_info_sent": True,
            "notification_date": "16-Apr-2026 16:00",
            "channel": "Email & WhatsApp with CN Copy",
        },
        "data_dictionary": [
            {"field": "gs_no", "description": "Goods Slip reference"},
            {"field": "party_name", "description": "Party commercial entity name"},
            {"field": "party_gstin", "description": "Customer GSTIN"},
            {"field": "party_doc_no", "description": "Debit Note or Invoice reference"},
            {
                "field": "gst_portal_status",
                "description": "Reflected vs Not Reflected portal checkpoint",
            },
            {
                "field": "verified_rate",
                "description": "Historical sales rate verified by Deepak Ji",
            },
            {"field": "cn_type", "description": "GST CN vs General CN vs JV Only"},
            {"field": "cn_no", "description": "Accounts Credit Note voucher number"},
            {"field": "total_amount", "description": "Total credited amount including GST"},
            {
                "field": "prior_info_sent",
                "description": "Mandatory prior party communication confirmation",
            },
        ],
    },
}


class PrintTemplatesService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    def list_templates(self, user: CurrentUser) -> list[PrintTemplateOut]:
        with self._uow.transaction(user.id) as session:
            rows = session.execute(
                text(
                    """
                    select pt.* from public.print_templates pt
                    where pt.status = 'PUBLISHED'
                    order by pt.code asc
                    """
                )
            ).mappings()
            return [PrintTemplateOut.model_validate(dict(r)) for r in rows]

    def get_published_template(self, code: str) -> PrintTemplateOut:
        with self._uow.transaction() as session:
            row = (
                session.execute(
                    text(
                        """
                    select pt.* from public.print_templates pt
                    where pt.code = :code and pt.status = 'PUBLISHED'
                    limit 1
                    """
                    ),
                    {"code": code},
                )
                .mappings()
                .first()
            )
            if not row:
                raise NotFound(f"No published template found for code '{code}'")
            return PrintTemplateOut.model_validate(dict(row))

    def get_template_version(
        self, user: CurrentUser, code: str, version_no: int
    ) -> PrintTemplateOut:
        with self._uow.transaction(user.id) as session:
            row = (
                session.execute(
                    text(
                        """
                    select pt.* from public.print_templates pt
                    where pt.code = :code and pt.version_no = :vno
                    """
                    ),
                    {"code": code, "vno": version_no},
                )
                .mappings()
                .first()
            )
            if not row:
                raise NotFound(f"Template '{code}' version {version_no} not found")
            return PrintTemplateOut.model_validate(dict(row))

    def create_draft(self, user: CurrentUser, code: str) -> PrintTemplateOut:
        with self._uow.transaction(user.id) as session:
            existing_draft = (
                session.execute(
                    text(
                        """
                        select pt.* from public.print_templates pt
                        where pt.code = :code and pt.status = 'DRAFT'
                        """
                    ),
                    {"code": code},
                )
                .mappings()
                .first()
            )
            if existing_draft:
                return PrintTemplateOut.model_validate(dict(existing_draft))

            published = self.get_published_template(code)
            new_vno = published.version_no + 1

            row = (
                session.execute(
                    text(
                        """
                    insert into public.print_templates (code, name, version_no, status, layout)
                    values (:code, :name, :vno, 'DRAFT', cast(:layout as jsonb))
                    returning *
                    """
                    ),
                    {
                        "code": code,
                        "name": published.name,
                        "vno": new_vno,
                        "layout": json.dumps(published.layout),
                    },
                )
                .mappings()
                .first()
            )
            if not row:
                raise NotFound(f"Failed to create draft for '{code}'")
            return PrintTemplateOut.model_validate(dict(row))

    def update_draft(
        self, user: CurrentUser, code: str, payload: PrintTemplateUpdate
    ) -> PrintTemplateOut:
        with self._uow.transaction(user.id) as session:
            draft = (
                session.execute(
                    text(
                        """
                        select pt.* from public.print_templates pt
                        where pt.code = :code and pt.status = 'DRAFT'
                        """
                    ),
                    {"code": code},
                )
                .mappings()
                .first()
            )
            if not draft:
                raise NotFound(f"No active draft found for template '{code}'")

            row = (
                session.execute(
                    text(
                        """
                    update public.print_templates
                    set name = coalesce(:name, name),
                        layout = cast(:layout as jsonb),
                        updated_at = now()
                    where id = :id
                    returning *
                    """
                    ),
                    {
                        "id": draft["id"],
                        "name": payload.name,
                        "layout": json.dumps(payload.layout),
                    },
                )
                .mappings()
                .first()
            )
            if not row:
                raise NotFound(f"Failed to update draft for '{code}'")
            return PrintTemplateOut.model_validate(dict(row))

    def publish_draft(
        self, user: CurrentUser, code: str, payload: PrintTemplatePublishRequest
    ) -> PrintTemplateOut:
        if not payload.reason or len(payload.reason.strip()) < 3:
            raise ValidationFailed(
                "A non-empty reason is required to publish a print template version."
            )

        with self._uow.transaction(user.id) as session:
            draft = (
                session.execute(
                    text(
                        """
                        select pt.* from public.print_templates pt
                        where pt.code = :code and pt.status = 'DRAFT'
                        """
                    ),
                    {"code": code},
                )
                .mappings()
                .first()
            )
            if not draft:
                raise NotFound(f"No active draft found for template '{code}'")

            # Retire current published
            session.execute(
                text(
                    """
                    update public.print_templates
                    set status = 'RETIRED', updated_at = now()
                    where code = :code and status = 'PUBLISHED'
                    """
                ),
                {"code": code},
            )

            # Publish draft
            pub_row = (
                session.execute(
                    text(
                        """
                    update public.print_templates
                    set status = 'PUBLISHED',
                        snapshot = layout,
                        published_by = :uid,
                        published_at = now(),
                        updated_at = now()
                    where id = :id
                    returning *
                    """
                    ),
                    {"id": draft["id"], "uid": user.id},
                )
                .mappings()
                .first()
            )

            # Audit to config_change_log
            options_repo.log_config_change(
                session=session,
                entity_type="print_template",
                entity_id=code,
                action="PUBLISH_PRINT_TEMPLATE",
                before=None,
                after={"code": code, "version_no": draft["version_no"]},
                reason=payload.reason,
                request_id=get_request_id(),
            )

            if not pub_row:
                raise NotFound(f"Failed to publish template '{code}'")
            return PrintTemplateOut.model_validate(dict(pub_row))

    def get_sample_data(self, code: str) -> PrintTemplateSampleDataOut:
        info = SAMPLE_DATA_REGISTRY.get(code)
        if not info:
            raise NotFound(f"No sample data found for template '{code}'")
        return PrintTemplateSampleDataOut(
            code=code,
            sample_data=info["sample_data"],
            data_dictionary=info["data_dictionary"],
        )
