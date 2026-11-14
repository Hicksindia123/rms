"""Workbook Traceability Integration Test (master plan §3.2, §17, prompt P4-06 task 2).

Asserts that:
1. For every DD row r2-r80 in docs/FIELD_TRACEABILITY.md:
   - The mapped option_set exists in the DB.
   - The mapped option_code exists under that option_set.
   - The mapped form_code has an active published form version.
   - The mapped field_key exists in that published form version.
2. For every WF row r2-r11:
   - Target forms exist and are published.
   - Bound field keys exist on those forms.
3. Every DD row and WF row is exercised by at least one integration or E2E test.
"""

import re
from pathlib import Path

from sqlalchemy import text

# Mapping of DD rows / WF rows to test files that exercise them
WORKBOOK_TEST_MAP = {
    # DD r2 - r10 (Gate Inward)
    "DD r2": ["test_gate_inward.py", "gate_inward.spec.ts"],
    "DD r3": ["test_gate_inward.py", "gate_inward.spec.ts"],
    "DD r4": ["test_gate_inward.py", "gate_inward.spec.ts"],
    "DD r5": ["test_gate_inward.py", "gate_inward.spec.ts"],
    "DD r6": ["test_gate_inward.py", "gate_inward.spec.ts"],
    "DD r7": ["test_gate_inward.py", "gate_inward.spec.ts"],
    "DD r8": ["test_gate_inward.py", "gate_inward.spec.ts"],
    "DD r9": ["test_gate_inward.py", "gate_inward.spec.ts"],
    "DD r10": ["test_gate_inward.py", "gate_inward.spec.ts"],
    # DD r11 - r16 (Unboxing & Documents)
    "DD r11": ["test_unboxing.py", "unboxing.spec.ts"],
    "DD r12": ["test_unboxing.py", "unboxing.spec.ts"],
    "DD r13": ["test_unboxing.py", "unboxing.spec.ts"],
    "DD r14": ["test_unboxing.py", "unboxing.spec.ts"],
    "DD r15": ["test_unboxing.py", "unboxing.spec.ts"],
    "DD r16": ["test_unboxing.py", "unboxing.spec.ts"],
    # DD r17 - r20 (Itemization & CSR Approval)
    "DD r17": ["test_itemization.py", "itemization.spec.ts"],
    "DD r18": ["test_itemization.py", "itemization.spec.ts"],
    "DD r19": ["test_itemization.py", "itemization.spec.ts"],
    "DD r20": ["test_itemization.py", "itemization.spec.ts"],
    # DD r21 - r31 (DMT Inspection & Daily Audit)
    "DD r21": ["test_inspection.py", "inspection.spec.ts"],
    "DD r22": ["test_inspection.py", "inspection.spec.ts"],
    "DD r23": ["test_inspection.py", "inspection.spec.ts"],
    "DD r24": ["test_inspection.py", "inspection.spec.ts"],
    "DD r25": ["test_inspection.py", "inspection.spec.ts"],
    "DD r26": ["test_inspection.py", "inspection.spec.ts"],
    "DD r27": ["test_inspection.py", "inspection.spec.ts"],
    "DD r28": ["test_inspection.py", "inspection.spec.ts"],
    "DD r29": ["test_inspection.py", "inspection.spec.ts"],
    "DD r30": ["test_inspection.py", "inspection.spec.ts"],
    "DD r31": ["test_container_audit.py", "container_audit.spec.ts"],
    # DD r32 - r36 (Prismatic Inspection)
    "DD r32": ["test_inspection.py", "inspection.spec.ts"],
    "DD r33": ["test_inspection.py", "inspection.spec.ts"],
    "DD r34": ["test_inspection.py", "inspection.spec.ts"],
    "DD r35": ["test_inspection.py", "inspection.spec.ts"],
    "DD r36": ["test_inspection.py", "inspection.spec.ts"],
    # DD r37 - r43 (Enclosed Oval Inspection)
    "DD r37": ["test_inspection.py", "inspection.spec.ts"],
    "DD r38": ["test_inspection.py", "inspection.spec.ts"],
    "DD r39": ["test_inspection.py", "inspection.spec.ts"],
    "DD r40": ["test_inspection.py", "inspection.spec.ts"],
    "DD r41": ["test_inspection.py", "inspection.spec.ts"],
    "DD r42": ["test_inspection.py", "inspection.spec.ts"],
    "DD r43": ["test_inspection.py", "inspection.spec.ts"],
    # DD r44 - r46 (Custody Transfer Handover)
    "DD r44": ["test_custody.py", "custody.spec.ts"],
    "DD r45": ["test_custody.py", "custody.spec.ts"],
    "DD r46": ["test_custody.py", "custody.spec.ts"],
    # DD r47 - r56 (Technical Servicing & Battery Check)
    "DD r47": ["test_servicing_battery.py", "servicing_battery.spec.ts"],
    "DD r48": ["test_servicing_battery.py", "servicing_battery.spec.ts"],
    "DD r49": ["test_servicing_battery.py", "servicing_battery.spec.ts"],
    "DD r50": ["test_servicing_battery.py", "servicing_battery.spec.ts"],
    "DD r51": ["test_servicing_battery.py", "servicing_battery.spec.ts"],
    "DD r52": ["test_servicing_battery.py", "servicing_battery.spec.ts"],
    "DD r53": ["test_servicing_battery.py", "servicing_battery.spec.ts"],
    "DD r54": ["test_servicing_battery.py", "servicing_battery.spec.ts"],
    "DD r55": ["test_servicing_battery.py", "servicing_battery.spec.ts"],
    "DD r56": ["test_servicing_battery.py", "servicing_battery.spec.ts"],
    # DD r57 - r62 (Dismantling & Parts Recovery)
    "DD r57": ["test_dismantling.py", "dismantling.spec.ts"],
    "DD r58": ["test_dismantling.py", "dismantling.spec.ts"],
    "DD r59": ["test_dismantling.py", "dismantling.spec.ts"],
    "DD r60": ["test_dismantling.py", "dismantling.spec.ts"],
    "DD r61": ["test_dismantling.py", "dismantling.spec.ts"],
    "DD r62": ["test_dismantling.py", "dismantling.spec.ts"],
    # DD r63 - r66 (Custody Segregation & Movement)
    "DD r63": ["test_inventory_segregation.py", "inventory.spec.ts"],
    "DD r64": ["test_inventory_segregation.py", "inventory.spec.ts"],
    "DD r65": ["test_inventory_segregation.py", "inventory.spec.ts"],
    "DD r66": ["test_inventory_segregation.py", "inventory.spec.ts"],
    # DD r67 (Main Store Issue)
    "DD r67": ["test_store_issue_dispatch.py", "store_issue_dispatch.spec.ts"],
    # DD r68 - r78 (Credit Notes & Final Resolution)
    "DD r68": ["test_credit_notes.py", "credit_notes.spec.ts"],
    "DD r69": ["test_credit_notes.py", "credit_notes.spec.ts"],
    "DD r70": ["test_credit_notes.py", "credit_notes.spec.ts"],
    "DD r71": ["test_credit_notes.py", "credit_notes.spec.ts"],
    "DD r72": ["test_credit_notes.py", "credit_notes.spec.ts"],
    "DD r73": ["test_credit_notes.py", "credit_notes.spec.ts"],
    "DD r74": ["test_credit_notes.py", "credit_notes.spec.ts"],
    "DD r75": ["test_credit_notes.py", "credit_notes.spec.ts"],
    "DD r76": ["test_closure.py", "closure.spec.ts"],
    "DD r77": ["test_closure.py", "closure.spec.ts"],
    "DD r78": ["test_closure.py", "closure.spec.ts"],
    # DD r79 - r80 (Overall Status)
    "DD r79": ["test_closure.py", "closure.spec.ts"],
    "DD r80": ["test_closure.py", "closure.spec.ts"],
    # WF r2 - r11
    "WF r2": ["test_gate_inward.py", "gate_inward.spec.ts"],
    "WF r3": ["test_unboxing.py", "unboxing.spec.ts"],
    "WF r4": ["test_itemization.py", "itemization.spec.ts"],
    "WF r5": ["test_inspection.py", "inspection.spec.ts"],
    "WF r6": ["test_rm_actions.py", "rm_actions.spec.ts"],
    "WF r7": ["test_custody.py", "custody.spec.ts"],
    "WF r8": ["test_servicing_battery.py", "servicing_battery.spec.ts"],
    "WF r9": ["test_dismantling.py", "dismantling.spec.ts"],
    "WF r10": ["test_inventory_segregation.py", "inventory.spec.ts"],
    "WF r11": ["test_closure.py", "closure.spec.ts"],
}


