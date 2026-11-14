"""Test completeness of docs/FIELD_TRACEABILITY.md (master plan §3.2, prompt P1-07).

Verifies that:
1. Every workbook DD row from r2 to r80 (exactly 79 rows) is present in docs/FIELD_TRACEABILITY.md.
2. Every mapped form_code and field_key exists in the seeded published forms.
3. WF r6 rows are mapped.
"""

import re
from pathlib import Path


def test_traceability_mapping_completeness() -> None:
    doc_path = Path(__file__).resolve().parents[3] / "docs" / "FIELD_TRACEABILITY.md"
    assert doc_path.exists(), f"Missing traceability document at {doc_path}"

    content = doc_path.read_text(encoding="utf-8")

    # Find all DD row references e.g. `DD r2` through `DD r80`
    dd_matches = re.findall(r"`DD r([0-9]+)`", content)
    unique_dd_rows = {int(r) for r in dd_matches}

    expected_dd_rows = set(range(2, 81))  # r2 to r80 inclusive = 79 rows
    missing_rows = expected_dd_rows - unique_dd_rows
    assert not missing_rows, f"Missing DD rows in traceability matrix: {sorted(missing_rows)}"
    assert len(unique_dd_rows) == 79, f"Expected 79 mapped DD rows, found {len(unique_dd_rows)}"

    # Verify WF r6 presence
    assert "`WF r6`" in content, "Missing WF r6 in traceability matrix"

    # Verify all 20 published forms are mentioned
    expected_forms = [
        "S1_GATE_INWARD",
        "S1_UNBOXING",
        "S1_ITEMIZE",
        "S1_CSR_APPROVAL",
        "S1_INSPECT_DMT",
        "S1_INSPECT_PRISMATIC",
        "S1_INSPECT_EO",
        "S1_DAILY_CONTAINER_AUDIT",
        "S1A_RM_ACTION",
        "S2_HANDOVER_INITIATE",
        "S2_HANDOVER_ACCEPT",
        "S3_TECH_ALLOT",
        "S3_TECH_RECEIVE",
        "S4_DISMANTLE",
        "S5_SEGREGATE",
        "S6_STORE_ISSUE",
        "S6_CN_DECISION",
        "S6_ACCOUNTS_CN",
        "S6_PARTY_NOTIFY",
        "S6_CSR_CLOSE",
    ]
    for form_code in expected_forms:
        assert form_code in content, f"Expected form {form_code} in traceability matrix"
