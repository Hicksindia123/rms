import { z } from 'zod';

import { ApiError, apiRequest } from '@/lib/api/client';
import type { Attachment } from '@/features/unboxing/api';

// Shapes mirror backend/app/modules/itemization/schemas.py (P2-04).

export interface ProductLookup {
  id: string;
  code: string;
  name: string;
  uom: string;
  category_id: string;
  category_code: string;
  category_name: string;
  subcategory_id?: string | null;
  subcategory_name?: string | null;
}

/** Counting search filters (AMD-07 Category -> Sub-Category). */
export interface CategoryLookup {
  id: string;
  code: string;
  name: string;
  subcategories: Array<{ id: string; code: string; name: string }>;
}

export interface ItemLine {
  id: string;
  gs_id: string;
  line_no: number;
  product_id: string;
  product_code: string | null;
  product_name: string | null;
  category_id: string;
  category_code: string | null;
  category_name: string | null;
  documented_qty: number;
  received_qty: number;
  short_qty: number;
  excess_qty: number;
  /** DEC-09: documented > received (all categories by default). */
  is_short: boolean;
  remarks: string | null;
  lot_id: string | null;
  stocked_qty: number | null;
}

/** An option of RETURN_CATEGORY / CSR_APPROVAL as published in the step form (labels from config). */
export interface StepOption {
  code: string;
  label: string;
  /** YES | CONDITIONAL — CONDITIONAL is shown as "Requires approval". */
  allowed_status: string | null;
  rule_text: string | null;
  next_action_text: string | null;
  remarks: string | null;
}

export interface CsrDecision {
  id: string;
  gs_id: string;
  decision_code: string;
  decision_label: string;
  remarks: string | null;
  is_current: boolean;
  is_admin_action: boolean;
  decided_by: string;
  decided_by_name: string | null;
  decided_at: string;
  reopened_by: string | null;
  reopened_by_name: string | null;
  reopened_at: string | null;
  reopen_reason: string | null;
}

export interface Transfer {
  id: string;
  transfer_no: string;
  status: string;
  purpose_code: string | null;
  with_packaging: boolean;
  stock_moved: boolean;
  from_location_code: string;
  from_location_name: string;
  to_location_code: string;
  to_location_name: string;
  initiated_by_name: string | null;
  initiated_at: string;
  notes: string | null;
  lines: Array<{
    lot_id: string;
    qty_sent: number;
    line_no: number | null;
    product_name: string | null;
  }>;
}

export interface PackagingCheck {
  id: string;
  lot_id: string;
  result_code: 'OK' | 'REPLACED';
  qty_replaced: number;
  remarks: string | null;
  by: string | null;
  by_name: string | null;
  at: string;
}

export interface Lot {
  lot_id: string;
  gs_item_id: string | null;
  condition_class: string;
  is_pending: boolean;
  total_qty: number;
  balances: Array<{ location_code: string; location_name: string; qty: number }>;
  packaging_checks: PackagingCheck[];
}

export interface LineCorrection {
  id: string;
  gs_id: string;
  gs_no: string;
  gs_item_id: string;
  line_no: number;
  product_name: string | null;
  old_documented_qty: number;
  old_received_qty: number;
  new_documented_qty: number;
  new_received_qty: number;
  reason: string;
  status: string;
  requested_by: string;
  requested_by_name: string | null;
  requested_at: string;
  decided_by: string | null;
  decided_by_name: string | null;
  decided_at: string | null;
  decision_remarks: string | null;
  applied_at: string | null;
}

export interface ItemizationGs {
  id: string;
  gs_no: string;
  status: string;
  party_name: string | null;
  station_name: string | null;
  carton_count: number;
  box_count: number;
  missing_documentation: boolean;
  category_code: string | null;
  original_category_code: string | null;
  csr_commercial_path: boolean;
  categorized_at: string | null;
}

export interface Totals {
  lines: number;
  documented_qty: number;
  received_qty: number;
  short_qty: number;
  excess_qty: number;
}

export interface ItemizationState {
  goods_slip: ItemizationGs;
  items: ItemLine[];
  totals: Totals;
  category_options: StepOption[];
  category_label: string | null;
  decision_options: StepOption[];
  current_decision: CsrDecision | null;
  decisions: CsrDecision[];
  lots: Lot[];
  transfers: Transfer[];
  corrections: LineCorrection[];
  evidence: Attachment[];
  permissions: {
    /** Counting (status ITEMIZATION): lines are a saved draft. */
    can_edit_lines: boolean;
    /** AMD-08: Counting -> CATEGORISATION. */
    can_submit_counting: boolean;
    can_categorize: boolean;
    can_decide: boolean;
    can_reopen: boolean;
    can_request_correction: boolean;
    can_decide_correction: boolean;
    can_check_packaging: boolean;
  };
}