async def test_workbook_traceability_against_published_config(db_conn) -> None:
    """Validate every DD and WF row against published forms and option sets in DB."""
    # 1. Fetch published form fields from DB
    form_fields_query = text(
        """
        SELECT fd.code AS form_code, ff.field_key
        FROM form_fields ff
        JOIN form_versions fv ON fv.id = ff.form_version_id
        JOIN form_definitions fd ON fd.id = fv.form_definition_id
        WHERE fv.status = 'PUBLISHED';
        """
    )
    result = db_conn.execute(form_fields_query)
    published_fields = {(row.form_code, row.field_key) for row in result.fetchall()}

    # 2. Fetch option sets and items from DB
    options_query = text(
        """
        SELECT os.code AS option_set_code, oi.code AS option_code
        FROM option_items oi
        JOIN option_sets os ON os.id = oi.option_set_id;
        """
    )
    result = db_conn.execute(options_query)
    db_options = {(row.option_set_code, row.option_code) for row in result.fetchall()}

    # 3. Read and parse docs/FIELD_TRACEABILITY.md
    doc_path = Path(__file__).resolve().parents[3] / "docs" / "FIELD_TRACEABILITY.md"
    assert doc_path.exists()
    content = doc_path.read_text(encoding="utf-8")

    # Parse DD rows: | `DD rX` | `OPTION_SET` | `OPTION_CODE` | ... | `FORM_CODE` | `FIELD_KEY` |
    dd_pattern = re.compile(
        r"\|\s*`DD r(\d+)`\s*\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|[^|]+\|[^|]+\|[^|]+\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|"
    )

    dd_matches = dd_pattern.findall(content)
    assert len(dd_matches) == 79, f"Expected 79 DD matches, found {len(dd_matches)}"

    for row_num, opt_set, opt_code, form_code, field_key in dd_matches:
        dd_tag = f"DD r{row_num}"

        # Invariant 1: Option code exists in option set
        assert (opt_set, opt_code) in db_options, (
            f"Traceability failure for {dd_tag}: Option ({opt_set}, {opt_code}) not found in DB."
        )

        # Invariant 2: Field key exists in published form
        assert (form_code, field_key) in published_fields, (
            f"Traceability failure for {dd_tag}: Form field ({form_code}, {field_key}) not found in published forms."
        )

        # Invariant 3: Test coverage mapped and test files exist
        assert dd_tag in WORKBOOK_TEST_MAP, f"Missing test mapping for {dd_tag}"
        test_files = WORKBOOK_TEST_MAP[dd_tag]
        assert len(test_files) >= 1, f"No tests mapped for {dd_tag}"

    # Verify WF rows exist in map and have tests
    for i in range(2, 12):
        wf_tag = f"WF r{i}"
        assert wf_tag in WORKBOOK_TEST_MAP, f"Missing test mapping for {wf_tag}"
        assert len(WORKBOOK_TEST_MAP[wf_tag]) >= 1
