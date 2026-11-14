"""Core fields registry for RMS versioned forms (master plan §8.3, §10, prompt P1-07).

Core fields are bound to typed columns (or planned columns in §8.4-§8.6).
Rules:
- Cannot be deleted
- Control type cannot be changed
- Cannot be made optional if system guard requires it (guarded_required=True)
- CAN be relabelled, reordered, have help text changed, and have extra validation tightened.
"""

from __future__ import annotations

from typing import NamedTuple


class CoreFieldDef(NamedTuple):
    field_key: str
    control_type: str
    guarded_required: bool = True
    system_guard: str | None = None


# Map form_code -> dict[field_key, CoreFieldDef]
FORM_CORE_FIELDS: dict[str, dict[str, CoreFieldDef]] = {
    "S1_GATE_INWARD": {
        "state": CoreFieldDef("state", "text", guarded_required=True),
        "station": CoreFieldDef("station", "text", guarded_required=True),
        "party_name": CoreFieldDef("party_name", "text", guarded_required=True),
        # Form v2 (change plan 2026-11-12, Phase 2): AMD-01 return type, AMD-03 carton count,
        # AMD-04 "no document" flag (document rows are structured, outside the form).
        "return_type": CoreFieldDef("return_type", "radio", guarded_required=True),
        "carton_count": CoreFieldDef("carton_count", "number", guarded_required=True),
        "delivery_mode": CoreFieldDef("delivery_mode", "dropdown", guarded_required=True),
        "no_document": CoreFieldDef("no_document", "checkbox", guarded_required=False),
        "gs_creation_format": CoreFieldDef("gs_creation_format", "dropdown", guarded_required=True),
    },
    "S1_UNBOXING": {
        "unboxing_video": CoreFieldDef(
            "unboxing_video", "file", guarded_required=True, system_guard="G-02"
        ),
        "doc_classification": CoreFieldDef("doc_classification", "dropdown", guarded_required=True),
        "document_photo": CoreFieldDef(
            "document_photo", "file", guarded_required=True, system_guard="G-02"
        ),
    },
    "S1_ITEMIZE": {
        "return_category": CoreFieldDef("return_category", "dropdown", guarded_required=True),
        "received_qty": CoreFieldDef("received_qty", "number", guarded_required=True),
    },
    "S1_CSR_APPROVAL": {
        "csr_approval": CoreFieldDef(
            "csr_approval", "dropdown", guarded_required=True, system_guard="G-03"
        ),
    },
    "S1_INSPECT_DMT": {
        "visual_condition": CoreFieldDef("visual_condition", "dropdown", guarded_required=True),
        "extraction_type": CoreFieldDef(
            "extraction_type", "radio", guarded_required=True, system_guard="G-07"
        ),
        "packaging_extracted_qty": CoreFieldDef(
            "packaging_extracted_qty", "number", guarded_required=True
        ),
        "container_extracted_qty": CoreFieldDef(
            "container_extracted_qty", "number", guarded_required=True
        ),
        "allocated_qty": CoreFieldDef(
            "allocated_qty", "number", guarded_required=True, system_guard="G-07"
        ),
    },
    "S1_INSPECT_PRISMATIC": {
        "visual_condition": CoreFieldDef(
            "visual_condition", "dropdown", guarded_required=True, system_guard="G-05"
        ),
        "extraction_type": CoreFieldDef(
            "extraction_type", "radio", guarded_required=True, system_guard="G-07"
        ),
        "packaging_extracted_qty": CoreFieldDef(
            "packaging_extracted_qty", "number", guarded_required=True
        ),
        "container_extracted_qty": CoreFieldDef(
            "container_extracted_qty", "number", guarded_required=True
        ),
        "allocated_qty": CoreFieldDef(
            "allocated_qty", "number", guarded_required=True, system_guard="G-07"
        ),
    },
    "S1_INSPECT_EO": {
        "inspection_protocol": CoreFieldDef(
            "inspection_protocol", "dropdown", guarded_required=True, system_guard="G-06"
        ),
        "visual_condition": CoreFieldDef(
            "visual_condition", "dropdown", guarded_required=True, system_guard="G-05"
        ),
        "extraction_type": CoreFieldDef(
            "extraction_type", "radio", guarded_required=True, system_guard="G-07"
        ),
        "packaging_extracted_qty": CoreFieldDef(
            "packaging_extracted_qty", "number", guarded_required=True
        ),
        "container_extracted_qty": CoreFieldDef(
            "container_extracted_qty", "number", guarded_required=True
        ),
        "allocated_qty": CoreFieldDef(
            "allocated_qty", "number", guarded_required=True, system_guard="G-07"
        ),
    },
    "S1_DAILY_CONTAINER_AUDIT": {
        "audit_check": CoreFieldDef("audit_check", "checkbox", guarded_required=True),
        "container_count": CoreFieldDef("container_count", "number", guarded_required=True),
        "sellable_packaging_separated": CoreFieldDef(
            "sellable_packaging_separated", "checkbox", guarded_required=True
        ),
    },
    "S1A_RM_ACTION": {
        "rm_action": CoreFieldDef(
            "rm_action", "dropdown", guarded_required=True, system_guard="G-08"
        ),
    },
    "S2_HANDOVER_INITIATE": {
        "transfer_mode": CoreFieldDef(
            "transfer_mode", "dropdown", guarded_required=True, system_guard="G-09"
        ),
        "transfer_qty": CoreFieldDef("transfer_qty", "number", guarded_required=True),
    },
    "S2_HANDOVER_ACCEPT": {
        "acceptance_status": CoreFieldDef(
            "acceptance_status", "dropdown", guarded_required=True, system_guard="G-09"
        ),
        "accepted_qty": CoreFieldDef("accepted_qty", "number", guarded_required=True),
    },
    "S3_TECH_ALLOT": {
        "assigned_technician": CoreFieldDef(
            "assigned_technician", "dropdown", guarded_required=True
        ),
        "data_entry_by": CoreFieldDef("data_entry_by", "dropdown", guarded_required=True),
        "allotted_qty": CoreFieldDef("allotted_qty", "number", guarded_required=True),
    },
    "S3_TECH_RECEIVE": {
        "battery_check": CoreFieldDef(
            "battery_check", "dropdown", guarded_required=True, system_guard="G-10"
        ),
        "cleaning_treatment": CoreFieldDef("cleaning_treatment", "dropdown", guarded_required=True),
        "post_servicing_classification": CoreFieldDef(
            "post_servicing_classification", "dropdown", guarded_required=True
        ),
    },
    "S4_DISMANTLE": {
        "part_type": CoreFieldDef(
            "part_type", "dropdown", guarded_required=True, system_guard="G-11"
        ),
        "parts_storage_separation": CoreFieldDef(
            "parts_storage_separation", "dropdown", guarded_required=True
        ),
        "scrap_disposal_marked": CoreFieldDef(
            "scrap_disposal_marked", "checkbox", guarded_required=True
        ),
    },
    "S5_SEGREGATE": {
        "custody_assignment": CoreFieldDef(
            "custody_assignment", "dropdown", guarded_required=True, system_guard="G-12"
        ),
        "storage_location_id": CoreFieldDef("storage_location_id", "text", guarded_required=True),
    },
    "S6_STORE_ISSUE": {
        "store_issue_type": CoreFieldDef("store_issue_type", "dropdown", guarded_required=True),
        "issue_qty": CoreFieldDef("issue_qty", "number", guarded_required=True),
        "main_store_inward_ref": CoreFieldDef(
            "main_store_inward_ref", "text", guarded_required=True
        ),
    },
    "S6_CN_DECISION": {
        "rm_cn_decision": CoreFieldDef(
            "rm_cn_decision", "dropdown", guarded_required=True, system_guard="G-13"
        ),
    },
    "S6_ACCOUNTS_CN": {
        "party_doc_verification": CoreFieldDef(
            "party_doc_verification", "dropdown", guarded_required=True
        ),
        "gst_portal_verification": CoreFieldDef(
            "gst_portal_verification", "dropdown", guarded_required=True, system_guard="G-13"
        ),
        "cn_type": CoreFieldDef("cn_type", "dropdown", guarded_required=True, system_guard="G-13"),
        "rate_verification_ref": CoreFieldDef(
            "rate_verification_ref", "dropdown", guarded_required=True, system_guard="G-14"
        ),
        "verified_rate": CoreFieldDef("verified_rate", "number", guarded_required=True),
        "cn_number": CoreFieldDef("cn_number", "text", guarded_required=True),
        "cn_date": CoreFieldDef("cn_date", "date", guarded_required=True),
        "cn_valuation": CoreFieldDef("cn_valuation", "number", guarded_required=True),
    },
    "S6_PARTY_NOTIFY": {
        "party_notification_status": CoreFieldDef(
            "party_notification_status", "dropdown", guarded_required=True, system_guard="G-15"
        ),
        "notification_sent_date": CoreFieldDef(
            "notification_sent_date", "date", guarded_required=True
        ),
        "notification_mode": CoreFieldDef("notification_mode", "text", guarded_required=True),
    },
    "S6_CSR_CLOSE": {
        "csr_final_status": CoreFieldDef(
            "csr_final_status", "dropdown", guarded_required=True, system_guard="G-15"
        ),
        "closure_checklist_confirmed": CoreFieldDef(
            "closure_checklist_confirmed", "checkbox", guarded_required=True
        ),
    },
}


def get_core_field_def(form_code: str, field_key: str) -> CoreFieldDef | None:
    return FORM_CORE_FIELDS.get(form_code, {}).get(field_key)


def is_form_core_field(form_code: str, field_key: str) -> bool:
    return field_key in FORM_CORE_FIELDS.get(form_code, {})
