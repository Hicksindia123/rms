"""Stage-4 Dismantling & Parts Recovery schemas (BR-26..BR-29, G-11, DEC-18, DEC-19, DEC-11)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

StorageMethodCode = Literal["DEDICATED_CONTAINERS", "PARTITIONED_CONTAINER"]
PartTypeCode = Literal["TIP", "BODY", "WIRE", "PCB"]
DismantleBatchStatus = Literal["OPEN", "COMPLETED", "CANCELLED"]
DisposalStatusCode = Literal["MARKED", "DISPOSED"]


class DismantleQueueItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    lot_id: UUID
    stock_item_id: UUID
    product_id: UUID | None = None
    product_name: str | None = None
    product_sku: str | None = None
    category_id: UUID | None = None
    category_code: str | None = None
    category_name: str | None = None
    supports_dismantling: bool
    condition_class: str
    source_condition_code: str | None = None
    routing_hint: str | None = None
    qty: int
    gs_no: str | None = None
    requires_evaluation: bool = False


class DismantleQueueResponse(BaseModel):
    dismantleable_lots: list[DismantleQueueItemOut]
    disposal_required_lots: list[DismantleQueueItemOut]
    total_dismantleable_qty: int
    total_disposal_required_qty: int


class DismantleBatchInputIn(BaseModel):
    lot_id: UUID
    qty: int = Field(gt=0, description="Quantity to dismantle from lot")


class DismantleBatchCreateIn(BaseModel):
    inputs: list[DismantleBatchInputIn] = Field(min_length=1)
    storage_method_code: StorageMethodCode


class RecoveredPartIn(BaseModel):
    part_type: PartTypeCode
    qty: int = Field(ge=0, description="Quantity recovered (0..n per DEC-19)")
    pcb_model_id: UUID | None = None
    pcb_supplier_id: UUID | None = None
    container_id: UUID | None = None
    partition_id: UUID | None = None


class ScrapIn(BaseModel):
    qty_pieces: int = Field(default=0, ge=0)
    weight_kg: float | None = Field(default=None, ge=0.0)
    hazardous: bool = False
    remarks: str | None = None


class DismantleRecoveryIn(BaseModel):
    parts: list[RecoveredPartIn] = Field(default_factory=list)
    scrap: ScrapIn = Field(default_factory=ScrapIn)
    units_dismantled: int | None = Field(
        default=None,
        ge=1,
        description="Units dismantled in this recovery action (defaults to all remaining)",
    )


class ScrapFromLotIn(BaseModel):
    """Mark quarantined hazard stock or a DEC-18 'disposal required' lot as scrap (DEC-11)."""

    lot_id: UUID
    qty: int = Field(ge=1)
    weight_kg: float | None = Field(default=None, ge=0.0)
    remarks: str | None = None


class ScrapDisposeIn(BaseModel):
    manifest_ref: str | None = None
    disposed_at: datetime | None = None


class PcbModelIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    supplier_id: UUID
    is_active: bool = True


class PcbSupplierIn(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    is_active: bool = True


class PcbModelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    supplier_id: UUID | None
    supplier_name: str | None = None
    is_active: bool


class PcbSupplierOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    is_active: bool


class ContainerPartitionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    container_id: UUID
    compartment_code: str
    part_type: str | None
    is_active: bool


class StorageContainerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    barcode: str
    name: str | None
    container_type: str
    storage_method: str | None
    dedicated_part_type: str | None
    location_id: UUID | None
    is_active: bool
    partitions: list[ContainerPartitionOut] = Field(default_factory=list)


class DismantleInputOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    batch_id: UUID
    lot_id: UUID
    product_name: str | None = None
    qty: int
    stock_movement_id: UUID | None = None
    created_at: datetime


class RecoveredPartOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    batch_id: UUID
    part_type: str
    qty: int
    pcb_model_id: UUID | None = None
    pcb_model_name: str | None = None
    pcb_supplier_id: UUID | None = None
    pcb_supplier_name: str | None = None
    container_id: UUID | None = None
    container_code: str | None = None
    partition_id: UUID | None = None
    partition_code: str | None = None
    lot_id: UUID | None = None
    stock_movement_id: UUID | None = None
    created_at: datetime


class ScrapRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    batch_id: UUID | None = None
    batch_no: str | None = None
    lot_id: UUID | None = None
    qty_pieces: int
    weight_kg: float | None = None
    hazardous: bool
    remarks: str | None = None
    disposal_status: str
    manifest_ref: str | None = None
    disposed_at: datetime | None = None
    disposed_by: UUID | None = None
    disposed_by_name: str | None = None
    stock_movement_id: UUID | None = None
    created_at: datetime


class DismantleBatchSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    batch_no: str
    technician_profile_id: UUID
    technician_name: str
    storage_method_code: str
    status: str
    total_input_qty: int
    total_dismantled_qty: int
    created_at: datetime
    completed_at: datetime | None = None


class DismantleBatchDetailOut(DismantleBatchSummaryOut):
    inputs: list[DismantleInputOut] = Field(default_factory=list)
    recovered_parts: list[RecoveredPartOut] = Field(default_factory=list)
    scrap_records: list[ScrapRecordOut] = Field(default_factory=list)
