import { apiRequest } from '@/lib/api/client';

import type {
  AcEntryQueueItem,
  AcEntryState,
  DispatchIn,
  DispatchSlipOut,
  DispatchSlipPrintOut,
  SaveAcEntryIn,
} from './types';

export type AcQueueFilter = 'pending' | 'completed' | 'all';
export type DispatchSlipFilter = 'READY' | 'DISPATCHED';

/** Change plan Phase 8 (AMD-18, AMD-19). All business data flows through FastAPI (rule h). */
export const acEntryApi = {
  queue: (status: AcQueueFilter) =>
    apiRequest<AcEntryQueueItem[]>(`/ac-entry/queue?status=${encodeURIComponent(status)}`),

  get: (gsId: string) => apiRequest<AcEntryState>(`/ac-entry/gs/${encodeURIComponent(gsId)}`),

  /** Partial save of CN / Challan data. Idempotency-Key mandatory (G-16). */
  save: (gsId: string, body: SaveAcEntryIn, idempotencyKey: string) =>
    apiRequest<AcEntryState>(`/ac-entry/gs/${encodeURIComponent(gsId)}/lines`, {
      method: 'PUT',
      body,
      idempotencyKey,
    }),

  /** Complete: generates the Dispatch Slip when a line ships goods (AMD-19). */
  complete: (
    gsId: string,
    acActionSlipId: string,
    remarks: string | null,
    idempotencyKey: string,
  ) =>
    apiRequest<AcEntryState>(`/ac-entry/gs/${encodeURIComponent(gsId)}/complete`, {
      method: 'POST',
      body: { ac_action_slip_id: acActionSlipId, remarks },
      idempotencyKey,
    }),
};

export const dispatchSlipsApi = {
  list: (status: DispatchSlipFilter) =>
    apiRequest<DispatchSlipOut[]>(`/dispatch-slips?status=${encodeURIComponent(status)}`),

  /** Store issue + rms_move_stock + DEC-26 tracking data. Idempotency-Key mandatory (G-16). */
  dispatch: (slipId: string, body: DispatchIn, idempotencyKey: string) =>
    apiRequest<DispatchSlipOut>(`/dispatch-slips/${encodeURIComponent(slipId)}/dispatch`, {
      method: 'POST',
      body,
      idempotencyKey,
    }),

  /** Print / re-print the stored PDF (logged); returns a short-lived URL. */
  print: (slipId: string) =>
    apiRequest<DispatchSlipPrintOut>(`/dispatch-slips/${encodeURIComponent(slipId)}/print`, {
      method: 'POST',
    }),
};
