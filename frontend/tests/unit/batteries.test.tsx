import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { batteryApi } from '@/features/inventory/batteries/api';
import { servicingApi } from '@/features/servicing/api';
import { BatteryStockPage } from '@/features/inventory/batteries/BatteryStockPage';
import type {
  BatteryAdjustment,
  BatteryBalance,
  BatteryMovement,
  BatteryType,
} from '@/features/inventory/batteries/types';
import type { BatteryReconciliation } from '@/features/servicing/types';

vi.mock('@/features/inventory/batteries/api');
vi.mock('@/features/servicing/api');

const mockTypes: BatteryType[] = [
  { id: 'bt-1', code: 'LR44', name: 'Button Cell LR44', is_active: true },
  { id: 'bt-2', code: 'AAA', name: 'AAA 1.5V Alkaline', is_active: true },
];

const mockBalances: BatteryBalance[] = [
  {
    battery_type_id: 'bt-1',
    code: 'LR44',
    name: 'Button Cell LR44',
    balance: 50,
    total_received: 100,
    total_consumed: 50,
    total_adjusted: 0,
  },
];

const mockMovements: BatteryMovement[] = [
  {
    id: 'mov-1',
    battery_type_id: 'bt-1',
    battery_type_code: 'LR44',
    battery_type_name: 'Button Cell LR44',
    movement_type: 'CONSUME',
    qty: 4,
    from_location: 'BATTERY_STORE',
    to_location: null,
    reference_type: 'TECHNICIAN_RECEIVING',
    reference_id: 'batch-1',
    created_at: '2026-11-04T11:00:00Z',
  },
];

const mockAdjustments: BatteryAdjustment[] = [
  {
    id: 'adj-1',
    battery_type_id: 'bt-1',
    battery_type_code: 'LR44',
    battery_type_name: 'Button Cell LR44',
    qty: 10,
    reason: 'Count variance',
    status: 'PENDING',
    requested_by: 'spm-1',
    requested_by_name: 'SPM User',
    requested_at: '2026-11-04T09:00:00Z',
    approved_by: null,
    approved_by_name: null,
    approved_at: null,
    approval_notes: null,
  },
];

const mockReconciliation: BatteryReconciliation = {
  pieces_checked: 20,
  pieces_with_battery_replaced: 12,
  batteries_installed: 12,
  battery_stock_movements: 12,
  discrepancy: 0,
  ties_out: true,
  by_battery_type: [
    {
      battery_type_id: 'bt-1',
      battery_type_code: 'LR44',
      battery_type_name: 'Button Cell LR44',
      batteries_installed: 12,
      battery_stock_movements: 12,
      discrepancy: 0,
      ties_out: true,
    },
  ],
};

describe('BatteryStockPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(batteryApi.getBalances).mockResolvedValue(mockBalances);
    vi.mocked(batteryApi.getTypes).mockResolvedValue(mockTypes);
    vi.mocked(batteryApi.getMovements).mockResolvedValue(mockMovements);
    vi.mocked(batteryApi.listAdjustments).mockResolvedValue(mockAdjustments);
    vi.mocked(servicingApi.getBatteryReconciliation).mockResolvedValue(mockReconciliation);
  });

  it('renders balances and reconciliation report banner', async () => {
    render(<BatteryStockPage canManage={true} canApprove={true} />);

    expect(screen.getByText('Battery Stock & Ledger')).toBeDefined();

    await waitFor(() => {
      expect(screen.getByText('LR44')).toBeDefined();
      expect(screen.getByText('50 pcs')).toBeDefined();
    });

    // Switch to Reconciliation tab
    const reconTab = screen.getByRole('button', { name: /reconciliation report/i });
    fireEvent.click(reconTab);

    await waitFor(() => {
      expect(screen.getByText(/Report Ties Out Perfectly/i)).toBeDefined();
      expect(screen.getAllByText(/12\s*pcs/).length).toBeGreaterThan(0);
    });
  });

  it('allows approving pending battery adjustments', async () => {
    const [adj0] = mockAdjustments;
    if (!adj0) throw new Error('Missing mock adjustment');
    vi.mocked(batteryApi.approveAdjustment).mockResolvedValue({
      ...adj0,
      status: 'APPROVED',
    });

    render(<BatteryStockPage canManage={true} canApprove={true} />);

    // Switch to Adjustments tab
    const adjTab = screen.getByRole('button', { name: /adjustments/i });
    fireEvent.click(adjTab);

    await waitFor(() => {
      expect(screen.getByText('Count variance')).toBeDefined();
      expect(screen.getByText('PENDING')).toBeDefined();
    });

    const approveBtn = screen.getByRole('button', { name: /approve/i });
    fireEvent.click(approveBtn);

    await waitFor(() => {
      expect(batteryApi.approveAdjustment).toHaveBeenCalledWith(
        'adj-1',
        expect.any(String),
        expect.any(String),
      );
    });
  });
});
