"""P3-02 Servicing & Battery Inventory integration tests.

Master plan references: §2.2 Stage-3, §3.2 DD r47-r56, BR-23..BR-25, G-10, G-12, G-16,
DEC-14..DEC-17, DEC-34.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Connection, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.db import get_session_factory
from app.core.middleware import limiter
from app.shared.storage import get_storage
from tests.conftest import JwtFactory
from tests.integration.conftest import UserFactory, as_admin, build_test_app
from tests.integration.test_gate_inward import Masters, _auth
from tests.integration.test_unboxing import FakeStorage


@pytest.fixture
def storage() -> FakeStorage:
    return FakeStorage()


@pytest.fixture
async def client(session_factory: sessionmaker[Session], storage: FakeStorage) -> Any:
    app = build_test_app()
    app.dependency_overrides[get_session_factory] = lambda: session_factory
    app.dependency_overrides[get_storage] = lambda: storage
    limiter.reset()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    limiter.reset()


@pytest.fixture
def masters(db_conn: Connection) -> Masters:
    return Masters(db_conn)


@dataclass
class ServicingActors:
    coordinator_aman: str
    coordinator_aman_id: uuid.UUID
    coordinator_sahil: str
    coordinator_sahil_id: uuid.UUID
    spm: str
    spm_id: uuid.UUID
    unauthorized: str
    admin: str
    technician_id: uuid.UUID


@pytest.fixture
def actors(users: UserFactory, make_token: JwtFactory, db_conn: Connection) -> ServicingActors:
    aman_id = users.create(roles=["INWARD_VERIFIER", "TECHNICIAN_COORDINATOR"], full_name="Aman")
    sahil_id = users.create(
        roles=["INTERMEDIATE_STORE_MANAGER", "TECHNICIAN_COORDINATOR"], full_name="Sahil"
    )
    spm_id = users.create(roles=["SPARE_PARTS_MANAGER"], full_name="SPM User")
    unauth_id = users.create(roles=["GATE_INWARD"], full_name="Gate Only")
    admin_id = users.create(super_admin=True, full_name="System Admin")

    # Get Raj Kumar technician id
    c = as_admin(db_conn)
    row = c.execute(
        text("select id from public.technicians where display_name = 'Raj Kumar Ji'")
    ).fetchone()
    assert row is not None
    tech_id = row[0]

    return ServicingActors(
        coordinator_aman=make_token(aman_id),
        coordinator_aman_id=aman_id,
        coordinator_sahil=make_token(sahil_id),
        coordinator_sahil_id=sahil_id,
        spm=make_token(spm_id),
        spm_id=spm_id,
        unauthorized=make_token(unauth_id),
        admin=make_token(admin_id),
        technician_id=tech_id,
    )


def _seed_lot(
    conn: Connection,
    *,
    location_code: str = "INTERMEDIATE_STORE",
    qty: int = 10,
    supports_battery: bool = True,
    condition_code: str = "DMT_DIRTY",
    requires_evaluation: bool = False,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Helper to create a product, stock_item, stock_lot and credit initial balance."""
    c = as_admin(conn)
    tag = uuid.uuid4().hex[:6].upper()

    # Product category
    cat_code = f"CAT_{tag}"
    c.execute(
        text(
            """
            insert into public.product_categories (code, name, supports_battery)
            values (:code, :name, :supp)
            """
        ),
        {"code": cat_code, "name": f"Category {tag}", "supp": supports_battery},
    )
    cat_id = c.execute(
        text("select id from public.product_categories where code = :code"), {"code": cat_code}
    ).scalar_one()

    # Product
    prod_code = f"PROD_{tag}"
    c.execute(
        text(
            """
            insert into public.products (code, name, category_id)
            values (:code, :name, :cat_id)
            """
        ),
        {"code": prod_code, "name": f"Product {tag}", "cat_id": cat_id},
    )
    prod_id = c.execute(
        text("select id from public.products where code = :code"), {"code": prod_code}
    ).scalar_one()

    # Stock item
    item_id = c.execute(
        text(
            """
            insert into public.stock_items (product_id, item_kind)
            values (:prod_id, 'FINISHED_GOOD')
            returning id
            """
        ),
        {"prod_id": prod_id},
    ).scalar_one()

    # Stock lot
    lot_id = c.execute(
        text(
            """
            insert into public.stock_lots (
                stock_item_id, condition_class, source_condition_code, requires_evaluation
            ) values (
                :item_id, 'FUNCTIONAL_REPAIRED', :cond, :eval
            ) returning id
            """
        ),
        {"item_id": item_id, "cond": condition_code, "eval": requires_evaluation},
    ).scalar_one()

    # Location id
    loc_id = c.execute(
        text("select id from public.inventory_locations where code = :code"),
        {"code": location_code},
    ).scalar_one()

    # Initial balance move via rms_move_stock
    c.execute(
        text(
            """
            select rms_private.rms_move_stock(
                p_lot := cast(:lot_id as uuid),
                p_from := cast(null as uuid),
                p_to := cast(:loc_id as uuid),
                p_qty := cast(:qty as integer),
                p_type := 'INWARD'::text,
                p_ref_type := cast(null as text),
                p_ref_id := cast(null as uuid),
                p_idem_key := cast(:idem as text),
                p_actor := cast(null as uuid),
                p_reason := 'Initial test load'::text
            )
            """
        ),
        {"lot_id": lot_id, "qty": qty, "loc_id": loc_id, "idem": f"init:{lot_id}"},
    )

    return cat_id, prod_id, lot_id


