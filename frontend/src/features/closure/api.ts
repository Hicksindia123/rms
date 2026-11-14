import { apiRequest, newIdempotencyKey } from '@/lib/api/client';

/** P3-07 closure engine (G-15, BR-38, BR-39, §6.5). Mirrors backend app/modules/closure/schemas. */

export interface ChecklistItem {
  code: string;
  rule_ref: string;
  applicable: boolean;
  passed: boolean;
  explanation: string;
  details: Record<string, unknown>;
  fix: { label: string; path: string } | null;
}

export interface ClosureRecord {
  closure_type: string;
  closure_label: string | null;
  checklist_snapshot: Record<string, unknown>;
  remarks: string | null;
  close_count: number;
  closed_by_name: string | null;
  closed_at: string;
  reopened_by_name: string | null;
  reopened_at: string | null;
  reopen_reason: string | null;
  reopen_count: number;
}

export interface StageDuration {
  status: string;
  entered_at: string;
  left_at: string | null;
  duration_seconds: number;
  by_name: string | null;
}

export interface ClosureState {
  gs_id: string;
  gs_no: string;
  status: string;
  category_code: string | null;
  party_name: string | null;
  state_name: string | null;
  station_name: string | null;
  created_at: string;
  closed_at: string | null;
  expected_closure_type: string;
  expected_closure_label: string | null;
  items: ChecklistItem[];
  all_passed: boolean;
  can_close: boolean;
  can_reopen: boolean;
  closure: ClosureRecord | null;
  lifecycle: StageDuration[];
  total_duration_seconds: number;
  lines: Array<{
    line_no: number;
    product_code: string | null;
    product_name: string | null;
    received_qty: number;
  }>;
  credit_notes: Array<{
    id: string;
    cn_type_code: string;
    cn_type_label: string | null;
    voucher_no: string | null;
    voucher_date: string | null;
    total_value: string;
    issued_at: string | null;
  }>;
  dispatches: Array<{
    id: string;
    dispatch_no: string;
    dispatch_type: string;
    transporter: string;
    docket_no: string | null;
    vehicle_no: string | null;
    qty: number;
    dispatched_at: string;
  }>;
  notifications: Array<{
    id: string;
    credit_note_id: string | null;
    status_code: string;
    status_label: string | null;
    channel_code: string;
    recipient: string;
    sent_at: string;
    sent_by_name: string | null;
  }>;
}

/** 422 G-15 details: every failed checklist item. */
export interface FailedItem {
  code: string;
  rule_ref: string;
  explanation: string;
}

export function failedItemsOf(details: unknown): FailedItem[] {
  if (details && typeof details === 'object' && 'failed_items' in details) {
    const items = details.failed_items;
    if (Array.isArray(items)) return items as FailedItem[];
  }
  return [];
}

const gs = (id: string) => `/gs/${encodeURIComponent(id)}`;

export const closureApi = {
  state: (gsId: string) => apiRequest<ClosureState>(`${gs(gsId)}/closure`),
  close: (gsId: string, remarks: string | null, idempotencyKey = newIdempotencyKey()) =>
    apiRequest<ClosureState>(`${gs(gsId)}/close`, {
      method: 'POST',
      body: { remarks },
      idempotencyKey,
    }),
  reopen: (gsId: string, reason: string) =>
    apiRequest<ClosureState>(`${gs(gsId)}/reopen`, { method: 'POST', body: { reason } }),
};

/** "3d 4h", "2h 05m", "12m" — stage durations of the lifecycle summary. */
export function formatDuration(seconds: number): string {
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d > 0) return `${String(d)}d ${String(h)}h`;
  if (h > 0) return `${String(h)}h ${String(m).padStart(2, '0')}m`;
  return `${String(m)}m`;
}
