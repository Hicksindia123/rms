/**
 * Phase P1 (DEC-61): Admin -> Intermediate Stores. The API client is mocked with backend-shaped
 * payloads (backend/app/modules/intermediate_stores/schemas.py).
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { ApiRequestOptions } from '@/lib/api/client';
import type { IntermediateStore, StoreMapping } from '@/features/intermediate-stores/api';

const apiRequestFn = vi.fn<(path: string, options?: ApiRequestOptions) => Promise<unknown>>();

vi.mock('@/lib/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api/client')>();
  return {
    ...actual,
    apiRequest: (path: string, options?: ApiRequestOptions) => apiRequestFn(path, options),
  };
});

const { IntermediateStoresPage } =
  await import('@/features/intermediate-stores/IntermediateStoresPage');
const { ApiError } = await import('@/lib/api/client');

function store(code: string, partial: Partial<IntermediateStore> = {}): IntermediateStore {
  return {
    id: `id-${code}`,
    code,
    name: `Intermediate Store ${code}`,
    is_default: false,
    is_active: true,
    sort_order: 10,
    role: { id: `r-${code}`, code: `ISTORE_${code}`, name: `Intermediate Store ${code}` },
    location: { id: `l-${code}`, code: `ISTORE_${code}`, name: `Intermediate Store ${code}` },
    category_count: 1,
    subcategory_count: 0,
    users: [],
    created_at: '2026-11-20T00:00:00Z',
    updated_at: '2026-11-20T00:00:00Z',
    ...partial,
  };
}

const STORES: IntermediateStore[] = [
  store('OP', {
    category_count: 2,
    users: [{ id: 'u1', full_name: 'Store OP User', email: 'op@rms.local', is_active: true }],
  }),
  store('DT'),
  store('RI', { is_default: true }),
];

const ref = (code: string) => ({
  id: `id-${code}`,
  code,
  name: `Intermediate Store ${code}`,
  is_active: true,
});

const DT_MAPPING: StoreMapping = {
  store: ref('DT'),
  default_store: ref('RI'),
  category_ids: ['c-dmt'],
  subcategory_ids: [],
  tree: [
    {
      id: 'c-dmt',
      code: 'DMT',
      name: 'DMT',
      is_active: true,
      store: ref('DT'),
      subcategories: [
        { id: 's-th', code: 'THERMOMETER', name: 'Thermometer', is_active: true, store: null },
      ],
    },
    {
      id: 'c-pri',
      code: 'PRISMATIC',
      name: 'PRISMATIC',
      is_active: true,
      store: ref('OP'),
      subcategories: [],
    },
  ],
};

const ALL = { canCreate: true, canEdit: true, canConfigure: true };

beforeEach(() => {
  apiRequestFn.mockReset();
});

describe('<IntermediateStoresPage />', () => {
  it('lists stores with role, location, default flag and the users of each store role', async () => {
    apiRequestFn.mockResolvedValue(STORES);
    render(<IntermediateStoresPage {...ALL} />);

    const op = await screen.findByTestId('istore-OP');
    expect(within(op).getByText('Intermediate Store OP')).toBeTruthy();
    expect(within(op).getByText(/Store OP User/)).toBeTruthy();
    expect(within(op).getAllByText('ISTORE_OP')).toHaveLength(2);
    expect(
      within(screen.getByTestId('istore-DT')).getByText(/Nobody holds this role yet/),
    ).toBeTruthy();

    const ri = screen.getByTestId('istore-RI');
    expect(within(ri).getByText('Default store')).toBeTruthy();
    // The default store has no Deactivate / Make default buttons.
    expect(within(ri).queryByRole('button', { name: 'Deactivate' })).toBeNull();
    expect(within(ri).queryByRole('button', { name: /Make default/ })).toBeNull();
    expect(within(op).getByRole('button', { name: 'Deactivate' })).toBeTruthy();
  });

  it('is read-only without write permissions', async () => {
    apiRequestFn.mockResolvedValue(STORES);
    render(<IntermediateStoresPage canCreate={false} canEdit={false} canConfigure={false} />);
    await screen.findByTestId('istore-OP');
    expect(screen.queryByRole('button', { name: /Add store/ })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Map categories' })).toBeNull();
    expect(screen.queryByRole('button', { name: /Rename/ })).toBeNull();
  });

  it('shows the error with code, request id and retry', async () => {
    apiRequestFn.mockRejectedValueOnce(
      new ApiError(500, 'INTERNAL_ERROR', 'Database down', null, 'req-77'),
    );
    render(<IntermediateStoresPage {...ALL} />);
    expect(await screen.findByText('Could not load the Intermediate Stores')).toBeTruthy();
    expect(screen.getByText(/Request ID: req-77/)).toBeTruthy();
    apiRequestFn.mockResolvedValue(STORES);
    fireEvent.click(screen.getByRole('button', { name: /Retry/ }));
    expect(await screen.findByTestId('istore-OP')).toBeTruthy();
  });

  it('shows the empty state', async () => {
    apiRequestFn.mockResolvedValue([]);
    render(<IntermediateStoresPage {...ALL} />);
    expect(await screen.findByText('No Intermediate Stores')).toBeTruthy();
  });

  it('adds a store (code upper-cased) and refreshes the list', async () => {
    const created = store('XY', { name: 'Store XY' });
    apiRequestFn.mockImplementation((_path, options) => {
      if (options?.method === 'POST') return Promise.resolve(created);
      return Promise.resolve(STORES);
    });
    render(<IntermediateStoresPage {...ALL} />);
    await screen.findByTestId('istore-OP');

    fireEvent.click(screen.getByRole('button', { name: /Add store/ }));
    fireEvent.change(screen.getByLabelText('Code'), { target: { value: 'xy' } });
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Store XY' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create store' }));

    expect(await screen.findByText(/Created Store XY with role ISTORE_XY/)).toBeTruthy();
    const post = apiRequestFn.mock.calls.find(([, o]) => o?.method === 'POST');
    expect(post?.[0]).toBe('/admin/intermediate-stores');
    expect(post?.[1]?.body).toEqual({
      code: 'XY',
      name: 'Store XY',
      sort_order: 100,
      is_default: false,
      reason: null,
    });
  });

  it('makes a store the default with PATCH is_default', async () => {
    apiRequestFn.mockImplementation((_path, options) =>
      Promise.resolve(options?.method === 'PATCH' ? STORES[1] : STORES),
    );
    render(<IntermediateStoresPage {...ALL} />);
    const dt = await screen.findByTestId('istore-DT');
    fireEvent.click(within(dt).getByRole('button', { name: /Make default/ }));
    await screen.findByText(/is now the default store/);
    const call = apiRequestFn.mock.calls.find(([, o]) => o?.method === 'PATCH');
    expect(call?.[0]).toBe('/admin/intermediate-stores/id-DT');
    expect(call?.[1]?.body).toEqual({ is_default: true });
  });

  it('maps categories: shows owners, blocks a conflicting save until the move is confirmed', async () => {
    apiRequestFn.mockImplementation((path, options) => {
      if (path.endsWith('/mapping') && options?.method === 'PUT')
        return Promise.resolve(DT_MAPPING);
      if (path.endsWith('/mapping')) return Promise.resolve(DT_MAPPING);
      return Promise.resolve(STORES);
    });
    render(<IntermediateStoresPage {...ALL} />);
    const dt = await screen.findByTestId('istore-DT');
    fireEvent.click(within(dt).getByRole('button', { name: 'Map categories' }));

    const dmt = await screen.findByLabelText(/^DMT/);
    expect((dmt as HTMLInputElement).checked).toBe(true);
    expect(screen.getByText('This store')).toBeTruthy();
    // PRISMATIC belongs to OP: ticking it is a conflict.
    fireEvent.click(screen.getByLabelText(/^PRISMATIC/));
    expect(screen.getByText(/Already mapped to another store/)).toBeTruthy();
    const save = screen.getByRole('button', { name: 'Save mapping' });
    expect((save as HTMLButtonElement).disabled).toBe(true);

    fireEvent.click(screen.getByLabelText(/Move it to Intermediate Store DT/));
    expect((save as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(screen.getByLabelText(/Thermometer/));
    fireEvent.click(save);

    await waitFor(() => {
      expect(screen.getByText(/Saved the category mapping of Intermediate Store DT/)).toBeTruthy();
    });
    const put = apiRequestFn.mock.calls.find(([, o]) => o?.method === 'PUT');
    expect(put?.[0]).toBe('/admin/intermediate-stores/id-DT/mapping');
    expect(put?.[1]?.body).toEqual({
      category_ids: ['c-dmt', 'c-pri'],
      subcategory_ids: ['s-th'],
      reassign: true,
      reason: null,
    });
  });
});
