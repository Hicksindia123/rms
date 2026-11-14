import type { InventoryOption, StockRow, StockView } from './types';

export type InventoryTab =
  | 'functional'
  | 'non-functional'
  | 'spare-parts'
  | 'batteries'
  | 'holds'
  | 'adjustments'
  | 'segregation';

const TABS: InventoryTab[] = [
  'functional',
  'non-functional',
  'spare-parts',
  'batteries',
  'holds',
  'adjustments',
  'segregation',
];

/** `#/inventory/<tab>` → tab (unknown segments fall back to the functional view). */
export function toInventoryTab(segment: string | undefined): InventoryTab {
  return TABS.find((t) => t === segment) ?? 'functional';
}

/** Screen names of the segregated views (navigation labels, not business values). */
export const VIEW_LABELS: Record<StockView, string> = {
  FUNCTIONAL: 'Functional Inventory',
  NON_FUNCTIONAL: 'Non-Functional',
  SPARE_PARTS: 'Spare Parts Ledger',
  BATTERIES: 'Batteries',
  REJECTED_HOLD: 'Rejected Hold',
  HAZARD_QUARANTINE: 'Hazard Quarantine',
  PENDING_HOLD: 'Pending Hold',
  IN_TRANSIT: 'In Transit',
};

export const HOLD_VIEWS: StockView[] = [
  'REJECTED_HOLD',
  'HAZARD_QUARANTINE',
  'PENDING_HOLD',
  'IN_TRANSIT',
];

/** Ledger condition classes (§8.5) each view can be filtered on. */
export const VIEW_CONDITIONS: Partial<Record<StockView, string[]>> = {
  FUNCTIONAL: ['FUNCTIONAL_GOOD', 'FUNCTIONAL_REPAIRED', 'AS_RECEIVED'],
  NON_FUNCTIONAL: ['NON_GOOD', 'NON_SELLABLE', 'NOT_ALLOWED'],
};

/** DD r63-66: only the assignment options the backend marked valid for this lot. */
export function validAssignmentOptions(
  row: Pick<StockRow, 'assignment_codes'>,
  options: InventoryOption[],
): InventoryOption[] {
  return options.filter((o) => row.assignment_codes.includes(o.code));
}

/** What the row holds: a product, a spare part or a battery type. */
export function itemTitle(
  row: Pick<
    StockRow,
    'item_kind' | 'product_name' | 'product_code' | 'part_type' | 'battery_type_name'
  >,
): string {
  if (row.item_kind === 'SPARE_PART') return `Part · ${row.part_type ?? '—'}`;
  if (row.item_kind === 'BATTERY') return `Battery · ${row.battery_type_name ?? '—'}`;
  return row.product_name ?? row.product_code ?? '—';
}

export function gsRef(row: Pick<StockRow, 'gs_no' | 'line_no'>): string {
  if (!row.gs_no) return '—';
  return row.line_no ? `${row.gs_no} · L${String(row.line_no)}` : row.gs_no;
}

/** Signed difference as shown on a count adjustment (+2 / −3). */
export function formatDelta(delta: number): string {
  return delta > 0 ? `+${String(delta)}` : `−${String(Math.abs(delta))}`;
}
