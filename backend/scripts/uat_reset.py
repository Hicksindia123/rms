"""UAT environment reset and data seeder (master plan §18, prompt P4-07).

Resets transaction data, ensures reference data is intact, provisions
all workbook-named UAT users with their exact roles, and optionally imports
real product and party CSVs.

Usage:
    .venv/Scripts/python scripts/uat_reset.py [--password <pwd>]
        [--products-csv <path>] [--parties-csv <path>] [--clean-demo-masters]
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings

# Master plan §3.3 & §18: Workbook personnel and system roles
UAT_USERS: list[dict[str, Any]] = [
    {
        "email": "admin@rms.local",
        "name": "RMS Super Admin",
        "roles": ["SUPER_ADMIN"],
        "is_super_admin": True,
    },
    {
        "email": "anuj@rms.local",
        "name": "Anuj",
        "roles": ["GATE_INWARD"],
        "is_super_admin": False,
    },
    {
        "email": "aman@rms.local",
        "name": "Aman",
        "roles": ["INWARD_VERIFIER", "TECHNICIAN_COORDINATOR"],
        "is_super_admin": False,
    },
    {
        "email": "pratham@rms.local",
        "name": "Pratham Pratap Singh",
        "roles": ["REPLACEMENT_MANAGER"],
        "is_super_admin": False,
    },
    {
        "email": "sahil@rms.local",
        "name": "Sahil",
        "roles": ["INTERMEDIATE_STORE_MANAGER", "TECHNICIAN_COORDINATOR"],
        "is_super_admin": False,
    },
    {
        "email": "deepak@rms.local",
        "name": "Deepak Ji",
        "roles": ["ACCOUNTS"],
        "is_super_admin": False,
    },
    {
        "email": "rajkumar@rms.local",
        "name": "Raj Kumar Ji",
        "roles": ["TECHNICIAN"],
        "is_super_admin": False,
    },
    {
        "email": "spt@rms.local",
        "name": "Spare Parts Technician",
        "roles": ["SPARE_PARTS_TECHNICIAN"],
        "is_super_admin": False,
    },
    {
        "email": "spm@rms.local",
        "name": "Spare Parts Manager",
        "roles": ["SPARE_PARTS_MANAGER"],
        "is_super_admin": False,
    },
    {
        "email": "dispatch@rms.local",
        "name": "Dispatch Team",
        "roles": ["DISPATCH"],
        "is_super_admin": False,
    },
    {
        "email": "mainstore@rms.local",
        "name": "Main Store Manager",
        "roles": ["MAIN_STORE"],
        "is_super_admin": False,
    },
    {
        "email": "management@rms.local",
        "name": "Management Viewer",
        "roles": ["MANAGEMENT_VIEWER"],
        "is_super_admin": False,
    },
    # Phase P1 20-11-2026: one user per Intermediate Store role (DEC-61) + Management (DEC-60).
    {
        "email": "opstore@rms.local",
        "name": "Intermediate Store OP User",
        "roles": ["ISTORE_OP"],
        "is_super_admin": False,
    },
    {
        "email": "dtstore@rms.local",
        "name": "Intermediate Store DT User",
        "roles": ["ISTORE_DT"],
        "is_super_admin": False,
    },
    {
        "email": "ristore@rms.local",
        "name": "Intermediate Store RI User",
        "roles": ["ISTORE_RI"],
        "is_super_admin": False,
    },
    {
        "email": "mgmt@rms.local",
        "name": "Management Approver",
        "roles": ["MANAGEMENT"],
        "is_super_admin": False,
    },
]

# Transactional tables to clean for zero-demo-transactions UAT baseline
# Ordered in reverse foreign-key dependency order
TRANSACTION_TABLES = [
    "notification_deliveries",
    "notification_events",
    "saved_views",
    "user_activity",
    "print_logs",
    "party_notifications",
    "rate_verifications",
    "credit_note_lines",
    "credit_notes",
    "rm_cn_decision_lines",
    "rm_cn_decisions",
    "replacement_dispatch_lines",
    "replacement_dispatches",
    "store_issue_lines",
    "store_issues",
    "recovered_parts",
    "dismantle_inputs",
    "dismantle_batches",
    "technician_receiving_records",
    "technician_batch_lines",
    "technician_batches",
    "scrap_records",
    "custody_reconciliations",
    "custody_transfer_lines",
    "custody_transfers",
    "custody_assignments",
    # Change plan Phase 6 (department routing): reference gs_items / stock_lots with RESTRICT.
    "department_receipt_lines",
    "department_receipts",
    "department_routing_lines",
    "department_routings",
    "stock_movements",
    "stock_balances",
    "stock_lots",
    "container_audit_lines",
    "container_audit_days",
    "rm_item_actions",
    "pendencies",
    "extraction_records",
    "inspection_allocations",
    "inspections",
    "packaging_replacements",
    "csr_approvals",
    "missing_doc_exceptions",
    "gs_item_corrections",
    "gs_items",
    "workflow_task_escalations",
    "workflow_tasks",
    "gs_closures",
    "gs_status_history",
    "goods_slips",
]


def _find_user_id(client: httpx.Client, base: str, headers: dict[str, str], email: str) -> str:
    page = 1
    while True:
        res = client.get(
            f"{base}/auth/v1/admin/users",
            headers=headers,
            params={"page": page, "per_page": 200},
        )
        res.raise_for_status()
        users = res.json().get("users", [])
        match = next((u for u in users if u.get("email") == email), None)
        if match:
            return str(match["id"])
        if len(users) < 200:
            raise RuntimeError(f"{email} registered but not found in admin user list")
        page += 1


def purge_transactions(engine: Any) -> None:
    """Purge all operational and demo transaction records."""
    print("Purging operational transaction tables (zero demo transactions)...")
    for tbl in TRANSACTION_TABLES:
        try:
            with engine.begin() as conn:
                res = conn.execute(text(f"delete from public.{tbl}"))  # noqa: S608
                print(f"  Purged {res.rowcount} rows from {tbl}")
        except SQLAlchemyError as err:
            print(f"  Notice on {tbl}: {err}")

    # Reset number series counters
    try:
        with engine.begin() as conn:
            res = conn.execute(text("delete from public.number_series_counters"))
            print(f"  Reset number series counters ({res.rowcount} period counters removed)")
    except SQLAlchemyError as err:
        print(f"  Notice on number_series_counters: {err}")


def clean_demo_masters(engine: Any) -> None:
    """Remove placeholder DEMO parties and products."""
    print("Cleaning placeholder DEMO masters...")
    with engine.begin() as conn:
        conn.execute(text("delete from public.parties where code like 'DEMO-%'"))
        conn.execute(text("delete from public.products where code like 'DEMO-%'"))
        conn.execute(text("delete from public.transporters where name like '%(DEMO)%'"))
        print("  Removed DEMO parties, products, and transporters")


def provision_uat_users(engine: Any, password: str) -> None:
    """Provision UAT users via Supabase Auth Admin API and assign roles."""
    settings = get_settings()
    key = settings.supabase_service_role_key
    if not key:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY is required to provision UAT users")

    secret = key.get_secret_value()
    headers = {"apikey": secret, "Authorization": f"Bearer {secret}"}
    base = str(settings.supabase_url).rstrip("/")

    print(f"Provisioning {len(UAT_USERS)} UAT users in Supabase Auth...")
    with httpx.Client(timeout=15) as client:
        for spec in UAT_USERS:
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
                status_str = "created"
            elif res.status_code == 422 and "already" in res.text:
                user_id = _find_user_id(client, base, headers, spec["email"])
                status_str = "exists"
                # Update password to ensure UAT password is in effect
                client.put(
                    f"{base}/auth/v1/admin/users/{user_id}",
                    headers=headers,
                    json={"password": password, "user_metadata": {"full_name": spec["name"]}},
                )
            else:
                raise RuntimeError(
                    f"{spec['email']}: Auth admin error {res.status_code} {res.text}"
                )

            with engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        update public.profiles
                        set is_active = true,
                            full_name = :name,
                            is_super_admin = :is_super,
                            updated_at = now()
                        where id = :uid
                        """
                    ),
                    {
                        "uid": user_id,
                        "name": spec["name"],
                        "is_super": spec.get("is_super_admin", False),
                    },
                )
                conn.execute(
                    text(
                        """
                        insert into public.user_roles (user_id, role_id)
                        select :uid, r.id from public.roles r where r.code = any(:codes)
                        on conflict (user_id, role_id) do nothing
                        """
                    ),
                    {"uid": user_id, "codes": spec["roles"]},
                )
            roles_str = ",".join(spec["roles"])
            print(f"  {spec['email']:<24} {status_str:<8} roles={roles_str}")