export interface CategorizeResult {
  state: ItemizationState;
  task_ids: string[];
  notified_user_count: number;
}

export interface CsrApprovalCardData {
  goods_slip: ItemizationGs;
  items: ItemLine[];
  totals: Totals;
  category_label: string | null;
  categorized_by_name: string | null;
  evidence: Attachment[];
  decision_options: StepOption[];
}

export interface LineInput {
  product_id: string;
  documented_qty: number;
  received_qty: number;
  remarks?: string | null;
}

const gs = (id: string) => `/gs/${encodeURIComponent(id)}`;

export const itemizationApi = {
  state: (gsId: string) => apiRequest<ItemizationState>(`${gs(gsId)}/itemization`),
  products: (q: string, filters: { categoryId?: string; subcategoryId?: string } = {}) =>
    apiRequest<ProductLookup[]>('/itemization/lookups/products', {
      query: {
        q,
        limit: 20,
        category_id: filters.categoryId || undefined,
        subcategory_id: filters.subcategoryId || undefined,
      },
    }),
  categories: () => apiRequest<CategoryLookup[]>('/itemization/lookups/categories'),
  submitCounting: (gsId: string, idempotencyKey: string) =>
    apiRequest<ItemizationState>(`${gs(gsId)}/counting/submit`, {
      method: 'POST',
      idempotencyKey,
    }),
  addItem: (gsId: string, body: LineInput) =>
    apiRequest<ItemLine>(`${gs(gsId)}/items`, { method: 'POST', body }),
  updateItem: (gsId: string, itemId: string, body: Partial<LineInput>) =>
    apiRequest<ItemLine>(`${gs(gsId)}/items/${encodeURIComponent(itemId)}`, {
      method: 'PATCH',
      body,
    }),
  deleteItem: (gsId: string, itemId: string) =>
    apiRequest<undefined>(`${gs(gsId)}/items/${encodeURIComponent(itemId)}`, {
      method: 'DELETE',
    }),
  categorize: (gsId: string, category: string, remarks: string, idempotencyKey: string) =>
    apiRequest<CategorizeResult>(`${gs(gsId)}/categorize`, {
      method: 'POST',
      body: { category, remarks: remarks || null },
      idempotencyKey,
    }),
  decide: (gsId: string, decision: string, remarks: string, idempotencyKey: string) =>
    apiRequest<ItemizationState>(`${gs(gsId)}/csr-decision`, {
      method: 'POST',
      body: { decision, remarks: remarks || null },
      idempotencyKey,
    }),
  reopen: (gsId: string, reason: string) =>
    apiRequest<ItemizationState>(`${gs(gsId)}/csr-decision/reopen`, {
      method: 'POST',
      body: { reason },
    }),
  pendingCsr: () => apiRequest<CsrApprovalCardData[]>('/csr-approvals/pending'),
  requestCorrection: (
    gsId: string,
    itemId: string,
    body: { documented_qty: number; received_qty: number; reason: string },
  ) =>
    apiRequest<LineCorrection>(`${gs(gsId)}/items/${encodeURIComponent(itemId)}/corrections`, {
      method: 'POST',
      body,
    }),
  decideCorrection: (
    gsId: string,
    correctionId: string,
    decision: 'APPROVE' | 'REJECT',
    remarks: string,
    idempotencyKey: string,
  ) =>
    apiRequest<LineCorrection>(
      `${gs(gsId)}/item-corrections/${encodeURIComponent(correctionId)}/decision`,
      { method: 'POST', body: { decision, remarks: remarks || null }, idempotencyKey },
    ),
  pendingCorrections: () => apiRequest<LineCorrection[]>('/item-corrections/pending'),
  packagingCheck: (
    lotId: string,
    body: { result: 'OK' | 'REPLACED'; qty_replaced: number; remarks: string | null },
  ) =>
    apiRequest<PackagingCheck>(`/lots/${encodeURIComponent(lotId)}/packaging-check`, {
      method: 'POST',
      body,
    }),
  getCategorisation: async (gsId: string) =>
    parseCategorisationState(await apiRequest<unknown>(`${gs(gsId)}/categorisation`)),
  /** Body mirrors SaveItemCategorisationIn: buckets by field_code, counts by count_type. */
  saveItemCategorisation: (
    gsId: string,
    itemId: string,
    body: {
      buckets: Array<{ field_code: string; qty: number }>;
      counts: Array<{ count_type: string; count_value: number }>;
    },
    idempotencyKey: string,
  ) =>
    apiRequest<{ item_id: string; status: string }>(
      `${gs(gsId)}/items/${encodeURIComponent(itemId)}/categorisation`,
      { method: 'PUT', body, idempotencyKey },
    ),
  submitCategorisation: (
    gsId: string,
    body: { category_code?: string; remarks?: string | null },
    idempotencyKey: string,
  ) =>
    apiRequest<{ goods_slip_id: string; status: string }>(`${gs(gsId)}/categorisation/submit`, {
      method: 'POST',
      body,
      idempotencyKey,
    }),
};

