import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { ItemizationState, ItemLine, StepOption } from '@/features/itemization/api';

// Test-only API doubles: the screens render the backend's state and option texts.
const stateFn = vi.fn<() => Promise<ItemizationState>>();
const decideFn = vi.fn<(...args: unknown[]) => Promise<ItemizationState>>();
const updateItemFn = vi.fn<(...args: unknown[]) => Promise<unknown>>();
const chooseReturnFn = vi.fn<(...args: unknown[]) => Promise<unknown>>();
const lockFn = vi.fn<(...args: unknown[]) => Promise<unknown>>();
const lockedUpdateFn = vi.fn<(...args: unknown[]) => Promise<unknown>>();
vi.mock('@/features/itemization/api', () => ({
  itemizationApi: {
    state: () => stateFn(),
    products: () => Promise.resolve([]),
    categories: () => Promise.resolve([]),
    decide: (...args: unknown[]) => decideFn(...args),
    updateItem: (...args: unknown[]) => updateItemFn(...args),
    chooseReturn: (...args: unknown[]) => chooseReturnFn(...args),
    lockCategorisation: (...args: unknown[]) => lockFn(...args),
    lockedUpdateLine: (...args: unknown[]) => lockedUpdateFn(...args),
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
    // DEC-64: the popup choices (RETURN_CATEGORY, labels from configuration).
    return_choices: [
      { ...CATEGORY[1], label: 'Replacement' } as StepOption,
      CATEGORY[0] as StepOption,
    ],
    permissions: {
      can_edit_lines: true,
      can_submit_counting: true,
      can_categorize: true,
      can_decide: false,
      can_reopen: false,
      can_request_correction: false,
      can_decide_correction: false,
      can_check_packaging: false,
      can_choose_return: true,
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
  chooseReturnFn.mockReset();
  lockFn.mockReset();
  lockedUpdateFn.mockReset();
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

  it('DEC-64: the item screen records quantities only; Next opens the popup (final choice)', async () => {
    stateFn.mockResolvedValue(state());
    chooseReturnFn.mockResolvedValue({
      state: state({
        goods_slip: { ...state().goods_slip, status: 'CATEGORISATION', category_code: 'RO' },
        permissions: { ...state().permissions, can_choose_return: false },
      }),
      revision_no: null,
    });
    render(<ItemizationPage gsId="gs-1" onBack={() => undefined} />);
    // The counted line with its shortage, and the line editor with the two big steppers only.
    expect(await screen.findByText('Demo DMT Product (DEMO)')).toBeInTheDocument();
    expect(screen.getAllByText('Short 2').length).toBeGreaterThan(0);
    expect(screen.getByLabelText('As per document (optional)')).toBeInTheDocument();
    expect(screen.getByLabelText('Physically received')).toBeInTheDocument();
    expect(screen.queryByTestId('line-split-editor')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Categorise GS' })).toBeNull();
    expect(screen.queryByRole('button', { name: /^Submit to / })).toBeNull();
    expect(screen.getByLabelText('Filter by category')).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('items-next'));
    const dialog = await screen.findByRole('dialog');
    expect(dialog).toHaveTextContent('Replacement');
    expect(dialog).toHaveTextContent('Complete Sales Return');
    expect(dialog).toHaveTextContent('cannot be changed later');
    const confirm = screen.getByTestId('return-choice-confirm');
    expect(confirm).toBeDisabled();
    fireEvent.click(screen.getByLabelText('Replacement'));
    fireEvent.click(confirm);
    await waitFor(() => {
      expect(chooseReturnFn).toHaveBeenCalledWith('gs-1', 'RO', 'web-test-key');
    });
  });

  it('DEC-64: Complete Sales Return on hold shows a banner and no further actions', async () => {
    stateFn.mockResolvedValue(
      state({
        goods_slip: { ...state().goods_slip, status: 'SALES_RETURN_HOLD', category_code: 'CSR' },
        category_label: 'Complete Sales Return',
        permissions: {
          ...state().permissions,
          can_edit_lines: false,
          can_categorize: false,
          can_choose_return: false,
        },
      }),
    );
    render(<ItemizationPage gsId="gs-1" onBack={() => undefined} />);
    expect(await screen.findByTestId('sales-return-hold')).toHaveTextContent(
      'Complete Sales Return',
    );
    expect(screen.queryByTestId('items-next')).toBeNull();
    expect(screen.queryByTestId('lock-categorisation')).toBeNull();
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

  it('categorisation: a line is saved with its condition split; Save waits until split = physical qty', async () => {
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

  it('DEC-64: Lock Categorisation asks for confirmation, then locks once', async () => {
    const balanced = state({
      goods_slip: { ...state().goods_slip, status: 'CATEGORISATION', category_code: 'RO' },
      items: [firstLine({ is_balanced: true, bucket_total: 8, buckets: [] })],
      permissions: { ...state().permissions, can_choose_return: false, can_lock: true },
    });
    stateFn.mockResolvedValue(balanced);
    lockFn.mockResolvedValue({ state: balanced, revision_no: 1 });
    render(<ItemizationPage gsId="gs-1" onBack={() => undefined} />);
    const lock = await screen.findByTestId('lock-categorisation');
    expect(lock).toBeEnabled();
    expect(screen.queryByTestId('items-next')).toBeNull();
    fireEvent.click(lock);
    expect(screen.getByText(/books 8 piece\(s\) into Inward Staging/)).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('lock-confirm'));
    await waitFor(() => {
      expect(lockFn).toHaveBeenCalledWith('gs-1', null, 'web-test-key');
    });
  });

  it('DEC-64: after the lock Management edits with a reason; removed lines are marked', async () => {
    stateFn.mockResolvedValue(
      state({
        goods_slip: {
          ...state().goods_slip,
          status: 'PENDING_TRANSFER_SLIP',
          category_code: 'RO',
          categorisation_locked_at: '2026-11-20T10:00:00Z',
        },
        items: [
          firstLine({ is_balanced: true, bucket_total: 8 }),
          firstLine({
            id: 'it-2',
            line_no: 2,
            documented_qty: 0,
            received_qty: 0,
            removed_at: '2026-11-20T11:00:00Z',
            removal_reason: 'wrong party',
          }),
        ],
        permissions: {
          ...state().permissions,
          can_edit_lines: false,
          can_categorize: false,
          can_choose_return: false,
          can_edit_locked: true,
        },
      }),
    );
    render(<ItemizationPage gsId="gs-1" onBack={() => undefined} />);
    expect(await screen.findByTestId('categorisation-locked')).toHaveTextContent('Inward Staging');
    expect(screen.getByTestId('line-removed')).toHaveTextContent('Removed: wrong party');
    expect(screen.queryByRole('button', { name: /Change line 2/ })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /Change line 1/ }));
    expect(await screen.findByLabelText('Reason for the change (required)')).toBeInTheDocument();
    expect(screen.queryByLabelText('Remarks (optional)')).toBeNull();
    expect(screen.getByRole('button', { name: 'Save line' })).toBeDisabled();
  });

  it('DEC-64: an unbalanced line blocks the lock and is listed', async () => {
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
        goods_slip: { ...state().goods_slip, status: 'CATEGORISATION', category_code: 'RO' },
        permissions: { ...state().permissions, can_choose_return: false, can_lock: false },
      }),
    );
    render(<ItemizationPage gsId="gs-1" onBack={() => undefined} />);
    expect(
      await screen.findByText(/does not match the physical quantity on line.s. #1/),
    ).toBeInTheDocument();
    expect(screen.getByTestId('lock-categorisation')).toBeDisabled();
    expect(screen.getByText('Split 5 ≠ physical 8')).toBeInTheDocument();
  });
});
