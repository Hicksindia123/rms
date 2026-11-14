"""Create the LOCAL demo users named in master plan §3.3 (demo only; never for remote/production).

    .venv/Scripts/python scripts/seed_demo_users.py            # default password Demo@123456

Idempotent: existing users are left in place; roles are (re)assigned with ON CONFLICT DO NOTHING.
Users are created through the Supabase Auth Admin API with `app_metadata.rms_activate = true` and
their profiles are then activated explicitly. Refuses to run unless APP_ENV is `local`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from sqlalchemy import create_engine, text

from app.core.config import get_settings

# §3.3 role catalogue → seed users (demo only). Emails use the local-only rms.local domain.
DEMO_USERS: list[dict[str, Any]] = [
    {"email": "anuj@rms.local", "name": "Anuj", "roles": ["GATE_INWARD"]},
    {
        "email": "aman@rms.local",
        "name": "Aman",
        "roles": ["INWARD_VERIFIER", "TECHNICIAN_COORDINATOR"],
    },
    {
        "email": "pratham@rms.local",
        "name": "Pratham Pratap Singh",
        "roles": ["REPLACEMENT_MANAGER"],
    },
    {
        "email": "sahil@rms.local",
        "name": "Sahil",
        "roles": ["INTERMEDIATE_STORE_MANAGER", "TECHNICIAN_COORDINATOR"],
    },
    {"email": "deepak@rms.local", "name": "Deepak Ji", "roles": ["ACCOUNTS"]},
    {
        "email": "spt@rms.local",
        "name": "Spare Parts Technician",
        "roles": ["SPARE_PARTS_TECHNICIAN"],
    },
    {"email": "spm@rms.local", "name": "Spare Parts Manager", "roles": ["SPARE_PARTS_MANAGER"]},
    {"email": "rajkumar@rms.local", "name": "Raj Kumar Ji", "roles": ["TECHNICIAN"]},
    {"email": "dispatch@rms.local", "name": "Dispatch Team", "roles": ["DISPATCH"]},
    {"email": "mainstore@rms.local", "name": "Main Store Manager", "roles": ["MAIN_STORE"]},
]


def _find_user_id(client: httpx.Client, base: str, headers: dict[str, str], email: str) -> str:
    page = 1
    while True:
        res = client.get(
            f"{base}/auth/v1/admin/users", headers=headers, params={"page": page, "per_page": 200}
        )
        res.raise_for_status()
        users = res.json().get("users", [])
        match = next((u for u in users if u.get("email") == email), None)
        if match:
            return str(match["id"])
        if len(users) < 200:
            raise RuntimeError(f"{email} is registered but was not found in the admin user list")
        page += 1


def seed_demo_users(password: str) -> None:
    settings = get_settings()
    if settings.app_env != "local":
        raise RuntimeError(f"Refusing to create demo users with APP_ENV={settings.app_env!r}")
    key = settings.supabase_service_role_key
    if not key:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY is required")
    secret = key.get_secret_value()
    headers = {"apikey": secret, "Authorization": f"Bearer {secret}"}
    base = str(settings.supabase_url).rstrip("/")
    engine = create_engine(settings.database_url.get_secret_value())

    with httpx.Client(timeout=10) as client:
        for spec in DEMO_USERS:
            res = client.post(
                f"{base}/auth/v1/admin/users",
                headers=headers,
                json={
                    "email": spec["email"],
                    "password": password,
                    "email_confirm": True,
                    "user_metadata": {"full_name": spec["name"]},
                    "app_metadata": {
                        "provider": "email",
                        "providers": ["email"],
                        "rms_activate": True,
                    },
                },
            )
            if res.status_code in (200, 201):
                user_id = str(res.json()["id"])
                state = "created"
            elif res.status_code == 422 and "already" in res.text:
                user_id = _find_user_id(client, base, headers, spec["email"])
                state = "exists"
            else:
                raise RuntimeError(
                    f"{spec['email']}: auth admin error {res.status_code} {res.text}"
                )

            with engine.begin() as conn:
                # GoTrue writes app_metadata after the INSERT the profile trigger sees, so the
                # profile is activated explicitly (same as bootstrap_super_admin.py).
                conn.execute(
                    text("update public.profiles set is_active = true where id = :uid"),
                    {"uid": user_id},
                )
                inserted = conn.execute(
                    text(
                        """
                        insert into public.user_roles (user_id, role_id)
                        select :uid, r.id from public.roles r where r.code = any(:codes)
                        on conflict (user_id, role_id) do nothing
                        """
                    ),
                    {"uid": user_id, "codes": spec["roles"]},
                ).rowcount
            print(f"{spec['email']:<22} {state:<8} roles={','.join(spec['roles'])} (+{inserted})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create local RMS demo users (§3.3).")
    parser.add_argument("--password", default="Demo@123456", help="Password for every demo user")
    args = parser.parse_args()
    try:
        seed_demo_users(args.password)
    except (RuntimeError, httpx.HTTPError) as exc:
        print(f"Error creating demo users: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
