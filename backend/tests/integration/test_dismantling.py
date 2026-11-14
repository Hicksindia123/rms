"""Stage-4 Dismantling & Parts Recovery integration tests.

Master plan references: §2.2 Stage-4, §3.2 DD r57-r62, BR-26..BR-29, G-11, DEC-18, DEC-19, DEC-11.
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
class DismantlingActors:
    technician: str
    technician_id: uuid.UUID
    spm: str
    spm_id: uuid.UUID
    unauthorized: str
    admin: str
    admin_id: uuid.UUID


@pytest.fixture
def actors(users: UserFactory, make_token: JwtFactory) -> DismantlingActors:
    tech_id = users.create(roles=["SPARE_PARTS_TECHNICIAN"], full_name="Dismantle Tech")
    spm_id = users.create(roles=["SPARE_PARTS_MANAGER"], full_name="Spare Parts Manager")
    unauth_id = users.create(roles=["GATE_INWARD"], full_name="Gate Only")
    admin_id = users.create(super_admin=True, full_name="System Admin")

    return DismantlingActors(
        technician=make_token(tech_id),
        technician_id=tech_id,
        spm=make_token(spm_id),
        spm_id=spm_id,
        unauthorized=make_token(unauth_id),
        admin=make_token(admin_id),
        admin_id=admin_id,
    )


def _seed_non_good_lot(
    conn: Connection,
    *,
    qty: int = 5,
    supports_dismantling: bool = True,
    condition_class: str = "NON_GOOD",
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    c = as_admin(conn)
    tag = uuid.uuid4().hex[:6].upper()

    # Product category
    cat_code = f"CAT_{tag}"
    c.execute(
        text(
            """
            insert into public.product_categories (code, name, supports_dismantling)
            values (:code, :name, :supp)
            """
        ),
        {"code": cat_code, "name": f"Category {tag}", "supp": supports_dismantling},
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
                stock_item_id, condition_class, source_condition_code
            ) values (
                :item_id, :cond, 'DMT_DEAD'
            ) returning id
            """
        ),
        {"item_id": item_id, "cond": condition_class},
    ).scalar_one()

    # Move initial balance into NON_FUNCTIONAL_STORE
    loc_id = c.execute(
        text("select id from public.inventory_locations where code = 'NON_FUNCTIONAL_STORE'")
    ).scalar_one()

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
                p_reason := 'Initial non-good test load'::text
            )
            """
        ),
        {"lot_id": lot_id, "qty": qty, "loc_id": loc_id, "idem": f"init:{lot_id}"},
    )

    return cat_id, prod_id, lot_id


@pytest.mark.anyio
async def test_dismantling_queue_filters_categories(
    client: AsyncClient, actors: DismantlingActors, db_conn: Connection
) -> None:
    """DEC-18: DMT lots with supports_dismantling=true are queued; non-DMT lots are separate."""
    # Seed 1 dismantleable lot (e.g. DMT) and 1 non-dismantleable lot (e.g. Prismatic)
    _, _, dmt_lot = _seed_non_good_lot(db_conn, qty=5, supports_dismantling=True)
    _, _, non_dmt_lot = _seed_non_good_lot(db_conn, qty=3, supports_dismantling=False)

    res = await client.get("/api/v1/dismantling/queue", headers=_auth(actors.technician))
    assert res.status_code == 200
    data = res.json()

    dismantleable_ids = [item["lot_id"] for item in data["dismantleable_lots"]]
    disposal_ids = [item["lot_id"] for item in data["disposal_required_lots"]]

    assert str(dmt_lot) in dismantleable_ids
    assert str(non_dmt_lot) in disposal_ids
    assert str(non_dmt_lot) not in dismantleable_ids


@pytest.mark.anyio
async def test_create_batch_permissions_and_guards(
    client: AsyncClient, actors: DismantlingActors, db_conn: Connection
) -> None:
    """Role check and DEC-18 check on batch creation."""
    _, _, dmt_lot = _seed_non_good_lot(db_conn, qty=4, supports_dismantling=True)
    _, _, non_dmt_lot = _seed_non_good_lot(db_conn, qty=2, supports_dismantling=False)

    payload_valid = {
        "inputs": [{"lot_id": str(dmt_lot), "qty": 4}],
        "storage_method_code": "DEDICATED_CONTAINERS",
    }

    # Unauthorized
    res = await client.post(
        "/api/v1/dismantling/batches",
        headers={**_auth(actors.unauthorized), "Idempotency-Key": str(uuid.uuid4())},
        json=payload_valid,
    )
    assert res.status_code == 403

    # Attempt to batch non-dismantleable lot (DEC-18)
    res = await client.post(
        "/api/v1/dismantling/batches",
        headers={**_auth(actors.technician), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "inputs": [{"lot_id": str(non_dmt_lot), "qty": 2}],
            "storage_method_code": "DEDICATED_CONTAINERS",
        },
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "DISMANTLING_NOT_SUPPORTED"

    # Successful creation by technician
    idem = str(uuid.uuid4())
    res = await client.post(
        "/api/v1/dismantling/batches",
        headers={**_auth(actors.technician), "Idempotency-Key": idem},
        json=payload_valid,
    )
    assert res.status_code == 201
    batch_data = res.json()
    assert batch_data["batch_no"].startswith("DSM/")
    assert batch_data["status"] == "OPEN"
    assert batch_data["total_input_qty"] == 4
    assert batch_data["total_dismantled_qty"] == 0

    # Stock at NON_FUNCTIONAL_STORE should now be 0 (consumed via DISMANTLE_IN)
    c = as_admin(db_conn)
    bal = c.execute(
        text(
            """
            select qty from public.stock_balances b
            join public.inventory_locations loc on loc.id = b.location_id
            where b.lot_id = :lot and loc.code = 'NON_FUNCTIONAL_STORE'
            """
        ),
        {"lot": dmt_lot},
    ).scalar_one()
    assert bal == 0


@pytest.mark.anyio
async def test_g11_pcb_guard_in_recovery(
    client: AsyncClient, actors: DismantlingActors, db_conn: Connection
) -> None:
    """G-11: PCB rows require both model and supplier in API and DB."""
    _, _, dmt_lot = _seed_non_good_lot(db_conn, qty=2, supports_dismantling=True)

    # Create batch with PARTITIONED_CONTAINER
    res = await client.post(
        "/api/v1/dismantling/batches",
        headers={**_auth(actors.technician), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "inputs": [{"lot_id": str(dmt_lot), "qty": 2}],
            "storage_method_code": "PARTITIONED_CONTAINER",
        },
    )
    assert res.status_code == 201
    batch_id = res.json()["id"]

    # Fetch partitions
    c = as_admin(db_conn)
    pcb_part_id = c.execute(
        text(
            "select id from public.container_partitions "
            "where part_type = 'PCB' and is_active = true limit 1"
        )
    ).scalar_one()

    # Recovery with PCB missing model/supplier
    recovery_invalid = {
        "parts": [
            {
                "part_type": "PCB",
                "qty": 2,
                "pcb_model_id": None,
                "pcb_supplier_id": None,
                "partition_id": str(pcb_part_id),
            }
        ],
        "scrap": {"qty_pieces": 0, "hazardous": False},
    }

    res = await client.post(
        f"/api/v1/dismantling/batches/{batch_id}/recover",
        headers={**_auth(actors.technician), "Idempotency-Key": str(uuid.uuid4())},
        json=recovery_invalid,
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "PCB_MODEL_SUPPLIER_REQUIRED"


@pytest.mark.anyio
async def test_recovery_with_storage_method_validation(
    client: AsyncClient, actors: DismantlingActors, db_conn: Connection
) -> None:
    """Validate that dedicated containers and partitioned containers match part type."""
    _, _, lot_ded = _seed_non_good_lot(db_conn, qty=3, supports_dismantling=True)

    # 1. Dedicated containers batch
    res = await client.post(
        "/api/v1/dismantling/batches",
        headers={**_auth(actors.technician), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "inputs": [{"lot_id": str(lot_ded), "qty": 3}],
            "storage_method_code": "DEDICATED_CONTAINERS",
        },
    )
    assert res.status_code == 201
    batch_ded_id = res.json()["id"]

    c = as_admin(db_conn)
    tip_container = c.execute(
        text(
            "select id from public.storage_containers "
            "where dedicated_part_type = 'TIP' and is_active = true limit 1"
        )
    ).scalar_one()
    wire_container = c.execute(
        text(
            "select id from public.storage_containers "
            "where dedicated_part_type = 'WIRE' and is_active = true limit 1"
        )
    ).scalar_one()

    # Try to put TIP into WIRE container -> Should fail
    res = await client.post(
        f"/api/v1/dismantling/batches/{batch_ded_id}/recover",
        headers={**_auth(actors.technician), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "parts": [{"part_type": "TIP", "qty": 3, "container_id": str(wire_container)}],
            "scrap": {"qty_pieces": 0, "hazardous": False},
        },
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] in ("CONTAINER_PART_MISMATCH", "INVALID_STORAGE_METHOD")

    # Put TIP into TIP container -> Success
    res = await client.post(
        f"/api/v1/dismantling/batches/{batch_ded_id}/recover",
        headers={**_auth(actors.technician), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "parts": [{"part_type": "TIP", "qty": 3, "container_id": str(tip_container)}],
            "scrap": {"qty_pieces": 0, "hazardous": False},
        },
    )
    assert res.status_code == 200
    batch_data = res.json()
    assert batch_data["status"] == "COMPLETED"
    assert len(batch_data["recovered_parts"]) == 1
    assert batch_data["recovered_parts"][0]["part_type"] == "TIP"
    assert batch_data["recovered_parts"][0]["qty"] == 3

    # Check SPARE_PARTS_STORE balance
    sp_loc_id = c.execute(
        text("select id from public.inventory_locations where code = 'SPARE_PARTS_STORE'")
    ).scalar_one()
    rec_lot_id = batch_data["recovered_parts"][0]["lot_id"]
    bal = c.execute(
        text("select qty from public.stock_balances where lot_id = :l and location_id = :loc"),
        {"l": rec_lot_id, "loc": sp_loc_id},
    ).scalar_one()
    assert bal == 3


@pytest.mark.anyio
async def test_full_dismantling_reconciliation_dec19_and_scrap_dec11(
    client: AsyncClient, actors: DismantlingActors, db_conn: Connection
) -> None:
    """Comprehensive test:
    - Dismantle 5 DMT units into a partitioned container
    - Free quantities (0 for TIP, 5 for BODY, 4 for WIRE, 5 for PCB)
    - PCB with model + supplier
    - Record hazardous scrap
    - Verify batch completed & reconciliation
    - Dispose hazardous scrap with manifest (DEC-11)
    """
    _, _, dmt_lot = _seed_non_good_lot(db_conn, qty=5, supports_dismantling=True)

    # 1. Create Batch
    res = await client.post(
        "/api/v1/dismantling/batches",
        headers={**_auth(actors.technician), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "inputs": [{"lot_id": str(dmt_lot), "qty": 5}],
            "storage_method_code": "PARTITIONED_CONTAINER",
        },
    )
    assert res.status_code == 201
    batch_id = res.json()["id"]

    # 2. Get partitions and PCB masters
    c = as_admin(db_conn)
    tip_part = c.execute(
        text("select id from public.container_partitions where part_type = 'TIP' limit 1")
    ).scalar_one()
    body_part = c.execute(
        text("select id from public.container_partitions where part_type = 'BODY' limit 1")
    ).scalar_one()
    wire_part = c.execute(
        text("select id from public.container_partitions where part_type = 'WIRE' limit 1")
    ).scalar_one()
    pcb_part = c.execute(
        text("select id from public.container_partitions where part_type = 'PCB' limit 1")
    ).scalar_one()

    model_id = c.execute(text("select id from public.pcb_models limit 1")).scalar_one()
    supplier_id = c.execute(
        text("select supplier_id from public.pcb_models where id = :m"), {"m": model_id}
    ).scalar_one()

    # 3. Partial Recovery (dismantle 2 units first)
    res = await client.post(
        f"/api/v1/dismantling/batches/{batch_id}/recover",
        headers={**_auth(actors.technician), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "units_dismantled": 2,
            "parts": [
                {"part_type": "BODY", "qty": 2, "partition_id": str(body_part)},
                {"part_type": "WIRE", "qty": 1, "partition_id": str(wire_part)},
            ],
            "scrap": {"qty_pieces": 1, "weight_kg": 0.05, "hazardous": False},
        },
    )
    assert res.status_code == 200
    part_batch = res.json()
    assert part_batch["status"] == "OPEN"
    assert part_batch["total_dismantled_qty"] == 2
    assert part_batch["total_input_qty"] == 5

    # 4. Remaining Recovery (remaining 3 units) with PCB + hazardous scrap
    res = await client.post(
        f"/api/v1/dismantling/batches/{batch_id}/recover",
        headers={**_auth(actors.technician), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "units_dismantled": 3,
            "parts": [
                {"part_type": "TIP", "qty": 0, "partition_id": str(tip_part)},  # 0 qty per DEC-19
                {"part_type": "BODY", "qty": 3, "partition_id": str(body_part)},
                {"part_type": "WIRE", "qty": 3, "partition_id": str(wire_part)},
                {
                    "part_type": "PCB",
                    "qty": 5,
                    "pcb_model_id": str(model_id),
                    "pcb_supplier_id": str(supplier_id),
                    "partition_id": str(pcb_part),
                },
            ],
            "scrap": {
                "qty_pieces": 2,
                "weight_kg": 0.12,
                "hazardous": True,
                "remarks": "Cracked casing & chemical residue",
            },
        },
    )
    assert res.status_code == 200
    full_batch = res.json()
    assert full_batch["status"] == "COMPLETED"
    assert full_batch["total_dismantled_qty"] == 5
    assert full_batch["completed_at"] is not None

    # Check scrap records
    scraps = full_batch["scrap_records"]
    assert len(scraps) == 2
    haz_scrap = next(s for s in scraps if s["hazardous"])
    assert haz_scrap["disposal_status"] == "MARKED"

    # 5. Dispose scrap: unauthorized fails
    res = await client.post(
        f"/api/v1/scrap/{haz_scrap['id']}/dispose",
        headers={**_auth(actors.technician), "Idempotency-Key": str(uuid.uuid4())},
        json={"manifest_ref": "MAN-2026-001"},
    )
    assert res.status_code == 403  # Only Spare Parts Manager can dispose scrap

    # Dispose hazardous scrap without manifest fails (DEC-11)
    res = await client.post(
        f"/api/v1/scrap/{haz_scrap['id']}/dispose",
        headers={**_auth(actors.spm), "Idempotency-Key": str(uuid.uuid4())},
        json={"manifest_ref": ""},
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "MANIFEST_REF_REQUIRED"

    # Dispose hazardous scrap with manifest succeeds
    res = await client.post(
        f"/api/v1/scrap/{haz_scrap['id']}/dispose",
        headers={**_auth(actors.spm), "Idempotency-Key": str(uuid.uuid4())},
        json={"manifest_ref": "HAZ-MAN-2026-999"},
    )
    assert res.status_code == 200
    disp_scrap = res.json()
    assert disp_scrap["disposal_status"] == "DISPOSED"
    assert disp_scrap["manifest_ref"] == "HAZ-MAN-2026-999"
    assert disp_scrap["disposed_by_name"] == "Spare Parts Manager"


@pytest.mark.anyio
async def test_pcb_masters_permissions(client: AsyncClient, actors: DismantlingActors) -> None:
    """Technicians cannot create PCB models/suppliers (requires masters permission)."""
    # Technician tries to create supplier
    res = await client.post(
        "/api/v1/dismantling/pcb-suppliers",
        headers=_auth(actors.technician),
        json={"name": "New Tech Supplier"},
    )
    assert res.status_code == 403

    # Admin creates supplier
    res = await client.post(
        "/api/v1/dismantling/pcb-suppliers",
        headers=_auth(actors.admin),
        json={"name": "New Tech Supplier"},
    )
    assert res.status_code == 201
    supplier_id = res.json()["id"]

    # Technician tries to create model
    res = await client.post(
        "/api/v1/dismantling/pcb-models",
        headers=_auth(actors.technician),
        json={"name": "PCB-MOD-999", "supplier_id": supplier_id},
    )
    assert res.status_code == 403

    # Admin creates model
    res = await client.post(
        "/api/v1/dismantling/pcb-models",
        headers=_auth(actors.admin),
        json={"name": "PCB-MOD-999", "supplier_id": supplier_id},
    )
    assert res.status_code == 201
    assert res.json()["name"] == "PCB-MOD-999"
