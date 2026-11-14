"""Bootstrap the initial Super Admin user (master plan §9.3, §12, docs/SETUP.md).

Idempotent: if an active Super Admin exists, reports it and exits 0.
Otherwise creates user via Supabase Auth Admin API, sets is_super_admin = true on public.profiles,
and assigns the SUPER_ADMIN role.

Credentials (production audit 2026-11-14, credentials policy): --email/--password, else the
SUPER_ADMIN_EMAIL / SUPER_ADMIN_PASSWORD / SUPER_ADMIN_NAME environment variables, else an
interactive prompt. The local defaults (admin@rms.local / Admin@123456) apply ONLY when APP_ENV is
local or test; elsewhere @rms.local addresses, the default password and passwords outside the
DEC-50 policy are refused. Prefer the environment or the prompt over --password (shell history).
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

# Add backend directory to sys.path so 'app' can be imported
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from sqlalchemy import create_engine, text

from app.core.config import get_settings


def bootstrap_super_admin(
    email: str = "admin@rms.local",
    password: str = "Admin@123456",  # noqa: S107
    full_name: str = "RMS Super Admin",
) -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url.get_secret_value())

    # 1. Check if an active Super Admin exists in public.profiles
    with engine.begin() as conn:
        existing = (
            conn.execute(
                text(
                    """
                    select id, email from public.profiles
                    where is_super_admin and is_active limit 1
                    """
                )
            )
            .mappings()
            .first()
        )

        if existing:
            print(f"Super Admin already exists: {existing['email']} (id: {existing['id']})")
            return

    service_role_key = (
        settings.supabase_service_role_key.get_secret_value()
        if settings.supabase_service_role_key
        else None
    )
    if not service_role_key:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY is required to bootstrap Super Admin")

    print(f"Bootstrapping initial Super Admin: {email} via Supabase Auth...")

    headers = {
        "apikey": service_role_key,
        "Authorization": f"Bearer {service_role_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "email": email,
        "password": password,
        "email_confirm": True,
        "user_metadata": {"full_name": full_name},
        "app_metadata": {"provider": "email", "providers": ["email"], "rms_activate": True},
    }

    with httpx.Client(timeout=10) as client:
        res = client.post(
            f"{settings.supabase_url}/auth/v1/admin/users",
            headers=headers,
            json=payload,
        )
        if res.status_code not in (200, 201):
            # Check if user already exists in auth.users
            if res.status_code == 422 and "already registered" in res.text:
                # Query auth.users to find the ID
                list_res = client.get(
                    f"{settings.supabase_url}/auth/v1/admin/users",
                    headers=headers,
                )
                users = list_res.json().get("users", [])
                match = next((u for u in users if u.get("email") == email), None)
                if not match:
                    raise RuntimeError(f"User exists in auth but could not find ID: {res.text}")
                user_id = match["id"]
            else:
                raise RuntimeError(f"Supabase auth admin error: {res.status_code} - {res.text}")
        else:
            data = res.json()
            user_id = data["id"]

    # 2. Update profile to is_super_admin = true and assign SUPER_ADMIN role
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                update public.profiles
                set is_super_admin = true, is_active = true
                where id = :id
                """
            ),
            {"id": user_id},
        )

        conn.execute(
            text(
                """
                insert into public.user_roles (user_id, role_id)
                select :uid, r.id from public.roles r where r.code = 'SUPER_ADMIN'
                on conflict (user_id, role_id) do nothing
                """
            ),
            {"uid": user_id},
        )

    print(f"Successfully bootstrapped Super Admin: {email} (id: {user_id})")


LOCAL_EMAIL = "admin@rms.local"
LOCAL_PASSWORD = "Admin@123456"  # noqa: S105 - local/test default only, refused elsewhere


def resolve_credentials(
    email: str | None, password: str | None, name: str | None, *, is_local: bool
) -> tuple[str, str, str]:
    """Explicit value > environment > (local default | interactive prompt), then policy checks."""
    from app.modules.users.schemas import check_password_policy

    email = (email or os.environ.get("SUPER_ADMIN_EMAIL") or "").strip().lower()
    password = password or os.environ.get("SUPER_ADMIN_PASSWORD") or ""
    name = (name or os.environ.get("SUPER_ADMIN_NAME") or "RMS Super Admin").strip()
    if is_local:
        return email or LOCAL_EMAIL, password or LOCAL_PASSWORD, name
    if not email:
        email = input("Super Admin email: ").strip().lower()
    if not password:
        password = getpass.getpass("Super Admin password: ")
        if getpass.getpass("Repeat the password: ") != password:
            raise ValueError("The passwords do not match")
    if not email or "@" not in email:
        raise ValueError("A valid Super Admin email is required")
    if email.endswith("@rms.local"):
        raise ValueError("@rms.local accounts are for local development only")
    if password == LOCAL_PASSWORD:
        raise ValueError("The local default password cannot be used outside local/test")
    check_password_policy(password)
    return email, password, name


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap the initial RMS Super Admin user.")
    parser.add_argument("--email", default=None, help="Super Admin email (or SUPER_ADMIN_EMAIL)")
    parser.add_argument(
        "--password", default=None, help="Super Admin password (prefer SUPER_ADMIN_PASSWORD)"
    )
    parser.add_argument("--name", default=None, help="Display name (or SUPER_ADMIN_NAME)")
    args = parser.parse_args()

    try:
        email, password, name = resolve_credentials(
            args.email, args.password, args.name, is_local=get_settings().is_local
        )
        bootstrap_super_admin(email=email, password=password, full_name=name)
    except Exception as exc:  # noqa: BLE001
        print(f"Error bootstrapping Super Admin: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