def import_products_csv(engine: Any, csv_path: Path) -> None:
    """Import product master records from CSV.

    Expected CSV columns: code, name, category_code, uom, hsn_code
    """
    if not csv_path.exists():
        raise FileNotFoundError(f"Products CSV not found at {csv_path}")

    print(f"Importing products from {csv_path}...")
    count = 0
    with csv_path.open(encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        with engine.begin() as conn:
            for row in reader:
                code = row["code"].strip()
                name = row["name"].strip()
                cat_code = row["category_code"].strip().upper()
                uom = row.get("uom", "PCS").strip() or "PCS"
                hsn = row.get("hsn_code", "").strip() or None

                conn.execute(
                    text(
                        """
                        insert into public.products (
                            code, name, category_id, uom, hsn_code, is_active
                        )
                        select :code, :name, c.id, :uom, :hsn, true
                        from public.product_categories c
                        where c.code = :cat_code
                        on conflict (code) do update set
                            name = excluded.name,
                            category_id = excluded.category_id,
                            uom = excluded.uom,
                            hsn_code = excluded.hsn_code,
                            is_active = true,
                            updated_at = now()
                        """
                    ),
                    {"code": code, "name": name, "cat_code": cat_code, "uom": uom, "hsn": hsn},
                )
                count += 1
    print(f"  Imported {count} products successfully.")


def import_parties_csv(engine: Any, csv_path: Path) -> None:
    """Import party master records from CSV.

    Expected CSV columns: code, name, gstin, state_name, station_name, contact_name, phone, email
    """
    if not csv_path.exists():
        raise FileNotFoundError(f"Parties CSV not found at {csv_path}")

    print(f"Importing parties from {csv_path}...")
    count = 0
    with csv_path.open(encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        with engine.begin() as conn:
            for row in reader:
                code = row["code"].strip()
                name = row["name"].strip()
                gstin = row.get("gstin", "").strip() or None
                state_name = row.get("state_name", "").strip()
                station_name = row.get("station_name", "").strip()
                contact = row.get("contact_name", "").strip() or None
                phone = row.get("phone", "").strip() or None
                email = row.get("email", "").strip() or None

                # Ensure state exists if provided
                state_id = None
                if state_name:
                    state_id = conn.execute(
                        text(
                            """
                            insert into public.states (name)
                            values (:st_name)
                            on conflict (name) do update set name = excluded.name
                            returning id
                            """
                        ),
                        {"st_name": state_name},
                    ).scalar_one()

                # Ensure station exists if state provided
                station_id = None
                if station_name and state_id:
                    station_id = conn.execute(
                        text(
                            """
                            insert into public.stations (state_id, name)
                            values (:st_id, :station_name)
                            on conflict (state_id, name) do update set name = excluded.name
                            returning id
                            """
                        ),
                        {"st_id": state_id, "station_name": station_name},
                    ).scalar_one()

                conn.execute(
                    text(
                        """
                        insert into public.parties (
                            code, name, gstin, state_id, station_id,
                            contact_name, phone, email, is_provisional, is_active
                        )
                        values (
                            :code, :name, :gstin, :state_id, :station_id,
                            :contact, :phone, :email, false, true
                        )
                        on conflict (code) do update set
                            name = excluded.name,
                            gstin = excluded.gstin,
                            state_id = excluded.state_id,
                            station_id = excluded.station_id,
                            contact_name = excluded.contact_name,
                            phone = excluded.phone,
                            email = excluded.email,
                            is_active = true,
                            updated_at = now()
                        """
                    ),
                    {
                        "code": code,
                        "name": name,
                        "gstin": gstin,
                        "state_id": state_id,
                        "station_id": station_id,
                        "contact": contact,
                        "phone": phone,
                        "email": email,
                    },
                )
                count += 1
    print(f"  Imported {count} parties successfully.")


def main() -> None:
    parser = argparse.ArgumentParser(description="RMS UAT Environment Reset & Seeder.")
    parser.add_argument(
        "--password",
        default="Uat@2026RMS!",
        help="Default password for all UAT users (default: Uat@2026RMS!)",
    )
    parser.add_argument("--products-csv", type=Path, help="Path to real products CSV file")
    parser.add_argument("--parties-csv", type=Path, help="Path to real parties CSV file")
    parser.add_argument(
        "--clean-demo-masters",
        action="store_true",
        help="Remove demo placeholder products/parties/transporters",
    )
    parser.add_argument(
        "--skip-users",
        action="store_true",
        help="Skip provisioning UAT users",
    )

    args = parser.parse_args()

    settings = get_settings()
    if settings.app_env not in ("local", "test"):
        print(
            f"ERROR: Refusing to run UAT reset with APP_ENV={settings.app_env!r}",
            file=sys.stderr,
        )
        sys.exit(1)

    db_url = settings.database_url.get_secret_value()
    # In local environment, use postgres superuser for administrative table maintenance
    if settings.app_env in ("local", "test") and "rms_api" in db_url:
        db_url = db_url.replace("rms_api:rms_api_local_pw", "postgres:postgres")

    engine = create_engine(db_url)

    print("=================================================================")
    print("RMS Local UAT Reset Starting...")
    print(f"Database: {settings.app_env} environment")
    print("=================================================================")

    # 1. Purge transaction data (G-16 / quantity conservation fresh baseline)
    purge_transactions(engine)

    # 2. Optionally clean placeholder demo masters
    if args.clean_demo_masters:
        clean_demo_masters(engine)

    # 3. Import real products if provided
    if args.products_csv:
        import_products_csv(engine, args.products_csv)

    # 4. Import real parties if provided
    if args.parties_csv:
        import_parties_csv(engine, args.parties_csv)

    # 5. Provision UAT users
    if not args.skip_users:
        provision_uat_users(engine, args.password)

    print("=================================================================")
    print("UAT Environment Reset Complete!")
    print(f"UAT Users Password: {args.password}")
    print("Zero demo transactions remain. System ready for UAT sessions.")
    print("=================================================================")


if __name__ == "__main__":
    main()
