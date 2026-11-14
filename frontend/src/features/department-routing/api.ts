import { apiRequest, toApiError } from '@/lib/api/client';
import type {
  CreateDepartmentReceiptIn,
  CreateDepartmentRoutingIn,
  DepartmentLegOut,
  DepartmentOutcomeHead,
  DepartmentReceiptOut,
  DepartmentRoutingOut,
  GsReconciliationOut,
  GsRoutingState,
  ReceivingQueueItemOut,
  RmRoutingQueueItemOut,
} from './types';

/** CLAUDE.md rule h: an error message always carries the request id when the API returned one. */
export function routingErrorMessage(err: unknown): string {
  const apiError = toApiError(err);
  return apiError.requestId
    ? `${apiError.message} (Request ID: ${apiError.requestId})`
    : apiError.message;
}

export const departmentRoutingApi = {
  getOutcomeHeads: (activeOnly = true) =>
    apiRequest<DepartmentOutcomeHead[]>(
      `/department-routing/outcome-heads?active_only=${activeOnly ? 'true' : 'false'}`,
    ),

  getRmRoutingQueue: () => apiRequest<RmRoutingQueueItemOut[]>('/department-routing/queue'),

  getGsRoutingState: (gsId: string) =>
    apiRequest<GsRoutingState>(`/department-routing/gs/${encodeURIComponent(gsId)}/state`),

  /** Stock-moving command: the Idempotency-Key is mandatory (G-16). */
  dispatchRouting: (payload: CreateDepartmentRoutingIn, idempotencyKey: string) =>
    apiRequest<DepartmentRoutingOut>('/department-routing/dispatch', {
      method: 'POST',
      body: payload,
      idempotencyKey,
    }),

  getReceivingQueue: () =>
    apiRequest<ReceivingQueueItemOut[]>('/department-routing/receiving-queue'),

  getRouting: (routingId: string) =>
    apiRequest<DepartmentRoutingOut>(`/department-routing/${encodeURIComponent(routingId)}`),

  /** Stock-moving command: the Idempotency-Key is mandatory (G-16). */
  receiveRouting: (routingId: string, payload: CreateDepartmentReceiptIn, idempotencyKey: string) =>
    apiRequest<DepartmentReceiptOut>(
      `/department-routing/${encodeURIComponent(routingId)}/receive`,
      {
        method: 'POST',
        body: payload,
        idempotencyKey,
      },
    ),

  getGsReconciliation: (gsId: string) =>
    apiRequest<GsReconciliationOut>(
      `/department-routing/gs/${encodeURIComponent(gsId)}/reconciliation`,
    ),

  getGsDepartmentLegs: (gsId: string) =>
    apiRequest<DepartmentLegOut[]>(`/department-routing/gs/${encodeURIComponent(gsId)}/legs`),
};
