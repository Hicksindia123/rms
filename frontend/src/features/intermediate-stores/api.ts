import { apiRequest } from '@/lib/api/client';

/**
 * Phase P1 (DEC-61): Intermediate Stores and the category -> store mapping.
 * Shapes mirror backend/app/modules/intermediate_stores/schemas.py.
 */
export interface StoreRole {
  id: string;
  code: string;
  name: string;
}

export interface StoreUser {
  id: string;
  full_name: string;
  email: string | null;
  is_active: boolean;
}

export interface IntermediateStore {
  id: string;
  code: string;
  name: string;
  is_default: boolean;
  is_active: boolean;
  sort_order: number;
  role: StoreRole;
  location: StoreRole;
  category_count: number;
  subcategory_count: number;
  users: StoreUser[];
  created_at: string;
  updated_at: string;
}

export interface StoreRef {
  id: string;
  code: string;
  name: string;
  is_active: boolean;
}

export interface MappingSubcategory {
  id: string;
  code: string;
  name: string;
  is_active: boolean;
  store: StoreRef | null;
}

export interface MappingCategory extends MappingSubcategory {
  subcategories: MappingSubcategory[];
}

export interface StoreMapping {
  store: StoreRef;
  default_store: StoreRef | null;
  category_ids: string[];
  subcategory_ids: string[];
  tree: MappingCategory[];
}

export interface MappingConflict {
  kind: 'CATEGORY' | 'SUBCATEGORY';
  id: string;
  code: string;
  name: string;
  store_code: string;
  store_name: string;
}

const BASE = '/admin/intermediate-stores';

export function fetchStores(): Promise<IntermediateStore[]> {
  return apiRequest<IntermediateStore[]>(BASE);
}

export function createStore(body: {
  code: string;
  name: string;
  sort_order: number;
  is_default: boolean;
  reason: string | null;
}): Promise<IntermediateStore> {
  return apiRequest<IntermediateStore>(BASE, { method: 'POST', body });
}

export function updateStore(
  id: string,
  body: {
    name?: string;
    sort_order?: number;
    is_active?: boolean;
    is_default?: boolean;
    reason?: string | null;
  },
): Promise<IntermediateStore> {
  return apiRequest<IntermediateStore>(`${BASE}/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body,
  });
}

export function fetchStoreMapping(id: string): Promise<StoreMapping> {
  return apiRequest<StoreMapping>(`${BASE}/${encodeURIComponent(id)}/mapping`);
}

export function saveStoreMapping(
  id: string,
  body: {
    category_ids: string[];
    subcategory_ids: string[];
    reassign: boolean;
    reason: string | null;
  },
): Promise<StoreMapping> {
  return apiRequest<StoreMapping>(`${BASE}/${encodeURIComponent(id)}/mapping`, {
    method: 'PUT',
    body,
  });
}
