"""Local verification script for P3-03 (Stage-4 Dismantling & Parts Recovery).

Master Plan §2.2 (Stage-4), §3.2 DD r57-r62, BR-26..BR-29, G-11, DEC-18, DEC-19, DEC-11.
Lifecycle:
1. Seed 5 non-good DMT units into NON_FUNCTIONAL_STORE (and 2 non-DMT units to verify DEC-18 queue separation).
2. Fetch dismantling queue as SPARE_PARTS_TECHNICIAN.
3. Create a dismantling batch for the 5 DMT units with PARTITIONED_CONTAINER storage method.
4. Verify units consumed from NON_FUNCTIONAL_STORE via DISMANTLE_IN movement.
5. Recover TIP, BODY, WIRE, and PCB (with mandatory model & supplier G-11) into partitioned container.
6. Record hazardous scrap record.
7. Verify batch is closed (COMPLETED) with all units accounted for (DEC-19).
8. Dispose hazardous scrap as SPARE_PARTS_MANAGER with manifest reference (DEC-11).
9. Verify spare parts inventory balances in SPARE_PARTS_STORE.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

# Ensure backend root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, text

from app.core.config import get_settings
from app.core.security import CurrentUser, Role
from app.modules.dismantling.schemas import (
    DismantleBatchCreateIn,
    DismantleBatchInputIn,
    DismantleRecoveryIn,
    RecoveredPartIn,
    ScrapDisposeIn,
    ScrapIn,
)
from app.modules.dismantling.service import (
    create_batch,
    dispose_scrap,
    get_queue,
    recover_batch,
)


def run_verification() -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url.get_secret_value())

    print("=" * 70)
    print("P3-03 LOCAL VERIFICATION: STAGE-4 DISMANTLING & PARTS RECOVERY")
    print("=" * 70)

    with engine.begin() as conn:
        # 1. Fetch technician and manager user profiles
        spt_user = (
            conn.execute(
                text(
                    "select p.id, p.full_name from public.profiles p join public.user_roles ur on ur.user_id = p.id join public.roles r on r.id = ur.role_id where r.code = 'SPARE_PARTS_TECHNICIAN' limit 1"
                )
            )
            .mappings()
            .first()
        )
        if not spt_user:
            raise RuntimeError("No SPARE_PARTS_TECHNICIAN user found. Run seed_demo_users.py.")

        spm_user = (
            conn.execute(
                text(
                    "select p.id, p.full_name from public.profiles p join public.user_roles ur on ur.user_id = p.id join public.roles r on r.id = ur.role_id where r.code = 'SPARE_PARTS_MANAGER' limit 1"
                )
            )
            .mappings()
            .first()
        )
        if not spm_user:
            raise RuntimeError("No SPARE_PARTS_MANAGER user found. Run seed_demo_users.py.")

        spt_profile_id = str(spt_user["id"])
        spm_profile_id = str(spm_user["id"])
        print(f"Technician: {spt_user['full_name']} ({spt_profile_id})")
        print(f"Manager:    {spm_user['full_name']} ({spm_profile_id})")

        # 2. Find product & category for DMT and non-DMT
        dmt_cat = (
            conn.execute(
                text(
                    "select id, code, name, supports_dismantling from public.product_categories where supports_dismantling = true limit 1"
                )
            )
            .mappings()
            .first()
        )
        if not dmt_cat:
            raise RuntimeError("No category with supports_dismantling = true found")

        non_dmt_cat = (
            conn.execute(
                text(
                    "select id, code, name, supports_dismantling from public.product_categories where supports_dismantling = false limit 1"
                )
            )
            .mappings()
            .first()
        )
        if not non_dmt_cat:
            raise RuntimeError("No category with supports_dismantling = false found")

        dmt_prod = (
            conn.execute(
                text(
                    "select id, code, name from public.products where category_id = :cat_id limit 1"
                ),
                {"cat_id": dmt_cat["id"]},
            )
            .mappings()
            .first()
        )
        if not dmt_prod:
            # Create a test DMT product
            prod_id = str(uuid.uuid4())
            conn.execute(
                text(
                    "insert into public.products (id, category_id, code, name, is_active) values (:id, :cid, 'DMT-VERIFY-01', 'DMT Verification Unit', true)"
                ),
                {"id": prod_id, "cid": dmt_cat["id"]},
            )
            dmt_prod = {"id": prod_id, "code": "DMT-VERIFY-01", "name": "DMT Verification Unit"}

        non_dmt_prod = (
            conn.execute(
                text(
                    "select id, code, name from public.products where category_id = :cat_id limit 1"
                ),
                {"cat_id": non_dmt_cat["id"]},
            )
            .mappings()
            .first()
        )
        if not non_dmt_prod:
            prod_id = str(uuid.uuid4())
            conn.execute(
                text(
                    "insert into public.products (id, category_id, code, name, is_active) values (:id, :cid, 'EO-VERIFY-01', 'Enclosed Oval Verification Unit', true)"
                ),
                {"id": prod_id, "cid": non_dmt_cat["id"]},
            )
            non_dmt_prod = {
                "id": prod_id,
                "code": "EO-VERIFY-01",
                "name": "Enclosed Oval Verification Unit",
            }

        # 3. Locations
        loc_non_func = (
            conn.execute(
                text(
                    "select id, code from public.inventory_locations where code = 'NON_FUNCTIONAL_STORE'"
                )
            )
            .mappings()
            .first()
        )
        if not loc_non_func:
            raise RuntimeError("NON_FUNCTIONAL_STORE location missing")

        loc_spare = (
            conn.execute(
                text(
                    "select id, code from public.inventory_locations where code = 'SPARE_PARTS_STORE'"
                )
            )
            .mappings()
            .first()
        )
        if not loc_spare:
            raise RuntimeError("SPARE_PARTS_STORE location missing")

        # 4. Seed stock items and lots in NON_FUNCTIONAL_STORE
        # 4a. 5 non-good DMT units
        dmt_item_id = str(uuid.uuid4())
        conn.execute(
            text(
                "insert into public.stock_items (id, item_kind, product_id) values (:id, 'FINISHED_GOOD', :pid)"
            ),
            {"id": dmt_item_id, "pid": dmt_prod["id"]},
        )
        dmt_lot_id = str(uuid.uuid4())
        conn.execute(
            text("""
                insert into public.stock_lots (id, stock_item_id, condition_class, source_condition_code)
                values (:id, :item_id, 'NON_GOOD', 'DMT_DEAD')
            """),
            {"id": dmt_lot_id, "item_id": dmt_item_id},
        )
        conn.execute(
            text("""
                select rms_private.rms_move_stock(
                    p_lot := cast(:lot_id as uuid),
                    p_from := cast(null as uuid),
                    p_to := cast(:loc_id as uuid),
                    p_qty := 5,
                    p_type := 'INWARD'::text,
                    p_ref_type := cast(null as text),
                    p_ref_id := cast(null as uuid),
                    p_idem_key := cast(:idem as text),
                    p_actor := cast(null as uuid),
                    p_reason := 'Initial test non-good DMT units'::text
                )
            """),
            {"lot_id": dmt_lot_id, "loc_id": loc_non_func["id"], "idem": f"init:{dmt_lot_id}"},
        )

        # 4b. 2 non-good non-DMT units (for DEC-18 check)
        non_dmt_item_id = str(uuid.uuid4())
        conn.execute(
            text(
                "insert into public.stock_items (id, item_kind, product_id) values (:id, 'FINISHED_GOOD', :pid)"
            ),
            {"id": non_dmt_item_id, "pid": non_dmt_prod["id"]},
        )
        non_dmt_lot_id = str(uuid.uuid4())
        conn.execute(
            text("""
                insert into public.stock_lots (id, stock_item_id, condition_class, source_condition_code)
                values (:id, :item_id, 'NON_GOOD', 'NON_DMT_DEFECT')
            """),
            {"id": non_dmt_lot_id, "item_id": non_dmt_item_id},
        )
        conn.execute(
            text("""
                select rms_private.rms_move_stock(
                    p_lot := cast(:lot_id as uuid),
                    p_from := cast(null as uuid),
                    p_to := cast(:loc_id as uuid),
                    p_qty := 2,
                    p_type := 'INWARD'::text,
                    p_ref_type := cast(null as text),
                    p_ref_id := cast(null as uuid),
                    p_idem_key := cast(:idem as text),
                    p_actor := cast(null as uuid),
                    p_reason := 'Initial test non-DMT units'::text
                )
            """),
            {
                "lot_id": non_dmt_lot_id,
                "loc_id": loc_non_func["id"],
                "idem": f"init:{non_dmt_lot_id}",
            },
        )

        # 5. Fetch partitioned container and its 4 partitions
        part_cont = (
            conn.execute(
                text(
                    "select id, code, container_type, storage_method from public.storage_containers where storage_method = 'PARTITIONED_CONTAINER' and is_active = true limit 1"
                )
            )
            .mappings()
            .first()
        )
        if not part_cont:
            raise RuntimeError("No PARTITIONED_CONTAINER found")

        partitions = (
            conn.execute(
                text(
                    "select id, compartment_code, part_type from public.container_partitions where container_id = :cid and is_active = true"
                ),
                {"cid": part_cont["id"]},
            )
            .mappings()
            .all()
        )
        partition_map = {p["part_type"]: str(p["id"]) for p in partitions}
        for pt in ["TIP", "BODY", "WIRE", "PCB"]:
            if pt not in partition_map:
                raise RuntimeError(
                    f"Missing partition for part_type {pt} in container {part_cont['code']}"
                )

        # 6. Fetch PCB model and supplier
        pcb_mod = (
            conn.execute(
                text(
                    "select id, name, supplier_id from public.pcb_models where is_active = true limit 1"
                )
            )
            .mappings()
            .first()
        )
        pcb_sup = (
            conn.execute(
                text("select id, name from public.pcb_suppliers where is_active = true limit 1")
            )
            .mappings()
            .first()
        )
        if not pcb_mod or not pcb_sup:
            raise RuntimeError("PCB models or suppliers seed missing")

    # Use session for API service execution
    from app.core.db import get_session_factory

    session_local = get_session_factory()
    with session_local() as session:
        # Wrap CurrentUsers
        tech_user = CurrentUser(
            id=uuid.UUID(spt_profile_id),
            email="spt@rms.local",
            full_name=spt_user["full_name"],
            employee_code=None,
            phone=None,
            is_super_admin=False,
            department=None,
            roles=(
                Role(id=uuid.uuid4(), code="SPARE_PARTS_TECHNICIAN", name="Spare Parts Technician"),
            ),
        )
        mgr_user = CurrentUser(
            id=uuid.UUID(spm_profile_id),
            email="spm@rms.local",
            full_name=spm_user["full_name"],
            employee_code=None,
            phone=None,
            is_super_admin=False,
            department=None,
            roles=(Role(id=uuid.uuid4(), code="SPARE_PARTS_MANAGER", name="Spare Parts Manager"),),
        )

        # STEP 1: Verify queue filtering (DEC-18)
        print("\n[STEP 1] Verifying Dismantling Queue (DEC-18)...")
        queue = get_queue(session)
        dmt_in_queue = any(str(item.lot_id) == str(dmt_lot_id) for item in queue.dismantleable_lots)
        non_dmt_in_disposal = any(
            str(item.lot_id) == str(non_dmt_lot_id) for item in queue.disposal_required_lots
        )
        assert dmt_in_queue, "DMT lot must be in dismantleable queue"
        assert non_dmt_in_disposal, "Non-DMT lot must be in disposal required section (DEC-18)"
        print(f"  -> SUCCESS: DMT lot {str(dmt_lot_id)[:8]} in dismantleable queue.")
        print(
            f"  -> SUCCESS: Non-DMT lot {str(non_dmt_lot_id)[:8]} correctly separated under 'Disposal route required (DEC-18)'."
        )

        # STEP 2: Create dismantling batch
        print("\n[STEP 2] Creating Dismantling Batch for 5 DMT units...")
        batch_payload = DismantleBatchCreateIn(
            inputs=[DismantleBatchInputIn(lot_id=uuid.UUID(dmt_lot_id), qty=5)],
            storage_method_code="PARTITIONED_CONTAINER",
        )
        batch = create_batch(
            session,
            user=tech_user,
            payload=batch_payload,
            idempotency_key=str(uuid.uuid4()),
        )
        session.commit()
        print(f"  -> SUCCESS: Batch created: {batch.batch_no} (ID: {batch.id})")
        assert batch.total_input_qty == 5
        assert batch.status == "OPEN"

        # Check stock movement in DB
        with engine.begin() as conn:
            dmt_bal = conn.execute(
                text(
                    "select coalesce(sum(qty), 0) from public.stock_balances where lot_id = :lid and location_id = :loc_id"
                ),
                {"lid": dmt_lot_id, "loc_id": loc_non_func["id"]},
            ).scalar()
            assert dmt_bal == 0, f"DMT lot balance should be 0, got {dmt_bal}"
            mov = (
                conn.execute(
                    text(
                        "select movement_type, qty, from_location_id from public.stock_movements where reference_id = :bid"
                    ),
                    {"bid": batch.id},
                )
                .mappings()
                .first()
            )
            assert mov is not None and mov["movement_type"] == "DISMANTLE_IN"
            print(
                "  -> SUCCESS: 5 units consumed from NON_FUNCTIONAL_STORE via DISMANTLE_IN movement."
            )

        # STEP 3: Recover parts into partitioned container + mark scrap (G-11, DEC-19, DEC-11)
        print(
            "\n[STEP 3] Recovering TIP, BODY, WIRE, PCB (with G-11) and marking hazardous scrap..."
        )
        recovery_payload = DismantleRecoveryIn(
            units_dismantled=5,
            parts=[
                RecoveredPartIn(
                    part_type="TIP",
                    qty=5,
                    partition_id=uuid.UUID(partition_map["TIP"]),
                    container_id=uuid.UUID(str(part_cont["id"])),
                ),
                RecoveredPartIn(
                    part_type="BODY",
                    qty=5,
                    partition_id=uuid.UUID(partition_map["BODY"]),
                    container_id=uuid.UUID(str(part_cont["id"])),
                ),
                RecoveredPartIn(
                    part_type="WIRE",
                    qty=5,
                    partition_id=uuid.UUID(partition_map["WIRE"]),
                    container_id=uuid.UUID(str(part_cont["id"])),
                ),
                RecoveredPartIn(
                    part_type="PCB",
                    qty=5,
                    pcb_model_id=uuid.UUID(str(pcb_mod["id"])),
                    pcb_supplier_id=uuid.UUID(str(pcb_sup["id"])),
                    partition_id=uuid.UUID(partition_map["PCB"]),
                    container_id=uuid.UUID(str(part_cont["id"])),
                ),
            ],
            scrap=ScrapIn(
                qty_pieces=2,
                weight_kg=0.25,
                hazardous=True,
                remarks="Damaged casings with burn mark",
            ),
        )
        updated_batch = recover_batch(
            session,
            user=tech_user,
            batch_id=batch.id,
            payload=recovery_payload,
            idempotency_key=str(uuid.uuid4()),
        )
        session.commit()
        print(
            f"  -> SUCCESS: Recovery recorded. Batch status: {updated_batch.status}, Units dismantled: {updated_batch.total_dismantled_qty}/5"
        )
        assert updated_batch.status == "COMPLETED", (
            "Batch must be COMPLETED when all 5 units are dismantled (DEC-19)"
        )

        # Check recovered parts in DB
        with engine.begin() as conn:
            parts = (
                conn.execute(
                    text(
                        "select part_type, qty, pcb_model_id, pcb_supplier_id, partition_id from public.recovered_parts where batch_id = :bid"
                    ),
                    {"bid": batch.id},
                )
                .mappings()
                .all()
            )
            print(f"  -> Recovered parts count: {len(parts)}")
            for p in parts:
                print(
                    f"     * {p['part_type']}: qty={p['qty']}, partition={p['partition_id']}, model={p['pcb_model_id']}, supplier={p['pcb_supplier_id']}"
                )

            scrap = (
                conn.execute(
                    text(
                        "select id, qty_pieces, weight_kg, hazardous, disposal_status from public.scrap_records where batch_id = :bid"
                    ),
                    {"bid": batch.id},
                )
                .mappings()
                .first()
            )
            assert scrap is not None
            assert scrap["hazardous"] is True
            assert scrap["disposal_status"] == "MARKED"
            scrap_id = str(scrap["id"])
            print(
                f"  -> Hazardous scrap recorded: {scrap['qty_pieces']} pcs, status={scrap['disposal_status']}"
            )

        # STEP 4: Dispose hazardous scrap (DEC-11)
        print("\n[STEP 4] Disposing hazardous scrap as Spare Parts Manager (DEC-11)...")
        manifest_no = "MNF-HAZ-2026-VERIFY-001"
        disposed_scrap = dispose_scrap(
            session,
            user=mgr_user,
            scrap_id=uuid.UUID(scrap_id),
            payload=ScrapDisposeIn(manifest_ref=manifest_no),
            idempotency_key=str(uuid.uuid4()),
        )
        session.commit()
        print(
            f"  -> SUCCESS: Scrap disposed with manifest: {disposed_scrap.manifest_ref}, status={disposed_scrap.disposal_status}"
        )
        assert disposed_scrap.disposal_status == "DISPOSED"
        assert disposed_scrap.manifest_ref == manifest_no

        # STEP 5: View spare parts balances in SPARE_PARTS_STORE
        print("\n[STEP 5] Viewing spare parts balances in SPARE_PARTS_STORE...")
        with engine.begin() as conn:
            balances = (
                conn.execute(
                    text("""
                    select si.part_type, m.name as model_name, sup.name as supplier_name,
                           sl.condition_class, sb.qty as available_qty, cp.compartment_code, sc.code as container_code
                    from public.stock_balances sb
                    join public.stock_lots sl on sl.id = sb.lot_id
                    join public.stock_items si on si.id = sl.stock_item_id
                    join public.inventory_locations il on il.id = sb.location_id
                    left join public.pcb_models m on m.id = si.pcb_model_id
                    left join public.pcb_suppliers sup on sup.id = si.pcb_supplier_id
                    left join public.container_partitions cp on cp.id = sl.partition_id
                    left join public.storage_containers sc on sc.id = sl.container_id
                    where il.code = 'SPARE_PARTS_STORE' and sb.qty > 0
                    order by si.part_type
                """)
                )
                .mappings()
                .all()
            )

            print(f"  Total spare parts inventory records: {len(balances)}")
            for b in balances:
                extra = (
                    f" (model: {b['model_name']}, supplier: {b['supplier_name']})"
                    if b["part_type"] == "PCB"
                    else ""
                )
                print(
                    f"    - {b['part_type']:<8} qty={b['available_qty']} condition={b['condition_class']} container={b['container_code']} partition={b['compartment_code']}{extra}"
                )

    print("\n" + "=" * 70)
    print("ALL VERIFICATION STEPS PASSED SUCCESSFULLY (P3-03 Stage-4 Complete)")
    print("=" * 70)


if __name__ == "__main__":
    # An uncaught failure prints its traceback and exits non-zero (no blind except, rule j).
    run_verification()
