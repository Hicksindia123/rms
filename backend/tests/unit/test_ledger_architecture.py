"""Architecture enforcement test for inventory ledger (prompt P2-01).

Guarantees that all stock movement and balance mutations flow strictly
through the authoritative ledger service and database functions.
No other service or repository may directly insert, update, or delete
stock_movements or stock_balances.
"""

from __future__ import annotations

import re
from pathlib import Path


def test_no_direct_writes_to_stock_movements_or_balances() -> None:
    """Assert that no code outside ledger_service writes to stock_movements or stock_balances."""
    app_dir = Path(__file__).resolve().parents[2] / "app"
    assert app_dir.exists(), f"App directory not found: {app_dir}"

    # Pattern detecting INSERT/UPDATE/DELETE targeting stock_movements or stock_balances
    forbidden_pattern = re.compile(
        r"(?i)(insert\s+into|update|delete\s+from)\s+(?:public\.)?stock_(?:movements|balances)\b"
    )

    violations: list[str] = []

    for py_file in app_dir.rglob("*.py"):
        # ledger_service.py is also checked to ensure it uses rms_private functions
        # rather than direct SQL inserts on stock_movements / stock_balances
        content = py_file.read_text(encoding="utf-8")
        for line_no, line in enumerate(content.splitlines(), start=1):
            if forbidden_pattern.search(line):
                violations.append(f"{py_file.name}:{line_no} -> {line.strip()}")

    assert not violations, (
        "Direct SQL writes to stock_movements or stock_balances are forbidden:\n"
        + "\n".join(violations)
    )


def test_no_insert_into_stock_outside_inventory_module() -> None:
    """Assert that no repository outside app/modules/inventory writes to stock_ tables."""
    modules_dir = Path(__file__).resolve().parents[2] / "app" / "modules"
    assert modules_dir.exists(), f"Modules directory not found: {modules_dir}"

    stock_insert_pattern = re.compile(r"(?i)insert\s+into\s+(?:public\.)?stock_")

    violations: list[str] = []

    for py_file in modules_dir.rglob("*.py"):
        # Skip inventory module and test support router
        if "inventory" in py_file.parts or "test_support" in py_file.parts:
            continue

        content = py_file.read_text(encoding="utf-8")
        for line_no, line in enumerate(content.splitlines(), start=1):
            if stock_insert_pattern.search(line):
                violations.append(f"{py_file.name}:{line_no} -> {line.strip()}")

    assert not violations, (
        "Direct INSERT into stock_ tables outside inventory module is forbidden:\n"
        + "\n".join(violations)
    )
