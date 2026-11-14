import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { inventoryApi } from '@/features/inventory/api';
import { CustodyAssignModal } from '@/features/inventory/CustodyAssignModal';
import {
  formatDelta,
  gsRef,
  itemTitle,
  toInventoryTab,
  validAssignmentOptions,
} from '@/features/inventory/rules';
import type { Assignment, InventoryOption, StockRow } from '@/features/inventory/types';

vi.mock('@/features/inventory/api');

// Labels / next-action texts arrive from the published S5_SEGREGATE form (DD r63-66).
const OPTIONS: InventoryOption[] = [
  { code: 'CUST_FUNCTIONAL_GOOD', label: 'Good option', description: 'Good next action' },
  { code: 'CUST_FUNCTIONAL_REPAIRED', label: 'Repaired option', description: 'Repaired next' },
  { code: 'CUST_NON_FUNCTIONAL', label: 'Non-functional option', description: 'SPM' },
  { code: 'CUST_SALVAGED_PARTS', label: 'Parts option', description: 'Ledger' },
];

function row(overrides: Partial<StockRow> = {}): StockRow {
  return {
    lot_id: 'lot-1',
    location_id: 'loc-1',
    location_code: 'TECHNICIAN_BENCH',
    location_name: 'Technician Bench',
    location_class: 'TECHNICIAN',
    qty: 4,
    condition_class: 'NON_SELLABLE',
    source_condition_code: null,
    is_pending: false,
    item_kind: 'FINISHED_GOOD',
    gs_id: 'gs-1',
    gs_no: 'GS/2026-27/00001',
    line_no: 2,
    product_id: 'p-1',
    product_code: 'DMT-01',
    product_name: 'Digital thermometer',
    category_code: 'DMT',
    part_type: null,
    pcb_model_name: null,
    pcb_supplier_name: null,
    battery_type_code: null,
    battery_type_name: null,
    container_code: null,
    partition_code: null,
    received_at: '2026-11-01T10:00:00Z',
    age_days: 3,
    transfer_id: null,
    transfer_no: null,
    transfer_to_name: null,
    next_action_code: 'CUST_NON_FUNCTIONAL',
    next_action_text: 'SPM',
    assignment_codes: ['CUST_NON_FUNCTIONAL'],
    ...overrides,
  };
}

describe('inventory rules', () => {
  it('offers only the assignment options valid for the lot', () => {
    expect(validAssignmentOptions(row(), OPTIONS).map((o) => o.code)).toEqual([
      'CUST_NON_FUNCTIONAL',
    ]);
    expect(validAssignmentOptions(row({ assignment_codes: [] }), OPTIONS)).toEqual([]);
  });

  it('describes products, parts and batteries', () => {
    expect(itemTitle(row())).toBe('Digital thermometer');
    expect(itemTitle(row({ item_kind: 'SPARE_PART', part_type: 'PCB' }))).toBe('Part · PCB');
    expect(itemTitle(row({ item_kind: 'BATTERY', battery_type_name: 'LR44' }))).toBe(
      'Battery · LR44',
    );
    expect(gsRef(row())).toBe('GS/2026-27/00001 · L2');
    expect(gsRef(row({ gs_no: null }))).toBe('—');
  });

  it('maps route segments and deltas', () => {
    expect(toInventoryTab('spare-parts')).toBe('spare-parts');
    expect(toInventoryTab('nope')).toBe('functional');
    expect(toInventoryTab(undefined)).toBe('functional');
    expect(formatDelta(2)).toBe('+2');
    expect(formatDelta(-3)).toBe('−3');
  });
});

describe('CustodyAssignModal', () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it('shows only valid options and starts the transfer with one idempotency key', async () => {
    const result: Assignment = {
      id: 'a-1',
      lot_id: 'lot-1',
      qty: 4,
      assignment_code: 'CUST_NON_FUNCTIONAL',
      assignment_label: 'Non-functional option',
      condition_class: 'NON_SELLABLE',
      from_location_code: 'TECHNICIAN_BENCH',
      to_location_code: 'NON_FUNCTIONAL_STORE',
      to_location_name: 'Non-Functional Store',
      outcome: 'TRANSFER_INITIATED',
      transfer_id: 't-1',
      transfer_no: 'TRF/2026-27/00009',
      notes: null,
      created_by_name: 'Admin',
      created_at: '2026-11-04T10:00:00Z',
    };
    vi.mocked(inventoryApi.assign).mockResolvedValue(result);
    const onDone = vi.fn();
    const onOpenTransfer = vi.fn();
    render(
      <CustodyAssignModal
        row={row()}
        options={OPTIONS}
        onClose={vi.fn()}
        onDone={onDone}
        onOpenTransfer={onOpenTransfer}
      />,
    );

    expect(screen.getByText('Non-functional option')).toBeInTheDocument();
    expect(screen.queryByText('Good option')).not.toBeInTheDocument();
    expect(screen.queryByText('Parts option')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Assign' }));
    await waitFor(() => {
      expect(onDone).toHaveBeenCalled();
    });
    const [body, key] = vi.mocked(inventoryApi.assign).mock.calls[0] ?? [];
    expect(body).toMatchObject({
      lot_id: 'lot-1',
      qty: 4,
      assignment_code: 'CUST_NON_FUNCTIONAL',
      from_location_id: 'loc-1',
    });
    expect(typeof key).toBe('string');
    expect(screen.getByRole('status')).toHaveTextContent('TRF/2026-27/00009');
    fireEvent.click(screen.getByRole('button', { name: 'Open transfer' }));
    expect(onOpenTransfer).toHaveBeenCalledWith('t-1');
  });

  it('blocks a quantity above the lot balance', () => {
    render(
      <CustodyAssignModal
        row={row({ qty: 2 })}
        options={OPTIONS}
        onClose={vi.fn()}
        onDone={vi.fn()}
        onOpenTransfer={vi.fn()}
      />,
    );
    fireEvent.change(screen.getByLabelText('Quantity (max 2)'), { target: { value: '3' } });
    expect(screen.getByRole('button', { name: 'Assign' })).toBeDisabled();
  });
});
