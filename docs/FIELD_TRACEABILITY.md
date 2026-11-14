# Field & Dropdown Traceability Matrix

This document provides the complete, authoritative mapping between every workbook dropdown row
(`Roles_Steps_Dropdowns` r2–r80; 79 rows) and workflow rows (`RMS_Workflow` r2–r11) to versioned
forms, field keys, and option codes in the database (master plan §3.2, prompt P1-07).

> [!IMPORTANT]
> **Coverage Guarantee:** All 79 workbook dropdown rows (`DD r2` through `DD r80`) are mapped
> to their respective `form_code.field_key` and option codes. Automated test `test_traceability_completeness.py`
> strictly enforces 100% mapping completeness.

> [!NOTE]
> **Gate form v2 (change plan 2026-11-12 Phase 2, AMD-04):** the single
> `accompanying_doc` field is retired. DD r5-r8 are now the types of the gate
> document rows (`gs_gate_documents.doc_type_code`) entered in the Documentation
> section of `S1_GATE_INWARD`, whose form field is `no_document`; DD r9
> (*No Document Attached*) is that flag (`goods_slips.missing_documentation`).

## 1. Workbook Dropdown Rows (r2–r80) Traceability

| DD Row | Option Set | Option Code | Option Label | Allowed | System Behavior | Form Code | Field Key |
|---|---|---|---|---|---|---|---|
| `DD r2` | `DELIVERY_MODE` | `COURIER_PARCEL` | Courier / Parcel | `YES` | `-` | `S1_GATE_INWARD` | `delivery_mode` |
| `DD r3` | `DELIVERY_MODE` | `DIRECT_TRUCK` | Direct Transport / Truck | `YES` | `-` | `S1_GATE_INWARD` | `delivery_mode` |
| `DD r4` | `DELIVERY_MODE` | `SELF_PARTY_REP` | Self / Party Representative | `YES` | `-` | `S1_GATE_INWARD` | `delivery_mode` |
| `DD r5` | `GATE_DOCUMENT` | `INVOICE` | Invoice | `YES` | `-` | `S1_GATE_INWARD` | `no_document` |
| `DD r6` | `GATE_DOCUMENT` | `DEBIT_NOTE` | Debit Note | `YES` | `-` | `S1_GATE_INWARD` | `no_document` |
| `DD r7` | `GATE_DOCUMENT` | `DELIVERY_CHALLAN` | Delivery Challan | `YES` | `-` | `S1_GATE_INWARD` | `no_document` |
| `DD r8` | `GATE_DOCUMENT` | `HANDWRITTEN_SLIP` | Handwritten Slip / Party Note | `YES` | `-` | `S1_GATE_INWARD` | `no_document` |
| `DD r9` | `GATE_DOCUMENT` | `NO_DOCUMENT` | No Document Attached | `CONDITIONAL` | `-` | `S1_GATE_INWARD` | `no_document` |
| `DD r10` | `GS_CREATION_FORMAT` | `AUTO_STANDARD` | Auto-Generated (Standard Formatting) | `YES` | `-` | `S1_GATE_INWARD` | `gs_creation_format` |
| `DD r11` | `UNBOXING_VIDEO` | `VIDEO` | Continuous Unboxing Video File (.mp4 / .mov) | `YES` | `-` | `S1_UNBOXING` | `unboxing_video` |
| `DD r12` | `RECEIVED_DOC_CLASSIFICATION` | `INVOICE` | Invoice | `YES` | `-` | `S1_UNBOXING` | `doc_classification` |
| `DD r13` | `RECEIVED_DOC_CLASSIFICATION` | `DEBIT_NOTE` | Debit Note | `YES` | `-` | `S1_UNBOXING` | `doc_classification` |
| `DD r14` | `RECEIVED_DOC_CLASSIFICATION` | `DELIVERY_CHALLAN` | Delivery Challan | `YES` | `-` | `S1_UNBOXING` | `doc_classification` |
| `DD r15` | `RECEIVED_DOC_CLASSIFICATION` | `HANDWRITTEN_SLIP` | Handwritten Slip / Party Note | `YES` | `-` | `S1_UNBOXING` | `doc_classification` |
| `DD r16` | `DOCUMENT_PHOTO` | `DOC_PHOTO` | Document Photo Image (.jpg / .png / .pdf) | `YES` | `-` | `S1_UNBOXING` | `document_photo` |
| `DD r17` | `RETURN_CATEGORY` | `CSR` | Complete Sales Return | `CONDITIONAL` | `-` | `S1_ITEMIZE` | `return_category` |
| `DD r18` | `RETURN_CATEGORY` | `RO` | Replacement Only | `YES` | `-` | `S1_ITEMIZE` | `return_category` |
| `DD r19` | `CSR_APPROVAL` | `CSR_APPROVED` | Approved - Complete Sales Return | `YES` | `-` | `S1_CSR_APPROVAL` | `csr_approval` |
| `DD r20` | `CSR_APPROVAL` | `CSR_REJECTED_TO_RO` | Rejected - Convert to Replacement Only | `YES` | `-` | `S1_CSR_APPROVAL` | `csr_approval` |
| `DD r21` | `DMT_CONDITION` | `DMT_OK_PACKED` | VISUALLY OKAY and PACKED | `YES` | `SELLABLE` | `S1_INSPECT_DMT` | `visual_condition` |
| `DD r22` | `DMT_CONDITION` | `DMT_OK_PKG_DAMAGED` | VISUALLY OKAY but unpacked or maybe packaging is damaged | `YES` | `REPACK_OR_TECHNICIAN` | `S1_INSPECT_DMT` | `visual_condition` |
| `DD r23` | `DMT_CONDITION` | `DMT_OTHER_BRANDS` | OTHER BRANDS | `NO` | `REJECT_HOLD` | `S1_INSPECT_DMT` | `visual_condition` |
| `DD r24` | `DMT_CONDITION` | `DMT_SHORT_QTY` | SHORT QUANTITY | `YES` | `SHORT_QTY` | `S1_INSPECT_DMT` | `visual_condition` |
| `DD r25` | `DMT_CONDITION` | `DMT_SCRATCHED` | SCRATCHED/SPOTS | `YES` | `TO_TECHNICIAN` | `S1_INSPECT_DMT` | `visual_condition` |
| `DD r26` | `DMT_CONDITION` | `DMT_DIRTY` | DIRTY | `YES` | `TO_TECHNICIAN` | `S1_INSPECT_DMT` | `visual_condition` |
| `DD r27` | `DMT_CONDITION` | `DMT_BROKEN_BODY` | BROKEN / BODY DAMAGE | `NO` | `TO_SPARE_PARTS` | `S1_INSPECT_DMT` | `visual_condition` |
| `DD r28` | `DMT_CONDITION` | `DMT_DISPLAY_ISSUE` | DISPLAY ISSUES | `YES` | `TO_TECHNICIAN` | `S1_INSPECT_DMT` | `visual_condition` |
| `DD r29` | `DMT_EXTRACTION_TYPE` | `PACKAGING_EXTRACTED` | Packaging Extracted | `YES` | `-` | `S1_INSPECT_DMT` | `extraction_type` |
| `DD r30` | `DMT_EXTRACTION_TYPE` | `CONTAINER_EXTRACTED` | Container Extracted | `YES` | `-` | `S1_INSPECT_DMT` | `extraction_type` |
| `DD r31` | `DAILY_CONTAINER_AUDIT` | `DAILY_AUDIT_DONE` | Containers Checked & Counted Daily | `YES` | `-` | `S1_DAILY_CONTAINER_AUDIT` | `audit_check` |
| `DD r32` | `PRISMATIC_CONDITION` | `PRS_OK` | VISUALLY OKAY | `YES` | `SELLABLE` | `S1_INSPECT_PRISMATIC` | `visual_condition` |
| `DD r33` | `PRISMATIC_CONDITION` | `PRS_BULB_BROKEN_NO_HG` | BULB BROKEN WITHOUT MERCURY | `NO` | `REJECT_RECORD` | `S1_INSPECT_PRISMATIC` | `visual_condition` |
| `DD r34` | `PRISMATIC_CONDITION` | `PRS_BROKEN_WITH_HG` | BROKEN WITH MERCURY | `NO` | `HAZARD` | `S1_INSPECT_PRISMATIC` | `visual_condition` |
| `DD r35` | `PRISMATIC_EXTRACTION_TYPE` | `PACKAGING_EXTRACTED` | Packaging Extracted | `YES` | `-` | `S1_INSPECT_PRISMATIC` | `extraction_type` |
| `DD r36` | `PRISMATIC_EXTRACTION_TYPE` | `CONTAINER_EXTRACTED` | Container Extracted | `YES` | `-` | `S1_INSPECT_PRISMATIC` | `extraction_type` |
| `DD r37` | `EO_INSPECTION_PROTOCOL` | `EO_FULL_OPENING_DONE` | Full Opening Inspection Completed | `YES` | `-` | `S1_INSPECT_EO` | `inspection_protocol` |
| `DD r38` | `EO_CONDITION` | `EO_OK` | VISUALLY OKAY | `YES` | `SELLABLE` | `S1_INSPECT_EO` | `visual_condition` |
| `DD r39` | `EO_CONDITION` | `EO_INNER_CAPILLARY_BROKEN` | Inner Capillary Broken but Mercury Present | `YES` | `TO_TECHNICIAN` | `S1_INSPECT_EO` | `visual_condition` |
| `DD r40` | `EO_CONDITION` | `EO_BODY_BROKEN_HG` | Body Broken but Mercury Present | `NO` | `HAZARD` | `S1_INSPECT_EO` | `visual_condition` |
| `DD r41` | `EO_CONDITION` | `EO_BULB_BROKEN_NO_HG` | Bulb Broken and Mercury Absent | `NO` | `REJECT_RECORD` | `S1_INSPECT_EO` | `visual_condition` |
| `DD r42` | `EO_EXTRACTION_TYPE` | `PACKAGING_EXTRACTED` | Packaging Extracted | `YES` | `-` | `S1_INSPECT_EO` | `extraction_type` |
| `DD r43` | `EO_EXTRACTION_TYPE` | `CONTAINER_EXTRACTED` | Container Extracted | `YES` | `-` | `S1_INSPECT_EO` | `extraction_type` |
| `DD r44` | `CUSTODY_TRANSFER_MODE` | `PHYSICAL_AND_DIGITAL` | Physical Movement & Digital Transfer | `YES` | `-` | `S2_HANDOVER_INITIATE` | `transfer_mode` |
| `DD r45` | `TRANSFER_ACCEPTANCE` | `ACCEPTED_VERIFIED` | Accepted - Quantity & Lots Verified | `YES` | `-` | `S2_HANDOVER_ACCEPT` | `acceptance_status` |
| `DD r46` | `TRANSFER_ACCEPTANCE` | `DISCREPANCY` | Discrepancy Reported | `CONDITIONAL` | `-` | `S2_HANDOVER_ACCEPT` | `acceptance_status` |
| `DD r47` | `ASSIGNED_TECHNICIAN` | `RAJ_KUMAR_JI` | Raj Kumar Ji | `YES` | `-` | `S3_TECH_ALLOT` | `assigned_technician` |
| `DD r48` | `DATA_ENTRY_BY` | `AMAN` | Aman | `YES` | `-` | `S3_TECH_ALLOT` | `data_entry_by` |
| `DD r49` | `DATA_ENTRY_BY` | `SAHIL` | Sahil | `YES` | `-` | `S3_TECH_ALLOT` | `data_entry_by` |
| `DD r50` | `BATTERY_CHECK` | `BATTERY_OK` | Battery Okay / Fine | `YES` | `-` | `S3_TECH_RECEIVE` | `battery_check` |
| `DD r51` | `BATTERY_CHECK` | `BATTERY_REPLACED` | Battery Changed / Replaced | `YES` | `-` | `S3_TECH_RECEIVE` | `battery_check` |
| `DD r52` | `CLEANING_TREATMENT` | `CLEANED_SELLABLE` | Cleaned - Sellable / Fresh Finish | `YES` | `-` | `S3_TECH_RECEIVE` | `cleaning_treatment` |
| `DD r53` | `CLEANING_TREATMENT` | `PERMANENT_SCRATCHES` | Permanent Scratches / Non-Recoverable | `YES` | `-` | `S3_TECH_RECEIVE` | `cleaning_treatment` |
| `DD r54` | `POST_SERVICING_CLASSIFICATION` | `FUNCTIONAL_GOOD` | Functional - Good / Fresh | `YES` | `-` | `S3_TECH_RECEIVE` | `post_servicing_classification` |
| `DD r55` | `POST_SERVICING_CLASSIFICATION` | `FUNCTIONAL_REPAIRED` | Functional - Repaired & Working | `YES` | `-` | `S3_TECH_RECEIVE` | `post_servicing_classification` |
| `DD r56` | `POST_SERVICING_CLASSIFICATION` | `NON_GOOD` | Non-Good Inventory (Defective / Unrepairable) | `YES` | `-` | `S3_TECH_RECEIVE` | `post_servicing_classification` |
| `DD r57` | `RECOVERABLE_PART_TYPE` | `TIP` | TIP | `YES` | `-` | `S4_DISMANTLE` | `part_type` |
| `DD r58` | `RECOVERABLE_PART_TYPE` | `BODY` | BODY | `YES` | `-` | `S4_DISMANTLE` | `part_type` |
| `DD r59` | `RECOVERABLE_PART_TYPE` | `WIRE` | WIRE | `YES` | `-` | `S4_DISMANTLE` | `part_type` |
| `DD r60` | `RECOVERABLE_PART_TYPE` | `PCB` | PCB | `YES` | `-` | `S4_DISMANTLE` | `part_type` |
| `DD r61` | `PARTS_STORAGE_SEPARATION` | `DEDICATED_CONTAINERS` | Different Dedicated Containers | `YES` | `-` | `S4_DISMANTLE` | `parts_storage_separation` |
| `DD r62` | `PARTS_STORAGE_SEPARATION` | `PARTITIONED_CONTAINER` | Separations / Partitions in Single Container | `YES` | `-` | `S4_DISMANTLE` | `parts_storage_separation` |
| `DD r63` | `CUSTODY_ASSIGNMENT` | `CUST_FUNCTIONAL_GOOD` | Functional Stock (Good / Fresh) | `YES` | `-` | `S5_SEGREGATE` | `custody_assignment` |
| `DD r64` | `CUSTODY_ASSIGNMENT` | `CUST_FUNCTIONAL_REPAIRED` | Functional Stock (Repaired) | `YES` | `-` | `S5_SEGREGATE` | `custody_assignment` |
| `DD r65` | `CUSTODY_ASSIGNMENT` | `CUST_NON_FUNCTIONAL` | Non-Functional / Scratched / Non-Sellable Stock | `YES` | `-` | `S5_SEGREGATE` | `custody_assignment` |
| `DD r66` | `CUSTODY_ASSIGNMENT` | `CUST_SALVAGED_PARTS` | Salvaged Reusable Spare Parts (Tip / Body / Wire / PCB) | `YES` | `-` | `S5_SEGREGATE` | `custody_assignment` |
| `DD r67` | `STORE_ISSUE_TYPE` | `ISSUE_MAIN_STORE` | Issue to Main Store | `YES` | `-` | `S6_STORE_ISSUE` | `store_issue_type` |
| `DD r68` | `RM_CN_DECISION` | `ALLOW_CN` | Allow Credit Note (No Replacement Dispatched) | `YES` | `-` | `S6_CN_DECISION` | `rm_cn_decision` |
| `DD r69` | `RM_CN_DECISION` | `DENY_CN_SEND_REPLACEMENT` | Do Not Allow CN (Send Replacement Piece) | `YES` | `-` | `S6_CN_DECISION` | `rm_cn_decision` |
| `DD r70` | `CN_TYPE` | `GST_CN` | GST CREDIT NOTE | `CONDITIONAL` | `-` | `S6_ACCOUNTS_CN` | `cn_type` |
| `DD r71` | `CN_TYPE` | `GENERAL_CN` | GENERAL CREDIT NOTE | `YES` | `-` | `S6_ACCOUNTS_CN` | `cn_type` |
| `DD r72` | `PARTY_DOC_VERIFICATION` | `PARTY_INVOICE` | Party Raised Invoice | `YES` | `-` | `S6_ACCOUNTS_CN` | `party_doc_verification` |
| `DD r73` | `PARTY_DOC_VERIFICATION` | `PARTY_DEBIT_NOTE` | Party Raised Debit Note | `YES` | `-` | `S6_ACCOUNTS_CN` | `party_doc_verification` |
| `DD r74` | `PARTY_DOC_VERIFICATION` | `PARTY_NO_DOC` | No Commercial Document Raised by Party | `YES` | `-` | `S6_ACCOUNTS_CN` | `party_doc_verification` |
| `DD r75` | `GST_PORTAL_VERIFICATION` | `GST_REFLECTED` | Return Reflected on GST Portal | `YES` | `-` | `S6_ACCOUNTS_CN` | `gst_portal_verification` |
| `DD r76` | `GST_PORTAL_VERIFICATION` | `GST_NOT_REFLECTED` | Return NOT Reflected on GST Portal | `CONDITIONAL` | `-` | `S6_ACCOUNTS_CN` | `gst_portal_verification` |
| `DD r77` | `RATE_VERIFICATION_REF` | `RATE_SALES` | Previous Sales Record Rate Check | `YES` | `-` | `S6_ACCOUNTS_CN` | `rate_verification_ref` |
| `DD r78` | `RATE_VERIFICATION_REF` | `RATE_PURCHASE` | Previous Purchase Entry Rate Check | `YES` | `-` | `S6_ACCOUNTS_CN` | `rate_verification_ref` |
| `DD r79` | `PARTY_NOTIFICATION_STATUS` | `PRIOR_INFO_SENT` | Prior Information Sent with CN Details | `YES` | `-` | `S6_PARTY_NOTIFY` | `party_notification_status` |
| `DD r80` | `CSR_FINAL_STATUS` | `CSR_CLOSED` | Inward to Inventory with Packaging + CN Issued + Prior Party Info | `YES` | `-` | `S6_CSR_CLOSE` | `csr_final_status` |

