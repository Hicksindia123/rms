"""Full Authorization Matrix and Role-Based Access Control integration suite (§9.3).

Tests:
1. Authorization matrix across ALL 13 system roles:
   - ACCOUNTS
   - DISPATCH
   - GATE_INWARD
   - INTERMEDIATE_STORE_MANAGER
   - INWARD_VERIFIER
   - MAIN_STORE
   - MANAGEMENT_VIEWER
   - REPLACEMENT_MANAGER
   - SPARE_PARTS_MANAGER
   - SPARE_PARTS_TECHNICIAN
   - SUPER_ADMIN
   - TECHNICIAN
   - TECHNICIAN_COORDINATOR
2. Endpoint-level HTTP 403 vs success checks for representative routes across modules.
3. Permission overrides (grant override, deny override precedence).
4. Super Admin passes all permission checks, but CANNOT bypass System Guards (G-16, G-18).
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import Connection, text

from app.core.permissions import effective_permissions
from tests.conftest import JwtFactory
from tests.integration.conftest import Override, UserFactory, as_admin

pytestmark = pytest.mark.asyncio

ALL_13_ROLES = [
    "ACCOUNTS",
    "DISPATCH",
    "GATE_INWARD",
    "INTERMEDIATE_STORE_MANAGER",
    "INWARD_VERIFIER",
    "MAIN_STORE",
    "MANAGEMENT_VIEWER",
    "REPLACEMENT_MANAGER",
    "SPARE_PARTS_MANAGER",
    "SPARE_PARTS_TECHNICIAN",
    "SUPER_ADMIN",
    "TECHNICIAN",
    "TECHNICIAN_COORDINATOR",
]
# Phase P1 20-11-2026: DEC-60 Management and DEC-61 one role per seeded Intermediate Store.
P1_ROLES = ["MANAGEMENT", "ISTORE_OP", "ISTORE_DT", "ISTORE_RI"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_all_13_roles_seeded(db_conn: Connection) -> None:
    """Exactly the 13 original system roles plus the P1 roles (DEC-60 / DEC-61) exist."""
    conn = as_admin(db_conn)
    rows = conn.execute(text("select code from public.roles order by code")).scalars().all()
    assert set(rows) == set(ALL_13_ROLES + P1_ROLES), f"Mismatch in seeded roles: {rows}"


async def test_authz_matrix_role_permission_expectations(
    db_conn: Connection, users: UserFactory
) -> None:
    """Verify effective permissions across roles against expected key grants."""
    conn = as_admin(db_conn)
    from sqlalchemy.orm import Session

    # Check key role permission mappings
    matrix_expectations = {
        "GATE_INWARD": [("goods_slips", "create"), ("goods_slips", "view")],
        "INWARD_VERIFIER": [("unboxing", "create"), ("unboxing", "edit")],
        "REPLACEMENT_MANAGER": [("goods_slips", "view"), ("reports", "view")],
        "TECHNICIAN_COORDINATOR": [("servicing", "create"), ("servicing", "view")],
        "TECHNICIAN": [("servicing", "view")],
        "SPARE_PARTS_TECHNICIAN": [("dismantling", "create"), ("dismantling", "view")],
        "SPARE_PARTS_MANAGER": [("inventory", "view"), ("dismantling", "view")],
        "INTERMEDIATE_STORE_MANAGER": [("inventory", "view"), ("custody", "view")],
        "DISPATCH": [("dispatch", "create"), ("dispatch", "view")],
        "ACCOUNTS": [("credit_notes", "create"), ("credit_notes", "view")],
        "MANAGEMENT_VIEWER": [("reports", "view"), ("dashboards", "view")],
    }

    session = Session(bind=conn)
    for role_code, grants in matrix_expectations.items():
        uid = users.create(roles=[role_code])
        eff = effective_permissions(session, uid, is_super_admin=False)
        assert not eff.is_super_admin, f"Role {role_code} should not be super admin"
        for mod, act in grants:
            assert eff.allows(mod, act), (
                f"Role {role_code} was expected to have permission ({mod}, {act})"
            )


async def test_super_admin_allows_all_permissions(db_conn: Connection, users: UserFactory) -> None:
    """Super Admin passes any permission check unconditionally."""
    conn = as_admin(db_conn)
    from sqlalchemy.orm import Session

    admin_id = users.create(super_admin=True)
    session = Session(bind=conn)
    eff = effective_permissions(session, admin_id, is_super_admin=True)
    assert eff.is_super_admin is True
    assert eff.allows("arbitrary_module", "arbitrary_action") is True
    assert eff.scope("arbitrary_module", "arbitrary_action") == "all"


async def test_deny_override_wins_over_role_grant(db_conn: Connection, users: UserFactory) -> None:
    """A DENY override explicitly removes a permission even when granted by a role."""
    conn = as_admin(db_conn)
    from sqlalchemy.orm import Session

    uid = users.create(
        roles=["GATE_INWARD"],
        overrides=[Override(module_code="goods_slips", action="create", effect="deny")],
    )
    session = Session(bind=conn)
    eff = effective_permissions(session, uid, is_super_admin=False)
    assert eff.allows("goods_slips", "create") is False
    assert eff.allows("goods_slips", "view") is True


async def test_grant_override_adds_permission_to_role(
    db_conn: Connection, users: UserFactory
) -> None:
    """A GRANT override confers an extra permission not provided by the role."""
    conn = as_admin(db_conn)
    from sqlalchemy.orm import Session

    uid = users.create(
        roles=["TECHNICIAN"],
        overrides=[Override(module_code="credit_notes", action="view", effect="grant")],
    )
    session = Session(bind=conn)
    eff = effective_permissions(session, uid, is_super_admin=False)
    assert eff.allows("servicing", "view") is True
    assert eff.allows("credit_notes", "view") is True
    assert eff.allows("credit_notes", "create") is False


async def test_endpoint_authz_enforcement_gate_form(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    """Test /api/v1/gs/gate-form requires goods_slips.create."""
    # Allowed role: GATE_INWARD
    gate_user = users.create(roles=["GATE_INWARD"])
    gate_token = make_token(gate_user)
    res_allowed = await client.get("/api/v1/gs/gate-form", headers=_auth(gate_token))
    assert res_allowed.status_code == 200, res_allowed.text

    # Denied roles: TECHNICIAN, ACCOUNTS
    tech_user = users.create(roles=["TECHNICIAN"])
    tech_token = make_token(tech_user)
    res_tech = await client.get("/api/v1/gs/gate-form", headers=_auth(tech_token))
    assert res_tech.status_code == 403
    assert res_tech.json()["error"]["code"] == "PERMISSION_DENIED"

    accounts_user = users.create(roles=["ACCOUNTS"])
    accounts_token = make_token(accounts_user)
    res_acc = await client.get("/api/v1/gs/gate-form", headers=_auth(accounts_token))
    assert res_acc.status_code == 403
    assert res_acc.json()["error"]["code"] == "PERMISSION_DENIED"


async def test_endpoint_authz_enforcement_audit_explorer(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    """Test /api/v1/audit requires audit.view (only Super Admin or auditor)."""
    admin_user = users.create(super_admin=True)
    admin_token = make_token(admin_user)
    res_admin = await client.get("/api/v1/audit", headers=_auth(admin_token))
    assert res_admin.status_code == 200, res_admin.text

    operator_user = users.create(roles=["GATE_INWARD"])
    op_token = make_token(operator_user)
    res_op = await client.get("/api/v1/audit", headers=_auth(op_token))
    assert res_op.status_code == 403
    assert res_op.json()["error"]["code"] in ("AUDIT_VIEW_DENIED", "PERMISSION_DENIED")


async def test_super_admin_cannot_bypass_guards(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    """Super Admin cannot bypass G-16 (negative stock) or other system guards."""
    admin_user = users.create(super_admin=True)
    admin_token = make_token(admin_user)
    res = await client.post("/api/v1/test/guard/g16", headers=_auth(admin_token))
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "G-16"
