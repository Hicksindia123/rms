import { apiDownload, apiRequest } from '@/lib/api/client';
import type {
  Adjustment,
  AdjustmentPage,
  AdjustmentStatus,
  Assignment,
  AssignmentCode,
  InventoryLookups,
  SegregationCheck,
  StockCard,
  StockFilters,
  StockPage,
  StockView,
} from './types';

const viewQuery = (view: StockView, f: StockFilters) => ({ view, ...f });

/** P3-04 inventory API. Stock-moving commands carry an Idempotency-Key (G-16). */
export const inventoryApi = {
  lookups: () => apiRequest<InventoryLookups>('/inventory/lookups'),
  stock: (view: StockView, f: StockFilters, page: number) =>
    apiRequest<StockPage>('/inventory/stock', { query: { ...viewQuery(view, f), page } }),
  exportCsv: (view: StockView, f: StockFilters) =>
    apiDownload(
      '/inventory/stock/export',
      viewQuery(view, f),
      `inventory-${view.toLowerCase()}.csv`,
    ),
  stockCard: (lotId: string) =>
    apiRequest<StockCard>(`/inventory/lots/${encodeURIComponent(lotId)}/stock-card`),
  assign: (
    body: {
      lot_id: string;
      qty: number;
      assignment_code: AssignmentCode;
      from_location_id?: string;
      notes?: string;
    },
    idempotencyKey: string,
  ) =>
    apiRequest<Assignment>('/inventory/custody-assignment', {
      method: 'POST',
      body,
      idempotencyKey,
    }),
  segregationCheck: () => apiRequest<SegregationCheck>('/inventory/segregation-check'),
  adjustments: (status: AdjustmentStatus | '', page: number) =>
    apiRequest<AdjustmentPage>('/inventory/adjustments', { query: { status, page } }),
  requestAdjustment: (body: {
    lot_id: string;
    location_id: string;
    counted_qty: number;
    reason: string;
  }) => apiRequest<Adjustment>('/inventory/adjustments', { method: 'POST', body }),
  approveAdjustment: (id: string, remarks: string, idempotencyKey: string) =>
    apiRequest<Adjustment>(`/inventory/adjustments/${encodeURIComponent(id)}/approve`, {
      method: 'POST',
      body: { remarks: remarks || null },
      idempotencyKey,
    }),
  rejectAdjustment: (id: string, remarks: string) =>
    apiRequest<Adjustment>(`/inventory/adjustments/${encodeURIComponent(id)}/reject`, {
      method: 'POST',
      body: { remarks },
    }),
};
