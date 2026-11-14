import { apiRequest } from '@/lib/api/client';
import type { ClearPendencyRequest, PendencyItem } from './types';

export interface ListPendenciesParams {
  status?: string;
  gs_id?: string;
  from_date?: string;
  to_date?: string;
}

export const pendencyApi = {
  listPendencies: (params?: ListPendenciesParams): Promise<PendencyItem[]> =>
    apiRequest<PendencyItem[]>('/pendencies', {
      query: {
        ...(params?.status ? { status: params.status } : {}),
        ...(params?.gs_id ? { gs_id: params.gs_id } : {}),
        ...(params?.from_date ? { from_date: params.from_date } : {}),
        ...(params?.to_date ? { to_date: params.to_date } : {}),
      },
    }),

  clearPendency: (id: string, body: ClearPendencyRequest): Promise<PendencyItem> =>
    apiRequest<PendencyItem>(`/pendencies/${encodeURIComponent(id)}/clear`, {
      method: 'POST',
      body,
    }),
};
