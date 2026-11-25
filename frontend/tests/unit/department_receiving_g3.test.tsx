/**
 * Gap plan G3 (DEC-56; Q7, Q8, Q17): receiving records outcome + condition after work.
 * The API client is mocked with backend-shaped payloads (department_routing/schemas.py).
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { ApiRequestOptions } from '@/lib/api/client';
import type { DepartmentRoutingOut } from '@/features/department-routing/types';

const apiRequestFn = vi.fn<(path: string, options?: ApiRequestOptions) => Promise<unknown>>();

vi.mock('@/lib/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api/client')>();
  return {
    ...actual,
    apiRequest: (path: string, options?: ApiRequestOptions) => apiRequestFn(path, options),
  };
});

const { DepartmentReceiveModal } =
  await import('@/features/department-routing/DepartmentReceiveModal');
const { ApiError } = await import('@/lib/api/client');

const HEADS = [
  {
    id: 'h-rep',
    code: 'REPAIRED',
    label: 'Repaired',
    is_wastage: false,
    returns_to_routing: false,
    sort_order: 10,
    is_active: true,
    destination_location_code: 'INTERMEDIATE_STORE',
    destination_location_name: 'Intermediate Store',
  },
  {
    id: 'h-hg',
    code: 'MERCURY_EXTRACTED',
    label: 'Mercury Extracted',
    is_wastage: false,
    returns_to_routing: false,
    sort_order: 45,
    is_active: true,
    destination_location_code: 'NON_FUNCTIONAL_STORE',
    destination_location_name: 'Non-Functional Store',
  },
];

const OPTIONS = [
  { field_id: 'c-good', code: 'GOOD', label: 'Good' },
  { field_id: 'c-broken', code: 'DMT_BROKEN_BODY', label: 'Broken Body' },
];

const ROUTING: DepartmentRoutingOut = {
  id: 'rtg-1',
  routing_no: 'DIN/2026/00001',
  gs_id: 'gs-1',
  gs_no: 'GS/2026/00001',
  department_field_id: 'dept-rep',
  department_code: 'REPAIR',
  department_label: 'Technician / Repair',
  status: 'DISPATCHED',
  dispatched_at: '2026-11-18T09:00:00Z',
  dispatched_by: null,
  dispatched_by_name: 'Sanjay',
  remarks: null,
  location_code: 'DEPT_TECHNICIAN_REPAIR',
  location_name: 'Department: Technician / Repair',
  lines: [
    {
      id: 'rl-1',
      routing_id: 'rtg-1',
      gs_item_id: 'item-1',
      line_no: 1,
      item_name: 'Digital Thermometer',
      sku_code: 'DMT-01',
      source_bucket_field_id: 'c-broken',
      source_bucket_code: 'DMT_BROKEN_BODY',
      source_bucket_label: 'Broken Body',
      qty_sent: 3,
      qty_received: 0,
      qty_pending: 3,
      notes: null,
      condition_options: OPTIONS,
    },
    {
      id: 'rl-2',
      routing_id: 'rtg-1',
      gs_item_id: 'item-2',
      line_no: 2,
      item_name: 'Unsplit Item',
      sku_code: null,
      source_bucket_field_id: null,
      source_bucket_code: null,
      source_bucket_label: null,
      qty_sent: 2,
      qty_received: 0,
      qty_pending: 2,
      notes: null,
      condition_options: [],
    },
  ],
};

function serve(receive: () => Promise<unknown>) {
  apiRequestFn.mockImplementation((path) => {
    if (path.startsWith('/department-routing/outcome-heads')) return Promise.resolve(HEADS);
    if (path.endsWith('/receive')) return receive();
    return Promise.reject(new Error(`unexpected ${path}`));
  });
}

describe('G3 / DEC-56: department receiving with the condition after work', () => {
  beforeEach(() => {
    apiRequestFn.mockReset();
  });

  it('defaults the condition to the one the pieces left in and shows the destination', async () => {
    serve(() => Promise.resolve({}));
    render(<DepartmentReceiveModal routing={ROUTING} onClose={vi.fn()} onSuccess={vi.fn()} />);

    const cond = await screen.findByLabelText('Condition after work');
    expect((cond as HTMLSelectElement).value).toBe('c-broken');
    // Only the line routed from a condition asks for one (rl-2 has no condition select).
    expect(screen.getAllByLabelText('Condition after work')).toHaveLength(1);
    expect(screen.getAllByText(/Stock goes to Intermediate Store/).length).toBe(2);

    fireEvent.change(screen.getAllByLabelText('Outcome')[0] as HTMLElement, {
      target: { value: 'h-hg' },
    });
    expect(screen.getByText(/Stock goes to Non-Functional Store/)).toBeInTheDocument();
  });

  it('splits a line into outcome / condition rows and sends condition per row (Idempotency-Key)', async () => {
    const onSuccess = vi.fn();
    serve(() => Promise.resolve({ id: 'rc-1' }));
    render(<DepartmentReceiveModal routing={ROUTING} onClose={vi.fn()} onSuccess={onSuccess} />);

    const qty = await screen.findAllByLabelText('Qty');
    fireEvent.change(qty[0] as HTMLElement, { target: { value: '2' } });
    fireEvent.change(screen.getByLabelText('Condition after work'), {
      target: { value: 'c-good' },
    });
    fireEvent.click(screen.getByRole('button', { name: /Split: add another/i }));

    const conds = screen.getAllByLabelText('Condition after work');
    expect(conds).toHaveLength(2);
    fireEvent.change(screen.getAllByLabelText('Outcome')[1] as HTMLElement, {
      target: { value: 'h-hg' },
    });

    fireEvent.click(screen.getByRole('button', { name: /Confirm receipt \(5 pcs\)/i }));
    await waitFor(() => {
      expect(onSuccess).toHaveBeenCalledTimes(1);
    });

    const call = apiRequestFn.mock.calls.find(([p]) => p.endsWith('/receive'));
    expect(call?.[0]).toBe('/department-routing/rtg-1/receive');
    const opts = call?.[1];
    expect(opts?.idempotencyKey).toMatch(/^web-/);
    const body = opts?.body as { lines: unknown[] };
    expect(body.lines).toEqual([
      {
        routing_line_id: 'rl-1',
        outcome_head_id: 'h-rep',
        quantity: 2,
        condition_field_id: 'c-good',
        remarks: undefined,
      },
      {
        routing_line_id: 'rl-1',
        outcome_head_id: 'h-hg',
        quantity: 1,
        condition_field_id: 'c-broken',
        remarks: undefined,
      },
      {
        routing_line_id: 'rl-2',
        outcome_head_id: 'h-rep',
        quantity: 2,
        condition_field_id: null,
        remarks: undefined,
      },
    ]);
  });

  it('blocks a missing condition and over-receiving; shows the request id on API errors', async () => {
    serve(() =>
      Promise.reject(
        new ApiError(422, 'CONDITION_REQUIRED', 'Record the condition', null, 'req-g3-1'),
      ),
    );
    render(<DepartmentReceiveModal routing={ROUTING} onClose={vi.fn()} onSuccess={vi.fn()} />);

    const cond = await screen.findByLabelText('Condition after work');
    fireEvent.change(cond, { target: { value: '' } });
    expect(screen.getByText(/#1: choose the condition after work/)).toBeInTheDocument();
    const submit = screen.getByRole('button', { name: /Confirm receipt/i });
    expect(submit).toBeDisabled();

    fireEvent.change(cond, { target: { value: 'c-good' } });
    fireEvent.change(screen.getAllByLabelText('Qty')[0] as HTMLElement, {
      target: { value: '4' },
    });
    expect(screen.getByText(/#1: more than the 3 pcs pending/)).toBeInTheDocument();
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getAllByLabelText('Qty')[0] as HTMLElement, {
      target: { value: '3' },
    });
    fireEvent.click(submit);
    expect(await screen.findByText(/Request ID: req-g3-1/)).toBeInTheDocument();
  });
});
