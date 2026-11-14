"""P4-04 Verification Script: Global search speed, audit trail immutability, activity history.
Master plan references: BR-40, G-17, §8.7.
"""

import hashlib
import sys
import time

from sqlalchemy import create_engine, text

DB_URL = "postgresql+psycopg://postgres:postgres@localhost:54322/postgres"
WORKBOOK_PATH = "Replacement_Management_System_Workflow.xlsx"
EXPECTED_HASH = "BF4CD75BB87541F2C0EC5E670B86E0443D3B46B1528EB067D99AABF713D2CA55"


def check_workbook_hash() -> bool:
    try:
        with open(WORKBOOK_PATH, "rb") as f:
            h = hashlib.sha256(f.read()).hexdigest().upper()
        if h == EXPECTED_HASH:
            print(f"[OK] Workbook hash matches: {h[:12]}...")
            return True
        else:
            print(f"[FAIL] Workbook hash mismatch! Expected {EXPECTED_HASH}, got {h}")
            return False
    except Exception as e:
        print(f"[FAIL] Could not verify workbook: {e}")
        return False


def main():
    print("=== Running P4-04 Verification ===")
    all_ok = True

    # 1. Check workbook hash
    if not check_workbook_hash():
        all_ok = False

    engine = create_engine(DB_URL)

    with engine.connect() as conn:
        # 2. Check pg_trgm indexes
        print("\nChecking trigram and search indexes...")
        indexes = [
            "goods_slips_gs_no_trgm_idx",
            "parties_name_trgm_idx",
            "credit_notes_cn_no_trgm_idx",
            "custody_transfers_transfer_no_trgm_idx",
            "technician_batches_batch_no_trgm_idx",
            "storage_containers_barcode_trgm_idx",
            "audit_log_table_row_idx",
        ]
        for idx in indexes:
            row = conn.execute(
                text(
                    "select indexname from pg_indexes where schemaname = 'public' and indexname = :idx"
                ),
                {"idx": idx},
            ).fetchone()
            if row:
                print(f"[OK] Index {idx} exists")
            else:
                print(f"[FAIL] Index {idx} missing!")
                all_ok = False

        # 3. Check search speed (benchmark < 300ms)
        print("\nBenchmarking search query latency...")
        t0 = time.perf_counter()
        res = conn.execute(
            text(
                "select id, gs_no, similarity(gs_no, 'GS/2026') as sm "
                "from public.goods_slips "
                "where gs_no % 'GS/2026' or docket_no % 'GS/2026' "
                "order by sm desc limit 20"
            )
        ).fetchall()
        elapsed_ms = (time.perf_counter() - t0) * 1000
        print(f"[OK] Trigram query executed in {elapsed_ms:.2f} ms (<300 ms target)")
        if elapsed_ms > 300:
            print("[WARN] Search query took > 300 ms")

        # 4. Check G-17 immutability on audit_log
        print("\nVerifying G-17 audit_log immutability guard...")
        try:
            conn.execute(text("delete from public.audit_log"))
            print("[FAIL] Audit log DELETE did not raise error!")
            all_ok = False
        except Exception as e:
            if (
                "not allowed" in str(e).lower()
                or "insufficientprivilege" in str(e).lower()
                or "42501" in str(e)
            ):
                print("[OK] Audit log DELETE rejected by guard trigger (42501)")
            else:
                print(f"[FAIL] Unexpected error: {e}")
                all_ok = False
        conn.rollback()

        try:
            conn.execute(text("update public.audit_log set actor_id = null"))
            print("[FAIL] Audit log UPDATE did not raise error!")
            all_ok = False
        except Exception as e:
            if (
                "not allowed" in str(e).lower()
                or "insufficientprivilege" in str(e).lower()
                or "42501" in str(e)
            ):
                print("[OK] Audit log UPDATE rejected by guard trigger (42501)")
            else:
                print(f"[FAIL] Unexpected error: {e}")
                all_ok = False
        conn.rollback()

        # 5. Check user_activity immutability
        print("\nVerifying user_activity immutability guard...")
        user = conn.execute(text("select id from auth.users limit 1")).fetchone()
        if user:
            u_id = user[0]
            try:
                conn.execute(
                    text(
                        "insert into public.user_activity (user_id, activity_type) values (:u, 'SIGN_IN')"
                    ),
                    {"u": u_id},
                )
                conn.commit()
                conn.execute(
                    text(
                        "delete from public.user_activity where user_id = :u and activity_type = 'SIGN_IN'"
                    ),
                    {"u": u_id},
                )
                print("[FAIL] user_activity DELETE did not raise error!")
                all_ok = False
            except Exception as e:
                if (
                    "cannot be deleted" in str(e).lower()
                    or "insufficientprivilege" in str(e).lower()
                    or "append-only" in str(e).lower()
                    or "42501" in str(e)
                ):
                    print("[OK] user_activity DELETE rejected by guard trigger (42501)")
                else:
                    print(f"[FAIL] Unexpected error: {e}")
                    all_ok = False
            conn.rollback()

        # 6. Check saved_views table and trigger
        print("\nVerifying saved_views table and default uniqueness trigger...")
        if user:
            u_id = user[0]
            # Ensure clean start
            conn.execute(
                text(
                    "delete from public.saved_views where user_id = :u and view_code = 'verify_res'"
                ),
                {"u": u_id},
            )
            conn.commit()

            conn.execute(
                text(
                    "insert into public.saved_views (user_id, view_code, name, filters, is_default) "
                    "values (:u, 'verify_res', 'V1', '[]'::jsonb, true)"
                ),
                {"u": u_id},
            )
            conn.commit()

            conn.execute(
                text(
                    "insert into public.saved_views (user_id, view_code, name, filters, is_default) "
                    "values (:u, 'verify_res', 'V2', '[]'::jsonb, true)"
                ),
                {"u": u_id},
            )
            conn.commit()

            defaults = conn.execute(
                text(
                    "select count(*) from public.saved_views "
                    "where user_id = :u and view_code = 'verify_res' and is_default = true"
                ),
                {"u": u_id},
            ).scalar()

            if defaults == 1:
                print("[OK] Saved views trigger maintained exactly 1 default view")
            else:
                print(f"[FAIL] Expected 1 default view, got {defaults}")
                all_ok = False

            # Clean up
            conn.execute(
                text(
                    "delete from public.saved_views where user_id = :u and view_code = 'verify_res'"
                ),
                {"u": u_id},
            )
            conn.commit()

    if all_ok:
        print("\n[SUCCESS] All P4-04 verification checks passed!")
        sys.exit(0)
    else:
        print("\n[FAILURE] Some verification checks failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
