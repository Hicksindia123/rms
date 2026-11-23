import { apiRequest } from '@/lib/api/client';

import type { ChangeIn, ManagementGs, QueueRow, Stamp, VerifyResult } from './types';

const gsPath = (gsId: string) => `/management-approval/gs/${encodeURIComponent(gsId)}`;

/** Phase P10 (DEC-70). All business data flows through FastAPI (rule h). */
export const managementApprovalApi = {
  /** Sent for approval (open request first) + every goods slip between analysis and Accounts. */
  getQueue: (q: string) =>
    apiRequest<QueueRow[]>(
      `/management-approval/queue${q.trim() ? `?q=${encodeURIComponent(q.trim())}` : ''}`,
    ),

  getGs: (gsId: string) => apiRequest<ManagementGs>(gsPath(gsId)),

  /** Replace the decisions of item + condition groups (reason per change). Idempotency-Key (G-16). */
  saveChanges: (gsId: string, changes: ChangeIn[], idempotencyKey: string) =>
    apiRequest<ManagementGs>(`${gsPath(gsId)}/changes`, {
      method: 'POST',
      body: { changes },
      idempotencyKey,
    }),

  /** Record the e-approval (DB-computed SHA-256). Idempotency-Key (G-16). */
  approve: (gsId: string, remarks: string | null, idempotencyKey: string) =>
    apiRequest<ManagementGs>(`${gsPath(gsId)}/approve`, {
      method: 'POST',
      body: { remarks },
      idempotencyKey,
    }),

  /** The stamp of any goods slip the user can see (goods_slips.view). */
  getStamp: (gsId: string) => apiRequest<Stamp>(`${gsPath(gsId)}/stamp`),

  /** Recompute the hash now: VALID or CHANGED. */
  verify: (gsId: string) => apiRequest<VerifyResult>(`${gsPath(gsId)}/verify`),
};
