"""Generator for migration 20261102000900_seed_v1_forms.sql.

Seeds published v1 forms for all 20 workflow steps (master plan §3.2, §8.3, §10, prompt P1-07).
"""

import json

FORMS = [
    {
        "code": "S1_GATE_INWARD",
        "step_code": "S1_GATE",
        "name": "Gate Inward & GS Creation",
        "fields": [
            {"key": "state", "label": "State", "type": "text", "core": True, "req": True, "sort": 10, "sec": "Consignment Header"},
            {"key": "station", "label": "Station", "type": "text", "core": True, "req": True, "sort": 20, "sec": "Consignment Header"},
            {"key": "party_name", "label": "Party Name", "type": "text", "core": True, "req": True, "sort": 30, "sec": "Consignment Header"},
            {"key": "box_count", "label": "Box Count", "type": "number", "core": True, "req": True, "sort": 40, "sec": "Consignment Header", "val": {"min": 1}},
            {"key": "delivery_mode", "label": "Delivery Mode / Transporter", "type": "dropdown", "opt_set": "DELIVERY_MODE", "core": True, "req": True, "sort": 50, "sec": "Delivery Details"},
            {"key": "courier_name", "label": "Courier Name", "type": "text", "core": False, "req": False, "sort": 60, "sec": "Delivery Details", "vw": {"field": "delivery_mode", "op": "eq", "value": "COURIER_PARCEL"}, "rw": {"field": "delivery_mode", "op": "eq", "value": "COURIER_PARCEL"}},
            {"key": "docket_no", "label": "Docket Number", "type": "text", "core": False, "req": False, "sort": 70, "sec": "Delivery Details", "vw": {"field": "delivery_mode", "op": "eq", "value": "COURIER_PARCEL"}, "rw": {"field": "delivery_mode", "op": "eq", "value": "COURIER_PARCEL"}},
            {"key": "vehicle_no", "label": "Vehicle Number", "type": "text", "core": False, "req": False, "sort": 80, "sec": "Delivery Details", "vw": {"field": "delivery_mode", "op": "eq", "value": "DIRECT_TRUCK"}, "rw": {"field": "delivery_mode", "op": "eq", "value": "DIRECT_TRUCK"}},
            {"key": "transporter_name", "label": "Transporter Name", "type": "text", "core": False, "req": False, "sort": 90, "sec": "Delivery Details", "vw": {"field": "delivery_mode", "op": "eq", "value": "DIRECT_TRUCK"}, "rw": {"field": "delivery_mode", "op": "eq", "value": "DIRECT_TRUCK"}},
            {"key": "rep_name", "label": "Representative Name", "type": "text", "core": False, "req": False, "sort": 100, "sec": "Delivery Details", "vw": {"field": "delivery_mode", "op": "eq", "value": "SELF_PARTY_REP"}, "rw": {"field": "delivery_mode", "op": "eq", "value": "SELF_PARTY_REP"}},
            {"key": "rep_contact", "label": "Representative Contact No.", "type": "text", "core": False, "req": False, "sort": 110, "sec": "Delivery Details", "vw": {"field": "delivery_mode", "op": "eq", "value": "SELF_PARTY_REP"}, "rw": {"field": "delivery_mode", "op": "eq", "value": "SELF_PARTY_REP"}},
            {"key": "accompanying_doc", "label": "Accompanying Document at Gate", "type": "dropdown", "opt_set": "GATE_DOCUMENT", "core": True, "req": True, "sort": 120, "sec": "Documentation"},
            {"key": "gate_doc_no", "label": "Gate Document Number", "type": "text", "core": False, "req": False, "sort": 130, "sec": "Documentation", "vw": {"field": "accompanying_doc", "op": "in", "value": ["INVOICE", "DEBIT_NOTE", "DELIVERY_CHALLAN"]}, "rw": {"field": "accompanying_doc", "op": "in", "value": ["INVOICE", "DEBIT_NOTE", "DELIVERY_CHALLAN"]}},
            {"key": "gate_doc_date", "label": "Gate Document Date", "type": "date", "core": False, "req": False, "sort": 140, "sec": "Documentation", "vw": {"field": "accompanying_doc", "op": "in", "value": ["INVOICE", "DEBIT_NOTE", "DELIVERY_CHALLAN"]}, "rw": {"field": "accompanying_doc", "op": "in", "value": ["INVOICE", "DEBIT_NOTE", "DELIVERY_CHALLAN"]}, "val": {"date_not_in_future": True}},
            {"key": "gate_doc_remarks", "label": "Slip Remarks / Party Note", "type": "textarea", "core": False, "req": False, "sort": 150, "sec": "Documentation", "vw": {"field": "accompanying_doc", "op": "eq", "value": "HANDWRITTEN_SLIP"}, "rw": {"field": "accompanying_doc", "op": "eq", "value": "HANDWRITTEN_SLIP"}},
            {"key": "missing_doc_warning_acknowledged", "label": "Missing documentation warning acknowledged", "type": "checkbox", "core": False, "req": False, "sort": 160, "sec": "Documentation", "vw": {"field": "accompanying_doc", "op": "eq", "value": "NO_DOCUMENT"}, "rw": {"field": "accompanying_doc", "op": "eq", "value": "NO_DOCUMENT"}},
            {"key": "gs_creation_format", "label": "GS Creation Format", "type": "dropdown", "opt_set": "GS_CREATION_FORMAT", "core": True, "req": True, "sort": 170, "sec": "System Generation", "def": "AUTO_STANDARD"},
        ],
    },
    {
        "code": "S1_UNBOXING",
        "step_code": "S1_UNBOX",
        "name": "Unboxing & Document Capture",
        "fields": [
            {"key": "unboxing_video", "label": "Continuous Unboxing Video File (.mp4 / .mov)", "type": "file", "opt_set": "UNBOXING_VIDEO", "core": True, "req": True, "sort": 10, "sec": "Video Recording", "val": {"file_types": [".mp4", ".mov"], "max_file_size": 209715200}},
            {"key": "doc_classification", "label": "Received Document Classification", "type": "dropdown", "opt_set": "RECEIVED_DOC_CLASSIFICATION", "core": True, "req": True, "sort": 20, "sec": "Document Verification"},
            {"key": "buyer_gstin", "label": "Buyer GSTIN", "type": "text", "core": False, "req": False, "sort": 30, "sec": "Document Verification", "vw": {"field": "doc_classification", "op": "eq", "value": "INVOICE"}, "rw": {"field": "doc_classification", "op": "eq", "value": "INVOICE"}, "val": {"regex": "^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$"}},
            {"key": "seller_gstin", "label": "Seller GSTIN", "type": "text", "core": False, "req": False, "sort": 40, "sec": "Document Verification", "vw": {"field": "doc_classification", "op": "eq", "value": "INVOICE"}, "rw": {"field": "doc_classification", "op": "eq", "value": "INVOICE"}, "val": {"regex": "^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$"}},
            {"key": "dn_number", "label": "Debit Note Number", "type": "text", "core": False, "req": False, "sort": 50, "sec": "Document Verification", "vw": {"field": "doc_classification", "op": "eq", "value": "DEBIT_NOTE"}, "rw": {"field": "doc_classification", "op": "eq", "value": "DEBIT_NOTE"}},
            {"key": "dn_amount", "label": "Debit Note Amount", "type": "number", "core": False, "req": False, "sort": 60, "sec": "Document Verification", "vw": {"field": "doc_classification", "op": "eq", "value": "DEBIT_NOTE"}, "rw": {"field": "doc_classification", "op": "eq", "value": "DEBIT_NOTE"}, "val": {"min": 0}},
            {"key": "challan_qty_matched", "label": "Challan quantity matched against parcel contents", "type": "checkbox", "core": False, "req": False, "sort": 70, "sec": "Document Verification", "vw": {"field": "doc_classification", "op": "eq", "value": "DELIVERY_CHALLAN"}, "rw": {"field": "doc_classification", "op": "eq", "value": "DELIVERY_CHALLAN"}},
            {"key": "party_claim_text", "label": "Party Claim / Complaint Details", "type": "textarea", "core": False, "req": False, "sort": 80, "sec": "Document Verification", "vw": {"field": "doc_classification", "op": "eq", "value": "HANDWRITTEN_SLIP"}, "rw": {"field": "doc_classification", "op": "eq", "value": "HANDWRITTEN_SLIP"}},
            {"key": "document_photo", "label": "Document Photo Image (.jpg / .png / .pdf)", "type": "file", "opt_set": "DOCUMENT_PHOTO", "core": True, "req": True, "sort": 90, "sec": "Document Verification", "val": {"file_types": [".jpg", ".jpeg", ".png", ".pdf"], "max_file_size": 20971520}},
        ],
    },
    {
        "code": "S1_ITEMIZE",
        "step_code": "S1_ITEMIZE",
        "name": "Item Addition & Return Categorization",
        "fields": [
            {"key": "return_category", "label": "Return Categorization (GS Wise)", "type": "dropdown", "opt_set": "RETURN_CATEGORY", "core": True, "req": True, "sort": 10, "sec": "Categorization"},
            {"key": "received_qty", "label": "Received Quantity", "type": "number", "core": True, "req": True, "sort": 20, "sec": "Quantities", "val": {"min": 1}},
            {"key": "item_notes", "label": "Itemization Remarks / Observations", "type": "textarea", "core": False, "req": False, "sort": 30, "sec": "Notes"},
        ],
    },
    {
        "code": "S1_CSR_APPROVAL",
        "step_code": "S1_CSR_APPROVAL",
        "name": "Complete Sales Return Approval",
        "fields": [
            {"key": "csr_approval", "label": "Complete Sales Return Approval", "type": "dropdown", "opt_set": "CSR_APPROVAL", "core": True, "req": True, "sort": 10, "sec": "Approval"},
            {"key": "rm_approval_notes", "label": "Manager Check & Approval Remarks", "type": "textarea", "core": False, "req": False, "sort": 20, "sec": "Approval"},
        ],
    },
    {
        "code": "S1_INSPECT_DMT",
        "step_code": "S1_INSPECT",
        "name": "DMT Visual Inspection & Grading",
        "fields": [
            {"key": "visual_condition", "label": "DMT Visual Condition", "type": "dropdown", "opt_set": "DMT_CONDITION", "core": True, "req": True, "sort": 10, "sec": "Grading"},
            {"key": "discrepancy_count", "label": "Discrepancy Short Count", "type": "number", "core": False, "req": False, "sort": 20, "sec": "Grading", "vw": {"field": "visual_condition", "op": "eq", "value": "DMT_SHORT_QTY"}, "rw": {"field": "visual_condition", "op": "eq", "value": "DMT_SHORT_QTY"}, "val": {"min": 1}},
            {"key": "extraction_type", "label": "DMT Extraction Type", "type": "radio", "opt_set": "DMT_EXTRACTION_TYPE", "core": True, "req": True, "sort": 30, "sec": "Extraction Reconciliation"},
            {"key": "packaging_extracted_qty", "label": "Packaging Extracted Quantity", "type": "number", "core": True, "req": True, "sort": 40, "sec": "Extraction Reconciliation", "def": 0, "val": {"min": 0}},
            {"key": "container_extracted_qty", "label": "Container Extracted Quantity", "type": "number", "core": True, "req": True, "sort": 50, "sec": "Extraction Reconciliation", "def": 0, "val": {"min": 0}},
            {"key": "allocated_qty", "label": "Total Allocated Quantity", "type": "number", "core": True, "req": True, "sort": 60, "sec": "Extraction Reconciliation", "val": {"min": 1, "cross_field_sums": {"sum_equals": {"fields": ["packaging_extracted_qty", "container_extracted_qty"], "target": "allocated_qty"}}}},
        ],
    },
    {
        "code": "S1_INSPECT_PRISMATIC",
        "step_code": "S1_INSPECT",
        "name": "Prismatic Inspection & Grading",
        "fields": [
            {"key": "visual_condition", "label": "Prismatic Visual Condition", "type": "dropdown", "opt_set": "PRISMATIC_CONDITION", "core": True, "req": True, "sort": 10, "sec": "Grading"},
            {"key": "extraction_type", "label": "Prismatic Extraction Type", "type": "radio", "opt_set": "PRISMATIC_EXTRACTION_TYPE", "core": True, "req": True, "sort": 20, "sec": "Extraction Reconciliation"},
            {"key": "packaging_extracted_qty", "label": "Packaging Extracted Quantity", "type": "number", "core": True, "req": True, "sort": 30, "sec": "Extraction Reconciliation", "def": 0, "val": {"min": 0}},
            {"key": "container_extracted_qty", "label": "Container Extracted Quantity", "type": "number", "core": True, "req": True, "sort": 40, "sec": "Extraction Reconciliation", "def": 0, "val": {"min": 0}},
            {"key": "allocated_qty", "label": "Total Allocated Quantity", "type": "number", "core": True, "req": True, "sort": 50, "sec": "Extraction Reconciliation", "val": {"min": 1, "cross_field_sums": {"sum_equals": {"fields": ["packaging_extracted_qty", "container_extracted_qty"], "target": "allocated_qty"}}}},
        ],
    },
    {
        "code": "S1_INSPECT_EO",
        "step_code": "S1_INSPECT",
        "name": "Enclosed Oval Inspection & Grading",
        "fields": [
            {"key": "inspection_protocol", "label": "Inspection Protocol", "type": "dropdown", "opt_set": "EO_INSPECTION_PROTOCOL", "core": True, "req": True, "sort": 10, "sec": "Protocol"},
            {"key": "visual_condition", "label": "Enclosed Oval Visual Condition", "type": "dropdown", "opt_set": "EO_CONDITION", "core": True, "req": True, "sort": 20, "sec": "Grading"},
            {"key": "extraction_type", "label": "Enclosed Oval Extraction Type", "type": "radio", "opt_set": "EO_EXTRACTION_TYPE", "core": True, "req": True, "sort": 30, "sec": "Extraction Reconciliation"},
            {"key": "packaging_extracted_qty", "label": "Packaging Extracted Quantity", "type": "number", "core": True, "req": True, "sort": 40, "sec": "Extraction Reconciliation", "def": 0, "val": {"min": 0}},
            {"key": "container_extracted_qty", "label": "Container Extracted Quantity", "type": "number", "core": True, "req": True, "sort": 50, "sec": "Extraction Reconciliation", "def": 0, "val": {"min": 0}},
            {"key": "allocated_qty", "label": "Total Allocated Quantity", "type": "number", "core": True, "req": True, "sort": 60, "sec": "Extraction Reconciliation", "val": {"min": 1, "cross_field_sums": {"sum_equals": {"fields": ["packaging_extracted_qty", "container_extracted_qty"], "target": "allocated_qty"}}}},
        ],
    },
    {
        "code": "S1_DAILY_CONTAINER_AUDIT",
        "step_code": "S1_INSPECT",
        "name": "Daily Container Audit",
        "fields": [
            {"key": "audit_check", "label": "Containers Checked & Counted Daily", "type": "checkbox", "opt_set": "DAILY_CONTAINER_AUDIT", "core": True, "req": True, "sort": 10, "sec": "Audit Verification"},
            {"key": "container_count", "label": "Total DMT Containers Counted", "type": "number", "core": True, "req": True, "sort": 20, "sec": "Audit Verification", "val": {"min": 0}},
            {"key": "sellable_packaging_separated", "label": "Sellable packaging separated", "type": "checkbox", "core": True, "req": True, "sort": 30, "sec": "Audit Verification"},
            {"key": "audit_notes", "label": "Audit Notes & Observations", "type": "textarea", "core": False, "req": False, "sort": 40, "sec": "Audit Verification"},
        ],
    },
    {
        "code": "S1A_RM_ACTION",
        "step_code": "S1A_RM_ACTION",
        "name": "RM Item-wise Actions",
        "fields": [
            {"key": "rm_action", "label": "Item-wise RM action", "type": "dropdown", "opt_set": "RM_ITEM_ACTION", "core": True, "req": True, "sort": 10, "sec": "RM Decision"},
            {"key": "rm_action_remarks", "label": "Replacement Slip Remarks", "type": "textarea", "core": False, "req": False, "sort": 20, "sec": "RM Decision"},
        ],
    },
    {
        "code": "S2_HANDOVER_INITIATE",
        "step_code": "S2_HANDOVER",
        "name": "Custody Handover Initiation",
        "fields": [
            {"key": "transfer_mode", "label": "Custody Transfer Mode", "type": "dropdown", "opt_set": "CUSTODY_TRANSFER_MODE", "core": True, "req": True, "sort": 10, "sec": "Handover Details", "def": "PHYSICAL_AND_DIGITAL"},
            {"key": "transfer_qty", "label": "Dispatched Transfer Quantity", "type": "number", "core": True, "req": True, "sort": 20, "sec": "Handover Details", "val": {"min": 1}},
            {"key": "dispatch_notes", "label": "Handover Dispatch Notes", "type": "textarea", "core": False, "req": False, "sort": 30, "sec": "Handover Details"},
        ],
    },
    {
        "code": "S2_HANDOVER_ACCEPT",
        "step_code": "S2_HANDOVER",
        "name": "Custody Handover Acceptance",
        "fields": [
            {"key": "acceptance_status", "label": "Transfer Acceptance Status", "type": "dropdown", "opt_set": "TRANSFER_ACCEPTANCE", "core": True, "req": True, "sort": 10, "sec": "Acceptance Check"},
            {"key": "discrepancy_reason", "label": "Discrepancy Explanation & Details", "type": "textarea", "core": False, "req": False, "sort": 20, "sec": "Acceptance Check", "vw": {"field": "acceptance_status", "op": "eq", "value": "DISCREPANCY"}, "rw": {"field": "acceptance_status", "op": "eq", "value": "DISCREPANCY"}},
            {"key": "accepted_qty", "label": "Physical Count Accepted Quantity", "type": "number", "core": True, "req": True, "sort": 30, "sec": "Acceptance Check", "val": {"min": 0}},
        ],
    },
    {
        "code": "S3_TECH_ALLOT",
        "step_code": "S3_TECHNICAL",
        "name": "Technician Servicing Allotment",
        "fields": [
            {"key": "assigned_technician", "label": "Assigned Technician", "type": "dropdown", "opt_set": "ASSIGNED_TECHNICIAN", "core": True, "req": True, "sort": 10, "sec": "Allotment", "mref": "technicians"},
            {"key": "data_entry_by", "label": "Data Entry Performed By", "type": "dropdown", "opt_set": "DATA_ENTRY_BY", "core": True, "req": True, "sort": 20, "sec": "Allotment", "mref": "profiles:TECHNICIAN_COORDINATOR"},
            {"key": "allotted_qty", "label": "Pieces Allotted for Servicing", "type": "number", "core": True, "req": True, "sort": 30, "sec": "Allotment", "val": {"min": 1}},
        ],
    },
    {
        "code": "S3_TECH_RECEIVE",
        "step_code": "S3_TECHNICAL",
        "name": "Technician Servicing Receiving",
        "fields": [
            {"key": "battery_check", "label": "Battery Check Result", "type": "dropdown", "opt_set": "BATTERY_CHECK", "core": True, "req": True, "sort": 10, "sec": "Battery Servicing"},
            {"key": "pieces_checked", "label": "Pieces Checked", "type": "number", "core": False, "req": False, "sort": 20, "sec": "Battery Servicing", "vw": {"field": "battery_check", "op": "in", "value": ["BATTERY_OK", "BATTERY_REPLACED"]}, "rw": {"field": "battery_check", "op": "in", "value": ["BATTERY_OK", "BATTERY_REPLACED"]}, "val": {"min": 1}},
            {"key": "batteries_installed", "label": "Batteries Installed", "type": "number", "core": False, "req": False, "sort": 30, "sec": "Battery Servicing", "vw": {"field": "battery_check", "op": "eq", "value": "BATTERY_REPLACED"}, "rw": {"field": "battery_check", "op": "eq", "value": "BATTERY_REPLACED"}, "val": {"min": 1}},
            {"key": "battery_type", "label": "Battery Type / Model", "type": "text", "core": False, "req": False, "sort": 40, "sec": "Battery Servicing", "vw": {"field": "battery_check", "op": "eq", "value": "BATTERY_REPLACED"}, "rw": {"field": "battery_check", "op": "eq", "value": "BATTERY_REPLACED"}},
            {"key": "cleaning_treatment", "label": "Cleaning & Scratch Treatment", "type": "dropdown", "opt_set": "CLEANING_TREATMENT", "core": True, "req": True, "sort": 50, "sec": "Finishing & Grading"},
            {"key": "post_servicing_classification", "label": "Post-Servicing Classification", "type": "dropdown", "opt_set": "POST_SERVICING_CLASSIFICATION", "core": True, "req": True, "sort": 60, "sec": "Finishing & Grading"},
            {"key": "technician_remarks", "label": "Technician Observations / Servicing Remarks", "type": "textarea", "core": False, "req": False, "sort": 70, "sec": "Finishing & Grading"},
        ],
    },
    {
        "code": "S4_DISMANTLE",
        "step_code": "S4_DISMANTLE",
        "name": "Dismantling & Parts Recovery",
        "fields": [
            {"key": "part_type", "label": "Recoverable Part Type", "type": "dropdown", "opt_set": "RECOVERABLE_PART_TYPE", "core": True, "req": True, "sort": 10, "sec": "Part Classification"},
            {"key": "model_name", "label": "PCB Model Name", "type": "text", "core": False, "req": False, "sort": 20, "sec": "Part Classification", "vw": {"field": "part_type", "op": "eq", "value": "PCB"}, "rw": {"field": "part_type", "op": "eq", "value": "PCB"}},
            {"key": "supplier_name", "label": "PCB Supplier Name", "type": "text", "core": False, "req": False, "sort": 30, "sec": "Part Classification", "vw": {"field": "part_type", "op": "eq", "value": "PCB"}, "rw": {"field": "part_type", "op": "eq", "value": "PCB"}},
            {"key": "parts_storage_separation", "label": "Parts Storage Separation", "type": "dropdown", "opt_set": "PARTS_STORAGE_SEPARATION", "core": True, "req": True, "sort": 40, "sec": "Storage Allocation"},
            {"key": "container_barcode", "label": "Dedicated Container Barcode / Shelf", "type": "text", "core": False, "req": False, "sort": 50, "sec": "Storage Allocation", "vw": {"field": "parts_storage_separation", "op": "eq", "value": "DEDICATED_CONTAINERS"}, "rw": {"field": "parts_storage_separation", "op": "eq", "value": "DEDICATED_CONTAINERS"}},
            {"key": "partition_id", "label": "Container Compartment / Partition ID", "type": "text", "core": False, "req": False, "sort": 60, "sec": "Storage Allocation", "vw": {"field": "parts_storage_separation", "op": "eq", "value": "PARTITIONED_CONTAINER"}, "rw": {"field": "parts_storage_separation", "op": "eq", "value": "PARTITIONED_CONTAINER"}},
            {"key": "scrap_disposal_marked", "label": "Remaining scrap marked for safe disposal", "type": "checkbox", "core": True, "req": True, "sort": 70, "sec": "Scrap Handling"},
        ],
    },
    {
        "code": "S5_SEGREGATE",
        "step_code": "S5_SEGREGATE",
        "name": "Inventory Custody Segregation",
        "fields": [
            {"key": "custody_assignment", "label": "Inventory Custody Assignment", "type": "dropdown", "opt_set": "CUSTODY_ASSIGNMENT", "core": True, "req": True, "sort": 10, "sec": "Custody Routing"},
            {"key": "storage_location_id", "label": "Assigned Storage Location ID", "type": "text", "core": True, "req": True, "sort": 20, "sec": "Custody Routing"},
            {"key": "segregation_notes", "label": "Segregation & Storage Remarks", "type": "textarea", "core": False, "req": False, "sort": 30, "sec": "Custody Routing"},
        ],
    },
    {
        "code": "S6_STORE_ISSUE",
        "step_code": "S6_STORE_ISSUE",
        "name": "Main Store Issue",
        "fields": [
            {"key": "store_issue_type", "label": "Store Issue Type", "type": "dropdown", "opt_set": "STORE_ISSUE_TYPE", "core": True, "req": True, "sort": 10, "sec": "Issue Details", "def": "ISSUE_MAIN_STORE"},
            {"key": "issue_qty", "label": "Main Store Inward Issue Quantity", "type": "number", "core": True, "req": True, "sort": 20, "sec": "Issue Details", "val": {"min": 1}},
            {"key": "main_store_inward_ref", "label": "Main Store Inward Voucher Ref", "type": "text", "core": True, "req": True, "sort": 30, "sec": "Issue Details"},
        ],
    },
    {
        "code": "S6_CN_DECISION",
        "step_code": "S6_CN_DECISION",
        "name": "Replacement Manager CN Decision",
        "fields": [
            {"key": "rm_cn_decision", "label": "Replacement Manager CN Decision", "type": "dropdown", "opt_set": "RM_CN_DECISION", "core": True, "req": True, "sort": 10, "sec": "Decision"},
            {"key": "cn_decision_remarks", "label": "Decision Justification & Remarks", "type": "textarea", "core": False, "req": False, "sort": 20, "sec": "Decision"},
        ],
    },
    {
        "code": "S6_ACCOUNTS_CN",
        "step_code": "S6_ACCOUNTS_CN",
        "name": "Accounts Credit Note Verification",
        "fields": [
            {"key": "party_doc_verification", "label": "Party Document Verification", "type": "dropdown", "opt_set": "PARTY_DOC_VERIFICATION", "core": True, "req": True, "sort": 10, "sec": "Verification"},
            {"key": "gst_portal_verification", "label": "GST Portal Return Verification", "type": "dropdown", "opt_set": "GST_PORTAL_VERIFICATION", "core": True, "req": True, "sort": 20, "sec": "Verification"},
            {"key": "cn_type", "label": "Credit Note Type", "type": "dropdown", "opt_set": "CN_TYPE", "core": True, "req": True, "sort": 30, "sec": "Voucher Generation", "val": {"restricted_when": {"condition": {"field": "gst_portal_verification", "op": "eq", "value": "GST_NOT_REFLECTED"}, "allowed_values": ["GENERAL_CN"]}}},
            {"key": "rate_verification_ref", "label": "Rate Verification Reference", "type": "dropdown", "opt_set": "RATE_VERIFICATION_REF", "core": True, "req": True, "sort": 40, "sec": "Valuation"},
            {"key": "verified_rate", "label": "Verified Commercial Rate", "type": "number", "core": True, "req": True, "sort": 50, "sec": "Valuation", "val": {"min": 0}},
            {"key": "cn_number", "label": "Credit Note Voucher Number", "type": "text", "core": True, "req": True, "sort": 60, "sec": "Voucher Details"},
            {"key": "cn_date", "label": "Credit Note Voucher Date", "type": "date", "core": True, "req": True, "sort": 70, "sec": "Voucher Details", "val": {"date_not_in_future": True}},
            {"key": "cn_valuation", "label": "Total Credit Note Valuation", "type": "number", "core": True, "req": True, "sort": 80, "sec": "Voucher Details", "val": {"min": 0}},
        ],
    },
    {
        "code": "S6_PARTY_NOTIFY",
        "step_code": "S6_NOTIFY",
        "name": "Party Notification Prior to Closure",
        "fields": [
            {"key": "party_notification_status", "label": "Party Notification Status", "type": "dropdown", "opt_set": "PARTY_NOTIFICATION_STATUS", "core": True, "req": True, "sort": 10, "sec": "Notification", "def": "PRIOR_INFO_SENT"},
            {"key": "notification_sent_date", "label": "Notification Sent Date", "type": "date", "core": True, "req": True, "sort": 20, "sec": "Notification", "val": {"date_not_in_future": True}},
            {"key": "notification_mode", "label": "Notification Mode (Email / WhatsApp / Letter)", "type": "text", "core": True, "req": True, "sort": 30, "sec": "Notification"},
        ],
    },
    {
        "code": "S6_CSR_CLOSE",
        "step_code": "S6_CLOSE",
        "name": "Complete Sales Return Closure",
        "fields": [
            {"key": "csr_final_status", "label": "Complete Sales Return Final Status", "type": "dropdown", "opt_set": "CSR_FINAL_STATUS", "core": True, "req": True, "sort": 10, "sec": "Closure Checklist", "def": "CSR_CLOSED"},
            {"key": "closure_checklist_confirmed", "label": "Goods in stock + CN issued + party notified", "type": "checkbox", "core": True, "req": True, "sort": 20, "sec": "Closure Checklist"},
            {"key": "closure_remarks", "label": "Closure Notes / Final Remarks", "type": "textarea", "core": False, "req": False, "sort": 30, "sec": "Closure Checklist"},
        ],
    },
]