# =================================================================================================
# 1. BATTERY STOCK & ADJUSTMENTS
# =================================================================================================


@pytest.mark.anyio
async def test_battery_receipt_and_balances(
    client: AsyncClient, actors: ServicingActors, db_conn: Connection
) -> None:
    # 1. List battery types (LR44, CR2032, etc.)
    r = await client.get("/api/v1/inventory/batteries/types", headers=_auth(actors.spm))
    assert r.status_code == 200, r.text
    types = r.json()
    assert len(types) >= 4
    next(t for t in types if t["code"] == "LR44")

    # 2. Unauthorized user cannot receive batteries
    r = await client.post(
        "/api/v1/inventory/batteries/receipts",
        headers={**_auth(actors.unauthorized), "Idempotency-Key": str(uuid.uuid4())},
        json={"battery_type": "LR44", "qty": 100, "ref": "SUP-001"},
    )
    assert r.status_code == 403

    # 3. SPM receives 100 LR44 batteries (the shared local DB may already hold committed stock)
    r = await client.get("/api/v1/inventory/batteries/balances", headers=_auth(actors.spm))
    before_lr44 = {b["code"]: b["balance"] for b in r.json()}.get("LR44", 0)
    idem = str(uuid.uuid4())
    r = await client.post(
        "/api/v1/inventory/batteries/receipts",
        headers={**_auth(actors.spm), "Idempotency-Key": idem},
        json={
            "battery_type": "LR44",
            "qty": 100,
            "ref": "SUP-001",
            "notes": "Initial batch",
        },
    )
    assert r.status_code == 201, r.text
    receipt = r.json()
    assert receipt["qty"] == 100
    assert receipt["reference_no"] == "SUP-001"

    # 4. Idempotency (G-16): replaying the same request returns the original receipt without
    #    double crediting; the same key with a different request is a conflict (P3-08).
    same = {"battery_type": "LR44", "qty": 100, "ref": "SUP-001", "notes": "Initial batch"}
    r2 = await client.post(
        "/api/v1/inventory/batteries/receipts",
        headers={**_auth(actors.spm), "Idempotency-Key": idem},
        json=same,
    )
    assert r2.status_code == 201
    assert r2.headers.get("Idempotency-Replayed") == "true"
    assert r2.json()["id"] == receipt["id"]
    r3 = await client.post(
        "/api/v1/inventory/batteries/receipts",
        headers={**_auth(actors.spm), "Idempotency-Key": idem},
        json={**same, "qty": 99},
    )
    assert r3.status_code == 409, r3.text
    assert r3.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

    # 5. Check balance
    r = await client.get("/api/v1/inventory/batteries/balances", headers=_auth(actors.spm))
    assert r.status_code == 200
    bals = {b["code"]: b["balance"] for b in r.json()}
    assert bals["LR44"] == before_lr44 + 100


