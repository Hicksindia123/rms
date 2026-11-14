import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { CategorisationStateOut, ItemCategorisationDetail } from '@/features/itemization/api';

const mockState: CategorisationStateOut = {
  goods_slip: {
    id: 'gs-111',
    gs_no: 'GS/2026/001',
    status: 'CATEGORISATION',
    counted_by: 'user-aman',
    created_at: '2026-11-13T10:00:00Z',
  },
  items: [
    {
      id: 'item-1',
      line_no: 1,
      product_id: 'prod-1',
      sku_code: 'DMT-SKU-01',
      sku_name: 'DMT Product A',
      category_name: 'Domestic Appliances',
      documented_qty: 10,
      received_qty: 10,
      allowed_buckets: [
        { field_id: 'f-1', field_code: 'DMT_OK_PACKED', label: 'VISUALLY OKAY and PACKED', rank: 10 },
        { field_id: 'f-2', field_code: 'DMT_DEFECTIVE', label: 'DEFECTIVE / DAMAGED', rank: 20 },
      ],
      allowed_counts: [
        { field_id: 'fc-1', field_code: 'PACKAGING_COUNT', label: 'Packaging Box Count', rank: 10 },
      ],
      buckets: [
        { field_code: 'DMT_OK_PACKED', qty: 10 },
        { field_code: 'DMT_DEFECTIVE', qty: 0 },
      ],
      counts: [{ field_code: 'PACKAGING_COUNT', count_value: 10 }],
      total_bucket_qty: 10,
      is_conserved: true,
    },
  ],
  all_conserved: true,
  can_submit: true,
  counted_by_id: 'user-aman',
  is_counted_by_current_user: true,
};

const getCategorisationFn = vi.fn<() => Promise<CategorisationStateOut>>();
const saveItemCategorisationFn = vi.fn<(...args: unknown[]) => Promise<ItemCategorisationDetail>>();
const submitCategorisationFn = vi.fn<(...args: unknown[]) => Promise<{ gs_id: string; status: string }>>();

vi.mock('@/features/itemization/api', () => ({
  itemizationApi: {
    getCategorisation: () => getCategorisationFn(),
    saveItemCategorisation: (...args: unknown[]) => saveItemCategorisationFn(...args),
    submitCategorisation: (...args: unknown[]) => submitCategorisationFn(...args),
  },
  newIdempotencyKey: () => 'web-test-key',
}));

const { ItemCategorisationSection } = await import('@/features/itemization/ItemCategorisationSection');

describe('ItemCategorisationSection (AMD-09, G-19)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getCategorisationFn.mockResolvedValue(mockState);
  });

  it('renders item categorisation buckets and G-19 conservation meter', async () => {
    render(<ItemCategorisationSection gsId="gs-111" onDone={vi.fn()} />);

    expect(await screen.findByText(/Item Categorisation \(AMD-09\)/i)).toBeInTheDocument();
    expect(screen.getByText(/DMT Product A/i)).toBeInTheDocument();
    expect(screen.getByText(/Conserved \(10\/10\)/i)).toBeInTheDocument();
    expect(screen.getByText(/VISUALLY OKAY and PACKED/i)).toBeInTheDocument();
  });

  it('shows authorization notice when current user is not the verifier who counted', async () => {
    getCategorisationFn.mockResolvedValue({
      ...mockState,
      is_counted_by_current_user: false,
      can_submit: false,
    });

    render(<ItemCategorisationSection gsId="gs-111" onDone={vi.fn()} />);

    expect(
      await screen.findByText(/Only the inward verifier who counted this slip can submit categorisation \(AMD-08\)/i),
    ).toBeInTheDocument();

    const submitBtn = screen.getByRole('button', { name: /Submit Categorisation to RM Review/i });
    expect(submitBtn).toBeDisabled();
  });

  it('updates bucket quantity and saves line', async () => {
    saveItemCategorisationFn.mockResolvedValue({
      ...mockState.items[0]!,
      total_bucket_qty: 10,
      is_conserved: true,
    });

    render(<ItemCategorisationSection gsId="gs-111" onDone={vi.fn()} />);

    expect(await screen.findByText(/DMT Product A/i)).toBeInTheDocument();

    const saveLineBtn = screen.getByRole('button', { name: /Save Line 1/i });
    fireEvent.click(saveLineBtn);

    await waitFor(() => {
      expect(saveItemCategorisationFn).toHaveBeenCalledWith(
        'gs-111',
        'item-1',
        expect.objectContaining({
          buckets: expect.any(Array),
          counts: expect.any(Array),
        }),
      );
    });
  });

  it('submits categorisation to RM Review when all lines are conserved', async () => {
    submitCategorisationFn.mockResolvedValue({ gs_id: 'gs-111', status: 'RM_REVIEW' });
    const onDone = vi.fn();

    render(<ItemCategorisationSection gsId="gs-111" onDone={onDone} />);

    expect(await screen.findByText(/DMT Product A/i)).toBeInTheDocument();

    const submitBtn = screen.getByRole('button', { name: /Submit Categorisation to RM Review/i });
    expect(submitBtn).not.toBeDisabled();

    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(submitCategorisationFn).toHaveBeenCalledWith(
        'gs-111',
        expect.objectContaining({ category_code: 'REGULAR_RETURN' }),
        'web-test-key',
      );
      expect(onDone).toHaveBeenCalled();
    });
  });
});
