"""Local verification script for P3-06 (Step-7 Credit Notes Workflow).

Master Plan references:
- §2.2 (Step-7), §3.2 DD r68-r78, BR-32..BR-37
- Guards: G-13, G-14
- Decisions: DEC-13, DEC-22, DEC-23, DEC-24, DEC-33

Scenarios executed:
1. Scenario A: GST Credit Note Path
   - RM records ALLOW_CN decision for FUNCTIONAL_GOOD lot
   - Accounts creates GST_CN draft
   - Verifies party invoice and GST portal reflection (GST_REFLECTED, GSTR-1)
   - Enforces G-14: Issue blocked while line rate is unverified
   - Records RATE_SALES verification
   - Enforces DEC-22: Accounts issues voucher with external accounting CN number
   - Retrieves printable CN_SUMMARY with dual signatures

2. Scenario B: General Credit Note Path (Repaired pieces)
   - RM records ALLOW_CN decision for FUNCTIONAL_REPAIRED lot
   - Accounts creates GENERAL_CN draft
   - Records purchase baseline rate (RATE_PURCHASE) and sales rate (RATE_SALES)
   - Enforces DEC-24: Variance warning computed when sales rate diverges > 15%
   - Issues external General CN voucher

3. Scenario C: Journal Voucher (JV-Only) Path (Not reflected on GST portal)
   - RM records ALLOW_CN decision
   - Accounts marks GST_NOT_REFLECTED
   - System enforces DD r76 & G-13: strictly restricts CN type to JV_ONLY
   - Attempt to switch to GST_CN fails with G-13 guard violation
   - Verifies rate and issues voucher with external JV number

4. Guard Invariant Checks:
   - G-13: Attempt to create CN draft without RM ALLOW_CN decision fails
   - G-13: Attempt to draft GST_CN with GST_NOT_REFLECTED fails
   - G-14: Attempt to issue without rate verification fails
"""

from __future__ import annotations

import sys
import uuid
from datetime import date
from decimal import Decimal
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
from app.modules.credit_notes.schemas import (  # noqa: E402
    CnTypeUpdateIn,
    CreditNoteCreateIn,
    CreditNoteIssueIn,
    CreditNoteLineIn,
    GstCheckIn,
    PartyDocumentVerifyIn,
    RateVerificationIn,
    RmCnDecisionIn,
    RmCnDecisionLineIn,
)
from app.modules.credit_notes.service import CreditNotesService  # noqa: E402


