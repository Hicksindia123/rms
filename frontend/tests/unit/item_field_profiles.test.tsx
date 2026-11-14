import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { ItemField, ScopeProfile } from '@/features/config/field-profiles/api';

// Change plan 2026-11-12 Phase 4 (AMD-10, AMD-11, AMD-16): Item Field Profiles admin screen.
// Test-only API doubles; the screen renders whatever labels/codes the backend returns.

const scopeFn = vi.fn<(sel: unknown) => Promise<ScopeProfile>>();
const setOverrideFn = vi.fn<(...args: unknown[]) => Promise<ScopeProfile>>();
const fieldsFn = vi.fn<(group: string) => Promise<ItemField[]>>();
const createFieldFn = vi.fn<(...args: unknown[]) => Promise<ItemField>>();

vi.mock('@/features/config/field-profiles/api', () => ({
  fieldProfilesApi: {
    scope: (sel: unknown) => scopeFn(sel),
    setOverride: (...args: unknown[]) => setOverrideFn(...args),
    fields: (group: string) => fieldsFn(group),
    createField: (...args: unknown[]) => createFieldFn(...args),
    guards: () =>
      Promise.resolve([
        {
          code: 'G-18',
          name: 'Config versioning',
          statement: 'Statement from the guard catalogue',
          enforcement_layer: 'DB',
          is_locked: true,
        },
      ]),
  },
}));
vi.mock('@/features/masters/api', () => ({
  mastersApi: {
    categories: () =>
      Promise.resolve([
        {
          id: 'cat-1',
          code: 'DMT',
          name: 'DMT',
          is_active: true,
          requires_full_opening: false,
          supports_battery: true,
          supports_dismantling: true,
          hazard_capable: false,
          subcategory_count: 1,
          product_count: 1,
        },
      ]),
    subcategories: () =>
      Promise.resolve([
        {
          id: 'sub-1',
          category_id: 'cat-1',
          category_code: 'DMT',
          category_name: 'DMT',
          code: 'RIGID',
          name: 'Rigid',
          is_active: true,
          product_count: 1,
          created_at: '',
          updated_at: '',
        },
      ]),
    products: () => Promise.resolve({ items: [], total: 0, page: 1, page_size: 20 }),
  },
}));
vi.mock('@/features/auth/useAuth', () => ({
  useAuth: () => ({
    status: 'signed-in',
    me: { profile: { is_super_admin: true } },
    can: () => true,
  }),
}));

const { ItemFieldProfilesPage } =
  await import('@/features/config/field-profiles/ItemFieldProfilesPage');

const resolved = (code: string, label: string, scope: 'CATEGORY' | 'SUBCATEGORY') => ({
  field_id: `f-${code}`,
  code,
  label,
  sort_order: 10,
  source_scope_type: scope,
  source_scope_id: scope === 'CATEGORY' ? 'cat-1' : 'sub-1',
  is_wastage: false,
  returns_to_routing: false,
  requires_cn: false,
  requires_challan: false,
  system_behavior: null,
});

function profile(over: Partial<ScopeProfile> = {}): ScopeProfile {
  const groups = (['CATEGORISATION', 'DEPARTMENT', 'ACTION', 'ITEM_COUNT'] as const).map((g) => ({
    field_group: g,
    overridden: false,
    own: [],
    inherited_from: {
      scope_type: 'CATEGORY' as const,
      scope_id: 'cat-1',
      code: 'DMT',
      name: 'DMT',
    },
    inherited:
      g === 'CATEGORISATION'
        ? [resolved('DMT_OK_PACKED', 'Label from config: OK packed', 'CATEGORY')]
        : [],
    effective:
      g === 'CATEGORISATION'
        ? [resolved('DMT_OK_PACKED', 'Label from config: OK packed', 'CATEGORY')]
        : [],
  }));
  return {
    scope: { scope_type: 'SUBCATEGORY', scope_id: 'sub-1', code: 'RIGID', name: 'Rigid' },
    chain: [
      { scope_type: 'CATEGORY', scope_id: 'cat-1', code: 'DMT', name: 'DMT' },
      { scope_type: 'SUBCATEGORY', scope_id: 'sub-1', code: 'RIGID', name: 'Rigid' },
    ],
    version_id: 'v-1',
    version_no: 7,
    groups,
    ...over,
  };
}