@pytest.mark.anyio
async def test_battery_adjustment_approval_workflow(
    client: AsyncClient, actors: ServicingActors, db_conn: Connection
) -> None:
    # Get CR2032 type
    r = await client.get("/api/v1/inventory/batteries/types", headers=_auth(actors.spm))
    next(t for t in r.json() if t["code"] == "CR2032")

    # The adjustment list without a status filter (P3-04 fix: untyped NULL parameter → 500).
    r = await client.get("/api/v1/inventory/batteries/adjustments", headers=_auth(actors.spm))
    assert r.status_code == 200, r.text

    # 1. Request adjustment (+50 initial found stock)
    r = await client.post(
        "/api/v1/inventory/batteries/adjustments",
        headers=_auth(actors.spm),
        json={
            "battery_type": "CR2032",
            "qty": 50,
            "reason": "Stock found during store count",
        },
    )
    assert r.status_code == 201, r.text
    adj = r.json()
    assert adj["status"] == "PENDING"
    adj_id = adj["id"]

    # 2. Coordinator cannot approve (only SPM or Admin)
    r = await client.post(
        f"/api/v1/inventory/batteries/adjustments/{adj_id}/approve",
        headers={**_auth(actors.coordinator_sahil), "Idempotency-Key": str(uuid.uuid4())},
        json={"notes": "Sahil approving"},
    )
    assert r.status_code == 403

    # 3. SPM approves adjustment
    r = await client.post(
        f"/api/v1/inventory/batteries/adjustments/{adj_id}/approve",
        headers={**_auth(actors.admin), "Idempotency-Key": str(uuid.uuid4())},
        json={"approval_notes": "Approved by Admin"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "APPROVED"

    # 4. Check balance increased by 50
    r = await client.get("/api/v1/inventory/batteries/balances", headers=_auth(actors.spm))
    bals = {b["code"]: b["balance"] for b in r.json()}
    assert bals["CR2032"] == 50


# =================================================================================================
# 2. SERVICING ALLOTMENT (BR-23, DEC-34)
# =================================================================================================


@pytest.mark.anyio
async def test_allot_batch_success_and_role_guards(
    client: AsyncClient, actors: ServicingActors, db_conn: Connection
) -> None:
    _, _, lot_id = _seed_lot(db_conn, location_code="INTERMEDIATE_STORE", qty=12)

    # 1. Non-coordinator cannot allot
    r = await client.post(
        "/api/v1/servicing/batches",
        headers={**_auth(actors.unauthorized), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "technician_id": str(actors.technician_id),
            "lines": [{"lot_id": str(lot_id), "qty": 6}],
        },
    )
    assert r.status_code == 403

    # 2. Coordinator (Aman) allots 6 pieces to Raj Kumar Ji
    idem = str(uuid.uuid4())
    r = await client.post(
        "/api/v1/servicing/batches",
        headers={**_auth(actors.coordinator_aman), "Idempotency-Key": idem},
        json={
            "technician_id": str(actors.technician_id),
            "lines": [{"lot_id": str(lot_id), "qty": 6}],
            "notes": "Batch 1 test",
        },
    )
    assert r.status_code == 201, r.text
    batch = r.json()
    assert batch["batch_no"].startswith("TB")
    assert batch["status"] == "ALLOTTED"

    # The technician board lists batches without filters (P3-04 fix: untyped NULL parameters
    # raised AmbiguousParameter → 500).
    r = await client.get("/api/v1/servicing/batches", headers=_auth(actors.coordinator_aman))
    assert r.status_code == 200, r.text
    assert batch["id"] in {b["id"] for b in r.json()}
    assert batch["total_qty_allotted"] == 6
    assert batch["entry_by"] == str(actors.coordinator_aman_id)
    assert len(batch["lines"]) == 1
    assert batch["lines"][0]["qty_allotted"] == 6

    # 3. Check custody move: Intermediate Store balance should decrease from 12 to 6,
    # and Technician Bench should now have 6.
    c = as_admin(db_conn)
    inter_bal = c.execute(
        text(
            """
            select qty from public.stock_balances sb
            join public.inventory_locations l on l.id = sb.location_id
            where sb.lot_id = :lid and l.code = 'INTERMEDIATE_STORE'
            """
        ),
        {"lid": lot_id},
    ).scalar_one()
    bench_bal = c.execute(
        text(
            """
            select qty from public.stock_balances sb
            join public.inventory_locations l on l.id = sb.location_id
            where sb.lot_id = :lid and l.code = 'TECHNICIAN_BENCH'
            """
        ),
        {"lid": lot_id},
    ).scalar_one()
    assert inter_bal == 6
    assert bench_bal == 6


# =================================================================================================
# 3. RECEIVING, BATTERY GUARDS (G-10, G-16) & CLEANING (DEC-16, DEC-17)
# =================================================================================================


@pytest.mark.anyio
async def test_receiving_g10_battery_replaced_requires_counts(
    client: AsyncClient, actors: ServicingActors, db_conn: Connection
) -> None:
    _, _, lot_id = _seed_lot(db_conn, qty=6, supports_battery=True)

    # Allot 6 pieces
    r = await client.post(
        "/api/v1/servicing/batches",
        headers={**_auth(actors.coordinator_aman), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "technician_id": str(actors.technician_id),
            "lines": [{"lot_id": str(lot_id), "qty": 6}],
        },
    )
    assert r.status_code == 201
    batch = r.json()
    line_id = batch["lines"][0]["id"]

    # Try receive with BATTERY_REPLACED but 0 batteries_installed -> must fail with G-10
    r = await client.post(
        f"/api/v1/servicing/batches/{batch['id']}/receive",
        headers={**_auth(actors.coordinator_aman), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "lines": [
                {
                    "batch_line_id": line_id,
                    "qty_receiving": 6,
                    "battery_check_code": "BATTERY_REPLACED",
                    "pieces_checked": 6,
                    "batteries_installed": 0,
                    "battery_type_id": None,
                    "cleaning_code": "CLEANED_SELLABLE",
                    "allocations": {"FUNCTIONAL_GOOD": 6},
                }
            ]
        },
    )
    assert r.status_code == 409
    assert "G-10" in r.text or "BATTERY_REPLACED requires" in r.text


@pytest.mark.anyio
async def test_receiving_insufficient_battery_stock_fails_g16(
    client: AsyncClient, actors: ServicingActors, db_conn: Connection
) -> None:
    # Seed product with battery support
    _, _, lot_id = _seed_lot(db_conn, qty=6, supports_battery=True)

    # Allot 6 pieces
    r = await client.post(
        "/api/v1/servicing/batches",
        headers={**_auth(actors.coordinator_aman), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "technician_id": str(actors.technician_id),
            "lines": [{"lot_id": str(lot_id), "qty": 6}],
        },
    )
    assert r.status_code == 201
    batch = r.json()
    line_id = batch["lines"][0]["id"]

    # Get LR44 type and its current balance (committed local data may hold some stock)
    r = await client.get("/api/v1/inventory/batteries/types", headers=_auth(actors.spm))
    lr44 = next(t for t in r.json() if t["code"] == "LR44")
    r = await client.get("/api/v1/inventory/batteries/balances", headers=_auth(actors.spm))
    balance = {b["code"]: b["balance"] for b in r.json()}.get("LR44", 0)

    # Receive with one battery more than the store holds -> must fail with G-16
    r = await client.post(
        f"/api/v1/servicing/batches/{batch['id']}/receive",
        headers={**_auth(actors.coordinator_aman), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "lines": [
                {
                    "batch_line_id": line_id,
                    "qty_receiving": 6,
                    "battery_check_code": "BATTERY_REPLACED",
                    "pieces_checked": 6,
                    "batteries_installed": balance + 1,
                    "battery_type_id": lr44["id"],
                    "cleaning_code": "CLEANED_SELLABLE",
                    "allocations": {"FUNCTIONAL_GOOD": 6},
                }
            ]
        },
    )
    assert r.status_code == 409
    assert "insufficient" in r.text.lower() or "G-16" in r.text


@pytest.mark.anyio
async def test_dec17_permanent_scratches_forces_non_sellable(
    client: AsyncClient, actors: ServicingActors, db_conn: Connection
) -> None:
    # Seed product with DMT_SCRATCHED condition
    _, _, lot_id = _seed_lot(db_conn, qty=5, supports_battery=False, condition_code="DMT_SCRATCHED")

    # Allot 5 pieces
    r = await client.post(
        "/api/v1/servicing/batches",
        headers={**_auth(actors.coordinator_aman), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "technician_id": str(actors.technician_id),
            "lines": [{"lot_id": str(lot_id), "qty": 5}],
        },
    )
    assert r.status_code == 201
    batch = r.json()
    line_id = batch["lines"][0]["id"]

    # Receiving with PERMANENT_SCRATCHES but allocating to FUNCTIONAL_GOOD -> fails DEC-17
    r = await client.post(
        f"/api/v1/servicing/batches/{batch['id']}/receive",
        headers={**_auth(actors.coordinator_aman), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "lines": [
                {
                    "batch_line_id": line_id,
                    "qty_receiving": 5,
                    "battery_check_code": None,
                    "cleaning_code": "PERMANENT_SCRATCHES",
                    "allocations": {"FUNCTIONAL_GOOD": 5},
                }
            ]
        },
    )
    assert r.status_code == 422
    assert "NON_SELLABLE" in r.text

    # Receiving with PERMANENT_SCRATCHES and allocating to NON_SELLABLE -> succeeds
    r = await client.post(
        f"/api/v1/servicing/batches/{batch['id']}/receive",
        headers={**_auth(actors.coordinator_aman), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "lines": [
                {
                    "batch_line_id": line_id,
                    "qty_receiving": 5,
                    "battery_check_code": None,
                    "cleaning_code": "PERMANENT_SCRATCHES",
                    "allocations": {"NON_SELLABLE": 5},
                }
            ]
        },
    )
    assert r.status_code == 200, r.text

    # G-12: Permanent scratches pieces must end in NON_FUNCTIONAL_STORE, never Intermediate Store
    c = as_admin(db_conn)
    non_func_bal = c.execute(
        text(
            """
            select coalesce(sum(sb.qty), 0)::int
            from public.stock_balances sb
            join public.inventory_locations l on l.id = sb.location_id
            join public.stock_lots sl on sl.id = sb.lot_id
            where l.code = 'NON_FUNCTIONAL_STORE' and sl.condition_class = 'NON_SELLABLE'
            """
        )
    ).scalar_one()
    assert non_func_bal >= 5


# =================================================================================================
# 4. END-TO-END VERIFICATION: 10 RECEIVE, 6 ALLOT, 4 REPLACED -> BALANCE 6 & RECONCILIATION TIE-OUT
# =================================================================================================


@pytest.mark.anyio
async def test_p3_02_verification_scenario(
    client: AsyncClient, actors: ServicingActors, db_conn: Connection
) -> None:
    """Prompt requirement:
    VERIFY LOCALLY: receive 10 batteries; allot 6 pieces; receive with 4 replaced;
    check the battery balance = 6 and the reconciliation report ties out.
    """
    # Step 1: Receive 10 batteries (AAA)
    r = await client.get("/api/v1/inventory/batteries/types", headers=_auth(actors.spm))
    aaa_type = next(t for t in r.json() if t["code"] == "AAA")

    r = await client.post(
        "/api/v1/inventory/batteries/receipts",
        headers={**_auth(actors.spm), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "battery_type": "AAA",
            "qty": 10,
            "ref": "VERIF-AAA-10",
        },
    )
    assert r.status_code == 201

    # Step 2: Seed lot with 6 pieces and allot to technician
    _, _, lot_id = _seed_lot(db_conn, qty=6, supports_battery=True, condition_code="DMT_DIRTY")

    r = await client.post(
        "/api/v1/servicing/batches",
        headers={**_auth(actors.coordinator_aman), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "technician_id": str(actors.technician_id),
            "lines": [{"lot_id": str(lot_id), "qty": 6}],
            "notes": "P3-02 verification batch",
        },
    )
    assert r.status_code == 201
    batch = r.json()
    line_id = batch["lines"][0]["id"]

    # Step 3: Receive 6 pieces with 4 batteries replaced (6 pieces checked, 4 batteries installed)
    # 4 functional repaired, 1 functional good, 1 non-good
    receive_idem = str(uuid.uuid4())
    r = await client.post(
        f"/api/v1/servicing/batches/{batch['id']}/receive",
        headers={**_auth(actors.coordinator_aman), "Idempotency-Key": receive_idem},
        json={
            "lines": [
                {
                    "batch_line_id": line_id,
                    "qty_receiving": 6,
                    "battery_check_code": "BATTERY_REPLACED",
                    "pieces_checked": 6,
                    "batteries_installed": 4,
                    "battery_type_id": aaa_type["id"],
                    "cleaning_code": "CLEANED_SELLABLE",
                    "allocations": {
                        "FUNCTIONAL_REPAIRED": 4,
                        "FUNCTIONAL_GOOD": 1,
                        "NON_GOOD": 1,
                    },
                    "technician_remarks": "Cleaned and 4 batteries replaced",
                }
            ]
        },
    )
    assert r.status_code == 200, r.text
    batch_done = r.json()
    assert batch_done["status"] == "COMPLETED"

    # Step 4: Verify duplicate receive does not double-deduct (rejects completed batch with 409)
    r_dup = await client.post(
        f"/api/v1/servicing/batches/{batch['id']}/receive",
        headers={**_auth(actors.coordinator_aman), "Idempotency-Key": receive_idem},
        json={
            "lines": [
                {
                    "batch_line_id": line_id,
                    "qty_receiving": 6,
                    "battery_check_code": "BATTERY_REPLACED",
                    "pieces_checked": 6,
                    "batteries_installed": 4,
                    "battery_type_id": aaa_type["id"],
                    "cleaning_code": "CLEANED_SELLABLE",
                    "allocations": {
                        "FUNCTIONAL_REPAIRED": 4,
                        "FUNCTIONAL_GOOD": 1,
                        "NON_GOOD": 1,
                    },
                }
            ]
        },
    )
    assert r_dup.status_code == 409

    # Step 5: Check battery balance = 6 (10 received - 4 installed)
    r = await client.get("/api/v1/inventory/batteries/balances", headers=_auth(actors.spm))
    assert r.status_code == 200
    bals = {b["code"]: b["balance"] for b in r.json()}
    assert bals["AAA"] == 6

    # Step 6: Check reconciliation report ties out
    r = await client.get("/api/v1/servicing/battery-reconciliation", headers=_auth(actors.spm))
    assert r.status_code == 200, r.text
    recon = r.json()
    assert recon["ties_out"] is True
    assert recon["discrepancy"] == 0
    assert recon["batteries_installed"] >= 4
    assert recon["battery_stock_movements"] >= 4

    aaa_recon = next(t for t in recon["by_battery_type"] if t["battery_type_code"] == "AAA")
    assert aaa_recon["batteries_installed"] == 4
    assert aaa_recon["battery_stock_movements"] == 4
    assert aaa_recon["discrepancy"] == 0
    assert aaa_recon["ties_out"] is True
