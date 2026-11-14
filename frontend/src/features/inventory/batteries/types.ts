export interface BatteryType {
  id: string;
  code: string;
  name: string;
  is_active: boolean;
}

export interface BatteryBalance {
  battery_type_id: string;
  code: string;
  name: string;
  balance: number;
  total_received: number;
  total_consumed: number;
  total_adjusted: number;
}

export interface BatteryMovement {
  id: string;
  battery_type_id: string;
  battery_type_code: string;
  battery_type_name: string;
  movement_type: string;
  qty: number;
  from_location: string | null;
  to_location: string | null;
  reference_type: string | null;
  reference_id: string | null;
  created_at: string;
}

export interface BatteryReceipt {
  id: string;
  battery_type_id: string;
  battery_type_code: string;
  battery_type_name: string;
  qty: number;
  reference_no: string;
  received_by: string;
  received_by_name: string;
  received_at: string;
  notes: string | null;
}

export interface BatteryReceiptPayload {
  battery_type: string;
  qty: number;
  ref: string;
  notes?: string | undefined;
}

export interface BatteryAdjustment {
  id: string;
  battery_type_id: string;
  battery_type_code: string;
  battery_type_name: string;
  qty: number;
  reason: string;
  status: 'PENDING' | 'APPROVED' | 'REJECTED';
  requested_by: string;
  requested_by_name: string;
  requested_at: string;
  approved_by: string | null;
  approved_by_name: string | null;
  approved_at: string | null;
  approval_notes: string | null;
}

export interface BatteryAdjustmentPayload {
  battery_type: string;
  qty: number;
  reason: string;
}
