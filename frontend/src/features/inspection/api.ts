import { apiRequest } from '@/lib/api/client';
import type {
  FinaliseAllOut,
  FinaliseLineOut,
  InspectionDraftIn,
  InspectionGsOut,
  InspectionLineOut,
} from './types';

export const inspectionApi = {
  getGsInspection: (gsId: string) =>
    apiRequest<InspectionGsOut>(`/gs/${encodeURIComponent(gsId)}/inspection`),

  saveDraft: (gsItemId: string, body: InspectionDraftIn) =>
    apiRequest<InspectionLineOut>(`/gs-items/${encodeURIComponent(gsItemId)}/inspection`, {
      method: 'PUT',
      body,
    }),

  finaliseLine: (gsItemId: string, idempotencyKey?: string) =>
    apiRequest<FinaliseLineOut>(
      `/gs-items/${encodeURIComponent(gsItemId)}/inspection/finalise`,
      idempotencyKey ? { method: 'POST', idempotencyKey } : { method: 'POST' },
    ),

  finaliseAll: (gsId: string, idempotencyKey?: string) =>
    apiRequest<FinaliseAllOut>(
      `/gs/${encodeURIComponent(gsId)}/inspection/finalise-all`,
      idempotencyKey ? { method: 'POST', idempotencyKey } : { method: 'POST' },
    ),

  reopenLine: (gsItemId: string, reason: string) =>
    apiRequest<InspectionLineOut>(`/gs-items/${encodeURIComponent(gsItemId)}/inspection/reopen`, {
      method: 'POST',
      body: { reason },
    }),
};

export function newIdempotencyKey(): string {
  return `web-${crypto.randomUUID()}`;
}
