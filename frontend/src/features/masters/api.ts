import { apiRequest } from '@/lib/api/client';

// Shapes mirror backend/app/modules/masters/schemas.py (change plan 2026-11-12 Phase 1, AMD-07).

export interface ProductCategory {
  id: string;
  code: string;
  name: string;
  is_active: boolean;
  requires_full_opening: boolean;
  supports_battery: boolean;
  supports_dismantling: boolean;
  hazard_capable: boolean;
  subcategory_count: number;
  product_count: number;
}

export interface ProductSubCategory {
  id: string;
  category_id: string;
  category_code: string;
  category_name: string;
  code: string;
  name: string;
  is_active: boolean;
  product_count: number;
  created_at: string;
  updated_at: string;
}

export interface Product {
  id: string;
  code: string;
  name: string;
  uom: string;
  hsn_code: string | null;
  is_active: boolean;
  category_id: string;
  category_code: string;
  category_name: string;
  subcategory_id: string | null;
  subcategory_code: string | null;
  subcategory_name: string | null;
  updated_at: string;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface ProductUpdateInput {
  name?: string;
  category_id?: string;
  /** null clears the sub-category. */
  subcategory_id?: string | null;
  uom?: string;
  hsn_code?: string | null;
  is_active?: boolean;
}

export interface ProductImportResult {
  dry_run: boolean;
  rows_read: number;
  new_categories: Array<{ code: string; name: string }>;
  new_subcategories: Array<{ category_code: string; code: string; name: string }>;
  new_products: Array<{
    row_no: number;
    code: string | null;
    name: string;
    category_code: string;
    subcategory_code: string | null;
  }>;
  updates: Array<{
    row_no: number;
    product_code: string;
    name: string;
    from_category: string;
    to_category: string;
    from_subcategory: string | null;
    to_subcategory: string | null;
  }>;
  category_changes: number;
  unchanged: number;
  duplicates_in_file: number;
  exceptions: Array<{
    row_no: number;
    item_name: string;
    category: string;
    sub_category: string;
    reason: string;
  }>;
}

export const mastersApi = {
  categories: (signal?: AbortSignal) =>
    apiRequest<ProductCategory[]>('/masters/product-categories', signal ? { signal } : {}),

  subcategories: (categoryId: string | null, includeInactive: boolean) =>
    apiRequest<ProductSubCategory[]>('/masters/product-subcategories', {
      query: { category_id: categoryId, include_inactive: includeInactive },
    }),

  createSubcategory: (
    input: { category_id: string; name: string; code?: string },
    idempotencyKey: string,
  ) =>
    apiRequest<ProductSubCategory>('/masters/product-subcategories', {
      method: 'POST',
      body: input,
      idempotencyKey,
    }),

  updateSubcategory: (id: string, input: { name?: string; is_active?: boolean }) =>
    apiRequest<ProductSubCategory>(`/masters/product-subcategories/${id}`, {
      method: 'PATCH',
      body: input,
    }),

  products: (query: {
    q?: string;
    category_id?: string | null;
    subcategory_id?: string | null;
    without_subcategory?: boolean;
    page: number;
    page_size: number;
  }) => apiRequest<Page<Product>>('/masters/products', { query }),

  updateProduct: (id: string, input: ProductUpdateInput) =>
    apiRequest<Product>(`/masters/products/${id}`, { method: 'PATCH', body: input }),

  previewImport: (csvText: string, createCategories: boolean) =>
    apiRequest<ProductImportResult>('/masters/products/import/preview', {
      method: 'POST',
      body: { csv_text: csvText, create_categories: createCategories },
    }),

  runImport: (csvText: string, createCategories: boolean, idempotencyKey: string) =>
    apiRequest<ProductImportResult>('/masters/products/import', {
      method: 'POST',
      body: { csv_text: csvText, create_categories: createCategories },
      idempotencyKey,
    }),
};
