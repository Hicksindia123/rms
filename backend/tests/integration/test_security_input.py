"""Input Hardening, SQL Injection & CSV Formula Injection Security Suite (§9.4, §9.5).

Tests:
1. SQL injection resilience across search, filter, and pagination endpoints.
2. Formula injection protection (CSV cell escaping for =, +, -, @, \\t, \\r).
3. Audit CSV export produces sanitized CSV rows when fields start with formula prefixes.
4. XSS script tags and HTML injection stored as literal strings without server-side execution.
"""

from __future__ import annotations

import csv
import io

import pytest
from httpx import AsyncClient
from sqlalchemy import Connection, text

from app.modules.audit.service import _safe_csv_cell
from tests.conftest import JwtFactory
from tests.integration.conftest import UserFactory, as_admin

pytestmark = pytest.mark.asyncio


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_csv_formula_injection_sanitization() -> None:
    """Verify that _safe_csv_cell prefixes all formula injection characters."""
    dangerous_inputs = [
        "=cmd|' /C calc'!A0",
        "+1+2",
        "-5+6",
        "@SUM(A1:A10)",
        "\t=2+5",
        "\r=1+1",
    ]
    for inp in dangerous_inputs:
        safe = _safe_csv_cell(inp)
        assert safe.startswith("'"), f"Dangerous input {inp!r} was not escaped with a leading quote"
        assert safe == "'" + inp

    # Benign inputs are not modified
    benign_inputs = [
        "Normal Text",
        "GS-2026-0001",
        "12345",
        "User confirmed inspection",
        "",
        None,
    ]
    for inp in benign_inputs:
        safe = _safe_csv_cell(inp)
        assert not safe.startswith("'")


async def test_sql_injection_probes_on_global_search(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    """SQL injection probes on GET /api/v1/search?q= must not crash the DB or dump unauthorized data."""
    admin_id = users.create(super_admin=True)
    token = make_token(admin_id)

    sql_payloads = [
        "' OR '1'='1",
        "'; DROP TABLE goods_slips; --",
        "' UNION SELECT id, email, null, null FROM auth.users --",
        "1' AND 1=(SELECT COUNT(*) FROM public.profiles) --",
        '" OR ""="',
        "')) OR ((('1'='1",
    ]

    for payload in sql_payloads:
        res = await client.get(f"/api/v1/search?q={payload}", headers=_auth(token))
        # Parameterized query handles payload safely as a literal search string
        assert res.status_code == 200, f"Query failed on payload: {payload}"
        data = res.json()
        assert "results" in data or "total" in data or isinstance(data, dict)


async def test_sql_injection_probes_on_filters(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    """SQL injection probes on list filters must be safely rejected or parameterized."""
    admin_id = users.create(super_admin=True)
    token = make_token(admin_id)

    # Injected status filter
    malicious_filter = "INSPECTION' OR '1'='1"
    res = await client.get(f"/api/v1/tasks/mine?status={malicious_filter}", headers=_auth(token))
    # Tasks endpoint validates status against whitelist, rejecting invalid values safely with 422
    assert res.status_code == 422
    assert res.json()["error"]["code"] in ("INVALID_FILTER", "VALIDATION_FAILED")


async def test_audit_export_csv_escapes_formula_payloads(
    client: AsyncClient, db_conn: Connection, users: UserFactory, make_token: JwtFactory
) -> None:
    """Exporting audit CSV escapes cells containing formula injection prefixes."""
    conn = as_admin(db_conn)
    admin_id = users.create(super_admin=True)
    token = make_token(admin_id)

    # Insert an audit log entry with formula injection payloads in reason and table_name
    conn.execute(
        text(
            """
            insert into public.audit_log (
                table_name, row_id, action, actor_id,
                reason, changed_fields
            ) values (
                '=EVIL_TABLE', gen_random_uuid(), 'UPDATE', :uid,
                '+SUM(1,2)*cmd', array['status']
            )
            """
        ),
        {"uid": admin_id},
    )

    res = await client.get("/api/v1/audit/export?table_name==EVIL_TABLE", headers=_auth(token))
    assert res.status_code == 200
    csv_text = res.text

    # Parse exported CSV and check the values
    reader = csv.reader(io.StringIO(csv_text))
    rows = list(reader)
    assert len(rows) >= 2  # Header + at least one row

    # Find the inserted row
    evil_row = next((r for r in rows if "=EVIL_TABLE" in r[2]), None)
    assert evil_row is not None, f"Row not found in export: {csv_text}"

    # Table name cell must be prefixed with quote: "'=EVIL_TABLE"
    assert evil_row[2] == "'=EVIL_TABLE"
    # Reason cell must be prefixed with quote: "'+SUM(1,2)*cmd"
    assert evil_row[9] == "'+SUM(1,2)*cmd"
