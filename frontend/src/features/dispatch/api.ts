import { apiRequest } from '@/lib/api/client';
import type {
  DispatchCandidateLot,
  DispatchQueueItem,
  ReplacementDispatch,
  ReplacementDispatchCreateRequest,
} from './types';

export const dispatchApi = {
  getQueue: (): Promise<DispatchQueueItem[]> =>
    apiRequest<DispatchQueueItem[]>('/dispatches/queue'),

  getCandidateLots: (productId?: string, gsItemId?: string): Promise<DispatchCandidateLot[]> => {
    const params = new URLSearchParams();
    if (productId) params.append('product_id', productId);
    if (gsItemId) params.append('gs_item_id', gsItemId);
    const qs = params.toString() ? `?${params.toString()}` : '';
    return apiRequest<DispatchCandidateLot[]>(`/dispatches/candidate-lots${qs}`);
  },

  createDispatch: (body: ReplacementDispatchCreateRequest): Promise<ReplacementDispatch> =>
    apiRequest<ReplacementDispatch>('/dispatches', {
      method: 'POST',
      body,
    }),

  listDispatches: (gsId?: string, dispatchType?: string): Promise<ReplacementDispatch[]> => {
    const params = new URLSearchParams();
    if (gsId) params.append('gs_id', gsId);
    if (dispatchType) params.append('dispatch_type', dispatchType);
    const qs = params.toString() ? `?${params.toString()}` : '';
    return apiRequest<ReplacementDispatch[]>(`/dispatches${qs}`);
  },

  getDispatch: (id: string): Promise<ReplacementDispatch> =>
    apiRequest<ReplacementDispatch>(`/dispatches/${encodeURIComponent(id)}`),
};
