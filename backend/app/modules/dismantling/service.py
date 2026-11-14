"""Stage-4 Dismantling & Parts Recovery service (BR-26..BR-29, G-11, DEC-18, DEC-19, DEC-11)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.errors import (
    Conflict,
    NotFound,
    PermissionDenied,
    ValidationFailed,
)
from app.core.permissions import effective_permissions
from app.core.security import CurrentUser
from app.modules.dismantling import repository as repo
from app.modules.dismantling.schemas import (
    ContainerPartitionOut,
    DismantleBatchCreateIn,
    DismantleBatchDetailOut,
    DismantleBatchSummaryOut,
    DismantleInputOut,
    DismantleQueueItemOut,
    DismantleQueueResponse,
    DismantleRecoveryIn,
    PcbModelIn,
    PcbModelOut,
    PcbSupplierIn,
    PcbSupplierOut,
    RecoveredPartOut,
    ScrapDisposeIn,
    ScrapFromLotIn,
    ScrapRecordOut,
    StorageContainerOut,
)
from app.modules.inventory import ledger_service
from app.modules.notifications import service as notifications


def _can_dismantle(session: Session, user: CurrentUser) -> bool:
    if user.is_super_admin or "SPARE_PARTS_TECHNICIAN" in user.role_codes:
        return True
    perms = effective_permissions(session, user.id, is_super_admin=user.is_super_admin)
    return perms.allows("dismantling", "create") or perms.allows("dismantling", "edit")


def _can_dispose_scrap(session: Session, user: CurrentUser) -> bool:
    if user.is_super_admin or "SPARE_PARTS_MANAGER" in user.role_codes:
        return True
    perms = effective_permissions(session, user.id, is_super_admin=user.is_super_admin)
    return perms.allows("dismantling", "approve")


def _can_manage_masters(session: Session, user: CurrentUser) -> bool:
    if user.is_super_admin:
        return True
    perms = effective_permissions(session, user.id, is_super_admin=user.is_super_admin)
    return perms.allows("masters", "create") or perms.allows("masters", "edit")


def get_queue(session: Session) -> DismantleQueueResponse:
    """Fetch all candidate lots in NON_FUNCTIONAL_STORE.

    DEC-18: DMT lots with supports_dismantling=true go to dismantleable_lots.
    Non-DMT lots (e.g. Prismatic, Enclosed Oval) go to disposal_required_lots.
    """
    rows = repo.get_dismantling_queue_lots(session)
    dismantleable: list[DismantleQueueItemOut] = []
    disposal_required: list[DismantleQueueItemOut] = []

    for r in rows:
        item = DismantleQueueItemOut(**r)
        if item.supports_dismantling:
            dismantleable.append(item)
        else:
            disposal_required.append(item)

    total_dismantleable_qty = sum(i.qty for i in dismantleable)
    total_disposal_required_qty = sum(i.qty for i in disposal_required)

    return DismantleQueueResponse(
        dismantleable_lots=dismantleable,
        disposal_required_lots=disposal_required,
        total_dismantleable_qty=total_dismantleable_qty,
        total_disposal_required_qty=total_disposal_required_qty,
    )


def create_batch(
    session: Session,
    *,
    user: CurrentUser,
    payload: DismantleBatchCreateIn,
    idempotency_key: str,
) -> DismantleBatchDetailOut:
    """Create a dismantle batch and consume units from NON_FUNCTIONAL_STORE via DISMANTLE_IN.

    BR-26 / BR-27: Parts Recovery Technician dismantles units.
    DEC-18: Only categories that support dismantling can be batched.
    """
    if not _can_dismantle(session, user):
        raise PermissionDenied(
            "Only Spare Parts Technicians may create dismantle batches",
            code="NOT_SPARE_PARTS_TECHNICIAN",
        )

    non_func_loc = repo.get_location_by_code(session, "NON_FUNCTIONAL_STORE")
    if not non_func_loc:
        raise NotFound("NON_FUNCTIONAL_STORE location not found", code="LOCATION_NOT_FOUND")

    seen_lots: set[UUID] = set()
    total_input_qty = 0

    for inp in payload.inputs:
        if inp.lot_id in seen_lots:
            raise ValidationFailed(
                "Each lot may appear only once in a dismantle batch",
                code="DUPLICATE_LOT_IN_BATCH",
                details={"lot_id": str(inp.lot_id)},
            )
        seen_lots.add(inp.lot_id)

        lot_info = repo.get_lot_details(session, inp.lot_id)
        if not lot_info:
            raise NotFound(
                f"Lot {inp.lot_id} not found",
                code="LOT_NOT_FOUND",
                details={"lot_id": str(inp.lot_id)},
            )

        if not lot_info.get("supports_dismantling"):
            raise ValidationFailed(
                f"Lot {inp.lot_id} category does not support dismantling (DEC-18)",
                code="DISMANTLING_NOT_SUPPORTED",
                details={"lot_id": str(inp.lot_id)},
            )

        available_balance = repo.get_lot_balance(session, inp.lot_id, non_func_loc["id"])
        if available_balance < inp.qty:
            raise ValidationFailed(
                f"Insufficient balance for lot {inp.lot_id} in NON_FUNCTIONAL_STORE "
                f"(available {available_balance}, requested {inp.qty})",
                code="INSUFFICIENT_STOCK",
                details={
                    "lot_id": str(inp.lot_id),
                    "available": available_balance,
                    "requested": inp.qty,
                },
            )

        total_input_qty += inp.qty

    batch_no = repo.next_dismantle_batch_no(session)
    batch = repo.create_dismantle_batch(
        session,
        batch_no=batch_no,
        technician_profile_id=user.id,
        storage_method_code=payload.storage_method_code,
        total_input_qty=total_input_qty,
        created_by=user.id,
    )
    batch_id = batch["id"]

    for idx, inp in enumerate(payload.inputs, start=1):
        movement_id = ledger_service.move_stock(
            session,
            lot_id=inp.lot_id,
            from_location_id=non_func_loc["id"],
            to_location_id=None,
            qty=inp.qty,
            movement_type="DISMANTLE_IN",
            reference_type="DISMANTLE_BATCH",
            reference_id=batch_id,
            idempotency_key=f"{idempotency_key}:input:{inp.lot_id}:{idx}",
            actor_id=user.id,
            reason=f"Stage-4 dismantle batch {batch_no}",
        )
        repo.create_dismantle_input(
            session,
            batch_id=batch_id,
            lot_id=inp.lot_id,
            qty=inp.qty,
            stock_movement_id=movement_id,
            created_by=user.id,
        )

    return get_batch_detail(session, batch_id)


def get_batch_detail(session: Session, batch_id: UUID) -> DismantleBatchDetailOut:
    batch = repo.get_batch(session, batch_id)
    if not batch:
        raise NotFound("Dismantle batch not found", code="BATCH_NOT_FOUND")

    inputs = repo.get_batch_inputs(session, batch_id)
    parts = repo.get_recovered_parts(session, batch_id)
    scrap = repo.get_scrap_records(session, batch_id=batch_id)

    return DismantleBatchDetailOut(
        id=batch["id"],
        batch_no=batch["batch_no"],
        technician_profile_id=batch["technician_profile_id"],
        technician_name=batch["technician_name"],
        storage_method_code=batch["storage_method_code"],
        status=batch["status"],
        total_input_qty=batch["total_input_qty"],
        total_dismantled_qty=batch["total_dismantled_qty"],
        created_at=batch["created_at"],
        completed_at=batch["completed_at"],
        inputs=[DismantleInputOut(**inp) for inp in inputs],
        recovered_parts=[RecoveredPartOut(**p) for p in parts],
        scrap_records=[ScrapRecordOut(**s) for s in scrap],
    )


def list_batches(
    session: Session,
    *,
    status: str | None = None,
    technician_profile_id: UUID | None = None,
    page: int = 1,
    page_size: int = 50,
) -> list[DismantleBatchSummaryOut]:
    limit = max(1, min(page_size, 100))
    offset = max(0, (page - 1) * limit)
    rows = repo.list_batches(
        session,
        status=status,
        technician_profile_id=technician_profile_id,
        limit=limit,
        offset=offset,
    )
    return [DismantleBatchSummaryOut(**r) for r in rows]


def recover_batch(
    session: Session,
    *,
    user: CurrentUser,
    batch_id: UUID,
    payload: DismantleRecoveryIn,
    idempotency_key: str,
) -> DismantleBatchDetailOut:
    """Recover parts from dismantled units and record scrap.

    G-11: PCB rows require both model and supplier.
    BR-28: Dedicated containers or partitions must match the storage method and part type.
    DEC-19: Free quantities (0..n per type). Every input unit must be accounted for.
    """
    if not _can_dismantle(session, user):
        raise PermissionDenied(
            "Only Spare Parts Technicians may recover dismantled parts",
            code="NOT_SPARE_PARTS_TECHNICIAN",
        )

    batch = repo.get_batch(session, batch_id)
    if not batch:
        raise NotFound("Dismantle batch not found", code="BATCH_NOT_FOUND")

    if batch["status"] == "COMPLETED":
        raise Conflict("Dismantle batch is already completed", code="BATCH_ALREADY_COMPLETED")

    storage_method = batch["storage_method_code"]
    remaining_units = batch["total_input_qty"] - batch["total_dismantled_qty"]

    units_dismantled = (
        payload.units_dismantled if payload.units_dismantled is not None else remaining_units
    )

    if units_dismantled <= 0:
        raise ValidationFailed(
            "Units dismantled must be greater than zero",
            code="INVALID_DISMANTLED_QTY",
        )

    if units_dismantled > remaining_units:
        raise ValidationFailed(
            f"Cannot dismantle {units_dismantled} units; only {remaining_units} remaining in batch",
            code="EXCESS_DISMANTLED_QTY",
            details={"requested": units_dismantled, "remaining": remaining_units},
        )

    sp_store_loc = repo.get_location_by_code(session, "SPARE_PARTS_STORE")
    if not sp_store_loc:
        raise NotFound("SPARE_PARTS_STORE location not found", code="LOCATION_NOT_FOUND")

    # Validate each recovered part
    for idx, part in enumerate(payload.parts, start=1):
        # G-11: PCB rows require model + supplier
        if part.part_type == "PCB" and (not part.pcb_model_id or not part.pcb_supplier_id):
            raise ValidationFailed(
                "G-11: PCB parts require both PCB model and supplier",
                code="PCB_MODEL_SUPPLIER_REQUIRED",
                details={"part_type": "PCB", "index": idx},
            )

        # Storage method and container/partition check
        if storage_method == "DEDICATED_CONTAINERS":
            if not part.container_id:
                raise ValidationFailed(
                    f"Part {part.part_type} requires a dedicated container "
                    "(storage method: DEDICATED_CONTAINERS)",
                    code="DEDICATED_CONTAINER_REQUIRED",
                    details={"part_type": part.part_type, "index": idx},
                )
            container = repo.get_storage_container(session, part.container_id)
            if not container or not container.get("is_active"):
                raise NotFound(
                    f"Dedicated container for {part.part_type} not found or inactive",
                    code="CONTAINER_NOT_FOUND",
                    details={"container_id": str(part.container_id)},
                )
            if container.get("storage_method") != "DEDICATED_CONTAINERS":
                raise ValidationFailed(
                    f"Container {container['code']} is not a dedicated container",
                    code="INVALID_STORAGE_METHOD",
                    details={"container_id": str(part.container_id)},
                )
            if container.get("dedicated_part_type") != part.part_type:
                raise ValidationFailed(
                    f"Container {container['code']} is dedicated to "
                    f"{container.get('dedicated_part_type')}, not {part.part_type}",
                    code="CONTAINER_PART_MISMATCH",
                    details={
                        "expected": part.part_type,
                        "container_part": container.get("dedicated_part_type"),
                    },
                )
        elif storage_method == "PARTITIONED_CONTAINER":
            if not part.partition_id:
                raise ValidationFailed(
                    f"Part {part.part_type} requires a container partition "
                    "(storage method: PARTITIONED_CONTAINER)",
                    code="PARTITION_REQUIRED",
                    details={"part_type": part.part_type, "index": idx},
                )
            partition = repo.get_container_partition(session, part.partition_id)
            if not partition or not partition.get("is_active"):
                raise NotFound(
                    f"Container partition for {part.part_type} not found or inactive",
                    code="PARTITION_NOT_FOUND",
                    details={"partition_id": str(part.partition_id)},
                )
            if partition.get("storage_method") != "PARTITIONED_CONTAINER":
                raise ValidationFailed(
                    f"Partition {partition['compartment_code']} does not belong "
                    "to a partitioned container",
                    code="INVALID_STORAGE_METHOD",
                    details={"partition_id": str(part.partition_id)},
                )
            if partition.get("part_type") != part.part_type:
                raise ValidationFailed(
                    f"Partition {partition['compartment_code']} is assigned to "
                    f"{partition.get('part_type')}, not {part.part_type}",
                    code="PARTITION_PART_MISMATCH",
                    details={
                        "expected": part.part_type,
                        "partition_part": partition.get("part_type"),
                    },
                )

    # Process and record parts
    for idx, part in enumerate(payload.parts, start=1):
        lot_id: UUID | None = None
        movement_id: UUID | None = None

        container_id = part.container_id
        partition_id = part.partition_id
        if storage_method == "PARTITIONED_CONTAINER" and partition_id and not container_id:
            partition = repo.get_container_partition(session, partition_id)
            if partition:
                container_id = partition["container_id"]

        if part.qty > 0:
            stock_item_id = repo.find_or_create_spare_part_item(
                session,
                part_type=part.part_type,
                pcb_model_id=part.pcb_model_id,
                pcb_supplier_id=part.pcb_supplier_id,
                actor_id=user.id,
            )

            lot_id = ledger_service.create_stock_lot(
                session,
                stock_item_id=stock_item_id,
                condition_class="SALVAGED",
                container_id=container_id,
                partition_id=partition_id,
                is_pending=False,
                requires_evaluation=False,
                created_by=user.id,
            )

            movement_id = ledger_service.move_stock(
                session,
                lot_id=lot_id,
                from_location_id=None,
                to_location_id=sp_store_loc["id"],
                qty=part.qty,
                movement_type="RECEIPT",
                reference_type="DISMANTLE_BATCH",
                reference_id=batch_id,
                idempotency_key=f"{idempotency_key}:part:{idx}:{part.part_type}",
                actor_id=user.id,
                reason=f"Stage-4 recovered spare part {part.part_type}",
            )

        repo.create_recovered_part(
            session,
            batch_id=batch_id,
            part_type=part.part_type,
            qty=part.qty,
            pcb_model_id=part.pcb_model_id,
            pcb_supplier_id=part.pcb_supplier_id,
            container_id=container_id,
            partition_id=partition_id,
            lot_id=lot_id,
            stock_movement_id=movement_id,
            created_by=user.id,
        )

    # Process scrap if any pieces or weight entered
    if payload.scrap.qty_pieces > 0 or payload.scrap.weight_kg is not None:
        repo.create_scrap_record(
            session,
            batch_id=batch_id,
            lot_id=None,
            qty_pieces=payload.scrap.qty_pieces,
            weight_kg=payload.scrap.weight_kg,
            hazardous=payload.scrap.hazardous,
            remarks=payload.scrap.remarks,
            created_by=user.id,
        )

    # Update batch progress & reconciliation
    new_dismantled_qty = batch["total_dismantled_qty"] + units_dismantled
    mark_completed = new_dismantled_qty >= batch["total_input_qty"]

    repo.update_batch_progress(
        session,
        batch_id=batch_id,
        additional_dismantled_qty=units_dismantled,
        mark_completed=mark_completed,
    )

    # P4-03: PARTS_RECOVERED (BR-27/BR-28; rule seeded inactive). Context: Spare Parts Managers,
    # who own the salvaged spare-parts ledger (BR-30).
    recovered = sum(p.qty for p in payload.parts)
    if recovered > 0:
        by_type: dict[str, int] = {}
        for p in payload.parts:
            if p.qty > 0:
                by_type[str(p.part_type)] = by_type.get(str(p.part_type), 0) + p.qty
        notifications.publish(
            session,
            "PARTS_RECOVERED",
            role_codes=["SPARE_PARTS_MANAGER"],
            title=f"{batch['batch_no']}: {recovered} part(s) recovered",
            body=", ".join(f"{k} x{v}" for k, v in sorted(by_type.items()))
            + f" from {units_dismantled} unit(s); recorded by {user.full_name}.",
            entity_type="dismantle_batch",
            entity_id=batch_id,
            data={"batch_no": str(batch["batch_no"])},
            dedupe_key=f"parts-recovered:{idempotency_key}",
        )

    return get_batch_detail(session, batch_id)


def list_scrap_records(
    session: Session,
    *,
    batch_id: UUID | None = None,
    disposal_status: str | None = None,
    page: int = 1,
    page_size: int = 100,
) -> list[ScrapRecordOut]:
    limit = max(1, min(page_size, 200))
    offset = max(0, (page - 1) * limit)
    rows = repo.get_scrap_records(
        session,
        batch_id=batch_id,
        disposal_status=disposal_status,
        limit=limit,
        offset=offset,
    )
    return [ScrapRecordOut(**r) for r in rows]


def dispose_scrap(
    session: Session,
    *,
    user: CurrentUser,
    scrap_id: UUID,
    payload: ScrapDisposeIn,
    idempotency_key: str,
) -> ScrapRecordOut:
    """Safely dispose scrap.

    DEC-11: Hazardous scrap requires manifest_ref.
    Only Spare Parts Manager may dispose scrap.
    """
    if not _can_dispose_scrap(session, user):
        raise PermissionDenied(
            "Only Spare Parts Managers may dispose scrap",
            code="NOT_SPARE_PARTS_MANAGER",
        )

    scrap = repo.get_scrap_record(session, scrap_id)
    if not scrap:
        raise NotFound("Scrap record not found", code="SCRAP_NOT_FOUND")

    if scrap["disposal_status"] == "DISPOSED":
        raise Conflict("Scrap record already disposed", code="SCRAP_ALREADY_DISPOSED")

    if scrap["hazardous"] and (not payload.manifest_ref or not payload.manifest_ref.strip()):
        raise ValidationFailed(
            "DEC-11: Hazardous scrap requires a manifest reference for disposal",
            code="MANIFEST_REF_REQUIRED",
        )

    disposed_at = payload.disposed_at or datetime.now(UTC)
    manifest_ref = payload.manifest_ref.strip() if payload.manifest_ref else None

    # P3-03 task 4 / DEC-11: scrap marked from a stock lot leaves the ledger here — one DISPOSE
    # movement into SCRAP_DISPOSED through rms_move_stock (G-05 allows HAZARD lots only there).
    movement_id: UUID | None = None
    if scrap["lot_id"]:
        lot = repo.get_disposable_lot(session, scrap["lot_id"])
        scrap_loc = repo.get_location_id(session, "SCRAP_DISPOSED")
        if lot is None or scrap_loc is None or int(lot["balance"]) < int(scrap["qty_pieces"]):
            raise Conflict(
                "The marked pieces are no longer held in quarantine / non-functional stock",
                code="SCRAP_STOCK_NOT_AVAILABLE",
                details={"lot_id": str(scrap["lot_id"]), "qty": scrap["qty_pieces"]},
            )
        movement_id = ledger_service.move_stock(
            session,
            lot_id=scrap["lot_id"],
            from_location_id=lot["location_id"],
            to_location_id=scrap_loc,
            qty=int(scrap["qty_pieces"]),
            movement_type="DISPOSE",
            reference_type="scrap_record",
            reference_id=scrap_id,
            idempotency_key=f"scrap-dispose:{scrap_id}",
            actor_id=user.id,
            reason=f"Safe disposal, manifest {manifest_ref}" if manifest_ref else "Safe disposal",
        )

    repo.update_scrap_disposed(
        session,
        scrap_id=scrap_id,
        manifest_ref=manifest_ref,
        disposed_at=disposed_at,
        disposed_by=user.id,
        stock_movement_id=movement_id,
    )

    updated = repo.get_scrap_record(session, scrap_id)
    return ScrapRecordOut(**updated)  # type: ignore[arg-type]


def mark_lot_for_disposal(
    session: Session,
    *,
    user: CurrentUser,
    payload: ScrapFromLotIn,
) -> ScrapRecordOut:
    """Mark quarantined hazard stock (DEC-11) or a DEC-18 'disposal required' lot as scrap.

    The Spare Parts Manager (HAZARD_QUARANTINE / NON_FUNCTIONAL_STORE custodian, DEC-10) marks the
    pieces; POST /scrap/{id}/dispose then moves them to SCRAP_DISPOSED with a manifest (hazardous
    scrap requires one). DMT non-good units take the dismantling route instead (BR-26).
    """
    if not _can_dispose_scrap(session, user):
        raise PermissionDenied(
            "Only Spare Parts Managers may mark stock for disposal",
            code="NOT_SPARE_PARTS_MANAGER",
        )
    lot = repo.get_disposable_lot(session, payload.lot_id)
    if lot is None:
        raise ValidationFailed(
            "Only stock held in Hazard Quarantine or the Non-Functional Store can be scrapped",
            code="LOT_NOT_DISPOSABLE",
        )
    hazard = lot["location_code"] == "HAZARD_QUARANTINE"
    if not hazard and (
        lot["supports_dismantling"]
        or lot["condition_class"] not in ("NON_GOOD", "NON_SELLABLE", "NOT_ALLOWED")
    ):
        raise ValidationFailed(
            "This lot follows the dismantling route (DEC-18); only non-dismantleable stock is "
            "scrapped directly",
            code="LOT_NOT_DISPOSABLE",
            details={"condition_class": lot["condition_class"]},
        )
    available = int(lot["balance"]) - int(lot["marked_qty"])
    if payload.qty > available:
        raise ValidationFailed(
            f"Only {available} piece(s) of this lot are not yet marked for disposal",
            code="SCRAP_QTY_EXCEEDS_STOCK",
            details={"available": available, "requested": payload.qty},
        )
    row = repo.create_scrap_record(
        session,
        batch_id=None,
        lot_id=payload.lot_id,
        qty_pieces=payload.qty,
        weight_kg=payload.weight_kg,
        hazardous=hazard or lot["condition_class"] == "HAZARD",
        remarks=payload.remarks,
        created_by=user.id,
    )
    created = repo.get_scrap_record(session, row["id"])
    return ScrapRecordOut(**created)  # type: ignore[arg-type]


def list_containers(
    session: Session,
    *,
    storage_method: str | None = None,
    part_type: str | None = None,
) -> list[StorageContainerOut]:
    rows = repo.list_containers(session, storage_method=storage_method, part_type=part_type)
    return [
        StorageContainerOut(
            id=c["id"],
            code=c["code"],
            barcode=c["barcode"],
            name=c["name"],
            container_type=c["container_type"],
            storage_method=c["storage_method"],
            dedicated_part_type=c["dedicated_part_type"],
            location_id=c["location_id"],
            is_active=c["is_active"],
            partitions=[ContainerPartitionOut(**p) for p in c.get("partitions", [])],
        )
        for c in rows
    ]


def list_pcb_models(session: Session) -> list[PcbModelOut]:
    rows = repo.list_pcb_models(session)
    return [PcbModelOut(**r) for r in rows]


def create_pcb_model(
    session: Session,
    *,
    user: CurrentUser,
    payload: PcbModelIn,
) -> PcbModelOut:
    if not _can_manage_masters(session, user):
        raise PermissionDenied(
            "Only administrators or masters managers may add new PCB models",
            code="MASTERS_PERMISSION_REQUIRED",
        )
    row = repo.create_pcb_model(
        session,
        name=payload.name.strip(),
        supplier_id=payload.supplier_id,
        is_active=payload.is_active,
        actor_id=user.id,
    )
    return PcbModelOut(**row)


def list_pcb_suppliers(session: Session) -> list[PcbSupplierOut]:
    rows = repo.list_pcb_suppliers(session)
    return [PcbSupplierOut(**r) for r in rows]


def create_pcb_supplier(
    session: Session,
    *,
    user: CurrentUser,
    payload: PcbSupplierIn,
) -> PcbSupplierOut:
    if not _can_manage_masters(session, user):
        raise PermissionDenied(
            "Only administrators or masters managers may add new PCB suppliers",
            code="MASTERS_PERMISSION_REQUIRED",
        )
    row = repo.create_pcb_supplier(
        session,
        name=payload.name.strip(),
        is_active=payload.is_active,
        actor_id=user.id,
    )
    return PcbSupplierOut(**row)
