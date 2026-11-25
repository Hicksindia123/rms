import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { departmentRoutingApi } from '@/features/department-routing/api';
import { DepartmentReconciliationPanel } from '@/features/department-routing/DepartmentReconciliationPanel';
import { DepartmentLegsTimeline } from '@/features/department-routing/DepartmentLegsTimeline';
import { RmRoutingPlanModal } from '@/features/department-routing/RmRoutingPlanModal';
import { DepartmentIssuePage } from '@/features/department-routing/DepartmentIssuePage';
import type {
  GsReconciliationOut,
  DepartmentLegOut,
  DepartmentRoutingOut,
  GsRoutingState,
  IssueQueueGroup,
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
        planned_qty: 1,
        no_work_qty: 0,
        unplanned_qty: 3,
        allowed_departments: [
          {
            field_id: 'dept-store',
            code: 'STORE',
            label: 'Store (no work)',
            sort_order: 5,
            is_no_work: true,
          },
          {
            field_id: 'dept-f-1',
            code: 'REPAIR',
            label: 'Technician / Repair',
            sort_order: 10,
            is_no_work: false,
          },
        ],
        buckets: [
          {
            id: 'b-1',
            field_id: 'bf-1',
            field_code: 'DEFECTIVE',
            field_label: 'Defective Units',
            qty: 10,
            routed_qty: 7,
            plannable_qty: 3,
          },
        ],
        // DEC-56: current split (2 pcs came back from a department as "Good").
        conditions: [
          {
            field_id: 'bf-1',
            field_code: 'DEFECTIVE',
            field_label: 'Defective Units',
            original_qty: 10,
            current_qty: 8,
            committed_qty: 5,
            free_qty: 3,
            plannable_qty: 3,
          },
          {
            field_id: 'bf-2',
            field_code: 'GOOD',
            field_label: 'Good',
            original_qty: 0,
            current_qty: 2,
            committed_qty: 2,
            free_qty: 0,
            plannable_qty: 0,
          },
        ],
      },
    ],
    plan_lines: [
      {
        id: 'pl-1',
        gs_id: 'gs-test-01',
        gs_no: 'GS/2026/042',
        gs_item_id: 'item-1',
        line_no: 1,
        item_name: 'Smart Mixer Grinder 750W',
        source_bucket_field_id: 'bf-1',
        source_bucket_label: 'Defective Units',
        department_field_id: 'dept-f-1',
        department_code: 'REPAIR',
        department_label: 'Technician / Repair',
        is_no_work: false,
        qty: 1,
        status: 'PLANNED',
        planned_at: '2026-11-18T09:00:00Z',
      },
    ],
  };

  const mockIssueGroup: IssueQueueGroup = {
    gs_id: 'gs-test-01',
    gs_no: 'GS/2026/042',
    party_name: 'Alpha Traders',
    department_field_id: 'dept-f-1',
    department_code: 'REPAIR',
    department_label: 'Technician / Repair',
    planned_since: '2026-11-18T09:00:00Z',
    total_qty: 5,
    lines: [{ ...mockPlanLine('pl-1', 2) }, { ...mockPlanLine('pl-2', 3) }],
  };

  function mockPlanLine(id: string, qty: number) {
    return {
      id,
      gs_id: 'gs-test-01',
      gs_no: 'GS/2026/042',
      gs_item_id: 'item-1',
      line_no: 1,
      item_name: 'Smart Mixer Grinder 750W',
      source_bucket_field_id: 'bf-1',
      source_bucket_label: 'Defective Units',
      department_field_id: 'dept-f-1',
      department_code: 'REPAIR',
      department_label: 'Technician / Repair',
      is_no_work: false,
      qty,
      status: 'PLANNED' as const,
      planned_at: '2026-11-18T09:00:00Z',
    };
  }

  it('renders Guard G-20 reconciliation panel with conserved status', () => {
    render(<DepartmentReconciliationPanel reconciliation={mockReconConserved} />);

    // Header and G-20 meter
    expect(screen.getByText(/Quantity Reconciliation Panel/i)).toBeInTheDocument();
    expect(screen.getByText(/^\s*Conserved\s*$/i)).toBeInTheDocument();
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

    expect(screen.getByText(/Imbalance Detected/i)).toBeInTheDocument();
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

  it('DEC-55: plan modal caps each condition at its free qty and lists the current plan', () => {
    render(
      <RmRoutingPlanModal
        state={mockRoutingState}
        canPlan={true}
        onClose={vi.fn()}
        onSuccess={vi.fn()}
      />,
    );

    expect(screen.getByText(/Plan Department Routing/i)).toBeInTheDocument();
    // existing PLANNED line is shown with its status and can be cancelled
    expect(screen.getByText('Waiting for store issue')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Cancel line/i })).toBeInTheDocument();
    // department labels come from the payload; STORE is flagged "no work"
    expect(screen.getByLabelText(/Store \(no work\)/i)).toBeInTheDocument();
    expect(screen.getByText(/no work · stays in store/i)).toBeInTheDocument();
    // DEC-56: rows come from the current split; changed conditions show the counted qty.
    expect(screen.getByText(/8 pcs now \(counted 10\)/)).toBeInTheDocument();
    expect(screen.getByText(/2 pcs now \(counted 0\)/)).toBeInTheDocument();
    expect(screen.getByText(/Fully routed \(2 pcs\)/)).toBeInTheDocument();

    const repair = screen.getByLabelText(/Technician \/ Repair/i);
    fireEvent.change(repair, { target: { value: '4' } });
    expect(screen.getByText(/More than the 3 pcs not yet planned/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Save routing plan/i })).toBeDisabled();

    fireEvent.change(repair, { target: { value: '2' } });
    expect(screen.getByRole('button', { name: /Save routing plan/i })).toBeEnabled();
  });

  it('DEC-55: plan sends one stable Idempotency-Key per modal and shows the request id (G-16)', async () => {
    const handleSuccess = vi.fn();
    const spy = vi
      .spyOn(departmentRoutingApi, 'planRouting')
      .mockRejectedValueOnce(new ApiError(409, 'G-20', 'G-20: only 3 pcs left', null, 'req-g2-123'))
      .mockResolvedValueOnce({ gs_id: 'gs-test-01', lines: [] });

    render(
      <RmRoutingPlanModal
        state={mockRoutingState}
        canPlan={true}
        onClose={vi.fn()}
        onSuccess={handleSuccess}
      />,
    );

    fireEvent.change(screen.getByLabelText(/Store \(no work\)/i), { target: { value: '1' } });
    fireEvent.change(screen.getByLabelText(/Technician \/ Repair/i), { target: { value: '2' } });
    fireEvent.click(screen.getByRole('button', { name: /Save routing plan/i }));
    expect(await screen.findByText(/Request ID: req-g2-123/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /Save routing plan/i }));
    await waitFor(() => {
      expect(handleSuccess).toHaveBeenCalledTimes(1);
    });

    expect(spy).toHaveBeenCalledTimes(2);
    const [payload, firstKey] = spy.mock.calls[0] ?? [];
    expect(firstKey).toMatch(/^web-/);
    expect(spy.mock.calls[1]?.[1]).toBe(firstKey);
    expect(payload?.lines).toEqual(
      expect.arrayContaining([
        {
          gs_item_id: 'item-1',
          source_bucket_field_id: 'bf-1',
          department_field_id: 'dept-store',
          qty: 1,
        },
        {
          gs_item_id: 'item-1',
          source_bucket_field_id: 'bf-1',
          department_field_id: 'dept-f-1',
          qty: 2,
        },
      ]),
    );
    spy.mockRestore();
  });

  it('DEC-55: Store issue page issues the selected lines and opens the DIN', async () => {
    const queueSpy = vi
      .spyOn(departmentRoutingApi, 'getIssueQueue')
      .mockResolvedValue([mockIssueGroup]);
    const issueSpy = vi
      .spyOn(departmentRoutingApi, 'issueToDepartment')
      .mockResolvedValue({ id: 'rtg-9' } as DepartmentRoutingOut);
    const onOpenPrint = vi.fn();

    render(<DepartmentIssuePage canIssue={true} onOpenGs={vi.fn()} onOpenPrint={onOpenPrint} />);

    expect(await screen.findByText(/→ Technician \/ Repair/)).toBeInTheDocument();
    const boxes = screen.getAllByRole('checkbox');
    expect(boxes).toHaveLength(2);
    fireEvent.click(boxes[1] as HTMLElement); // untick the 3-pc line
    fireEvent.click(screen.getByRole('button', { name: /Issue 2 pcs & print DIN/i }));

    await waitFor(() => {
      expect(onOpenPrint).toHaveBeenCalledWith('rtg-9');
    });
    const [payload, key] = issueSpy.mock.calls[0] ?? [];
    expect(payload).toEqual({
      gs_id: 'gs-test-01',
      department_field_id: 'dept-f-1',
      plan_line_ids: ['pl-1'],
      remarks: undefined,
    });
    expect(key).toMatch(/^web-/);
    queueSpy.mockRestore();
    issueSpy.mockRestore();
  });

  it('DEC-55: Store issue page without the approve permission shows no issue button', async () => {
    const queueSpy = vi
      .spyOn(departmentRoutingApi, 'getIssueQueue')
      .mockResolvedValue([mockIssueGroup]);

    render(<DepartmentIssuePage canIssue={false} onOpenGs={vi.fn()} onOpenPrint={vi.fn()} />);

    expect(await screen.findByText(/→ Technician \/ Repair/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /print DIN/i })).not.toBeInTheDocument();
    queueSpy.mockRestore();
  });

  it('DEC-55: Store issue page shows an empty state and a retry on errors', async () => {
    const queueSpy = vi
      .spyOn(departmentRoutingApi, 'getIssueQueue')
      .mockRejectedValueOnce(new ApiError(500, 'INTERNAL', 'Boom', null, 'req-g2-err'))
      .mockResolvedValueOnce([]);

    render(<DepartmentIssuePage canIssue={true} onOpenGs={vi.fn()} onOpenPrint={vi.fn()} />);

    expect(await screen.findByText(/Request ID: req-g2-err/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Retry/i }));
    expect(await screen.findByText(/Nothing to issue/i)).toBeInTheDocument();
    queueSpy.mockRestore();
  });
});