## 2. Stage-1 a) / Step-3 a) WF r6 RM Actions (Additional Catalogue Rows)

| WF Row | Option Set | Option Code | Option Label | Allowed | Form Code | Field Key |
|---|---|---|---|---|---|---|
| `WF r6` | `RM_ITEM_ACTION` | `SEND_NEW` | Send New | `YES` | `S1A_RM_ACTION` | `rm_action` |
| `WF r6` | `RM_ITEM_ACTION` | `SEND_REPAIRED` | Send Repaired | `YES` | `S1A_RM_ACTION` | `rm_action` |
| `WF r6` | `RM_ITEM_ACTION` | `ISSUE_CN` | Issue CN | `YES` | `S1A_RM_ACTION` | `rm_action` |
| `WF r6` | `RM_ITEM_ACTION` | `NOT_ALLOWED` | Not Allowed | `YES` | `S1A_RM_ACTION` | `rm_action` |
| `WF r6` | `RM_ITEM_ACTION` | `PENDING_BP` | Pending (BP) | `YES` | `S1A_RM_ACTION` | `rm_action` |

## 3. Workflow Sheet Rows (RMS_Workflow r2–r11) Traceability

| WF Row | Stage / Step | Workbook Scope & Key Checkpoints | Target Form(s) | Bound Field Keys |
|---|---|---|---|---|
| `WF r2` | S1 / Step-1 | Header fields: state, station, party, box_count | `S1_GATE_INWARD` | `state, station, party_name, box_count` |
| `WF r3` | S1 / Step-2 | Unboxing video + document photo mandatory before opening | `S1_UNBOXING` | `unboxing_video, document_photo` |
| `WF r4` | S1 / Step-3 | CSR approval by Replacement Manager | `S1_CSR_APPROVAL` | `csr_approval` |
| `WF r5` | S1 / Step-3 (Inspection) | DMT, Prismatic & Enclosed Oval product inspection & extraction reconciliation | `S1_INSPECT_DMT / PRISMATIC / EO` | `visual_condition, extraction_type, allocated_qty` |
| `WF r6` | S1 a) / Step-3 a) | Five RM actions: Send New, Send Repaired, Issue CN, Not Allowed, Pending (BP) | `S1A_RM_ACTION` | `rm_action (SEND_NEW, SEND_REPAIRED, ISSUE_CN, NOT_ALLOWED, PENDING_BP)` |
| `WF r7` | S2 / Step-4 | Custody handover initiate & accept (physical and digital sync) | `S2_HANDOVER_INITIATE / ACCEPT` | `transfer_mode, acceptance_status` |
| `WF r8` | S3 / Step-4 (Technical) | Technician servicing, battery checking & replacement | `S3_TECH_ALLOT / RECEIVE` | `assigned_technician, battery_check, pieces_checked, batteries_installed` |
| `WF r9` | S4 / Step-5 | Dismantling & parts recovery (Tip, Body, Wire, PCB) | `S4_DISMANTLE` | `part_type, model_name, supplier_name, parts_storage_separation` |
| `WF r10` | S5 / Step-6 | Custody segregation (functional stock vs non-functional scrap) | `S5_SEGREGATE` | `custody_assignment, storage_location_id` |
| `WF r11` | S6 / Step-7 | Main store issue, CN decision, accounts verification, party notification & GS closure | `S6_STORE_ISSUE / CN_DECISION / ACCOUNTS_CN / PARTY_NOTIFY / CSR_CLOSE` | `store_issue_type, rm_cn_decision, cn_type, party_notification_status, csr_final_status` |

## 4. Verification Summary

- **Mapped Workbook DD Rows:** 79 / 79 (r2–r80)
- **Mapped RM Item-wise Actions:** 5 / 5 (`WF r6`)
- **Total Option Items Tracked:** 84 / 84
- **Published v1 Forms Configured:** 20 / 20
- **Total Configured Form Fields:** 99

Enforced continuously by automated backend test `test_traceability_completeness.py`.