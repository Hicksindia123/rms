"""Unit test for traceability of Business Rules (BR-01..BR-40) and Guards (G-01..G-18).

Enforces prompt P4-06 task 1:
Every BR-01..BR-40 and G-01..G-18 has at least one explicit test referenced in
docs/TRACEABILITY_TESTS.md (BR/G id -> test names).
Fails if any BR/G id is missing or has empty test coverage.
"""

import re
from pathlib import Path


def test_all_guards_and_business_rules_in_traceability_matrix() -> None:
    doc_path = Path(__file__).resolve().parents[3] / "docs" / "TRACEABILITY_TESTS.md"
    assert doc_path.exists(), f"Missing docs/TRACEABILITY_TESTS.md at {doc_path}"

    content = doc_path.read_text(encoding="utf-8")

    # Verify all 18 System Guards: G-01 through G-18
    expected_guards = [f"G-{i:02d}" for i in range(1, 19)]
    missing_guards = []
    for g_id in expected_guards:
        # Check table row: | **G-xx** | ... | ... | test_name ... |
        pattern = rf"\|\s*\*\*{re.escape(g_id)}\*\*\s*\|([^|]+)\|([^|]+)\|([^|\r\n]+)\|"
        match = re.search(pattern, content)
        if not match:
            missing_guards.append(g_id)
        else:
            test_col = match.group(3).strip()
            assert test_col, f"Guard {g_id} has empty test coverage in docs/TRACEABILITY_TESTS.md"

    assert not missing_guards, f"Missing guards in docs/TRACEABILITY_TESTS.md: {missing_guards}"

    # Verify all 40 Business Rules: BR-01 through BR-40
    expected_rules = [f"BR-{i:02d}" for i in range(1, 41)]
    missing_rules = []
    for br_id in expected_rules:
        # Check table row: | **BR-xx** | ... | ... | test_name ... |
        pattern = rf"\|\s*\*\*{re.escape(br_id)}\*\*\s*\|([^|]+)\|([^|]+)\|([^|\r\n]+)\|"
        match = re.search(pattern, content)
        if not match:
            missing_rules.append(br_id)
        else:
            test_col = match.group(3).strip()
            assert test_col, (
                f"Business rule {br_id} has empty test coverage in docs/TRACEABILITY_TESTS.md"
            )

    assert not missing_rules, (
        f"Missing business rules in docs/TRACEABILITY_TESTS.md: {missing_rules}"
    )
