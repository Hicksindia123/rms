import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { ApiRequestOptions } from '@/lib/api/client';

/**
 * ItemCategorisationSection (AMD-09 buckets, AMD-11 counts, G-19).
 *
 * Only the HTTP layer (apiRequest) is mocked: the payloads below have the exact shape of the
 * backend's CategorisationStateOut, so the real itemizationApi + its runtime contract validation
 * run. (The previous test mocked the whole API module with an invented shape, which is how the
 * production `allowed_counts is not iterable` crash went unnoticed.)
 */

type Json = Record<string, unknown>;

function field(code: string, label: string, sort: number): Json {
  return { field_id: `f-${code}`, field_code: code, field_label: label, sort_order: sort };
}

function item(overrides: Json = {}): Json {
  return {
    item_id: 'item-1',
    line_no: 1,
    product_id: 'prod-1',
    sku_code: 'ITM-00180',
    sku_name: 'ENCLOSED SCALE OVAL THERMOMETER',
    category_name: 'Enclosed Oval',
    documented_qty: 6,
    received_qty: 6,
    profile_id: 'pv-1',
    profile_name: 'Profile v1',
    allowed_buckets: [
      field('EO_OK', 'VISUALLY OKAY', 10),
      field('EO_BODY_BROKEN_HG', 'Body Broken but Mercury Present', 30),
    ],
    // The Enclosed Oval profile enables no auxiliary counts: an empty list, not missing.
    allowed_counts: [],
    buckets: [],
    total_bucket_qty: 0,
    is_conserved: false,
    counts: [],
    ...overrides,
  };
}

function state(items: Json[], overrides: Json = {}): Json {
  return {
    goods_slip_id: 'gs-111',
    gs_no: 'GS/2026-27/00001',
    status: 'CATEGORISATION',
    counted_by: 'user-aman',
    counted_by_name: 'Aman',
    is_same_user_who_counted: true,
    can_submit: true,
    all_conserved: items.every((i) => i.is_conserved === true),
    items,
    ...overrides,
  };
}

const apiRequestFn = vi.fn<(path: string, options?: ApiRequestOptions) => Promise<unknown>>();

vi.mock('@/lib/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api/client')>();
  return {
    ...actual,
    apiRequest: (path: string, options?: ApiRequestOptions) => apiRequestFn(path, options),
  };
});

const { ItemCategorisationSection } = await import(
  '@/features/itemization/ItemCategorisationSection'
);
const { parseCategorisationState } = await import('@/features/itemization/api');

/** Route GETs to the given state(s) in order (the last one repeats); other calls resolve ok. */
function serve(...states: Json[]) {
  let n = 0;
  apiRequestFn.mockImplementation((path, options) => {
    if ((options?.method ?? 'GET') === 'GET') {
      const s = states[Math.min(n, states.length - 1)];
      n += 1;
      return Promise.resolve(s);
    }
    if (path.endsWith('/categorisation/submit')) {
      return Promise.resolve({ goods_slip_id: 'gs-111', status: 'RM_REVIEW' });
    }
    return Promise.resolve({ item_id: 'item-1', status: 'SAVED' });
  });
}

