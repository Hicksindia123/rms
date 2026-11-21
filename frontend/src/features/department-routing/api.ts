import { apiRequest, toApiError } from '@/lib/api/client';
import type {
  CreateDepartmentReceiptIn,
  CreateRoutingPlanIn,
  DepartmentLegOut,
  DepartmentOutcomeHead,
  DepartmentReceiptOut,
  DepartmentRoutingOut,
  GsReconciliationOut,
  GsRoutingState,
  IssueQueueGroup,
  ReceivingQueueItemOut,
  RmRoutingQueueItemOut,
  RoutingPlanLine,
  RoutingPlanOut,
  StoreIssueIn,
  StoreRoutingGs,
  StoreRoutingIn,
  StoreRoutingQueueRow,
  StoreRoutingResult,
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

  /** DEC-55: RM plans per item + condition (no stock move). Idempotency-Key (G-16). */
  planRouting: (payload: CreateRoutingPlanIn, idempotencyKey: string) =>
    apiRequest<RoutingPlanOut>('/department-routing/plan', {
      method: 'POST',
      body: payload,
      idempotencyKey,
    }),

  /** DEC-55: RM withdraws a planned (not yet issued) or no-work line. */
  cancelPlanLine: (planLineId: string, reason: string) =>
    apiRequest<RoutingPlanLine>(
      `/department-routing/plan-lines/${encodeURIComponent(planLineId)}/cancel`,
      { method: 'POST', body: { reason } },
    ),

  /** DEC-55: planned lines waiting for the Store issue, per GS + department. */
  getIssueQueue: () => apiRequest<IssueQueueGroup[]>('/department-routing/issue-queue'),

  /** DEC-55: Store Manager issues to a department (DIN). Stock-moving: Idempotency-Key (G-16). */
  issueToDepartment: (payload: StoreIssueIn, idempotencyKey: string) =>
    apiRequest<DepartmentRoutingOut>('/department-routing/issue', {
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

  /** DEC-67: goods slips on the Intermediate Stores (a store user: its own stores only). */
  getStoreQueue: (pendingOnly: boolean) =>
    apiRequest<StoreRoutingQueueRow[]>(
      `/department-routing/store/queue?pending_only=${pendingOnly ? 'true' : 'false'}`,
    ),

  /** DEC-67: routing view of one GS (every line with its store; `is_mine` = may route). */
  getStoreGs: (gsId: string) =>
    apiRequest<StoreRoutingGs>(`/department-routing/store/gs/${encodeURIComponent(gsId)}`),

  /** Q32: undo an own "Issue to Store" line (reason required); returns the GS routing view. */
  undoStoreLine: (planLineId: string, reason: string) =>
    apiRequest<StoreRoutingGs>(
      `/department-routing/store/plan-lines/${encodeURIComponent(planLineId)}/undo`,
      { method: 'POST', body: { reason } },
    ),

  /** DEC-67: saving the routing is the issue (DIN, stock moves). Idempotency-Key (G-16). */
  routeStoreGoods: (gsId: string, payload: StoreRoutingIn, idempotencyKey: string) =>
    apiRequest<StoreRoutingResult>(
      `/department-routing/store/gs/${encodeURIComponent(gsId)}/route`,
      { method: 'POST', body: payload, idempotencyKey },
    ),
};
