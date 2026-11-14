import { apiRequest } from '@/lib/api/client';
import type {
  BatteryAdjustment,
  BatteryAdjustmentPayload,
  BatteryBalance,
  BatteryMovement,
  BatteryReceipt,
  BatteryReceiptPayload,
  BatteryType,
} from './types';

export const batteryApi = {
  getTypes: () => apiRequest<BatteryType[]>('/inventory/batteries/types'),

  getBalances: () => apiRequest<BatteryBalance[]>('/inventory/batteries/balances'),

  getMovements: () => apiRequest<BatteryMovement[]>('/inventory/batteries/movements'),

  receiveBatteries: (payload: BatteryReceiptPayload, idempotencyKey: string) =>
    apiRequest<BatteryReceipt>('/inventory/batteries/receipts', {
      method: 'POST',
      idempotencyKey,
      body: payload,
    }),

  listAdjustments: (status?: string) =>
    apiRequest<BatteryAdjustment[]>('/inventory/batteries/adjustments', {
      query: { status },
    }),

  requestAdjustment: (payload: BatteryAdjustmentPayload) =>
    apiRequest<BatteryAdjustment>('/inventory/batteries/adjustments', {
      method: 'POST',
      body: payload,
    }),

  approveAdjustment: (id: string, notes: string | undefined, idempotencyKey: string) =>
    apiRequest<BatteryAdjustment>(
      `/inventory/batteries/adjustments/${encodeURIComponent(id)}/approve`,
      {
        method: 'POST',
        idempotencyKey,
        body: { approval_notes: notes },
      },
    ),

  rejectAdjustment: (id: string, reason: string) =>
    apiRequest<BatteryAdjustment>(
      `/inventory/batteries/adjustments/${encodeURIComponent(id)}/reject`,
      {
        method: 'POST',
        body: { reason },
      },
    ),
};
