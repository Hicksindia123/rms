import { apiRequest } from '@/lib/api/client';
import type {
  StoreIssue,
  StoreIssueCandidateLot,
  StoreIssueCreateRequest,
  StoreIssuePrintResponse,
} from './types';

export const storeIssueApi = {
  getCandidateLots: (): Promise<StoreIssueCandidateLot[]> =>
    apiRequest<StoreIssueCandidateLot[]>('/store-issues/candidate-lots'),

  createStoreIssue: (body: StoreIssueCreateRequest): Promise<StoreIssue> =>
    apiRequest<StoreIssue>('/store-issues', {
      method: 'POST',
      body,
    }),

  listStoreIssues: (status?: string): Promise<StoreIssue[]> => {
    const params = status ? `?status=${encodeURIComponent(status)}` : '';
    return apiRequest<StoreIssue[]>(`/store-issues${params}`);
  },

  getStoreIssue: (id: string): Promise<StoreIssue> =>
    apiRequest<StoreIssue>(`/store-issues/${encodeURIComponent(id)}`),

  acknowledgeStoreIssue: (id: string): Promise<StoreIssue> =>
    apiRequest<StoreIssue>(`/store-issues/${encodeURIComponent(id)}/acknowledge`, {
      method: 'POST',
    }),

  getStoreIssuePrint: (id: string): Promise<StoreIssuePrintResponse> =>
    apiRequest<StoreIssuePrintResponse>(`/store-issues/${encodeURIComponent(id)}/print`),
};