def generate_sql() -> str:
    lines = [
        "-- -----------------------------------------------------------------------------",
        "-- Published v1 forms for all 20 workflow steps (master plan §3.2, §8.3, §10, prompt P1-07)",
        "-- Idempotent: safe to run multiple times without re-creating existing published versions.",
        "-- -----------------------------------------------------------------------------",
        "do $$",
        "declare",
        "  v_def_id uuid;",
        "  v_ver_id uuid;",
        "  v_snapshot jsonb;",
        "  v_opt_set_id uuid;",
        "begin",
    ]

    for f in FORMS:
        code = f["code"]
        step = f["step_code"]
        name = f["name"]

        lines.append(f"  -- Form {code}")
        lines.append(f"  insert into public.form_definitions (code, step_code, name, is_active)")
        lines.append(f"  values ('{code}', '{step}', '{name}', true)")
        lines.append(f"  on conflict (code) do update set step_code = excluded.step_code, name = excluded.name")
        lines.append(f"  returning id into v_def_id;")
        lines.append("")
        lines.append(f"  -- If no published version exists for {code}, create draft v1, populate fields, and publish")
        lines.append(f"  if not exists (select 1 from public.form_versions where form_definition_id = v_def_id and status = 'PUBLISHED') then")
        lines.append(f"    -- Insert draft version")
        lines.append(f"    insert into public.form_versions (form_definition_id, version_no, status)")
        lines.append(f"    values (v_def_id, 1, 'DRAFT')")
        lines.append(f"    returning id into v_ver_id;")
        lines.append("")

        for fld in f["fields"]:
            key = fld["key"]
            label = fld["label"].replace("'", "''")
            ctype = fld["type"]
            opt_set = fld.get("opt_set")
            mref = fld.get("mref")
            core = "true" if fld.get("core") else "false"
            req = "true" if fld.get("req") else "false"
            sort = fld.get("sort", 0)
            sec = fld.get("sec", "")
            vw = json.dumps(fld["vw"]) if "vw" in fld else "null"
            rw = json.dumps(fld["rw"]) if "rw" in fld else "null"
            val = json.dumps(fld["val"]) if "val" in fld else "null"
            df = json.dumps(fld["def"]) if "def" in fld else "null"

            if opt_set:
                lines.append(f"    select id into v_opt_set_id from public.option_sets where code = '{opt_set}';")
                opt_expr = "v_opt_set_id"
            else:
                opt_expr = "null"

            mref_expr = f"'{mref}'" if mref else "null"
            vw_expr = f"'{vw}'::jsonb" if vw != "null" else "null"
            rw_expr = f"'{rw}'::jsonb" if rw != "null" else "null"
            val_expr = f"'{val}'::jsonb" if val != "null" else "null"
            df_expr = f"'{df}'::jsonb" if df != "null" else "null"
            sec_expr = f"'{sec}'" if sec else "null"

            lines.append(f"    insert into public.form_fields (")
            lines.append(f"      form_version_id, field_key, label, control_type, option_set_id,")
            lines.append(f"      master_ref_type, is_required, visible_when, required_when, validation,")
            lines.append(f"      default_value, sort_order, section, is_core")
            lines.append(f"    ) values (")
            lines.append(f"      v_ver_id, '{key}', '{label}', '{ctype}', {opt_expr},")
            lines.append(f"      {mref_expr}, {req}, {vw_expr}, {rw_expr}, {val_expr},")
            lines.append(f"      {df_expr}, {sort}, {sec_expr}, {core}")
            lines.append(f"    );")

        lines.append("")
        lines.append(f"    -- Build frozen snapshot jsonb")
        lines.append(f"    select jsonb_build_object(")
        lines.append(f"      'form_code', '{code}',")
        lines.append(f"      'name', '{name}',")
        lines.append(f"      'step_code', '{step}',")
        lines.append(f"      'version_no', 1,")
        lines.append(f"      'version_notes', 'Initial v1 seed',")
        lines.append(f"      'fields', coalesce(jsonb_agg(")
        lines.append(f"        to_jsonb(fld) || jsonb_build_object(")
        lines.append(f"          'option_items', coalesce((")
        lines.append(f"            select jsonb_agg(")
        lines.append(f"              jsonb_build_object(")
        lines.append(f"                'code', oi.code,")
        lines.append(f"                'label', oi.label,")
        lines.append(f"                'allowed_status', oi.allowed_status,")
        lines.append(f"                'rule_text', oi.rule_text,")
        lines.append(f"                'next_action_text', oi.next_action_text,")
        lines.append(f"                'remarks', oi.remarks,")
        lines.append(f"                'system_behavior', oi.system_behavior,")
        lines.append(f"                'sort_order', oi.sort_order,")
        lines.append(f"                'is_active', oi.is_active")
        lines.append(f"              ) order by oi.sort_order asc, oi.code asc")
        lines.append(f"            )")
        lines.append(f"            from public.option_items oi")
        lines.append(f"            where oi.option_set_id = fld.option_set_id")
        lines.append(f"          ), '[]'::jsonb)")
        lines.append(f"        ) order by fld.sort_order asc, fld.field_key asc")
        lines.append(f"      ), '[]'::jsonb)")
        lines.append(f"    ) into v_snapshot")
        lines.append(f"    from public.form_fields fld")
        lines.append(f"    where fld.form_version_id = v_ver_id;")
        lines.append("")
        lines.append(f"    -- Publish draft version 1")
        lines.append(f"    update public.form_versions")
        lines.append(f"    set status = 'PUBLISHED', snapshot = v_snapshot, published_at = now()")
        lines.append(f"    where id = v_ver_id;")
        lines.append(f"  end if;")
        lines.append("")

    lines.append("end $$;")
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    sql = generate_sql()
    with open("supabase/seed.sql", "r", encoding="utf-8") as f:
        content = f.read()

    marker = "-- DEMO:BEGIN"
    if "-- Published v1 forms for all 20 workflow steps" in content:
        # Replace existing block
        parts = content.split("-- Published v1 forms for all 20 workflow steps")
        before = parts[0].rsplit("-- -----------------------------------------------------------------------------", 1)[0]
        after = "-- =============================================================================\n-- DEMO:BEGIN" + content.split("-- DEMO:BEGIN")[1]
        new_content = before + sql + "\n\n" + after
    else:
        parts = content.split(marker)
        new_content = parts[0] + sql + "\n\n" + marker + parts[1]

    with open("supabase/seed.sql", "w", encoding="utf-8") as f:
        f.write(new_content)
    print("Injected published v1 forms seed into supabase/seed.sql successfully!")
