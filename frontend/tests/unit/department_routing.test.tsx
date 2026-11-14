import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { departmentRoutingApi } from '@/features/department-routing/api';
import { DepartmentReconciliationPanel } from '@/features/department-routing/DepartmentReconciliationPanel';
import { DepartmentLegsTimeline } from '@/features/department-routing/DepartmentLegsTimeline';
import { RmRoutingDispatchModal } from '@/features/department-routing/RmRoutingDispatchModal';
import type {
  GsReconciliationOut,
  DepartmentLegOut,
  DepartmentRoutingOut,
  GsRoutingState,
} from '@/features/department-routing/types';
import { ApiError } from '@/lib/api/client';

describe('Phase 6: Department Routing & Receiving with Guard G-20', () => {
  const mockReconConserved: GsReconciliationOut = {
    gs_id: 'gs-test-01',
    gs_no: 'GS/2026/042',
    is_fully_reconciled: true,
    total_counted: 10,
    total_in_store: 4,
    total_at_departments: 3,
    total_outcomes: 3,
    total_actioned: 0,
    items: [
      {
        gs_item_id: 'item-1',
        line_no: 1,
        item_name: 'Smart Mixer Grinder 750W',
        sku_code: 'SMG-750',
        counted_qty: 10,
        in_store_qty: 4,
        at_departments_qty: 3,
        outcome_heads_qty: 3,
        actioned_qty: 0,
        is_conserved: true,
      },
    ],
  };

  const mockReconBroken: GsReconciliationOut = {
    gs_id: 'gs-test-02',
    gs_no: 'GS/2026/043',
    is_fully_reconciled: false,
    total_counted: 10,
    total_in_store: 2,
    total_at_departments: 2,
    total_outcomes: 3,
    total_actioned: 0,
    items: [
      {
        gs_item_id: 'item-2',
        line_no: 1,
        item_name: 'Smart Mixer Grinder 750W',
        sku_code: 'SMG-750',
        counted_qty: 10,
        in_store_qty: 2,
        at_departments_qty: 2,
        outcome_heads_qty: 3,
        actioned_qty: 0,
        is_conserved: false, // 2 + 2 + 3 + 0 = 7 != 10 (broken)
      },
    ],
  };

  const mockLegs: DepartmentLegOut[] = [
    {
      routing_id: 'rtg-1',
      routing_no: 'DIN/2026/001',
      department_code: 'TESTING',
      department_label: 'Testing Lab',
      dispatched_at: '2026-11-13T10:00:00Z',
      dispatched_by_name: 'Aman RM',
      status: 'PARTIALLY_RECEIVED',
      qty_sent: 5,
      qty_received: 2,
      qty_pending: 3,
      lines: [
        {
          id: 'rtl-1',
          routing_id: 'rtg-1',
          gs_item_id: 'item-1',
          line_no: 1,
          item_name: 'Smart Mixer Grinder 750W',
          sku_code: 'SMG-750',
          source_bucket_field_id: 'f-1',
          source_bucket_code: 'DEFECTIVE',
          source_bucket_label: 'Defective Bucket',
          qty_sent: 5,
          qty_received: 2,
          qty_pending: 3,
          notes: 'Handle with care',
        },
      ],
      receipts: [
        {
          id: 'rcp-1',
          receipt_no: 'DRC/2026/001',
          routing_id: 'rtg-1',
          received_by: 'user-tech',
          received_by_name: 'Ravi Tester',
          received_at: '2026-11-13T11:00:00Z',
          remarks: 'First batch inspected',
          lines: [
            {
              id: 'rcl-1',
              receipt_id: 'rcp-1',
              routing_line_id: 'rtl-1',
              outcome_head_id: 'head-rep',
              outcome_code: 'REPAIRED',
              outcome_label: 'Repaired & Functional',
              is_wastage: false,
              returns_to_routing: false,
              quantity: 2,
              remarks: 'Motor coil fixed',
              created_at: '2026-11-13T11:00:00Z',
            },
          ],
        },
      ],
    },
  ];

  const mockRoutingState: GsRoutingState = {
    id: 'gs-test-01',
    gs_no: 'GS/2026/042',
    status: 'HELD_AT_INTERMEDIATE_STORE',
    party_name: 'Alpha Traders',
    created_at: '2026-11-13T09:00:00Z',
    updated_at: '2026-11-13T10:00:00Z',
    items: [
      {
        item_id: 'item-1',
        line_no: 1,
        item_name: 'Smart Mixer Grinder 750W',
        sku_code: 'SMG-750',
        product_id: 'prod-1',
        counted_qty: 10,
        in_store_qty: 4,
        at_departments_qty: 3,
        outcome_heads_qty: 3,
        actioned_qty: 0,
        allowed_departments: [
          {
            field_id: 'dept-f-1',
            code: 'TESTING',
            label: 'Testing & Repair Lab',
            sort_order: 10,
          },
          {
            field_id: 'dept-f-2',
            code: 'MERCURY',
            label: 'Mercury Extraction',
            sort_order: 20,
          },
        ],
        buckets: [
          {
            id: 'b-1',
            field_id: 'bf-1',
            field_code: 'DEFECTIVE',
            field_label: 'Defective Units',
            qty: 10,
          },
        ],
      },
    ],
  };

  it('renders Guard G-20 reconciliation panel with conserved status', () => {
    render(<DepartmentReconciliationPanel reconciliation={mockReconConserved} />);

    // Header and G-20 meter
    expect(screen.getByText(/Quantity Reconciliation Panel/i)).toBeInTheDocument();
    expect(screen.getByText(/Guard G-20 Conserved/i)).toBeInTheDocument();
    expect(screen.getByText(/100% Conserved/i)).toBeInTheDocument();

    // Summary cards
    expect(screen.getAllByText('10').length).toBeGreaterThanOrEqual(1); // Counted
    expect(screen.getAllByText('4').length).toBeGreaterThanOrEqual(1); // In Store
    expect(screen.getAllByText('3').length).toBeGreaterThanOrEqual(1); // At Depts

    // Per-item row shows conserved badge
    expect(screen.getByText('Smart Mixer Grinder 750W')).toBeInTheDocument();
    expect(screen.getAllByText(/100% Conserved/i).length).toBeGreaterThanOrEqual(1);
  });

  it('renders discrepancy warning when G-20 conservation is broken', () => {
    render(<DepartmentReconciliationPanel reconciliation={mockReconBroken} />);

    expect(screen.getByText(/G-20 Imbalance Detected/i)).toBeInTheDocument();
    expect(screen.getByText('Mismatch')).toBeInTheDocument();
  });

  it('renders department legs timeline with sent, received, and pending counts', () => {
    const handlePrint = vi.fn();
    const handleReceive = vi.fn();

    render(
      <DepartmentLegsTimeline
        legs={mockLegs}
        onPrintRoutingNote={handlePrint}
        onReceiveRouting={handleReceive}
        canReceive={true}
      />,
    );

    expect(screen.getByText('DIN/2026/001')).toBeInTheDocument();
    expect(screen.getByText(/Testing Lab/i)).toBeInTheDocument();
    expect(screen.getByText('Partially Received')).toBeInTheDocument();

    // Counts
    expect(screen.getByText(/2 \/ 5 Received/i)).toBeInTheDocument();
    expect(screen.getByText(/3 pending/i)).toBeInTheDocument();

    // Outcome head badge in receipt
    expect(screen.getAllByText('Repaired & Functional').length).toBeGreaterThanOrEqual(1);

    // Click print DIN
    const printBtn = screen.getByRole('button', { name: /Print DIN/i });
    fireEvent.click(printBtn);
    expect(handlePrint).toHaveBeenCalledWith('rtg-1');

    // Click Receive Items
    const receiveBtn = screen.getByRole('button', { name: /Receive Items/i });
    fireEvent.click(receiveBtn);
    expect(handleReceive).toHaveBeenCalledWith('rtg-1');
  });

  it('enforces store quantity cap in RmRoutingDispatchModal', () => {
    const handleClose = vi.fn();
    const handleSuccess = vi.fn();

    render(
      <RmRoutingDispatchModal
        state={mockRoutingState}
        onClose={handleClose}
        onSuccess={handleSuccess}
      />,
    );

    // Modal title & GS no
    expect(screen.getByText(/Route to Department \(Issue Note\)/i)).toBeInTheDocument();
    expect(screen.getByText(/GS\/2026\/042/i)).toBeInTheDocument();

    // Available in store is 4
    expect(screen.getByPlaceholderText(/Max 4/i)).toBeInTheDocument();

    // Allowed departments in select dropdown
    expect(screen.getByRole('combobox')).toBeInTheDocument();
    expect(screen.getByText(/Testing & Repair Lab/i)).toBeInTheDocument();
  });

  it('sends one stable Idempotency-Key per modal and shows the request id on errors (G-16)', async () => {
    const handleSuccess = vi.fn();
    const spy = vi
      .spyOn(departmentRoutingApi, 'dispatchRouting')
      .mockRejectedValueOnce(
        new ApiError(409, 'G-20', 'G-20: only 4 pcs available', null, 'req-ph6-123'),
      )
      .mockResolvedValueOnce({} as DepartmentRoutingOut);

    render(
      <RmRoutingDispatchModal
        state={mockRoutingState}
        onClose={vi.fn()}
        onSuccess={handleSuccess}
      />,
    );

    fireEvent.change(screen.getByPlaceholderText(/Max 4/i), { target: { value: '2' } });
    fireEvent.click(screen.getByRole('button', { name: /Dispatch Issue Note/i }));
    expect(await screen.findByText(/Request ID: req-ph6-123/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /Dispatch Issue Note/i }));
    await waitFor(() => {
      expect(handleSuccess).toHaveBeenCalledTimes(1);
    });

    expect(spy).toHaveBeenCalledTimes(2);
    const firstKey = spy.mock.calls[0]?.[1];
    expect(firstKey).toMatch(/^web-/);
    expect(spy.mock.calls[1]?.[1]).toBe(firstKey);
    spy.mockRestore();
  });
});
