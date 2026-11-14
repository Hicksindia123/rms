import { apiRequest } from '@/lib/api/client';

// Shapes mirror backend/app/modules/config/field_profiles/schemas.py
// (change plan 2026-11-12 Phase 4; AMD-10, AMD-11, AMD-16; G-18).

export type FieldGroup = 'CATEGORISATION' | 'DEPARTMENT' | 'ACTION' | 'ITEM_COUNT';
export type ScopeType = 'CATEGORY' | 'SUBCATEGORY' | 'PRODUCT';

export interface ItemField {
  id: string;
  field_group: FieldGroup;
  code: string;
  label: string;
  description: string | null;
  sort_order: number;
  is_active: boolean;
  is_system: boolean;
  is_wastage: boolean;
  returns_to_routing: boolean;
  requires_cn: boolean;
  requires_challan: boolean;
  system_behavior: string | null;
  source_ref: string | null;
  assignment_count: number;
  updated_at: string;
}

export interface ScopeRef {
  scope_type: ScopeType;
  scope_id: string;
  code: string;
  name: string;
}

export interface ResolvedField {
  field_id: string;
  code: string;
  label: string;
  sort_order: number;
  source_scope_type: ScopeType;
  source_scope_id: string;
  is_wastage: boolean;
  returns_to_routing: boolean;
  requires_cn: boolean;
  requires_challan: boolean;
  system_behavior: string | null;
}

export interface Assignment {
  field_id: string;
  code: string;
  label: string;
  is_included: boolean;
  sort_order: number;
  field_is_active: boolean;
}

export interface GroupProfile {
  field_group: FieldGroup;
  overridden: boolean;
  own: Assignment[];
  inherited_from: ScopeRef | null;
  inherited: ResolvedField[];
  effective: ResolvedField[];
}

export interface ScopeProfile {
  scope: ScopeRef;
  chain: ScopeRef[];
  version_id: string | null;
  version_no: number | null;
  groups: GroupProfile[];
}

export interface ScopeSelection {
  category_id: string;
  subcategory_id?: string | null;
  product_id?: string | null;
}

export interface AssignmentInput {
  field_id: string;
  is_included: boolean;
  sort_order: number;
}

export interface FieldCreateInput {
  field_group: FieldGroup;
  label: string;
  is_wastage?: boolean;
  returns_to_routing?: boolean;
  requires_cn?: boolean;
  requires_challan?: boolean;
}

export interface SystemGuard {
  code: string;
  name: string;
  statement: string;
  enforcement_layer: string;
  is_locked: boolean;
}

const BASE = '/config/item-field-profiles';

export const fieldProfilesApi = {
  fields: (fieldGroup: FieldGroup) =>
    apiRequest<ItemField[]>(`${BASE}/fields`, {
      query: { field_group: fieldGroup, include_inactive: true },
    }),

  createField: (input: FieldCreateInput, idempotencyKey: string) =>
    apiRequest<ItemField>(`${BASE}/fields`, { method: 'POST', body: input, idempotencyKey }),

  scope: (sel: ScopeSelection) =>
    apiRequest<ScopeProfile>(`${BASE}/scope`, {
      query: {
        category_id: sel.category_id,
        subcategory_id: sel.subcategory_id ?? undefined,
        product_id: sel.product_id ?? undefined,
      },
    }),

  /** Replace the scope's fields for one group; an empty list restores inheritance (idempotent). */
  setOverride: (group: FieldGroup, sel: ScopeSelection, fields: AssignmentInput[]) =>
    apiRequest<ScopeProfile>(`${BASE}/scope/${group}`, {
      method: 'PUT',
      body: {
        category_id: sel.category_id,
        subcategory_id: sel.subcategory_id ?? null,
        product_id: sel.product_id ?? null,
        fields,
      },
    }),

  guards: () => apiRequest<SystemGuard[]>('/config/system-guards'),
};
