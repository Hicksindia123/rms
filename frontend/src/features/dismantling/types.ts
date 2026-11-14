export type StorageMethodCode = 'DEDICATED_CONTAINERS' | 'PARTITIONED_CONTAINER';
export type PartTypeCode = 'TIP' | 'BODY' | 'WIRE' | 'PCB';
export type DismantleBatchStatus = 'OPEN' | 'COMPLETED' | 'CANCELLED';
export type DisposalStatusCode = 'MARKED' | 'DISPOSED';

export interface DismantleQueueItem {
  lot_id: string;
  stock_item_id: string;
  product_id?: string | null;
  product_name?: string | null;
  product_sku?: string | null;
  category_id?: string | null;
  category_code?: string | null;
  category_name?: string | null;
  supports_dismantling: boolean;
  condition_class: string;
  source_condition_code?: string | null;
  routing_hint?: string | null;
  qty: number;
  gs_no?: string | null;
  requires_evaluation: boolean;
}

export interface DismantleQueueResponse {
  dismantleable_lots: DismantleQueueItem[];
  disposal_required_lots: DismantleQueueItem[];
  total_dismantleable_qty: number;
  total_disposal_required_qty: number;
}

export interface ContainerPartition {
  id: string;
  container_id: string;
  compartment_code: string;
  part_type?: string | null;
  is_active: boolean;
}

export interface StorageContainer {
  id: string;
  code: string;
  barcode: string;
  name?: string | null;
  container_type: string;
  storage_method?: string | null;
  dedicated_part_type?: string | null;
  location_id?: string | null;
  is_active: boolean;
  partitions: ContainerPartition[];
}

export interface PcbModel {
  id: string;
  name: string;
  supplier_id?: string | null;
  supplier_name?: string | null;
  is_active: boolean;
}

export interface PcbSupplier {
  id: string;
  name: string;
  is_active: boolean;
}

export interface DismantleInput {
  id: string;
  batch_id: string;
  lot_id: string;
  product_name?: string | null;
  qty: number;
  stock_movement_id?: string | null;
  created_at: string;
}

export interface RecoveredPart {
  id: string;
  batch_id: string;
  part_type: string;
  qty: number;
  pcb_model_id?: string | null;
  pcb_model_name?: string | null;
  pcb_supplier_id?: string | null;
  pcb_supplier_name?: string | null;
  container_id?: string | null;
  container_code?: string | null;
  partition_id?: string | null;
  partition_code?: string | null;
  lot_id?: string | null;
  stock_movement_id?: string | null;
  created_at: string;
}

/** DEC-11 / DEC-18: stock the Spare Parts Manager can mark as scrap (P3-08). */
export interface DisposableLot {
  lot_id: string;
  gs_no?: string | null;
  product_name?: string | null;
  condition_class: string;
  location_code: string;
  qty: number;
  hazard: boolean;
}

export interface ScrapFromLotPayload {
  lot_id: string;
  qty: number;
  weight_kg?: number | null;
  remarks?: string | null;
}

export interface ScrapRecord {
  id: string;
  batch_id?: string | null;
  batch_no?: string | null;
  lot_id?: string | null;
  qty_pieces: number;
  weight_kg?: number | null;
  hazardous: boolean;
  remarks?: string | null;
  disposal_status: DisposalStatusCode;
  manifest_ref?: string | null;
  disposed_at?: string | null;
  disposed_by?: string | null;
  disposed_by_name?: string | null;
  stock_movement_id?: string | null;
  created_at: string;
}

export interface DismantleBatchSummary {
  id: string;
  batch_no: string;
  technician_profile_id: string;
  technician_name: string;
  storage_method_code: StorageMethodCode;
  status: DismantleBatchStatus;
  total_input_qty: number;
  total_dismantled_qty: number;
  created_at: string;
  completed_at?: string | null;
}

export interface DismantleBatchDetail extends DismantleBatchSummary {
  inputs: DismantleInput[];
  recovered_parts: RecoveredPart[];
  scrap_records: ScrapRecord[];
}

export interface DismantleBatchCreatePayload {
  inputs: Array<{ lot_id: string; qty: number }>;
  storage_method_code: StorageMethodCode;
}

export interface RecoveredPartPayload {
  part_type: PartTypeCode;
  qty: number;
  pcb_model_id?: string | null;
  pcb_supplier_id?: string | null;
  container_id?: string | null;
  partition_id?: string | null;
}

export interface ScrapPayload {
  qty_pieces: number;
  weight_kg?: number | null;
  hazardous: boolean;
  remarks?: string | null;
}

export interface DismantleRecoveryPayload {
  parts: RecoveredPartPayload[];
  scrap: ScrapPayload;
  units_dismantled?: number | null;
}

export interface ScrapDisposePayload {
  manifest_ref?: string | null;
  disposed_at?: string | null;
}
