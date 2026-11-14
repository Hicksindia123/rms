import { apiRequest } from '@/lib/api/client';

import type { AcSlipPrintOut, FinalActionsState, SaveFinalActionsIn } from './types';

const base = (gsId: string) => `/gs/${encodeURIComponent(gsId)}/final-actions`;

/** Change plan Phase 7 (AMD-16, AMD-17). All business data flows through FastAPI (rule h). */
export const finalActionsApi = {
  get: (gsId: string) => apiRequest<FinalActionsState>(base(gsId)),

  /** New revision of the split. Idempotency-Key mandatory (G-16). */
  save: (gsId: string, body: SaveFinalActionsIn, idempotencyKey: string) =>
    apiRequest<FinalActionsState>(base(gsId), { method: 'PUT', body, idempotencyKey }),

  /** Finalise: server renders and stores the A/c Actions PDF and notifies Accounts. */
  finalise: (gsId: string, remarks: string | null, idempotencyKey: string) =>
    apiRequest<FinalActionsState>(`${base(gsId)}/finalise`, {
      method: 'POST',
      body: { remarks },
      idempotencyKey,
    }),

  /** Print / re-print any version (logged); returns a short-lived URL of the stored PDF. */
  print: (gsId: string, slipId: string) =>
    apiRequest<AcSlipPrintOut>(`${base(gsId)}/slips/${encodeURIComponent(slipId)}/print`, {
      method: 'POST',
    }),
};
