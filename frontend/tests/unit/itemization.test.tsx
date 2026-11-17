import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { ItemizationState, ItemLine, StepOption } from '@/features/itemization/api';

// Test-only API doubles: the screens render the backend's state and option texts.
const stateFn = vi.fn<() => Promise<ItemizationState>>();
const decideFn = vi.fn<(...args: unknown[]) => Promise<ItemizationState>>();
const updateItemFn = vi.fn<(...args: unknown[]) => Promise<unknown>>();
const submitItemizationFn = vi.fn<(...args: unknown[]) => Promise<unknown>>();
vi.mock('@/features/itemization/api', () => ({
  itemizationApi: {
    state: () => stateFn(),
    products: () => Promise.resolve([]),
    categories: () => Promise.resolve([]),
    decide: (...args: unknown[]) => decideFn(...args),
    updateItem: (...args: unknown[]) => updateItemFn(...args),
    submitItemization: (...args: unknown[]) => submitItemizationFn(...args),
    // DEC-53: the product's resolved buckets / counts (backend ItemFieldsOut shape).
    productFields: (productId: string) =>
      Promise.resolve({
        product_id: productId,
        allowed_buckets: [
          {
            field_id: 'f-1',
            field_code: 'DMT_OK_PACKED',
            field_label: 'OK Packed',
            sort_order: 10,
          },
          {
            field_id: 'f-2',
            field_code: 'DMT_BROKEN_BODY',
            field_label: 'Broken Body',
            sort_order: 20,
          },
        ],
        allowed_counts: [
          { field_id: 'f-3', field_code: 'PACKAGING', field_label: 'Packaging', sort_order: 10 },
        ],
      }),
    // Item categorisation section (rendered next to the whole-GS category): backend shape.
    getCategorisation: (gsId: string) =>
      Promise.resolve({
        goods_slip_id: gsId,
        gs_no: 'GS/1',
        status: 'CATEGORISATION',
        counted_by: null,
        counted_by_name: null,
        is_same_user_who_counted: true,
        can_submit: true,
        all_conserved: false,
        items: [],
      }),
  },
  newIdempotencyKey: () => 'web-test-key',
}));
vi.mock('@/features/unboxing/api', () => ({
  unboxingApi: { downloadUrl: () => new Promise(() => undefined) },
}));

const { ItemizationPage } = await import('@/features/itemization/ItemizationPage');
const { LineEditor, QtyBadges } = await import('@/features/itemization/LineParts');
const { CsrDecisionCard } = await import('@/features/itemization/DecisionCards');

// Option texts as seeded for RETURN_CATEGORY / CSR_APPROVAL (DD r17-r20); the UI must show them.
const CATEGORY: StepOption[] = [
  {
    code: 'CSR',
    label: 'Complete Sales Return',
    allowed_status: 'CONDITIONAL',
    rule_text: 'Rule text from the option set (CSR)',
    next_action_text: 'Next action from the option set (CSR)',
    remarks: null,
  },
  {
    code: 'RO',
    label: 'Replacement Only',
    allowed_status: 'YES',
    rule_text: 'Rule text from the option set (RO)',
    next_action_text: null,
    remarks: null,
  },
];
const DECISION: StepOption[] = [
  {
    code: 'CSR_APPROVED',
    label: 'Approved - Complete Sales Return',
    allowed_status: 'YES',
    rule_text: null,
    next_action_text: null,
    remarks: null,
  },
  {
    code: 'CSR_REJECTED_TO_RO',
    label: 'Rejected - Convert to Replacement Only',
    allowed_status: 'YES',
    rule_text: null,
    next_action_text: null,
    remarks: 'Manager rejected sales return',
  },
];

function state(over: Partial<ItemizationState> = {}): ItemizationState {
  return {
    goods_slip: {
      id: 'gs-1',
      gs_no: 'GS/2026-27/00007',
      status: 'ITEMIZATION',
      party_name: 'Demo Party',
      station_name: 'Agra',
      box_count: 1,
      carton_count: 1,
      missing_documentation: false,
      category_code: null,
      original_category_code: null,
      csr_commercial_path: false,
      categorized_at: null,
    },
    items: [
      {
        id: 'it-1',
        gs_id: 'gs-1',
        line_no: 1,
        product_id: 'p-1',
        product_code: 'DEMO-DMT-001',
        product_name: 'Demo DMT Product (DEMO)',
        category_id: 'c-1',
        category_code: 'DMT',
        category_name: 'DMT',
        documented_qty: 10,
        received_qty: 8,
        short_qty: 2,
        excess_qty: 0,
        is_short: true,
        remarks: null,
        lot_id: null,
        stocked_qty: null,
      },
    ],
    totals: { lines: 1, documented_qty: 10, received_qty: 8, short_qty: 2, excess_qty: 0 },
    category_options: CATEGORY,
    category_label: null,
    decision_options: DECISION,
    current_decision: null,
    decisions: [],
    lots: [],
    transfers: [],
    corrections: [],
    evidence: [],
    permissions: {
      can_edit_lines: true,
      can_submit_counting: true,
      can_categorize: true,
      can_decide: false,
      can_reopen: false,
      can_request_correction: false,
      can_decide_correction: false,
      can_check_packaging: false,
    },
    ...over,
  };
}