async function pickSubcategory() {
  render(<ItemFieldProfilesPage />);
  const cat = await screen.findByLabelText(/^Category/);
  fireEvent.change(cat, { target: { value: 'cat-1' } });
  const sub = await screen.findByLabelText(/Sub-Category/);
  await waitFor(() => {
    expect(within(sub).getByRole('option', { name: 'Rigid' })).toBeInTheDocument();
  });
  fireEvent.change(sub, { target: { value: 'sub-1' } });
}

describe('ItemFieldProfilesPage', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('asks for a category first (empty state)', async () => {
    render(<ItemFieldProfilesPage />);
    expect(await screen.findByText('Choose a category')).toBeInTheDocument();
    expect(scopeFn).not.toHaveBeenCalled();
  });

  it('shows inherited fields greyed with "Override here" and the config version', async () => {
    scopeFn.mockResolvedValue(profile());
    await pickSubcategory();
    expect(await screen.findByText('Label from config: OK packed')).toBeInTheDocument();
    expect(screen.getByText(/Inherited from DMT/)).toBeInTheDocument();
    expect(screen.getByText(/Config version 7/)).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Override here' }).length).toBeGreaterThan(0);
    expect(scopeFn).toHaveBeenLastCalledWith({
      category_id: 'cat-1',
      subcategory_id: 'sub-1',
      product_id: null,
    });
  });

  it('overrides at this level with the inherited fields as a start and saves the order', async () => {
    scopeFn.mockResolvedValue(profile());
    fieldsFn.mockResolvedValue([]);
    const saved = profile();
    saved.groups[0] = {
      ...(saved.groups[0] as ScopeProfile['groups'][number]),
      overridden: true,
      own: [
        {
          field_id: 'f-DMT_OK_PACKED',
          code: 'DMT_OK_PACKED',
          label: 'Label from config: OK packed',
          is_included: true,
          sort_order: 10,
          field_is_active: true,
        },
      ],
    };
    setOverrideFn.mockResolvedValue(saved);
    await pickSubcategory();
    const overrideButtons = await screen.findAllByRole('button', { name: 'Override here' });
    fireEvent.click(overrideButtons[0] as HTMLElement);
    expect(await screen.findByLabelText('Included')).toBeChecked();
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => {
      expect(setOverrideFn).toHaveBeenCalledWith(
        'CATEGORISATION',
        { category_id: 'cat-1', subcategory_id: 'sub-1', product_id: null },
        [{ field_id: 'f-DMT_OK_PACKED', is_included: true, sort_order: 10 }],
      );
    });
    expect(await screen.findByRole('status')).toHaveTextContent(/Saved quantity buckets/);
    expect(screen.getByRole('button', { name: 'Use inherited' })).toBeInTheDocument();
  });

  it('creates a new label inline and adds it to the draft', async () => {
    scopeFn.mockResolvedValue(profile());
    fieldsFn.mockResolvedValue([]);
    createFieldFn.mockResolvedValue({
      id: 'f-new',
      field_group: 'CATEGORISATION',
      code: 'BODY_BROKEN',
      label: 'Body Broken',
      description: null,
      sort_order: 90,
      is_active: true,
      is_system: false,
      is_wastage: false,
      returns_to_routing: false,
      requires_cn: false,
      requires_challan: false,
      system_behavior: null,
      source_ref: null,
      assignment_count: 0,
      updated_at: '',
    });
    await pickSubcategory();
    const overrideButtons = await screen.findAllByRole('button', { name: 'Override here' });
    fireEvent.click(overrideButtons[0] as HTMLElement);
    const input = await screen.findByLabelText('Create new field');
    fireEvent.change(input, { target: { value: 'Body Broken' } });
    fireEvent.click(screen.getByRole('button', { name: /Create/ }));
    expect(await screen.findByText('BODY_BROKEN')).toBeInTheDocument();
    expect(createFieldFn).toHaveBeenCalledWith(
      expect.objectContaining({ field_group: 'CATEGORISATION', label: 'Body Broken' }),
      expect.any(String),
    );
  });

  it('shows the error with retry when the profile cannot load', async () => {
    scopeFn.mockRejectedValue(
      Object.assign(new Error('boom'), { code: 'INTERNAL_ERROR', status: 500, requestId: 'req-1' }),
    );
    await pickSubcategory();
    expect(await screen.findByRole('button', { name: /retry/i })).toBeInTheDocument();
  });
});
