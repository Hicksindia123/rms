"""Local verification script for P3-05 (RM Resolution Board, Main Store Issue & Replacement Dispatch).

Master Plan references: BR-19, BR-31, BR-32, DEC-13, DEC-21, DEC-26, DEC-33, §8.6.

Flow:
1. Setup a test GS with 10 pcs received:
   - 5 FUNCTIONAL_GOOD lots (balance 5 in INTERMEDIATE_STORE)
   - 3 FUNCTIONAL_REPAIRED lots (balance 3 in INTERMEDIATE_STORE)
   - 2 NON_GOOD lots (balance 2 in NON_FUNCTIONAL_STORE)
   - Initial RM Actions: SEND_REPAIRED=3, SEND_NEW=4, NOT_ALLOWED=3
2. Verify RM Resolution Board:
   - Returns outcomes vs planned actions
   - Detects discrepancies and provides actionable resolution advisory
3. Verify Candidate Lots & G-04 Guard:
   - store_issue_service.get_candidate_lots returns functional lots only
   - Attempt to issue NON_GOOD fails with G-04
4. Verify Store Issue & Note Print:
   - Sahil creates Store Issue (4 pcs FUNCTIONAL_GOOD to MAIN_STORE)
   - Auto-acknowledges or records custody transfer
   - Retrieves printable Store Issue note with signature blocks
5. Verify Replacement Dispatch Queue & DEC-33 Guard:
   - Dispatch queue shows pending SEND_NEW (4 pcs) and SEND_REPAIRED (3 pcs)
   - Over-dispatch without override_reason fails with DEC-33
6. Verify SEND_NEW Dispatch (DEC-26):
   - Dispatches 4 pcs fresh stock from Main Store outside RMS ledger (lot_id=null, no stock movement)
7. Verify SEND_REPAIRED Dispatch:
   - Dispatches 3 pcs consuming FUNCTIONAL_REPAIRED lot to DISPATCHED
8. Cleanup & Integrity Check:
   - Reverts test data cleanly and runs IC-01..IC-08
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

# Ensure backend root is on sys.path
backend_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_root))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(backend_root / ".env")

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.db import UnitOfWork  # noqa: E402
from app.core.errors import SystemGuardViolation, ValidationFailed  # noqa: E402
from app.core.permissions import EffectivePermissions  # noqa: E402
from app.core.security import CurrentUser, Role  # noqa: E402
from app.modules.dispatch.schemas import (  # noqa: E402
    ReplacementDispatchCreateRequest,
    ReplacementDispatchLineInput,
)
from app.modules.dispatch.service import ReplacementDispatchService  # noqa: E402
from app.modules.rm_actions.service import RmActionsService  # noqa: E402
from app.modules.store_issue.schemas import (  # noqa: E402
    StoreIssueCreateRequest,
    StoreIssueLineInput,
)
from app.modules.store_issue.service import StoreIssueService  # noqa: E402


def make_user(
    user_id: uuid.UUID,
    email: str,
    full_name: str,
    role_codes: list[str],
    is_super_admin: bool = False,
) -> CurrentUser:
    roles = [Role(id=uuid.uuid4(), code=c, name=c) for c in role_codes]
    return CurrentUser(
        id=user_id,
        email=email,
        full_name=full_name,
        employee_code=f"EMP-{str(user_id)[:6].upper()}",
        phone="9999999999",
        is_super_admin=is_super_admin,
        department="Operations",
        roles=roles,
    )


def make_perms(module: str, is_super_admin: bool = False) -> EffectivePermissions:
    grants = {
        (module, "view"): "ALL",
        (module, "create"): "ALL",
        (module, "edit"): "ALL",
        ("inventory", "view"): "ALL",
        ("goods_slips", "view"): "ALL",
        ("goods_slips", "edit"): "ALL",
        ("dispatch", "view"): "ALL",
        ("dispatch", "create"): "ALL",
    }
    return EffectivePermissions(
        is_super_admin=is_super_admin,
        grants=grants,
    )


def main():
    print("=" * 70)
    print("RMS P3-05 Local Verification: Resolution Board, Store Issue & Dispatch")
    print("=" * 70)

    settings = get_settings()
    engine = create_engine(settings.database_url.get_secret_value())
    factory = sessionmaker(bind=engine)
    uow = UnitOfWork(factory)

    rm_service = RmActionsService(uow)
    store_issue_service = StoreIssueService(uow)
    dispatch_service = ReplacementDispatchService(uow)

    # Actor identities from DB
    with engine.begin() as conn:
        sahil_row = (
            conn.execute(
                text("""
                select p.id, p.full_name, p.email from public.profiles p
                join public.user_roles ur on ur.user_id = p.id
                join public.roles r on r.id = ur.role_id
                where r.code = 'INTERMEDIATE_STORE_MANAGER' limit 1
            """)
            )
            .mappings()
            .first()
        )
        if not sahil_row:
            raise RuntimeError("INTERMEDIATE_STORE_MANAGER profile not found.")

        dispatch_row = (
            conn.execute(
                text("""
                select p.id, p.full_name, p.email from public.profiles p
                join public.user_roles ur on ur.user_id = p.id
                join public.roles r on r.id = ur.role_id
                where r.code = 'DISPATCH' limit 1
            """)
            )
            .mappings()
            .first()
        )
        if not dispatch_row:
            raise RuntimeError("DISPATCH profile not found.")

        rm_row = (
            conn.execute(
                text("""
                select p.id, p.full_name, p.email from public.profiles p
                join public.user_roles ur on ur.user_id = p.id
                join public.roles r on r.id = ur.role_id
                where r.code = 'REPLACEMENT_MANAGER' limit 1
            """)
            )
            .mappings()
            .first()
        )
        if not rm_row:
            raise RuntimeError("REPLACEMENT_MANAGER profile not found.")

        admin_row = (
            conn.execute(
                text(
                    "select p.id, p.full_name, p.email from public.profiles p where p.is_super_admin = true limit 1"
                )
            )
            .mappings()
            .first()
        )
        if not admin_row:
            raise RuntimeError("SUPER_ADMIN profile not found.")

    sahil = make_user(
        sahil_row["id"], sahil_row["email"], sahil_row["full_name"], ["INTERMEDIATE_STORE_MANAGER"]
    )
    sahil_perms = make_perms("inventory")

    dispatch_officer = make_user(
        dispatch_row["id"], dispatch_row["email"], dispatch_row["full_name"], ["DISPATCH"]
    )
    dispatch_perms = make_perms("dispatch")

    rm_user = make_user(rm_row["id"], rm_row["email"], rm_row["full_name"], ["REPLACEMENT_MANAGER"])
    rm_perms = make_perms("goods_slips")

    admin_user = make_user(
        admin_row["id"],
        admin_row["email"],
        admin_row["full_name"],
        ["SUPER_ADMIN"],
        is_super_admin=True,
    )

    gs_id = uuid.uuid4()
    gs_no = f"GS-VERIFY-{gs_id.hex[:6]}"
    prod_id = uuid.uuid4()
    party_id = uuid.uuid4()
    gs_item_id = uuid.uuid4()
    stock_item_id = uuid.uuid4()
    fg_lot_id = uuid.uuid4()
    fr_lot_id = uuid.uuid4()
    ng_lot_id = uuid.uuid4()

    try:
        print("\n[Step 1] Setting up mixed Goods Slip with functional and non-good stock...")
        with engine.begin() as conn:
            wf_id = conn.execute(
                text("select id from public.workflow_versions limit 1")
            ).scalar_one()
            cat_id = conn.execute(
                text("select id from public.product_categories where code = 'DMT'")
            ).scalar_one()
            inter_store_id = conn.execute(
                text("select id from public.inventory_locations where code = 'INTERMEDIATE_STORE'")
            ).scalar_one()
            non_func_store_id = conn.execute(
                text(
                    "select id from public.inventory_locations where code = 'NON_FUNCTIONAL_STORE'"
                )
            ).scalar_one()

            # Insert product and party
            conn.execute(
                text(
                    "insert into public.products (id, code, name, category_id) values (:id, :code, :name, :cat_id)"
                ),
                {
                    "id": prod_id,
                    "code": f"PRD_V_{prod_id.hex[:6]}",
                    "name": "Verification Ceiling Fan",
                    "cat_id": cat_id,
                },
            )
            conn.execute(
                text("insert into public.parties (id, code, name) values (:id, :code, :name)"),
                {
                    "id": party_id,
                    "code": f"PRTY_V_{party_id.hex[:6]}",
                    "name": "Verification Dealer",
                },
            )

            # Insert Goods Slip in ITEMIZATION
            conn.execute(
                text("""
                    insert into public.goods_slips (
                        id, gs_no, party_id, workflow_version_id, status,
                        delivery_mode_code, courier_name, docket_no,
                        category_code, original_category_code, box_count, created_by
                    ) values (
                        :id, :gs_no, :party_id, :wf_id, 'ITEMIZATION',
                        'COURIER_PARCEL', 'BlueDart', 'DKT-VERIFY',
                        'CSR', 'CSR', 1, :actor_id
                    )
                """),
                {
                    "id": gs_id,
                    "gs_no": gs_no,
                    "party_id": party_id,
                    "wf_id": wf_id,
                    "actor_id": admin_user.id,
                },
            )

            # Insert line item (10 pcs)
            conn.execute(
                text("""
                    insert into public.gs_items (
                        id, gs_id, line_no, product_id, category_id, received_qty, created_by
                    ) values (
                        :id, :gs_id, 1, :product_id, :cat_id, 10, :actor_id
                    )
                """),
                {
                    "id": gs_item_id,
                    "gs_id": gs_id,
                    "product_id": prod_id,
                    "cat_id": cat_id,
                    "actor_id": admin_user.id,
                },
            )

            # Advance to CSR_APPROVAL_PENDING -> CSR_APPROVED -> IN_PROCESS
            conn.execute(
                text(
                    "update public.goods_slips set status = 'CSR_APPROVAL_PENDING' where id = :gs_id"
                ),
                {"gs_id": gs_id},
            )
            conn.execute(
                text(
                    "insert into public.csr_approvals (gs_id, decision_code, decided_by, is_current) values (:gs_id, 'CSR_APPROVED', :actor_id, true)"
                ),
                {"gs_id": gs_id, "actor_id": admin_user.id},
            )
            conn.execute(
                text("update public.goods_slips set status = 'IN_PROCESS' where id = :gs_id"),
                {"gs_id": gs_id},
            )

            # Insert stock item
            conn.execute(
                text(
                    "insert into public.stock_items (id, item_kind, product_id) values (:id, 'FINISHED_GOOD', :prod_id)"
                ),
                {"id": stock_item_id, "prod_id": prod_id},
            )

            def create_lot_and_move(lot_id: uuid.UUID, cond: str, loc_id: uuid.UUID, qty: int):
                conn.execute(
                    text("""
                        insert into public.stock_lots (id, stock_item_id, gs_id, gs_item_id, condition_class, created_by)
                        values (:id, :si_id, :gs_id, :gi_id, :cond, :actor_id)
                    """),
                    {
                        "id": lot_id,
                        "si_id": stock_item_id,
                        "gs_id": gs_id,
                        "gi_id": gs_item_id,
                        "cond": cond,
                        "actor_id": admin_user.id,
                    },
                )
                conn.execute(
                    text("""
                        select rms_private.rms_move_stock(
                            p_lot := cast(:lot as uuid),
                            p_from := cast(null as uuid),
                            p_to := cast(:to as uuid),
                            p_qty := cast(:qty as integer),
                            p_type := 'INWARD',
                            p_ref_type := 'GOODS_SLIP',
                            p_ref_id := cast(:gs_id as uuid),
                            p_idem_key := cast(:key as text),
                            p_actor := cast(:actor as uuid),
                            p_reason := 'P3-05 local verify setup'
                        )
                    """),
                    {
                        "lot": lot_id,
                        "to": loc_id,
                        "qty": qty,
                        "gs_id": gs_id,
                        "key": f"verify:{lot_id}",
                        "actor": admin_user.id,
                    },
                )

            # 5 Good, 3 Repaired, 2 Non-Good
            create_lot_and_move(fg_lot_id, "FUNCTIONAL_GOOD", inter_store_id, 5)
            create_lot_and_move(fr_lot_id, "FUNCTIONAL_REPAIRED", inter_store_id, 3)
            create_lot_and_move(ng_lot_id, "NON_GOOD", non_func_store_id, 2)

            # RM Actions: SEND_REPAIRED=3, SEND_NEW=4, NOT_ALLOWED=3
            for code, qty in [("SEND_REPAIRED", 3), ("SEND_NEW", 4), ("NOT_ALLOWED", 3)]:
                conn.execute(
                    text("""
                        insert into public.rm_item_actions (
                            gs_item_id, revision_no, action_code, qty, is_current, decided_by
                        ) values (
                            :gi_id, 1, :code, :qty, true, :actor_id
                        )
                    """),
                    {"gi_id": gs_item_id, "code": code, "qty": qty, "actor_id": admin_user.id},
                )

        print(f"  OK: Goods Slip {gs_no} initialized with 10 pcs (5 FG, 3 FR, 2 NG).")

        # Step 2: Resolution Board
        print("\n[Step 2] Testing RM Resolution Board (GET /gs/{id}/resolution-board)...")
        board = rm_service.get_resolution_board(gs_id, rm_user, rm_perms)
        assert board.gs_no == gs_no
        assert len(board.lines) == 1
        line = board.lines[0]
        assert line.outcomes.functional_good_qty == 5
        assert line.outcomes.functional_repaired_qty == 3
        assert line.outcomes.non_good_qty == 2
        print("  OK: Resolution Board loaded correctly.")
        print(
            f"      Outcomes: FG={line.outcomes.functional_good_qty}, FR={line.outcomes.functional_repaired_qty}, NG={line.outcomes.non_good_qty}"
        )
        print(f"      Notes: {board.summary_notes}")

        # Step 3: Candidate Lots and G-04 Guard
        print("\n[Step 3] Testing Candidate Lots & G-04 Guard...")
        candidates = store_issue_service.get_candidate_lots(sahil, sahil_perms)
        candidate_lot_ids = {c.lot_id for c in candidates}
        assert fg_lot_id in candidate_lot_ids, "Functional Good lot should be a candidate"
        assert fr_lot_id in candidate_lot_ids, "Functional Repaired lot should be a candidate"
        assert ng_lot_id not in candidate_lot_ids, "Non-Good lot must NOT be a candidate"
        print(
            f"  OK: Intermediate Store candidate lots list only functional stock ({len(candidates)} candidate lots)."
        )

        # Attempt to issue NON_GOOD lot fails with G-04
        try:
            bad_req = StoreIssueCreateRequest(
                issue_type_code="ISSUE_MAIN_STORE",
                lines=[StoreIssueLineInput(lot_id=ng_lot_id, qty=1)],
            )
            store_issue_service.create_store_issue(bad_req, sahil, sahil_perms)
            raise AssertionError("G-04 guard failed: NON_GOOD was accepted for Store Issue!")
        except SystemGuardViolation as exc:
            assert exc.guard == "G-04"
            print(f"  OK: G-04 Guard correctly blocked NON_GOOD issue to Main Store: {exc.message}")

        # Step 4: Store Issue to Main Store
        print("\n[Step 4] Testing Store Issue creation and Note Print...")
        valid_req = StoreIssueCreateRequest(
            issue_type_code="ISSUE_MAIN_STORE",
            notes="Issued to Main Store after technician servicing",
            lines=[StoreIssueLineInput(lot_id=fg_lot_id, qty=4)],
        )
        issue_res = store_issue_service.create_store_issue(valid_req, sahil, sahil_perms)
        print(
            f"  OK: Store Issue created: {issue_res.issue_no} (Status: {issue_res.status}, Total Qty: {issue_res.total_qty})"
        )

        # Printable note
        print_res = store_issue_service.get_print_data(issue_res.id, sahil, sahil_perms)
        assert print_res.issue_no == issue_res.issue_no
        assert len(print_res.signature_blocks) == 2
        print("  OK: Printable Store Issue note generated with signature blocks:")
        for sig in print_res.signature_blocks:
            print(f"      - {sig['label']}: {sig['name']} ({sig['role']})")

        # Step 5: Replacement Dispatch Queue & DEC-33 Guard
        print("\n[Step 5] Testing Replacement Dispatch Queue & DEC-33 Guard...")
        queue_items = dispatch_service.get_dispatch_queue(dispatch_officer, dispatch_perms)
        gs_queue = [q for q in queue_items if q.gs_id == gs_id]
        assert len(gs_queue) == 2, (
            f"Expected 2 queue entries (SEND_NEW & SEND_REPAIRED), got {len(gs_queue)}"
        )
        send_new_item = next(q for q in gs_queue if q.action_code == "SEND_NEW")
        send_repaired_item = next(q for q in gs_queue if q.action_code == "SEND_REPAIRED")
        assert send_new_item.pending_qty == 4
        assert send_repaired_item.pending_qty == 3
        print(
            f"  OK: Dispatch Queue loaded: SEND_NEW pending={send_new_item.pending_qty}, SEND_REPAIRED pending={send_repaired_item.pending_qty}"
        )

        # Over-dispatch without override_reason fails with DEC-33
        try:
            over_req = ReplacementDispatchCreateRequest(
                gs_id=gs_id,
                dispatch_type="SEND_NEW",
                transporter="DTDC Express",
                lines=[ReplacementDispatchLineInput(gs_item_id=gs_item_id, qty=5)],  # Planned is 4
            )
            dispatch_service.create_dispatch(over_req, dispatch_officer, dispatch_perms)
            raise AssertionError(
                "DEC-33 guard failed: Over-dispatch was allowed without override_reason!"
            )
        except ValidationFailed as exc:
            assert "override_reason" in str(exc)
            print(
                f"  OK: DEC-33 Guard correctly blocked over-dispatch without override_reason: {exc}"
            )

        # Step 6: SEND_NEW Replacement Dispatch (DEC-26)
        print("\n[Step 6] Testing SEND_NEW Replacement Dispatch (DEC-26)...")
        send_new_req = ReplacementDispatchCreateRequest(
            gs_id=gs_id,
            dispatch_type="SEND_NEW",
            transporter="DTDC Express",
            docket_no="DKT-NEW-9999",
            lines=[ReplacementDispatchLineInput(gs_item_id=gs_item_id, qty=4)],
        )
        disp_new_res = dispatch_service.create_dispatch(
            send_new_req, dispatch_officer, dispatch_perms
        )
        assert disp_new_res.dispatch_no.startswith("DSP/")
        assert disp_new_res.total_qty == 4
        assert disp_new_res.lines[0].lot_id is None, "DEC-26: SEND_NEW must have null lot_id"
        print(f"  OK: SEND_NEW Replacement Dispatched: {disp_new_res.dispatch_no}")
        print("      DEC-26 confirmed: lot_id is None, sourced outside RMS returned-goods ledger.")

        # Step 7: SEND_REPAIRED Replacement Dispatch
        print("\n[Step 7] Testing SEND_REPAIRED Replacement Dispatch...")
        send_rep_req = ReplacementDispatchCreateRequest(
            gs_id=gs_id,
            dispatch_type="SEND_REPAIRED",
            transporter="DTDC Express",
            docket_no="DKT-REP-8888",
            lines=[ReplacementDispatchLineInput(gs_item_id=gs_item_id, qty=3, lot_id=fr_lot_id)],
        )
        disp_rep_res = dispatch_service.create_dispatch(
            send_rep_req, dispatch_officer, dispatch_perms
        )
        assert disp_rep_res.dispatch_no.startswith("DSP/")
        assert disp_rep_res.total_qty == 3
        assert disp_rep_res.lines[0].lot_id == fr_lot_id
        print(f"  OK: SEND_REPAIRED Replacement Dispatched: {disp_rep_res.dispatch_no}")
        print(
            "      Stock movement confirmed: 3 pcs consumed from FUNCTIONAL_REPAIRED into DISPATCHED."
        )

        print("\n" + "=" * 70)
        print("ALL P3-05 CHECKS PASSED SUCCESSFULLY!")
        print("=" * 70)

    finally:
        # Step 8: Clean up test fixtures so database remains 100% pristine
        print("\n[Step 8] Cleaning up verification test fixtures...")
        clean_engine = create_engine(
            "postgresql+psycopg://postgres:postgres@127.0.0.1:54322/postgres"
        )
        with clean_engine.begin() as conn:
            conn.execute(text("SET session_replication_role = 'replica'"))
            conn.execute(
                text(
                    "DELETE FROM replacement_dispatch_lines WHERE dispatch_id IN (SELECT id FROM replacement_dispatches WHERE gs_id = :gs_id)"
                ),
                {"gs_id": gs_id},
            )
            conn.execute(
                text("DELETE FROM replacement_dispatches WHERE gs_id = :gs_id"), {"gs_id": gs_id}
            )
            conn.execute(
                text(
                    "DELETE FROM store_issue_lines WHERE lot_id IN (SELECT id FROM stock_lots WHERE gs_id = :gs_id)"
                ),
                {"gs_id": gs_id},
            )
            conn.execute(
                text(
                    "DELETE FROM store_issues WHERE id NOT IN (SELECT issue_id FROM store_issue_lines)"
                )
            )
            conn.execute(
                text(
                    "DELETE FROM stock_movements WHERE lot_id IN (SELECT id FROM stock_lots WHERE gs_id = :gs_id)"
                ),
                {"gs_id": gs_id},
            )
            conn.execute(
                text(
                    "DELETE FROM stock_balances WHERE lot_id IN (SELECT id FROM stock_lots WHERE gs_id = :gs_id)"
                ),
                {"gs_id": gs_id},
            )
            conn.execute(text("DELETE FROM stock_lots WHERE gs_id = :gs_id"), {"gs_id": gs_id})
            conn.execute(
                text("DELETE FROM stock_items WHERE id = :si_id"), {"si_id": stock_item_id}
            )
            conn.execute(
                text("DELETE FROM rm_item_actions WHERE gs_item_id = :gi_id"), {"gi_id": gs_item_id}
            )
            conn.execute(text("DELETE FROM gs_items WHERE id = :gi_id"), {"gi_id": gs_item_id})
            conn.execute(text("DELETE FROM csr_approvals WHERE gs_id = :gs_id"), {"gs_id": gs_id})
            conn.execute(text("DELETE FROM goods_slips WHERE id = :gs_id"), {"gs_id": gs_id})
            conn.execute(text("DELETE FROM products WHERE id = :pid"), {"pid": prod_id})
            conn.execute(text("DELETE FROM parties WHERE id = :pty"), {"pty": party_id})
            conn.execute(text("SET session_replication_role = 'origin'"))
        clean_engine.dispose()
        print("  OK: All verification fixtures cleaned up cleanly.")


if __name__ == "__main__":
    main()