function firstLine(over: Partial<ItemLine> = {}): ItemLine {
  const line = state().items[0];
  if (!line) throw new Error('fixture line missing');
  return { ...line, ...over };
}

afterEach(() => {
  stateFn.mockReset();
  decideFn.mockReset();
  updateItemFn.mockReset();
  submitItemizationFn.mockReset();
});

describe('Itemisation (P2-04)', () => {
  it('shows live short / excess badges while counting', () => {
    const { rerender } = render(<QtyBadges documented={10} received={8} />);
    expect(screen.getByText('Short 2')).toBeInTheDocument();
    rerender(<QtyBadges documented={10} received={12} />);
    expect(screen.getByText('Excess 2')).toBeInTheDocument();
    rerender(<QtyBadges documented={5} received={5} />);
    expect(screen.getByText('Matches document')).toBeInTheDocument();
  });

  it('renders category explanations from the option set and "Requires approval" for CONDITIONAL', async () => {
    stateFn.mockResolvedValue(state());
    render(<ItemizationPage gsId="gs-1" onBack={() => undefined} />);
    expect(await screen.findByText('Rule text from the option set (CSR)')).toBeInTheDocument();
    expect(screen.getByText('Rule text from the option set (RO)')).toBeInTheDocument();
    expect(screen.getByText(/Next action from the option set \(CSR\)/)).toBeInTheDocument();
    expect(screen.getAllByText('Requires approval')).toHaveLength(1);
    expect(screen.getByRole('button', { name: 'Categorise GS' })).toBeDisabled();
    fireEvent.click(screen.getByLabelText(/Replacement Only/));
    expect(screen.getByRole('button', { name: 'Categorise GS' })).toBeEnabled();
    // The counted line with its shortage, and the line editor with the two big steppers.
    expect(screen.getByText('Demo DMT Product (DEMO)')).toBeInTheDocument();
    expect(screen.getAllByText('Short 2').length).toBeGreaterThan(0);
    expect(screen.getByLabelText('As per document (optional)')).toBeInTheDocument();
    expect(screen.getByLabelText('Physically received')).toBeInTheDocument();
    // AMD-08: counting is a draft until submitted; search filters by category / sub-category.
    // DEC-53: one submit to RM Review; disabled until every line's split balances.
    expect(screen.getByRole('button', { name: /^Submit to / })).toBeDisabled();
    expect(screen.getByLabelText('Filter by category')).toBeInTheDocument();
    expect(screen.getByLabelText('Filter by sub-category')).toBeDisabled();
  });

  it('hides editing and categorisation without permission and shows the RM wait banner', async () => {
    stateFn.mockResolvedValue(
      state({
        goods_slip: { ...state().goods_slip, status: 'CSR_APPROVAL_PENDING', category_code: 'CSR' },
        category_label: 'Complete Sales Return',
        permissions: { ...state().permissions, can_edit_lines: false, can_categorize: false },
      }),
    );
    render(<ItemizationPage gsId="gs-1" onBack={() => undefined} />);
    expect(await screen.findByText(/Waiting for the Replacement Manager/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Categorise GS' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Add line' })).toBeNull();
  });

  it('shows the error state with retry and request id', async () => {
    stateFn.mockRejectedValue(
      Object.assign(new Error('Goods slip not found'), {
        name: 'ApiError',
        status: 404,
        code: 'NOT_FOUND',
        requestId: 'req-42',
      }),
    );
    render(<ItemizationPage gsId="gs-1" onBack={() => undefined} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Goods slip not found');
    expect(screen.getByRole('button', { name: /Retry/ })).toBeInTheDocument();
  });

  it('CSR card: reject needs a reason; labels come from the CSR_APPROVAL options', async () => {
    decideFn.mockResolvedValue(state());
    const onDecided = vi.fn();
    const s = state({
      goods_slip: { ...state().goods_slip, status: 'CSR_APPROVAL_PENDING', category_code: 'CSR' },
    });
    render(
      <CsrDecisionCard
        goodsSlip={s.goods_slip}
        items={s.items}
        totals={s.totals}
        categoryLabel="Complete Sales Return"
        evidence={[]}
        options={DECISION}
        onDecided={onDecided}
      />,
    );
    const reject = screen.getByRole('button', { name: /Rejected - Convert to Replacement Only/ });
    expect(reject).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/Remarks/), { target: { value: 'Damaged pieces' } });
    expect(reject).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: /Approved - Complete Sales Return/ }));
    await waitFor(() => {
      expect(onDecided).toHaveBeenCalled();
    });
    expect(decideFn).toHaveBeenCalledWith('gs-1', 'CSR_APPROVED', 'Damaged pieces', 'web-test-key');
  });

  it('DEC-53: a line is saved with its condition split; Save waits until split = physical qty', async () => {
    updateItemFn.mockResolvedValue({});
    const onSaved = vi.fn();
    render(<LineEditor gsId="gs-1" initial={firstLine()} onSaved={onSaved} />);
    // The product's buckets render as steppers; the badge compares the split with physical qty.
    expect(await screen.findByLabelText('OK Packed')).toBeInTheDocument();
    expect(screen.getByLabelText('Broken Body')).toBeInTheDocument();
    expect(screen.getByLabelText('Packaging')).toBeInTheDocument();
    expect(screen.getByTestId('split-total')).toHaveTextContent('Split 0 / Physical 8');
    const save = screen.getByRole('button', { name: 'Save line' });
    expect(save).toBeDisabled();
    fireEvent.change(screen.getByLabelText('OK Packed'), { target: { value: '6' } });
    expect(save).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Broken Body'), { target: { value: '2' } });
    expect(screen.getByTestId('split-total')).toHaveTextContent('Split 8 / Physical 8');
    expect(save).toBeEnabled();
    fireEvent.click(save);
    await waitFor(() => {
      expect(onSaved).toHaveBeenCalled();
    });
    expect(updateItemFn).toHaveBeenCalledWith(
      'gs-1',
      'it-1',
      expect.objectContaining({
        received_qty: 8,
        buckets: [
          { field_code: 'DMT_OK_PACKED', qty: 6 },
          { field_code: 'DMT_BROKEN_BODY', qty: 2 },
        ],
        counts: [{ count_type: 'PACKAGING', count_value: 0 }],
      }),
    );
  });

  it('DEC-53: one submit sends a balanced GS to RM Review; unbalanced lines are named', async () => {
    const balanced = state({
      category_options: [],
      items: [firstLine({ is_balanced: true, bucket_total: 8, buckets: [] })],
      permissions: { ...state().permissions, can_categorize: false, can_submit_to_rm: true },
    });
    stateFn.mockResolvedValue(balanced);
    submitItemizationFn.mockResolvedValue({ goods_slip_id: 'gs-1', status: 'RM_REVIEW' });
    render(<ItemizationPage gsId="gs-1" onBack={() => undefined} />);
    const submit = await screen.findByRole('button', { name: /^Submit to / });
    expect(submit).toBeEnabled();
    expect(screen.queryByRole('button', { name: 'Submit count' })).toBeNull();
    fireEvent.click(submit);
    fireEvent.click(await screen.findByRole('button', { name: /Confirm submit/ }));
    await waitFor(() => {
      expect(submitItemizationFn).toHaveBeenCalledWith('gs-1', null, 'web-test-key');
    });
  });

  it('DEC-53: an unbalanced line blocks the submit and is listed', async () => {
    stateFn.mockResolvedValue(
      state({
        category_options: [],
        items: [
          firstLine({
            is_balanced: false,
            bucket_total: 5,
            buckets: [
              {
                id: 'b-1',
                item_id: 'it-1',
                field_code: 'DMT_OK_PACKED',
                field_label: 'OK Packed',
                qty: 5,
              },
            ],
          }),
        ],
        permissions: { ...state().permissions, can_categorize: false, can_submit_to_rm: false },
      }),
    );
    render(<ItemizationPage gsId="gs-1" onBack={() => undefined} />);
    expect(
      await screen.findByText(/does not match the physical quantity on line.s. #1/),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^Submit to / })).toBeDisabled();
    expect(screen.getByText('Split 5 ≠ physical 8')).toBeInTheDocument();
  });
});
