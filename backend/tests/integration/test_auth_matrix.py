"""Authorization matrix integration tests (master plan §9.2, prompt P1-09).

Parametrised test calling /admin and /masters endpoints for each seeded role.
Expectations (200 vs 403) are derived dynamically from public.role_permissions in the DB,
never hard-coded.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from tests.conftest import JwtFactory
from tests.integration.conftest import UserFactory

# Target endpoints representing admin and masters areas and their required permissions
MATRIX_ENDPOINTS = [
    # Config / Admin endpoints requiring ("config", "view")
    ("GET", "/api/v1/config/option-sets", "config", "view"),
    ("GET", "/api/v1/config/forms", "config", "view"),
    ("GET", "/api/v1/config/workflow", "config", "view"),
    ("GET", "/api/v1/config/numbering", "config", "view"),
    ("GET", "/api/v1/config/settings", "config", "view"),
    ("GET", "/api/v1/config/templates", "config", "view"),
    ("GET", "/api/v1/config/history", "config", "view"),
    ("GET", "/api/v1/config/system-guards", "config", "view"),
    ("GET", "/api/v1/admin/config-history", "config", "view"),
    ("GET", "/api/v1/admin/system-guards", "config", "view"),
    # Masters endpoints requiring ("masters", "view")
    ("GET", "/api/v1/template/departments", "masters", "view"),
]

SEEDED_ROLES = [
    "SUPER_ADMIN",
    "GATE_INWARD",
    "INWARD_VERIFIER",
    "REPLACEMENT_MANAGER",
    "INTERMEDIATE_STORE_MANAGER",
    "TECHNICIAN_COORDINATOR",
    "TECHNICIAN",
    "SPARE_PARTS_TECHNICIAN",
    "SPARE_PARTS_MANAGER",
    "ACCOUNTS",
    "DISPATCH",
    "MAIN_STORE",
    "MANAGEMENT_VIEWER",
]


@pytest.mark.parametrize("role_code", SEEDED_ROLES)
@pytest.mark.parametrize("method,path,module_code,action", MATRIX_ENDPOINTS)
async def test_authorization_matrix(
    client: AsyncClient,
    users: UserFactory,
    make_token: JwtFactory,
    role_code: str,
    method: str,
    path: str,
    module_code: str,
    action: str,
) -> None:
    """Dynamically query DB permissions for `role_code` and assert matching response status."""
    conn = users.conn

    # 1. Query role permissions dynamically from DB
    perm_query = text(
        """
        select exists (
            select 1
            from public.role_permissions rp
            join public.roles r on r.id = rp.role_id
            join public.permissions p on p.id = rp.permission_id
            where r.code = :role_code
              and p.module_code = :module_code
              and p.action = :action
        )
        """
    )
    has_permission = conn.execute(
        perm_query,
        {"role_code": role_code, "module_code": module_code, "action": action},
    ).scalar()

    # Super Admin has is_super_admin = True which grants all rights
    is_sa = role_code == "SUPER_ADMIN"
    expected_allowed = bool(has_permission or is_sa)

    # 2. Create user with the specified role
    user_id = users.create(roles=[role_code], super_admin=is_sa)
    token = make_token(user_id)
    headers = {"Authorization": f"Bearer {token}"}

    # 3. Call endpoint
    if method == "GET":
        res = await client.get(path, headers=headers)
    elif method == "POST":
        res = await client.post(path, headers=headers, json={})
    else:
        raise ValueError(f"Unsupported method: {method}")

    # 4. Assert response code based on DB expectations
    if expected_allowed:
        assert res.status_code == 200, (
            f"Expected 200 for role '{role_code}' on {method} {path}, "
            f"got {res.status_code}: {res.text}"
        )
    else:
        assert res.status_code == 403, (
            f"Expected 403 for role '{role_code}' on {method} {path}, "
            f"got {res.status_code}: {res.text}"
        )
        body = res.json()
        assert body["error"]["code"] == "PERMISSION_DENIED"