def main() -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url.get_secret_value())
    session_factory = sessionmaker(bind=engine)
    uow = UnitOfWork(session_factory)
    service = CreditNotesService(uow)

    print("==================================================================")
    print("  P3-06 STEP-7 CREDIT NOTES VERIFICATION SCRIPT")
    print("==================================================================")

    with engine.begin() as conn:
        actor_row = (
            conn.execute(
                text(
                    "select id, full_name, email from public.profiles where is_active = true limit 1"
                )
            )
            .mappings()
            .one()
        )
        actor_id = actor_row["id"]

        party_id = conn.execute(text("select id from public.parties limit 1")).scalar_one()
        product_id = conn.execute(text("select id from public.products limit 1")).scalar_one()
        cat_id = conn.execute(text("select id from public.product_categories limit 1")).scalar_one()
        wf_id = conn.execute(text("select id from public.workflow_versions limit 1")).scalar_one()

    # Actor identities & permissions
    perms = EffectivePermissions(is_super_admin=True)

    rm_user = CurrentUser(
        id=actor_id,
        email="rm@example.com",
        full_name="Replacement Manager",
        employee_code="EMP-RM01",
        phone="9999999991",
        is_super_admin=True,
        department=None,
        roles=(Role(id=uuid.uuid4(), code="REPLACEMENT_MANAGER", name="Replacement Manager"),),
    )

    accounts_user = CurrentUser(
        id=actor_id,
        email="deepak@example.com",
        full_name="Deepak Ji (Accounts)",
        employee_code="EMP-ACC01",
        phone="9999999992",
        is_super_admin=True,
        department=None,
        roles=(Role(id=uuid.uuid4(), code="ACCOUNTS", name="Accounts"),),
    )

    with engine.begin() as conn:
        # Seed test Goods Slip in ITEMIZATION
        test_gs_no = f"GS-TEST-{uuid.uuid4().hex[:6].upper()}"
        gs_id = conn.execute(
            text(
                """
                insert into public.goods_slips (
                    gs_no, party_id, workflow_version_id, status,
                    delivery_mode_code, courier_name, docket_no,
                    category_code, original_category_code, box_count, created_by
                ) values (
                    :gs_no, :party_id, :wf_id, 'ITEMIZATION',
                    'COURIER_PARCEL', 'BlueDart', 'DKT-P306',
                    'CSR', 'CSR', 1, :created_by
                ) returning id
                """
            ),
            {"gs_no": test_gs_no, "party_id": party_id, "wf_id": wf_id, "created_by": actor_id},
        ).scalar_one()

        # Seed Goods Slip items (3 lines for 3 scenarios)
        # Line 1: 10 pcs for GST CN
        gsi_1 = conn.execute(
            text(
                """
                insert into public.gs_items (
                    gs_id, product_id, category_id, line_no, received_qty, created_by
                ) values (
                    :gs_id, :product_id, :cat_id, 1, 10, :created_by
                ) returning id
                """
            ),
            {"gs_id": gs_id, "product_id": product_id, "cat_id": cat_id, "created_by": actor_id},
        ).scalar_one()

        # Line 2: 5 pcs for General CN
        gsi_2 = conn.execute(
            text(
                """
                insert into public.gs_items (
                    gs_id, product_id, category_id, line_no, received_qty, created_by
                ) values (
                    :gs_id, :product_id, :cat_id, 2, 5, :created_by
                ) returning id
                """
            ),
            {"gs_id": gs_id, "product_id": product_id, "cat_id": cat_id, "created_by": actor_id},
        ).scalar_one()

        # Line 3: 4 pcs for JV Only
        gsi_3 = conn.execute(
            text(
                """
                insert into public.gs_items (
                    gs_id, product_id, category_id, line_no, received_qty, created_by
                ) values (
                    :gs_id, :product_id, :cat_id, 3, 4, :created_by
                ) returning id
                """
            ),
            {"gs_id": gs_id, "product_id": product_id, "cat_id": cat_id, "created_by": actor_id},
        ).scalar_one()

        # Move GS through CSR approval to IN_PROCESS (G-03 compliance)
        conn.execute(
            text("update public.goods_slips set status = 'CSR_APPROVAL_PENDING' where id = :gs_id"),
            {"gs_id": gs_id},
        )
        conn.execute(
            text(
                """
                insert into public.csr_approvals (gs_id, decision_code, decided_by, is_current)
                values (:gs_id, 'CSR_APPROVED', :actor_id, true)
                """
            ),
            {"gs_id": gs_id, "actor_id": actor_id},
        )
        conn.execute(
            text("update public.goods_slips set status = 'IN_PROCESS' where id = :gs_id"),
            {"gs_id": gs_id},
        )

        # Seed initial RM planned action
        conn.execute(
            text(
                """
                insert into public.rm_item_actions (
                    gs_item_id, revision_no, action_code, qty, is_current, decided_by
                ) values
                (:gsi_1, 1, 'ISSUE_CN', 10, true, :rm_id),
                (:gsi_2, 1, 'SEND_REPAIRED', 5, true, :rm_id),
                (:gsi_3, 1, 'ISSUE_CN', 4, true, :rm_id)
                """
            ),
            {"gsi_1": gsi_1, "gsi_2": gsi_2, "gsi_3": gsi_3, "rm_id": rm_user.id},
        )

    print(f"\n[SETUP] Seeded test Goods Slip: {test_gs_no} (ID: {gs_id})")

    try:
        # =====================================================================
        # Step 1: Invariant Check - Guard G-13 (Blocked without RM ALLOW_CN)
        # =====================================================================
        print("\n--- Verifying Invariant: G-13 Blocks CN without active ALLOW_CN decision ---")
        try:
            service.create_credit_note(
                CreditNoteCreateIn(
                    gs_id=gs_id,
                    cn_type_code="GST_CN",
                    lines=[CreditNoteLineIn(gs_item_id=gsi_1, qty=10)],
                ),
                accounts_user,
                perms,
            )
            raise AssertionError(
                "G-13 violation failed: draft created without RM ALLOW_CN decision"
            )
        except (ValidationFailed, SystemGuardViolation) as e:
            print(f"  [PASS] Successfully blocked with G-13: {e.message}")

        # =====================================================================
        # Step 2: RM CN Decision (with deviation reason for Line 2 per DEC-13)
        # =====================================================================
        print("\n--- Recording Step-7 RM CN Decision ---")
        prefill = service.get_cn_decision_prefill(gs_id, rm_user, perms)
        print(f"  Prefill retrieved for {prefill.gs_no}: {len(prefill.prefill_lines)} lines")

        # Line 2 planned was SEND_REPAIRED, but RM authorizes ALLOW_CN with deviation justification
        decision = service.record_cn_decision(
            gs_id,
            RmCnDecisionIn(
                lines=[
                    RmCnDecisionLineIn(gs_item_id=gsi_1, decision="ALLOW_CN", qty=10),
                    RmCnDecisionLineIn(gs_item_id=gsi_2, decision="ALLOW_CN", qty=5),
                    RmCnDecisionLineIn(gs_item_id=gsi_3, decision="ALLOW_CN", qty=4),
                ],
                deviation_reason="Customer requested commercial credit note instead of repaired unit dispatch.",
            ),
            rm_user,
            perms,
        )
        print(f"  [PASS] RM CN decision recorded. Deviation: {decision.deviation_reason}")

        # =====================================================================
        # Scenario A: GST Credit Note Path (Reflected, Functional Good)
        # =====================================================================
        print("\n--- Scenario A: GST Credit Note Path ---")
        gst_cn = service.create_credit_note(
            CreditNoteCreateIn(
                gs_id=gs_id,
                cn_type_code="GST_CN",
                gst_portal_code="GST_REFLECTED",
                lines=[CreditNoteLineIn(gs_item_id=gsi_1, qty=10)],
            ),
            accounts_user,
            perms,
        )
        print(
            f"  Draft created: ID {gst_cn.id}, Type: {gst_cn.cn_type_code}, Total: Rs. {gst_cn.total_value}"
        )

        # Step 3: Verify Party Document
        gst_cn = service.verify_party_document(
            gst_cn.id,
            PartyDocumentVerifyIn(
                party_doc_code="PARTY_INVOICE",
                doc_no="INV-2026-9001",
                doc_date=date(2026, 10, 1),
                amount=Decimal("11800.00"),
                notes="Dealer original sales invoice verified against records.",
            ),
            accounts_user,
            perms,
        )
        print(f"  Party doc verified: {gst_cn.party_doc_code} {gst_cn.party_doc_no}")

        # Step 4: Verify GST Portal Reflection
        gst_cn = service.verify_gst_check(
            gst_cn.id,
            GstCheckIn(
                gst_portal_code="GST_REFLECTED",
                return_type="GSTR-1",
                return_period="102026",
                checked_on=date.today(),
            ),
            accounts_user,
            perms,
        )
        print(
            f"  GST portal verified: {gst_cn.gst_portal_code} in {gst_cn.gst_return_type} ({gst_cn.gst_return_period})"
        )

        # Step 5: Enforce G-14 Guard (Blocked issue without rate verification)
        print("  Checking Guard G-14: Attempt issue before rate verification...")
        try:
            service.issue_credit_note(
                gst_cn.id,
                CreditNoteIssueIn(cn_no="CN-TALLY-001", cn_date=date.today()),
                accounts_user,
                perms,
            )
            raise AssertionError("G-14 violation failed: issued without rate verification")
        except (ValidationFailed, SystemGuardViolation) as e:
            print(f"  [PASS] Blocked with G-14: {e.message}")

        # Step 6: Verify Rate (RATE_SALES @ Rs. 1,000 per piece, 18% GST)
        line_id = gst_cn.lines[0].id
        rate_res = service.verify_rate(
            line_id,
            RateVerificationIn(
                reference_code="RATE_SALES",
                ref_doc_no="INV-2026-9001",
                ref_doc_date=date(2026, 10, 1),
                rate=Decimal("1000.00"),
                notes="Matched historical sales invoice line rate",
            ),
            accounts_user,
            perms,
        )
        print(
            f"  Rate verified: Rs. {rate_res.sales_rate}/pc. Warning: {rate_res.has_variance_warning}"
        )

        # Step 7: Issue External Voucher (DEC-22)
        gst_cn = service.issue_credit_note(
            gst_cn.id,
            CreditNoteIssueIn(cn_no="CN-TALLY-001", cn_date=date.today()),
            accounts_user,
            perms,
        )
        print(
            f"  [PASS] GST Credit Note Issued: {gst_cn.cn_no} on {gst_cn.cn_date}. Status: {gst_cn.status}"
        )

        # Step 8: Printable Summary Verification
        print_summary = service.get_credit_note_print(gst_cn.id, accounts_user, perms)
        assert print_summary.voucher_no == "CN-TALLY-001"
        assert len(print_summary.signature_blocks) >= 2
        print(
            f"  [PASS] Print template CN_SUMMARY rendered: {print_summary.voucher_type_name} with dual signatures."
        )

        # =====================================================================
        # Scenario B: General Credit Note Path (Repaired Units, DEC-23, DEC-24)
        # =====================================================================
        print("\n--- Scenario B: General Credit Note Path (Repaired Pieces) ---")
        gen_cn = service.create_credit_note(
            CreditNoteCreateIn(
                gs_id=gs_id,
                cn_type_code="GENERAL_CN",
                lines=[CreditNoteLineIn(gs_item_id=gsi_2, qty=5)],
            ),
            accounts_user,
            perms,
        )
        print(f"  General CN draft created: ID {gen_cn.id}, Type: {gen_cn.cn_type_code}")

        # Party Doc
        gen_cn = service.verify_party_document(
            gen_cn.id,
            PartyDocumentVerifyIn(party_doc_code="PARTY_DEBIT_NOTE", doc_no="DN-555"),
            accounts_user,
            perms,
        )

        # Baseline purchase rate
        gen_line_id = gen_cn.lines[0].id
        service.verify_rate(
            gen_line_id,
            RateVerificationIn(
                reference_code="RATE_PURCHASE",
                ref_doc_no="PO-2026-001",
                ref_doc_date=date(2026, 8, 1),
                rate=Decimal("800.00"),
                notes="Purchase baseline",
            ),
            accounts_user,
            perms,
        )

        # Sales rate with > 15% variance (DEC-24 advisory warning)
        var_rate_res = service.verify_rate(
            gen_line_id,
            RateVerificationIn(
                reference_code="RATE_SALES",
                ref_doc_no="INV-2026-888",
                ref_doc_date=date(2026, 9, 1),
                rate=Decimal("1100.00"),  # > 30% higher than purchase baseline
                notes="Advisory variance test",
            ),
            accounts_user,
            perms,
        )
        assert var_rate_res.has_variance_warning is True
        clean_msg = (var_rate_res.variance_warning_message or "").replace("\u20b9", "Rs.")
        print(f"  [PASS] DEC-24 Variance advisory triggered: {clean_msg}")

        # Issue General CN (DEC-22)
        gen_cn = service.issue_credit_note(
            gen_cn.id,
            CreditNoteIssueIn(cn_no="GEN-CN-TALLY-002", cn_date=date.today()),
            accounts_user,
            perms,
        )
        print(f"  [PASS] General Credit Note Issued: {gen_cn.cn_no} on {gen_cn.cn_date}")

        # =====================================================================
        # Scenario C: Journal Voucher (JV-Only) Path (GST_NOT_REFLECTED)
        # =====================================================================
        print("\n--- Scenario C: JV-Only Path (GST Not Reflected) ---")
        jv_cn = service.create_credit_note(
            CreditNoteCreateIn(
                gs_id=gs_id,
                cn_type_code="JV_ONLY",
                gst_portal_code="GST_NOT_REFLECTED",
                lines=[CreditNoteLineIn(gs_item_id=gsi_3, qty=4)],
            ),
            accounts_user,
            perms,
        )
        print(f"  JV draft created: ID {jv_cn.id}, Type: {jv_cn.cn_type_code}")

        # Attempt to switch to GST_CN while NOT_REFLECTED fails G-13
        print("  Checking Guard G-13: Attempt to set GST_CN on GST_NOT_REFLECTED...")
        try:
            service.update_cn_type(
                jv_cn.id,
                CnTypeUpdateIn(cn_type_code="GST_CN"),
                accounts_user,
                perms,
            )
            raise AssertionError("G-13 violation failed: GST_CN allowed on unreflected return")
        except (ValidationFailed, SystemGuardViolation) as e:
            print(f"  [PASS] Blocked with G-13: {e.message}")

        # Verify rate and issue JV
        jv_line_id = jv_cn.lines[0].id
        service.verify_rate(
            jv_line_id,
            RateVerificationIn(
                reference_code="RATE_SALES",
                ref_doc_no="INV-LEGACY-003",
                ref_doc_date=date(2026, 8, 15),
                rate=Decimal("950.00"),
            ),
            accounts_user,
            perms,
        )

        jv_cn = service.issue_credit_note(
            jv_cn.id,
            CreditNoteIssueIn(jv_no="JV-TALLY-9999", jv_date=date.today()),
            accounts_user,
            perms,
        )
        print(
            f"  [PASS] Journal Voucher Issued: {jv_cn.jv_no} on {jv_cn.jv_date}. Status: {jv_cn.status}"
        )

        # =====================================================================
        # Step 9: Work Queue Verification
        # =====================================================================
        print("\n--- Verifying Accounts Work Queue ---")
        queue = service.get_work_queue(accounts_user, perms)
        print(
            f"  Pending GS items: {len(queue.pending_gs)}, Active credit notes: {len(queue.active_notes)}"
        )
        assert any(n.cn_no == "CN-TALLY-001" for n in queue.active_notes)
        assert any(n.jv_no == "JV-TALLY-9999" for n in queue.active_notes)
        print("  [PASS] All issued vouchers reflected in Accounts Work Queue Register.")

    finally:
        # Cleanup test records
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    delete from public.rate_verifications where credit_note_line_id in (
                        select id from public.credit_note_lines where credit_note_id in (
                            select id from public.credit_notes where gs_id = :gs_id
                        )
                    )
                    """
                ),
                {"gs_id": gs_id},
            )
            conn.execute(
                text(
                    """
                    delete from public.credit_note_lines where credit_note_id in (
                        select id from public.credit_notes where gs_id = :gs_id
                    )
                    """
                ),
                {"gs_id": gs_id},
            )
            conn.execute(
                text("delete from public.credit_notes where gs_id = :gs_id"),
                {"gs_id": gs_id},
            )
            conn.execute(
                text(
                    """
                    delete from public.rm_cn_decision_lines where decision_id in (
                        select id from public.rm_cn_decisions where gs_id = :gs_id
                    )
                    """
                ),
                {"gs_id": gs_id},
            )
            conn.execute(
                text("delete from public.rm_cn_decisions where gs_id = :gs_id"),
                {"gs_id": gs_id},
            )
            conn.execute(
                text(
                    """
                    delete from public.rm_item_actions where gs_item_id in (
                        select id from public.gs_items where gs_id = :gs_id
                    )
                    """
                ),
                {"gs_id": gs_id},
            )
            conn.execute(
                text("update public.goods_slips set status = 'CLOSED' where id = :gs_id"),
                {"gs_id": gs_id},
            )
            print(f"\n[CLEANUP] Cleaned credit notes and closed test GS {test_gs_no}.")

    print("\n==================================================================")
    print("  ALL P3-06 STEP-7 CREDIT NOTE VERIFICATIONS PASSED SUCCESSFULLY!")
    print("==================================================================")


if __name__ == "__main__":
    main()