// --- Item categorisation (AMD-09 buckets, AMD-11 counts, G-19) ---------------------------------
// Mirrors backend/app/modules/itemization/schemas.py (ItemCategorisationDetail,
// CategorisationStateOut). The response is validated at runtime: a missing or malformed field is
// reported as INVALID_API_RESPONSE naming the field, never iterated blindly or defaulted to [].

/** A field of the product's resolved item-field profile (bucket or count). Codes are stable. */
const resolvedFieldSchema = z.object({
  field_id: z.string(),
  field_code: z.string().min(1),
  field_label: z.string(),
  sort_order: z.number(),
});

const itemBucketSchema = z.object({
  id: z.string(),
  item_id: z.string(),
  field_code: z.string(),
  field_label: z.string().nullish(),
  qty: z.number().int(),
});

const itemCountSchema = z.object({
  id: z.string(),
  item_id: z.string(),
  /** The ITEM_COUNT field code (PACKAGING, CONTAINER, USER_MANUAL …). */
  count_type: z.string(),
  field_label: z.string().nullish(),
  count_value: z.number().int(),
});

const itemCategorisationSchema = z.object({
  item_id: z.string(),
  line_no: z.number().int(),
  product_id: z.string(),
  sku_code: z.string(),
  sku_name: z.string(),
  category_name: z.string().nullish(),
  documented_qty: z.number().int(),
  received_qty: z.number().int().nonnegative(),
  profile_id: z.string().nullable(),
  profile_name: z.string().nullable(),
  allowed_buckets: z.array(resolvedFieldSchema),
  allowed_counts: z.array(resolvedFieldSchema),
  buckets: z.array(itemBucketSchema),
  total_bucket_qty: z.number().int(),
  is_conserved: z.boolean(),
  counts: z.array(itemCountSchema),
});

const categorisationStateSchema = z.object({
  goods_slip_id: z.string(),
  gs_no: z.string(),
  status: z.string(),
  counted_by: z.string().nullable(),
  counted_by_name: z.string().nullable(),
  /** AMD-08: true when the caller is the verifier who counted (or super admin / nobody yet). */
  is_same_user_who_counted: z.boolean(),
  /** Server-side: same user + status CATEGORISATION + permission (G-19 is checked on submit). */
  can_submit: z.boolean(),
  all_conserved: z.boolean(),
  items: z.array(itemCategorisationSchema),
});

export type ResolvedBucketField = z.infer<typeof resolvedFieldSchema>;
export type ItemBucket = z.infer<typeof itemBucketSchema>;
export type ItemCount = z.infer<typeof itemCountSchema>;
export type ItemCategorisationDetail = z.infer<typeof itemCategorisationSchema>;
export type CategorisationStateOut = z.infer<typeof categorisationStateSchema>;

/** Validates GET /gs/{id}/categorisation; throws an actionable ApiError on a contract mismatch. */
export function parseCategorisationState(raw: unknown): CategorisationStateOut {
  const result = categorisationStateSchema.safeParse(raw);
  if (result.success) return result.data;
  const problems = result.error.issues.map(
    (i) => `${i.path.map(String).join('.') || '(response)'}: ${i.message}`,
  );
  throw new ApiError(
    0,
    'INVALID_API_RESPONSE',
    `The categorisation data from the server is incomplete or in an unexpected format ` +
      `(${problems.slice(0, 3).join('; ')}${problems.length > 3 ? '; …' : ''}). ` +
      'Retry; if it persists, report this goods slip to the administrator.',
    { issues: problems },
    null,
  );
}

/** A fresh key per user intent; reused when the same intent is retried after a failure. */
export function newIdempotencyKey(): string {
  return `web-${crypto.randomUUID()}`;
}
