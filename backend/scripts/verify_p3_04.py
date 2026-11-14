"""Local verification script for P3-04 (Custody Segregation, Functional Inventory & Spare Parts Ledger).

Master Plan §2.2 (Stage-5, Step-6), §3.2 DD r63-r66, BR-30, G-04, G-12.
Lifecycle:
1. Walk a GS's lots through the stock cards and reconstruct the full movement history.
2. Verify segregated views:
   - Sahil sees functional stock with proper DD r63/r64 next-action text; no spare parts ledger.
   - Spare Parts Manager sees non-functional stock and salvaged spare parts.
3. Test custody assignment (DD r63-66):
   - Valid assignment in place returns ALREADY_IN_PLACE.
   - Contradictory assignment (NON_GOOD -> CUST_FUNCTIONAL_GOOD) is rejected (G-04/G-12).
4. Test physical count adjustment:
   - Custodian requests adjustment (reason mandatory).
   - RM approves with idempotency key -> creates ADJUST movement.
5. Run segregation check: zero violations.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

# Ensure backend root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, text

from app.core.config import get_settings
from app.core.db import UnitOfWork
from app.core.errors import DomainError
from app.core.idempotency import IdempotencyKey
from app.core.permissions import EffectivePermissions
from app.core.security import CurrentUser, Role
from app.modules.inventory.schemas import (
    AdjustmentDecisionIn,
    AdjustmentIn,
    AssignmentIn,
)
from app.modules.inventory.service import (
    InventoryService,
    StockFilters,
    run_nightly_segregation_check,
)


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


def make_perms(is_super_admin: bool = False) -> EffectivePermissions:
    grants = {
        ("inventory", "view"): "ALL",
        ("inventory", "edit"): "ALL",
        ("inventory", "export"): "ALL",
        ("inventory", "adjust"): "ALL",
        ("inventory", "approve"): "ALL",
    }
    return EffectivePermissions(
        is_super_admin=is_super_admin,
        grants=grants,
    )


def run_verification() -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url.get_secret_value())

    print("=" * 70)
    print("P3-04 LOCAL VERIFICATION: CUSTODY SEGREGATION & INVENTORY")
    print("=" * 70)

    # 1. Fetch demo users
    with engine.begin() as conn:
        sahil_row = (
            conn.execute(
                text(
                    "select p.id, p.full_name, p.email from public.profiles p "
                    "join public.user_roles ur on ur.user_id = p.id "
                    "join public.roles r on r.id = ur.role_id "
                    "where r.code = 'INTERMEDIATE_STORE_MANAGER' limit 1"
                )
            )
            .mappings()
            .first()
        )
        if not sahil_row:
            raise RuntimeError("INTERMEDIATE_STORE_MANAGER not found. Run seed_demo_users.py.")

        spm_row = (
            conn.execute(
                text(
                    "select p.id, p.full_name, p.email from public.profiles p "
                    "join public.user_roles ur on ur.user_id = p.id "
                    "join public.roles r on r.id = ur.role_id "
                    "where r.code = 'SPARE_PARTS_MANAGER' limit 1"
                )
            )
            .mappings()
            .first()
        )
        if not spm_row:
            raise RuntimeError("SPARE_PARTS_MANAGER not found. Run seed_demo_users.py.")

        rm_row = (
            conn.execute(
                text(
                    "select p.id, p.full_name, p.email from public.profiles p "
                    "join public.user_roles ur on ur.user_id = p.id "
                    "join public.roles r on r.id = ur.role_id "
                    "where r.code = 'REPLACEMENT_MANAGER' limit 1"
                )
            )
            .mappings()
            .first()
        )
        if not rm_row:
            raise RuntimeError("REPLACEMENT_MANAGER not found. Run seed_demo_users.py.")

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
            raise RuntimeError("SUPER_ADMIN not found.")

        # Locations
        inter_loc = conn.execute(
            text("select id from public.inventory_locations where code = 'INTERMEDIATE_STORE'")
        ).scalar_one()
        non_func_loc = conn.execute(
            text("select id from public.inventory_locations where code = 'NON_FUNCTIONAL_STORE'")
        ).scalar_one()
        parts_loc = conn.execute(
            text("select id from public.inventory_locations where code = 'SPARE_PARTS_STORE'")
        ).scalar_one()

        # Seed verification GS and product
        product_row = (
            conn.execute(
                text("select id, name, code from public.products order by created_at asc limit 1")
            )
            .mappings()
            .first()
        )
        if not product_row:
            raise RuntimeError("No product found.")

        # Pick or create a GS
        gs_row = (
            conn.execute(
                text("select id, gs_no from public.goods_slips order by created_at desc limit 1")
            )
            .mappings()
            .first()
        )
        if gs_row:
            gs_id = gs_row["id"]
            gs_no = gs_row["gs_no"]
        else:
            gs_id = uuid.uuid4()
            gs_no = f"GS-VERIFY-{uuid.uuid4().hex[:6].upper()}"
            party_id = conn.execute(text("select id from public.parties limit 1")).scalar_one()
            conn.execute(
                text(
                    """
                    insert into public.goods_slips (
                      id, gs_no, party_id, status, delivery_mode,
                      transporter_name, inward_date, stage, current_step, created_by
                    ) values (
                      :id, :gs_no, :party_id, 'COMPLETED', 'HAND_DELIVERY',
                      'Self', current_date, 5, 'S5_CUSTODY', :created_by
                    )
                    """
                ),
                {"id": gs_id, "gs_no": gs_no, "party_id": party_id, "created_by": sahil_row["id"]},
            )

        item_row = (
            conn.execute(
                text(
                    """
                insert into public.stock_items (item_kind, product_id)
                values ('FINISHED_GOOD', :product_id)
                returning id
                """
                ),
                {"product_id": product_row["id"]},
            )
            .mappings()
            .first()
        )
        stock_item_id = item_row["id"]

        # Lot 1: Functional Good (qty 4 in INTERMEDIATE_STORE)
        lot1_id = uuid.uuid4()
        conn.execute(
            text(
                """
                insert into public.stock_lots (id, stock_item_id, gs_id, condition_class, created_by)
                values (:id, :item_id, :gs_id, 'FUNCTIONAL_GOOD', :created_by)
                """
            ),
            {
                "id": lot1_id,
                "item_id": stock_item_id,
                "gs_id": gs_id,
                "created_by": sahil_row["id"],
            },
        )
        conn.execute(
            text(
                """
                select rms_private.rms_move_stock(
                  p_lot := :lot, p_from := null, p_to := :to, p_qty := 4,
                  p_type := 'INWARD', p_ref_type := null, p_ref_id := null,
                  p_idem_key := :idem, p_actor := :actor, p_reason := 'P3-04 verification functional lot'
                )
                """
            ),
            {
                "lot": lot1_id,
                "to": inter_loc,
                "idem": f"idem-{uuid.uuid4()}",
                "actor": sahil_row["id"],
            },
        )

        # Lot 2: Non-Good (qty 2 in NON_FUNCTIONAL_STORE)
        lot2_id = uuid.uuid4()
        conn.execute(
            text(
                """
                insert into public.stock_lots (id, stock_item_id, gs_id, condition_class, created_by)
                values (:id, :item_id, :gs_id, 'NON_GOOD', :created_by)
                """
            ),
            {"id": lot2_id, "item_id": stock_item_id, "gs_id": gs_id, "created_by": spm_row["id"]},
        )
        conn.execute(
            text(
                """
                select rms_private.rms_move_stock(
                  p_lot := :lot, p_from := null, p_to := :to, p_qty := 2,
                  p_type := 'INWARD', p_ref_type := null, p_ref_id := null,
                  p_idem_key := :idem, p_actor := :actor, p_reason := 'P3-04 verification non-functional lot'
                )
                """
            ),
            {
                "lot": lot2_id,
                "to": non_func_loc,
                "idem": f"idem-{uuid.uuid4()}",
                "actor": spm_row["id"],
            },
        )

        # Lot 3: Salvaged parts (qty 3 in SPARE_PARTS_STORE)
        parts_item = (
            conn.execute(
                text(
                    """
                insert into public.stock_items (item_kind, part_type)
                values ('SPARE_PART', 'TIP')
                returning id
                """
                )
            )
            .mappings()
            .first()
        )
        parts_lot_id = uuid.uuid4()
        conn.execute(
            text(
                """
                insert into public.stock_lots (id, stock_item_id, condition_class, created_by)
                values (:id, :item_id, 'SALVAGED', :created_by)
                """
            ),
            {"id": parts_lot_id, "item_id": parts_item["id"], "created_by": spm_row["id"]},
        )
        conn.execute(
            text(
                """
                select rms_private.rms_move_stock(
                  p_lot := :lot, p_from := null, p_to := :to, p_qty := 3,
                  p_type := 'RECEIPT', p_ref_type := null, p_ref_id := null,
                  p_idem_key := :idem, p_actor := :actor, p_reason := 'P3-04 verification salvaged parts'
                )
                """
            ),
            {
                "lot": parts_lot_id,
                "to": parts_loc,
                "idem": f"idem-{uuid.uuid4()}",
                "actor": spm_row["id"],
            },
        )

    sahil = make_user(
        sahil_row["id"], sahil_row["email"], sahil_row["full_name"], ["INTERMEDIATE_STORE_MANAGER"]
    )
    spm = make_user(spm_row["id"], spm_row["email"], spm_row["full_name"], ["SPARE_PARTS_MANAGER"])
    rm = make_user(rm_row["id"], rm_row["email"], rm_row["full_name"], ["REPLACEMENT_MANAGER"])

    perms_sahil = make_perms()
    perms_spm = make_perms()
    perms_rm = make_perms()

    def uow_factory() -> UnitOfWork:
        return UnitOfWork(lambda: engine.connect())

    service = InventoryService(uow_factory())

    print(f"Sahil (Intermediate Store Manager): {sahil.full_name} ({sahil.id})")
    print(f"Spare Parts Manager:               {spm.full_name} ({spm.id})")
    print(f"Replacement Manager:               {rm.full_name} ({rm.id})")
    print(f"Verification GS:                   {gs_no} ({gs_id})")

    # =========================================================================
    # STEP 1: Reconstruct full movement history via Stock Cards
    # =========================================================================
    print("\n[STEP 1] Reconstructing Full Movement History via Stock Cards...")
    card_func = service.stock_card(sahil, lot1_id)
    func_qty = sum(b.qty for b in card_func.balances)
    print(f"  -> Functional Lot {lot1_id}:")
    print(f"     Condition: {card_func.condition_class}, Balance: {func_qty}")
    print(f"     Movements count: {len(card_func.movements)}")
    for m in card_func.movements:
        print(
            f"       * {m.movement_type}: qty={m.qty}, from={m.from_location_code} -> to={m.to_location_code}"
        )
    assert func_qty == 4
    assert len(card_func.movements) >= 1
    assert card_func.movements[0].movement_type == "INWARD"
    print("  -> SUCCESS: Functional lot stock card verified.")

    card_non_func = service.stock_card(spm, lot2_id)
    non_func_qty = sum(b.qty for b in card_non_func.balances)
    print(f"  -> Non-functional Lot {lot2_id}:")
    print(f"     Condition: {card_non_func.condition_class}, Balance: {non_func_qty}")
    assert non_func_qty == 2
    print("  -> SUCCESS: Non-functional lot stock card verified.")

    # =========================================================================
    # STEP 2: Verify Segregated Custody Views (BR-30)
    # =========================================================================
    print("\n[STEP 2] Verifying Segregated Custody Views (BR-30)...")
    func_page = service.stock(sahil, "FUNCTIONAL", StockFilters(gs_id=gs_id), page=1, page_size=50)
    print(f"  -> Sahil Functional view: {func_page.total} lots found.")
    assert func_page.total >= 1
    for row in func_page.items:
        print(
            f"     Lot: {row.lot_id}, condition={row.condition_class}, routing={row.next_action_text}"
        )
        assert row.condition_class in ("FUNCTIONAL_GOOD", "FUNCTIONAL_REPAIRED")
        assert "Store Issue" in (row.next_action_text or "")
    print("  -> SUCCESS: Sahil views only functional stock with correct DD r63 routing text.")

    # Sahil cannot see spare parts ledger
    try:
        service.stock(sahil, "SPARE_PARTS", StockFilters(), page=1, page_size=50)
        raise AssertionError("Sahil should be forbidden from accessing SPARE_PARTS view!")
    except DomainError as de:
        print(f"  -> SUCCESS: Sahil blocked from SPARE_PARTS view: {de.code}")

    # Spare Parts Manager sees non-functional and salvaged parts
    non_func_page = service.stock(
        spm, "NON_FUNCTIONAL", StockFilters(gs_id=gs_id), page=1, page_size=50
    )
    print(f"  -> SPM Non-Functional view: {non_func_page.total} lots found.")
    assert non_func_page.total >= 1

    parts_page = service.stock(spm, "SPARE_PARTS", StockFilters(), page=1, page_size=50)
    print(f"  -> SPM Spare Parts view: {parts_page.total} lots found.")
    assert parts_page.total >= 1
    print("  -> SUCCESS: Spare Parts Manager views non-functional and salvaged parts.")

    # =========================================================================
    # STEP 3: Test Custody Assignment (DD r63-66) & Contradiction Guard
    # =========================================================================
    print("\n[STEP 3] Testing Custody Assignment and Guard Enforcement (G-04/G-12)...")
    idem1 = IdempotencyKey(
        key=f"assign-{uuid.uuid4()}", endpoint="/inventory/custody-assignment", request_hash="h1"
    )
    assign_res = service.assign(
        sahil,
        perms_sahil,
        AssignmentIn(lot_id=lot1_id, qty=4, assignment_code="CUST_FUNCTIONAL_GOOD"),
        idem1,
    )
    print(f"  -> Assignment result for functional lot: outcome={assign_res.body['outcome']}")
    assert assign_res.body["outcome"] == "ALREADY_IN_PLACE"
    print("  -> SUCCESS: Lot already in Intermediate Store correctly confirmed in place.")

    # Contradictory assignment: attempt to assign NON_GOOD lot to CUST_FUNCTIONAL_GOOD
    print("  -> Testing contradictory assignment rejection (NON_GOOD -> CUST_FUNCTIONAL_GOOD)...")
    try:
        service.assign(
            spm,
            perms_spm,
            AssignmentIn(lot_id=lot2_id, qty=2, assignment_code="CUST_FUNCTIONAL_GOOD"),
            IdempotencyKey(
                key=f"assign-{uuid.uuid4()}",
                endpoint="/inventory/custody-assignment",
                request_hash="h2",
            ),
        )
        raise AssertionError("Contradictory assignment must fail with G-04/G-12 guard!")
    except DomainError as de:
        print(
            f"  -> SUCCESS: Contradictory assignment rejected as expected: {de.code} ({de.message})"
        )

    # =========================================================================
    # STEP 4: Test Stock Adjustment Workflow (Physical Count Differences)
    # =========================================================================
    print("\n[STEP 4] Testing Stock Adjustment Request & Approval Workflow...")
    # Sahil requests physical count difference (-1 piece)
    adj_req = service.request_adjustment(
        sahil,
        perms_sahil,
        AdjustmentIn(
            lot_id=lot1_id,
            location_id=inter_loc,
            counted_qty=3,
            reason="Cycle count difference: 1 piece missing",
        ),
    )
    print(
        f"  -> Adjustment requested: ID={adj_req.id}, system_qty={adj_req.system_qty}, counted_qty={adj_req.counted_qty}, delta={adj_req.delta}"
    )
    assert adj_req.status == "REQUESTED"
    assert adj_req.delta == -1

    # Separation of duties: Sahil cannot approve his own adjustment
    try:
        service.approve_adjustment(
            sahil,
            perms_sahil,
            adj_req.id,
            AdjustmentDecisionIn(notes="Self approval attempt"),
            IdempotencyKey(
                key=f"adj-{uuid.uuid4()}", endpoint="/inventory/adjustments", request_hash="h3"
            ),
        )
        raise AssertionError("Requester must not be allowed to approve their own adjustment!")
    except DomainError as de:
        print(f"  -> SUCCESS: Self-approval blocked by SoD: {de.code}")

    # RM approves adjustment
    adj_approved = service.approve_adjustment(
        rm,
        perms_rm,
        adj_req.id,
        AdjustmentDecisionIn(notes="Approved after physical count verification"),
        IdempotencyKey(
            key=f"adj-app-{uuid.uuid4()}", endpoint="/inventory/adjustments", request_hash="h4"
        ),
    )
    print(
        f"  -> Adjustment approved by RM: status={adj_approved.body['status']}, movement_id={adj_approved.body['movement_id']}"
    )
    assert adj_approved.body["status"] == "APPROVED"

    # Verify updated balance via stock card
    card_after = service.stock_card(sahil, lot1_id)
    after_qty = sum(b.qty for b in card_after.balances)
    print(f"  -> Updated functional lot balance: {after_qty} (expected 3)")
    assert after_qty == 3
    print("  -> SUCCESS: Adjustment successfully posted and reflected in stock card.")

    # =========================================================================
    # STEP 5: Run Segregation Check (Zero Violations Expected)
    # =========================================================================
    print("\n[STEP 5] Running Segregation Integrity Check (BR-30)...")
    admin_user = make_user(
        admin_row["id"], admin_row["email"], admin_row["full_name"], ["SUPER_ADMIN"], True
    )
    check_result = service.segregation_check(admin_user)
    print(f"  -> Segregation check result: {check_result.violation_count} violations found.")
    for v in check_result.violations:
        print(
            f"     ! Violation: {v.violation_type} on lot {v.lot_id} in {v.location_code}: {v.description}"
        )
    assert check_result.violation_count == 0
    assert len(check_result.violations) == 0
    print("  -> SUCCESS: Zero custody segregation violations detected.")

    # Run nightly job function
    with engine.begin() as conn_nightly:
        recorded_violations = run_nightly_segregation_check(conn_nightly)
        print(f"  -> Nightly segregation check job: recorded {recorded_violations} violations.")
        assert recorded_violations == 0
    print("  -> SUCCESS: Nightly segregation job executed cleanly.")

    print("\n" + "=" * 70)
    print("ALL VERIFICATION STEPS PASSED SUCCESSFULLY (P3-04 Complete)")
    print("=" * 70)


if __name__ == "__main__":
    run_verification()
