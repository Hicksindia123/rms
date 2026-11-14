"""P3-02 Servicing business logic (master plan §2.2 Stage-3, BR-23..BR-25, G-10, DEC-14..DEC-17)."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import (
    Conflict,
    NotFound,
    PermissionDenied,
    SystemGuardViolation,
    ValidationFailed,
)
from app.core.security import CurrentUser
from app.modules.custody import service as custody_service
from app.modules.custody.schemas import TransferLineIn
from app.modules.inventory import battery_service, ledger_service
from app.modules.notifications import service as notifications
from app.modules.servicing import repository as repo
from app.modules.servicing.schemas import (
    AllotBatchIn,
    BatchDetailOut,
    BatchLineOut,
    BatchSummaryOut,
    BatteryReconciliationOut,
    BatteryReconciliationTypeRow,
    IntermediateLotOut,
    ReceiveBatchIn,
    ReceivingRecordOut,
    TechnicianOut,
)


def _get_spare_parts_manager_user_ids(session: Session) -> list[UUID]:
    stmt = text(
        """
        select ur.user_id
        from public.user_roles ur
        join public.roles r on r.id = ur.role_id
        where r.code = 'SPARE_PARTS_MANAGER'
        """
    )
    rows = session.execute(stmt).scalars().all()
    return [UUID(str(u)) for u in rows]


def list_technicians(session: Session) -> list[TechnicianOut]:
    rows = repo.list_technicians(session)
    return [TechnicianOut(**r) for r in rows]


def get_intermediate_lots(session: Session) -> list[IntermediateLotOut]:
    rows = repo.get_intermediate_lots(session)
    return [IntermediateLotOut(**r) for r in rows]


def get_batch_detail(session: Session, batch_id: UUID) -> BatchDetailOut:
    batch = repo.get_batch(session, batch_id)
    if not batch:
        raise NotFound("Technician batch not found", code="BATCH_NOT_FOUND")

    lines = repo.get_batch_lines(session, batch_id)
    records = repo.get_receiving_records(session, batch_id)

    total_qty_allotted = sum(ln["qty_allotted"] for ln in lines)
    total_qty_received = sum(ln["qty_received"] for ln in lines)

    return BatchDetailOut(
        id=batch["id"],
        batch_no=batch["batch_no"],
        technician_id=batch["technician_id"],
        technician_name=batch["technician_name"],
        entry_by=batch["entry_by"],
        entry_by_name=batch["entry_by_name"],
        status=batch["status"],
        transfer_id=batch["transfer_id"],
        allotted_at=batch["allotted_at"],
        completed_at=batch["completed_at"],
        notes=batch["notes"],
        total_qty_allotted=total_qty_allotted,
        total_qty_received=total_qty_received,
        lines=[BatchLineOut(**ln) for ln in lines],
        receiving_records=[ReceivingRecordOut(**rec) for rec in records],
    )


def list_batches(
    session: Session,
    *,
    status: str | None = None,
    technician_id: UUID | None = None,
    page: int = 1,
    page_size: int = 50,
) -> list[BatchSummaryOut]:
    limit = max(1, min(page_size, 100))
    offset = max(0, (page - 1) * limit)
    rows = repo.list_batches(
        session, status=status, technician_id=technician_id, limit=limit, offset=offset
    )
    return [BatchSummaryOut(**r) for r in rows]


def allot_batch(
    session: Session,
    *,
    user: CurrentUser,
    payload: AllotBatchIn,
    idempotency_key: str,
) -> BatchDetailOut:
    """Technician Coordinator allots a batch to the technician (Raj Kumar Ji).

    BR-23: Technician allotment and receiving are entered by Aman or Sahil.
    DEC-34: Auto-accepted by coordinator on behalf of the technician.
    """
    if not user.is_super_admin and "TECHNICIAN_COORDINATOR" not in user.role_codes:
        raise PermissionDenied(
            "Only Technician Coordinators may allot technician batches",
            code="NOT_TECHNICIAN_COORDINATOR",
        )

    tech = repo.get_technician(session, payload.technician_id)
    if not tech:
        raise NotFound("Technician not found", code="TECHNICIAN_NOT_FOUND")

    inter_loc = repo.get_intermediate_store_location(session)

    # Validate each line and check available balance
    seen_lots: set[UUID] = set()
    for ln in payload.lines:
        if ln.lot_id in seen_lots:
            raise ValidationFailed(
                "Each lot may appear only once in an allotment batch",
                code="DUPLICATE_LOT_IN_BATCH",
                details={"lot_id": str(ln.lot_id)},
            )
        seen_lots.add(ln.lot_id)
        lot = repo.get_lot(session, ln.lot_id, for_update=True)
        if not lot:
            raise NotFound(f"Lot {ln.lot_id} not found", code="LOT_NOT_FOUND")
        bal = ledger_service.get_balance(session, ln.lot_id, inter_loc["id"])
        if ln.qty > bal:
            raise ValidationFailed(
                f"Lot holds {bal} pieces at Intermediate Store; cannot allot {ln.qty}",
                code="INSUFFICIENT_STORE_STOCK",
                details={"lot_id": str(ln.lot_id), "available": bal, "requested": ln.qty},
            )

    # Generate batch number from TECH_BATCH series
    batch_no = str(
        session.execute(text("select rms_private.next_number('TECH_BATCH')")).scalar_one()
    )

    # Create batch
    entry_by = user.id  # Captured automatically from the logged-in coordinator (BR-23)
    batch = repo.insert_batch(
        session,
        batch_no=batch_no,
        technician_id=tech["id"],
        entry_by=entry_by,
        transfer_id=None,
        notes=payload.notes.strip() if payload.notes else None,
    )
    batch_id = batch["id"]

    # Create batch lines
    for ln in payload.lines:
        lot = repo.get_lot(session, ln.lot_id)
        if lot is None:
            raise NotFound(f"Lot {ln.lot_id} not found", code="LOT_NOT_FOUND")
        repo.insert_batch_line(
            session,
            batch_id=batch_id,
            lot_id=ln.lot_id,
            qty_allotted=ln.qty,
            requires_evaluation=bool(lot.get("requires_evaluation", False)),
        )

    # Custody engine transfer: INTERMEDIATE_STORE -> TECHNICIAN_BENCH (auto-accepted DEC-34)
    transfer_lines = [TransferLineIn(lot_id=ln.lot_id, qty=ln.qty) for ln in payload.lines]
    transfer_id = custody_service.auto_transfer(
        session,
        actor=user,
        from_location_code="INTERMEDIATE_STORE",
        to_location_code="TECHNICIAN_BENCH",
        lines=transfer_lines,
        purpose_code="TECHNICIAN_ALLOTMENT",
        notes=f"Technician batch allotment {batch_no}",
        accepted_on_behalf_of=f"Technician: {tech['display_name']}",
    )

    # Link transfer to batch
    session.execute(
        text("update public.technician_batches set transfer_id = :tid where id = :bid"),
        {"tid": transfer_id, "bid": batch_id},
    )

    # P4-03: TECH_BATCH_ALLOTTED (BR-23; rule seeded inactive). Context: the technician's login.
    total_qty = sum(ln.qty for ln in payload.lines)
    notifications.publish(
        session,
        "TECH_BATCH_ALLOTTED",
        user_ids=[tech.get("profile_id")],
        title=f"{batch_no}: {total_qty} pc(s) allotted to {tech['display_name']}",
        body=f"{len(payload.lines)} lot(s) moved to the technician bench by {user.full_name}.",
        entity_type="technician_batch",
        entity_id=batch_id,
        data={"batch_no": batch_no},
        dedupe_key=f"tech-batch-allotted:{batch_id}",
    )

    return get_batch_detail(session, batch_id)


def receive_batch(
    session: Session,
    *,
    user: CurrentUser,
    batch_id: UUID,
    payload: ReceiveBatchIn,
    idempotency_key: str,
) -> BatchDetailOut:
    """Record technician receiving results: battery check, cleaning, and classification.

    BR-23: Coordinator enters allotment and receiving.
    BR-24, G-10: BATTERY_REPLACED requires pieces_checked > 0, batteries > 0, deducts battery stock.
    DEC-15: Battery check applies only when category.supports_battery.
    DEC-16: Cleaning required when source_condition in (DMT_DIRTY, DMT_SCRATCHED).
    DEC-17, BR-25: Permanent scratches forces NON_SELLABLE.
    """
    if not user.is_super_admin and "TECHNICIAN_COORDINATOR" not in user.role_codes:
        raise PermissionDenied(
            "Only Technician Coordinators may record technician receiving",
            code="NOT_TECHNICIAN_COORDINATOR",
        )

    batch = repo.get_batch(session, batch_id, for_update=True)
    if not batch:
        raise NotFound("Batch not found", code="BATCH_NOT_FOUND")

    if batch["status"] in ("COMPLETED", "CANCELLED"):
        raise Conflict(
            f"Cannot receive on a {batch['status']} batch",
            code="BATCH_INACTIVE",
            details={"status": batch["status"]},
        )

    battery_store = battery_service.get_battery_store_location(session)
    technician_bench = repo.get_technician_bench_location(session)
    battery_consumed: dict[UUID, int] = {}

    for line_in in payload.lines:
        batch_line = repo.get_batch_line(session, line_in.batch_line_id, for_update=True)
        if not batch_line:
            raise NotFound("Batch line not found", code="LINE_NOT_FOUND")
        if batch_line["batch_id"] != batch_id:
            raise ValidationFailed("Line does not belong to this batch", code="LINE_MISMATCH")

        qty_receiving = line_in.qty_receiving
        if qty_receiving <= 0:
            raise ValidationFailed("Receiving quantity must be > 0", code="INVALID_QTY")

        unreceived = batch_line["qty_allotted"] - batch_line["qty_received"]
        if qty_receiving > unreceived:
            raise ValidationFailed(
                f"Line has {unreceived} unreceived pieces; cannot receive {qty_receiving}",
                code="EXCEEDS_UNRECEIVED",
                details={"unreceived": unreceived, "requested": qty_receiving},
            )

        # Classification allocations sum check
        allocations = line_in.allocations or {}
        functional_good_qty = allocations.get("FUNCTIONAL_GOOD", 0)
        functional_repaired_qty = allocations.get("FUNCTIONAL_REPAIRED", 0)
        non_good_qty = allocations.get("NON_GOOD", 0)
        non_sellable_qty = allocations.get("NON_SELLABLE", 0)

        for name, val in [
            ("FUNCTIONAL_GOOD", functional_good_qty),
            ("FUNCTIONAL_REPAIRED", functional_repaired_qty),
            ("NON_GOOD", non_good_qty),
            ("NON_SELLABLE", non_sellable_qty),
        ]:
            if val < 0:
                raise ValidationFailed(
                    f"Allocation for {name} cannot be negative", code="NEGATIVE_ALLOCATION"
                )

        total_alloc = (
            functional_good_qty + functional_repaired_qty + non_good_qty + non_sellable_qty
        )
        if total_alloc != qty_receiving:
            raise ValidationFailed(
                (
                    f"Classification allocations ({total_alloc}) "
                    f"must equal receiving quantity ({qty_receiving})"
                ),
                code="ALLOCATION_SUM_MISMATCH",
                details={"allocations_sum": total_alloc, "qty_receiving": qty_receiving},
            )

        # Battery check validations (DEC-15, G-10, BR-24)
        battery_check_code = line_in.battery_check_code
        pieces_checked = line_in.pieces_checked
        batteries_installed = line_in.batteries_installed
        battery_type_id = line_in.battery_type_id

        if batch_line["supports_battery"]:
            if not battery_check_code:
                raise ValidationFailed(
                    "Battery check result is required for battery-supported products",
                    code="BATTERY_CHECK_REQUIRED",
                )
            if battery_check_code == "BATTERY_OK":
                if pieces_checked is None or pieces_checked < 1:
                    raise ValidationFailed(
                        "Pieces checked must be >= 1 for BATTERY_OK",
                        code="PIECES_CHECKED_REQUIRED",
                    )
                batteries_installed = 0
            elif battery_check_code == "BATTERY_REPLACED":
                # G-10: BATTERY_REPLACED requires counts and battery_type_id
                if (
                    not pieces_checked
                    or pieces_checked <= 0
                    or not batteries_installed
                    or batteries_installed <= 0
                    or not battery_type_id
                ):
                    raise SystemGuardViolation(
                        "G-10",
                        (
                            "BATTERY_REPLACED requires pieces_checked > 0, "
                            "batteries_installed > 0, and battery_type_id"
                        ),
                    )
            else:
                raise ValidationFailed(
                    f"Unknown battery check code {battery_check_code}", code="INVALID_BATTERY_CODE"
                )
        else:
            battery_check_code = None
            pieces_checked = None
            batteries_installed = None
            battery_type_id = None

        # Cleaning check validations (DEC-16, DEC-17, BR-25)
        source_cond = batch_line["source_condition_code"]
        cleaning_code = line_in.cleaning_code
        if source_cond in ("DMT_DIRTY", "DMT_SCRATCHED") and not cleaning_code:
            raise ValidationFailed(
                f"Cleaning treatment is required when source condition is {source_cond} (DEC-16)",
                code="CLEANING_REQUIRED",
            )

        if cleaning_code == "PERMANENT_SCRATCHES" and non_sellable_qty != qty_receiving:
            # DEC-17 / BR-25: Permanent scratches forces NON_SELLABLE
            raise ValidationFailed(
                "Permanent scratches force classification to NON_SELLABLE (DEC-17)",
                code="PERMANENT_SCRATCHES_NON_SELLABLE",
                details={"non_sellable_qty": non_sellable_qty, "required": qty_receiving},
            )

        # 1. Deduct battery stock if batteries were installed (G-10, BR-24, G-16)
        battery_movement_id = None
        if (
            battery_check_code == "BATTERY_REPLACED"
            and (batteries_installed or 0) > 0
            and battery_type_id
        ):
            _, battery_lot_id = battery_service.get_or_create_battery_stock_lot(
                session, battery_type_id, created_by=user.id
            )
            consume_key = (
                f"battery-consume:{batch_id}:{line_in.batch_line_id}:{batch_line['qty_received']}"
            )
            battery_movement_id = ledger_service.move_stock(
                session,
                lot_id=battery_lot_id,
                from_location_id=battery_store["id"],
                to_location_id=None,
                qty=batteries_installed or 0,
                movement_type="CONSUME",
                reference_type="TECH_BATCH_RECEIVE",
                reference_id=batch_id,
                idempotency_key=consume_key,
                actor_id=user.id,
                reason=f"Batteries installed for batch {batch['batch_no']}",
            )
            battery_consumed[battery_type_id] = battery_consumed.get(battery_type_id, 0) + (
                batteries_installed or 0
            )

        # 2. Reclassify lots at TECHNICIAN_BENCH and execute custody transfers back
        source_lot_id = batch_line["lot_id"]

        functional_lines: list[TransferLineIn] = []
        non_good_lines: list[TransferLineIn] = []
        non_sellable_lines: list[TransferLineIn] = []

        for cond_name, alloc_qty in [
            ("FUNCTIONAL_GOOD", functional_good_qty),
            ("FUNCTIONAL_REPAIRED", functional_repaired_qty),
            ("NON_GOOD", non_good_qty),
            ("NON_SELLABLE", non_sellable_qty),
        ]:
            if alloc_qty <= 0:
                continue

            target_routing = None
            target_lot_id = repo.find_or_create_target_lot(
                session,
                stock_item_id=batch_line["stock_item_id"],
                gs_id=batch_line["gs_id"],
                gs_item_id=batch_line["gs_item_id"],
                condition_class=cond_name,
                source_condition_code=batch_line["source_condition_code"],
                routing_hint=target_routing,
                created_by=user.id,
            )

            if target_lot_id != source_lot_id:
                reclass_key = (
                    f"reclass:{batch_id}:{line_in.batch_line_id}:{cond_name}:"
                    f"{batch_line['qty_received']}"
                )
                ledger_service.reclassify_lot(
                    session,
                    source_lot_id=source_lot_id,
                    target_lot_id=target_lot_id,
                    location_id=technician_bench["id"],
                    qty=alloc_qty,
                    reference_type="TECH_BATCH_RECEIVE",
                    reference_id=batch_id,
                    idempotency_key=reclass_key,
                    actor_id=user.id,
                    reason=f"Reclassified to {cond_name} on technician receive",
                )

            line_in_trf = TransferLineIn(lot_id=target_lot_id, qty=alloc_qty)
            if cond_name in ("FUNCTIONAL_GOOD", "FUNCTIONAL_REPAIRED"):
                functional_lines.append(line_in_trf)
            elif cond_name == "NON_GOOD":
                non_good_lines.append(line_in_trf)
            elif cond_name == "NON_SELLABLE":
                non_sellable_lines.append(line_in_trf)

        # Transfer FUNCTIONAL_* back to INTERMEDIATE_STORE (custodian: Sahil)
        functional_trf_id = None
        if functional_lines:
            functional_trf_id = custody_service.auto_transfer(
                session,
                actor=user,
                from_location_code="TECHNICIAN_BENCH",
                to_location_code="INTERMEDIATE_STORE",
                lines=functional_lines,
                purpose_code="TECHNICIAN_RECEIVING",
                notes=f"Functional return from batch {batch['batch_no']}",
                gs_id=batch_line["gs_id"],
                accepted_on_behalf_of="Intermediate Store (Sahil)",
            )

        # Transfer NON_GOOD to DISMANTLING queue (NON_FUNCTIONAL_STORE with "to_dismantle")
        non_good_trf_id = None
        if non_good_lines:
            non_good_trf_id = custody_service.auto_transfer(
                session,
                actor=user,
                from_location_code="TECHNICIAN_BENCH",
                to_location_code="NON_FUNCTIONAL_STORE",
                lines=non_good_lines,
                purpose_code="TECHNICIAN_RECEIVING",
                notes=f"Non-Good units (to dismantle) from batch {batch['batch_no']}",
                gs_id=batch_line["gs_id"],
                accepted_on_behalf_of="Spare Parts Manager (Dismantling queue)",
            )

        # Transfer NON_SELLABLE to NON_FUNCTIONAL_STORE (Spare Parts Manager)
        non_sellable_trf_id = None
        if non_sellable_lines:
            non_sellable_trf_id = custody_service.auto_transfer(
                session,
                actor=user,
                from_location_code="TECHNICIAN_BENCH",
                to_location_code="NON_FUNCTIONAL_STORE",
                lines=non_sellable_lines,
                purpose_code="TECHNICIAN_RECEIVING",
                notes=f"Non-Sellable units from batch {batch['batch_no']}",
                gs_id=batch_line["gs_id"],
                accepted_on_behalf_of="Spare Parts Manager",
            )
            # Notification to Spare Parts Manager
            spm_ids = _get_spare_parts_manager_user_ids(session)
            if spm_ids:
                notifications.publish(
                    session,
                    "NON_SELLABLE_RECEIVED",
                    user_ids=spm_ids,
                    notification_type="NON_SELLABLE_RECEIVED",
                    title=f"Non-Sellable stock received from {batch['batch_no']}",
                    body=f"{non_sellable_qty} non-sellable piece(s) moved to Non-Functional Store.",
                    entity_type="technician_batch",
                    entity_id=batch_id,
                    priority="NORMAL",
                )

        # 3. Insert receiving record
        record_key = f"tech-receive:{batch_id}:{line_in.batch_line_id}:{batch_line['qty_received']}"
        repo.insert_receiving_record(
            session,
            batch_id=batch_id,
            batch_line_id=line_in.batch_line_id,
            qty_received=qty_receiving,
            battery_check_code=battery_check_code,
            pieces_checked=pieces_checked,
            batteries_installed=batteries_installed,
            battery_type_id=battery_type_id,
            cleaning_code=cleaning_code,
            functional_good_qty=functional_good_qty,
            functional_repaired_qty=functional_repaired_qty,
            non_good_qty=non_good_qty,
            non_sellable_qty=non_sellable_qty,
            evaluation_notes=line_in.evaluation_notes.strip() if line_in.evaluation_notes else None,
            technician_remarks=line_in.technician_remarks.strip()
            if line_in.technician_remarks
            else None,
            entry_by=user.id,
            battery_stock_movement_id=battery_movement_id,
            functional_transfer_id=functional_trf_id,
            non_good_transfer_id=non_good_trf_id,
            non_sellable_transfer_id=non_sellable_trf_id,
            idempotency_key=record_key,
        )

        # 4. Update batch line status and counts
        new_received = batch_line["qty_received"] + qty_receiving
        line_status = (
            "RECEIVED" if new_received == batch_line["qty_allotted"] else "PARTIALLY_RECEIVED"
        )
        repo.update_batch_line(
            session,
            line_in.batch_line_id,
            qty_received=new_received,
            status=line_status,
            evaluation_notes=line_in.evaluation_notes.strip() if line_in.evaluation_notes else None,
        )

    # 5. Update overall batch status (PARTIALLY_RECEIVED or COMPLETED)
    all_lines = repo.get_batch_lines(session, batch_id)
    if all(ln["status"] == "RECEIVED" for ln in all_lines):
        new_status = "COMPLETED"
        repo.update_batch_status(session, batch_id, status="COMPLETED", completed=True)
    else:
        new_status = "PARTIALLY_RECEIVED"
        repo.update_batch_status(session, batch_id, status="PARTIALLY_RECEIVED", completed=False)

    # P4-03: TECH_BATCH_RECEIVED (BR-23/BR-24; rule seeded inactive). Context: the custodians of
    # the received stock (functional → Intermediate Store, non-functional → Spare Parts, BR-30).
    received_qty = sum(ln.qty_receiving for ln in payload.lines)
    notifications.publish(
        session,
        "TECH_BATCH_RECEIVED",
        role_codes=["INTERMEDIATE_STORE_MANAGER", "SPARE_PARTS_MANAGER"],
        title=f"{batch['batch_no']}: {received_qty} pc(s) received from technician",
        body=f"Batch {new_status.replace('_', ' ').lower()}; recorded by {user.full_name}.",
        entity_type="technician_batch",
        entity_id=batch_id,
        data={"batch_no": str(batch["batch_no"])},
        dedupe_key=f"tech-batch-received:{idempotency_key}",
    )

    # P4-03 item 6: BATTERY_LOW_STOCK when this receiving consumed batteries below the threshold.
    for type_id, consumed in battery_consumed.items():
        battery_service.check_low_stock(session, type_id, consumed=consumed)

    return get_batch_detail(session, batch_id)


def get_battery_reconciliation(
    session: Session,
    *,
    from_date: date | None = None,
    to_date: date | None = None,
) -> BatteryReconciliationOut:
    """Accurate checked-vs-replaced reconciliation tying out with stock movements (WF r8)."""
    from_dt = datetime.combine(from_date, time.min, tzinfo=UTC) if from_date else None
    to_dt = datetime.combine(to_date, time.max, tzinfo=UTC) if to_date else None

    data = repo.get_battery_reconciliation_summary(session, from_date=from_dt, to_date=to_dt)

    installed = data["batteries_installed"]
    movements = data["battery_stock_movements"]
    diff = installed - movements
    ties_out = diff == 0

    type_rows = [
        BatteryReconciliationTypeRow(
            battery_type_id=r["battery_type_id"],
            battery_type_code=r["battery_type_code"],
            battery_type_name=r["battery_type_name"],
            batteries_installed=r["batteries_installed"],
            battery_stock_movements=r["battery_stock_movements"],
            discrepancy=r["batteries_installed"] - r["battery_stock_movements"],
            ties_out=(r["batteries_installed"] == r["battery_stock_movements"]),
        )
        for r in data["by_battery_type"]
    ]

    return BatteryReconciliationOut(
        pieces_checked=data["pieces_checked"],
        pieces_with_battery_replaced=data["pieces_battery_replaced"],
        batteries_installed=installed,
        battery_stock_movements=movements,
        discrepancy=diff,
        ties_out=ties_out,
        by_battery_type=type_rows,
    )
