import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { servicingApi } from '@/features/servicing/api';
import { batteryApi } from '@/features/inventory/batteries/api';
import { TechnicianBoardPage } from '@/features/servicing/TechnicianBoardPage';
import { AllotBatchPage } from '@/features/servicing/AllotBatchPage';
import { ReceiveBatchPage } from '@/features/servicing/ReceiveBatchPage';
import type {
  BatchDetail,
  BatchSummary,
  IntermediateLot,
  Technician,
} from '@/features/servicing/types';
import type { BatteryType } from '@/features/inventory/batteries/types';

vi.mock('@/features/servicing/api');
vi.mock('@/features/inventory/batteries/api');

const mockTechnicians: Technician[] = [{ id: 'tech-1', display_name: 'Raj Kumar Ji' }];

const mockLots: IntermediateLot[] = [
  {
    lot_id: 'lot-1',
    stock_item_id: 'item-1',
    gs_id: 'gs-1',
    gs_no: 'GS/2026-27/00001',
    product_id: 'prod-1',
    product_name: 'Digital Thermometer DMT',
    product_code: 'DMT-01',
    category_code: 'THERMOMETER',
    supports_battery: true,
    condition_class: 'FUNCTIONAL_REPAIRED',
    source_condition_code: 'DMT_DIRTY',
    routing_hint: 'TO_TECHNICIAN',
    requires_evaluation: false,
    available_qty: 10,
  },
];

const mockBatches: BatchSummary[] = [
  {
    id: 'batch-1',
    batch_no: 'TB/2026-27/00001',
    technician_name: 'Raj Kumar Ji',
    entry_by_name: 'Aman',
    status: 'ALLOTTED',
    age_days: 1,
    allotted_at: '2026-11-04T10:00:00Z',
    total_qty_allotted: 6,
    total_qty_received: 0,
    line_count: 1,
  },
];

const mockBatchDetail: BatchDetail = {
  id: 'batch-1',
  batch_no: 'TB/2026-27/00001',
  technician_id: 'tech-1',
  technician_name: 'Raj Kumar Ji',
  entry_by: 'user-aman',
  entry_by_name: 'Aman',
  status: 'ALLOTTED',
  transfer_id: 'trf-1',
  allotted_at: '2026-11-04T10:00:00Z',
  completed_at: null,
  notes: 'Priority servicing',
  total_qty_allotted: 6,
  total_qty_received: 0,
  lines: [
    {
      id: 'line-1',
      batch_id: 'batch-1',
      lot_id: 'lot-1',
      product_name: 'Digital Thermometer DMT',
      product_code: 'DMT-01',
      category_code: 'THERMOMETER',
      supports_battery: true,
      source_condition_code: 'DMT_DIRTY',
      routing_hint: 'TO_TECHNICIAN',
      requires_evaluation: false,
      evaluation_notes: null,
      qty_allotted: 6,
      qty_received: 0,
      status: 'PENDING',
    },
  ],
  receiving_records: [],
};

const mockBatteryTypes: BatteryType[] = [
  { id: 'bt-1', code: 'LR44', name: 'Button Cell LR44', is_active: true },
  { id: 'bt-2', code: 'AAA', name: 'AAA 1.5V Alkaline', is_active: true },
];

describe('TechnicianBoardPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(servicingApi.listBatches).mockResolvedValue(mockBatches);
  });

  it('renders technician servicing board and lists batches', async () => {
    const onAllot = vi.fn();
    const onReceive = vi.fn();

    render(<TechnicianBoardPage canAllot={true} onAllot={onAllot} onReceive={onReceive} />);

    expect(screen.getByText('Technician Servicing Board')).toBeDefined();
    await waitFor(() => {
      expect(screen.getByText('TB/2026-27/00001')).toBeDefined();
      expect(screen.getByText('Raj Kumar Ji')).toBeDefined();
    });

    const receiveBtn = screen.getByRole('button', { name: /receive/i });
    fireEvent.click(receiveBtn);
    expect(onReceive).toHaveBeenCalledWith('batch-1');
  });
});

describe('AllotBatchPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(servicingApi.getIntermediateLots).mockResolvedValue(mockLots);
    vi.mocked(servicingApi.getTechnicians).mockResolvedValue(mockTechnicians);
    vi.mocked(servicingApi.allotBatch).mockResolvedValue(mockBatchDetail);
  });

  it('allows selecting lots, stepping quantity, and allotting batch', async () => {
    const onBack = vi.fn();
    const onCreated = vi.fn();

    render(<AllotBatchPage currentUserName="Aman" onBack={onBack} onCreated={onCreated} />);

    await waitFor(() => {
      expect(screen.getByText('Digital Thermometer DMT (DMT-01)')).toBeDefined();
    });

    // Toggle lot selection checkbox
    const checkbox = screen.getByRole('checkbox');
    fireEvent.click(checkbox);

    // Click Allot button
    const submitBtn = screen.getByRole('button', { name: /allot 10 pieces/i });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(servicingApi.allotBatch).toHaveBeenCalledWith(
        expect.objectContaining({
          technician_id: 'tech-1',
          lines: [{ lot_id: 'lot-1', qty: 10 }],
        }),
        expect.any(String),
      );
      expect(onCreated).toHaveBeenCalledWith('batch-1');
    });
  });
});

describe('ReceiveBatchPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(servicingApi.getBatch).mockResolvedValue(mockBatchDetail);
    vi.mocked(batteryApi.getTypes).mockResolvedValue(mockBatteryTypes);
    const [line0] = mockBatchDetail.lines;
    if (!line0) throw new Error('Missing mock line');
    vi.mocked(servicingApi.receiveBatch).mockResolvedValue({
      ...mockBatchDetail,
      status: 'COMPLETED',
      total_qty_received: 6,
      lines: [{ ...line0, qty_received: 6, status: 'RECEIVED' }],
    });
  });

  it('enforces G-10 and DEC-17 on receiving', async () => {
    const onBack = vi.fn();
    const onCompleted = vi.fn();

    render(<ReceiveBatchPage batchId="batch-1" onBack={onBack} onCompleted={onCompleted} />);

    await waitFor(() => {
      expect(screen.getByText('Receive Batch: TB/2026-27/00001')).toBeDefined();
      expect(screen.getByText('Battery Check & Replacement (G-10)')).toBeDefined();
    });

    // Selecting PERMANENT_SCRATCHES forces NON_SELLABLE
    const permRadio = screen.getByLabelText(/permanent scratches/i);
    fireEvent.click(permRadio);

    // Live reconciliation meter should still match (allocated 6 / receiving 6)
    expect(screen.getByText(/Allocated: 6 \/ Receiving: 6/i)).toBeDefined();

    // Confirm Receiving
    const confirmBtn = screen.getByRole('button', { name: /confirm receiving/i });
    fireEvent.click(confirmBtn);

    await waitFor(() => {
      const calls = vi.mocked(servicingApi.receiveBatch).mock.calls;
      expect(calls).toHaveLength(1);
      const call = calls[0];
      expect(call?.[0]).toBe('batch-1');
      expect(call?.[1].lines[0]?.cleaning_code).toBe('PERMANENT_SCRATCHES');
      expect(call?.[1].lines[0]?.allocations.NON_SELLABLE).toBe(6);
      expect(onCompleted).toHaveBeenCalled();
    });
  });
});