describe('ItemCategorisationSection (AMD-09, AMD-11, G-19)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('Scenario 1 (6 of 6): loads the backend payload for a product without auxiliary counts', async () => {
    serve(state([item()]));
    render(<ItemCategorisationSection gsId="gs-111" onDone={vi.fn()} />);

    expect(await screen.findByText(/ENCLOSED SCALE OVAL THERMOMETER/)).toBeInTheDocument();
    expect(screen.getByText(/SKU: ITM-00180/)).toBeInTheDocument();
    expect(screen.getByLabelText('VISUALLY OKAY')).toBeInTheDocument();
    expect(screen.getByLabelText('Body Broken but Mercury Present')).toBeInTheDocument();
    expect(screen.queryByText(/Item Auxiliary Counts/)).not.toBeInTheDocument();
    expect(screen.getByText(/Mismatch: 0\/6/)).toBeInTheDocument();
    expect(screen.queryByRole('alert', { name: /could not be loaded/ })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Submit Categorisation/ })).toBeDisabled();
  });

  it('Scenario 4: each product of a multi-product GS gets its own buckets, counts and quantities', async () => {
    serve(
      state([
        item(),
        item({
          item_id: 'item-2',
          line_no: 2,
          sku_code: 'DMT-01',
          sku_name: 'Digital Thermometer',
          documented_qty: 6,
          received_qty: 8,
          allowed_buckets: [field('DMT_OK_PACKED', 'VISUALLY OKAY and PACKED', 10)],
          allowed_counts: [field('PACKAGING', 'Packaging', 10), field('USER_MANUAL', 'User Manual', 30)],
          buckets: [
            { id: 'b-9', item_id: 'item-2', field_code: 'DMT_OK_PACKED', field_label: 'VISUALLY OKAY and PACKED', qty: 8 },
          ],
          counts: [
            { id: 'c-9', item_id: 'item-2', count_type: 'PACKAGING', field_label: 'Packaging', count_value: 5 },
          ],
          total_bucket_qty: 8,
          is_conserved: true,
        }),
      ]),
    );
    render(<ItemCategorisationSection gsId="gs-111" onDone={vi.fn()} />);

    expect(await screen.findByText(/Line 2: Digital Thermometer/)).toBeInTheDocument();
    expect(screen.getByText(/Mismatch: 0\/6/)).toBeInTheDocument(); // line 1, 6 counted
    expect(screen.getByText(/Conserved \(8\/8\)/)).toBeInTheDocument(); // line 2, 8 counted (excess)
    expect(screen.getByLabelText('VISUALLY OKAY and PACKED')).toHaveValue(8);
    expect(screen.getByLabelText('Packaging')).toHaveValue(5); // saved count prefilled by count_type
    expect(screen.getByLabelText('User Manual')).toHaveValue(0);
    expect(screen.queryByLabelText('VISUALLY OKAY')).toBeInTheDocument(); // line 1 only
  });

  it('saves a line with count_type + Idempotency-Key and refreshes conservation from the server', async () => {
    const dmt = {
      item_id: 'item-1',
      allowed_buckets: [field('DMT_OK_PACKED', 'VISUALLY OKAY and PACKED', 10)],
      allowed_counts: [field('PACKAGING', 'Packaging', 10)],
      received_qty: 4,
      documented_qty: 6,
    };
    serve(
      state([item(dmt)]),
      state([
        item({
          ...dmt,
          buckets: [{ id: 'b-1', item_id: 'item-1', field_code: 'DMT_OK_PACKED', field_label: 'x', qty: 4 }],
          counts: [{ id: 'c-1', item_id: 'item-1', count_type: 'PACKAGING', field_label: 'Packaging', count_value: 2 }],
          total_bucket_qty: 4,
          is_conserved: true,
        }),
      ]),
    );
    render(<ItemCategorisationSection gsId="gs-111" onDone={vi.fn()} />);

    fireEvent.change(await screen.findByLabelText('VISUALLY OKAY and PACKED'), { target: { value: '4' } });
    fireEvent.change(screen.getByLabelText('Packaging'), { target: { value: '2' } });
    fireEvent.click(screen.getByRole('button', { name: /Save Line 1/ }));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Submit Categorisation/ })).not.toBeDisabled();
    });
    const put = apiRequestFn.mock.calls.find(([, o]) => o?.method === 'PUT');
    expect(put?.[0]).toBe('/gs/gs-111/items/item-1/categorisation');
    expect(put?.[1]?.body).toEqual({
      buckets: [{ field_code: 'DMT_OK_PACKED', qty: 4 }],
      counts: [{ count_type: 'PACKAGING', count_value: 2 }],
    });
    expect(put?.[1]?.idempotencyKey).toMatch(/^web-/);
    expect(screen.getByText(/Conserved \(4\/4\)/)).toBeInTheDocument();
  });

  it('keeps a value typed while the post-save refresh is still in flight', async () => {
    let releaseRefresh: (v: unknown) => void = () => undefined;
    let gets = 0;
    apiRequestFn.mockImplementation((_path, options) => {
      if ((options?.method ?? 'GET') !== 'GET') return Promise.resolve({ item_id: 'item-1', status: 'SAVED' });
      gets += 1;
      if (gets === 1) return Promise.resolve(state([item()]));
      return new Promise((resolve) => {
        releaseRefresh = resolve;
      });
    });
    render(<ItemCategorisationSection gsId="gs-111" onDone={vi.fn()} />);

    const input = await screen.findByLabelText('VISUALLY OKAY');
    fireEvent.change(input, { target: { value: '6' } });
    fireEvent.click(screen.getByRole('button', { name: /Save Line 1/ }));
    await waitFor(() => {
      expect(gets).toBe(2);
    });
    fireEvent.change(input, { target: { value: '5' } }); // typed during the refresh
    releaseRefresh(
      state([
        item({
          buckets: [{ id: 'b-1', item_id: 'item-1', field_code: 'EO_OK', field_label: 'x', qty: 6 }],
          total_bucket_qty: 6,
          is_conserved: true,
        }),
      ]),
    );
    await waitFor(() => {
      expect(screen.getByText(/G-19 Conserved: All items/)).toBeInTheDocument();
    });
    expect(screen.getByLabelText('VISUALLY OKAY')).toHaveValue(5);
    expect(screen.getByText(/Mismatch: 5\/6/)).toBeInTheDocument();
  });

  it('lets another verifier submit a GS counted by someone else (DEC-51)', async () => {
    serve(
      state([item({ is_conserved: true, total_bucket_qty: 6 })], {
        is_same_user_who_counted: false,
        can_submit: true,
      }),
    );
    render(<ItemCategorisationSection gsId="gs-111" onDone={vi.fn()} />);

    const submit = await screen.findByRole('button', { name: /Submit Categorisation/ });
    expect(submit).not.toBeDisabled();
    expect(screen.queryByText(/Only the inward verifier who counted/)).not.toBeInTheDocument();
  });

  it('submits a conserved GS to RM review', async () => {
    serve(state([item({ is_conserved: true, total_bucket_qty: 6 })]));
    const onDone = vi.fn();
    render(<ItemCategorisationSection gsId="gs-111" onDone={onDone} />);

    const submit = await screen.findByRole('button', { name: /Submit Categorisation/ });
    expect(submit).not.toBeDisabled();
    fireEvent.click(submit);

    await waitFor(() => {
      expect(onDone).toHaveBeenCalled();
    });
    const post = apiRequestFn.mock.calls.find(([p]) => p.endsWith('/categorisation/submit'));
    expect(post?.[1]?.method).toBe('POST');
    expect(post?.[1]?.idempotencyKey).toMatch(/^web-/);
  });

  describe('Scenario 5: missing or malformed allowed_counts', () => {
    const malformed: Array<[string, Json]> = [
      ['null', state([item({ allowed_counts: null })])],
      ['undefined (missing)', state([item({ allowed_counts: undefined })])],
      ['an object', state([item({ allowed_counts: { PACKAGING: 1 } })])],
      ['a string', state([item({ allowed_counts: 'PACKAGING' })])],
      ['an array of wrong items', state([item({ allowed_counts: [{ code: 'PACKAGING' }] })])],
    ];

    it.each(malformed)('allowed_counts = %s → actionable error, no crash, retry works', async (_n, bad) => {
      serve(bad, state([item()]));
      render(<ItemCategorisationSection gsId="gs-111" onDone={vi.fn()} />);

      expect(await screen.findByText('Item categorisation could not be loaded')).toBeInTheDocument();
      expect(screen.getByText(/items\.0\.allowed_counts/)).toBeInTheDocument();
      expect(screen.getByText(/INVALID_API_RESPONSE/)).toBeInTheDocument();
      expect(screen.queryByText(/is not iterable/)).not.toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', { name: /retry/i }));
      expect(await screen.findByText(/ENCLOSED SCALE OVAL THERMOMETER/)).toBeInTheDocument();
    });

    it('rejects a null / non-object response and the legacy invented shape', () => {
      expect(() => parseCategorisationState(null)).toThrow(/unexpected format/);
      expect(() => parseCategorisationState({ goods_slip: {}, items: [] })).toThrow(
        /INVALID_API_RESPONSE|unexpected format/,
      );
      try {
        parseCategorisationState(state([item({ allowed_counts: null })]));
      } catch (err) {
        expect(err).toMatchObject({ code: 'INVALID_API_RESPONSE', status: 0 });
      }
      // Empty lists are valid business data (profile enables no counts) and are kept as-is.
      expect(parseCategorisationState(state([item()])).items[0]?.allowed_counts).toEqual([]);
    });
  });
});
