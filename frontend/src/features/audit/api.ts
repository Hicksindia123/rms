import { apiRequest } from '@/lib/api/client';

export interface FieldDiff {
  field: string;
  field_label: string;
  old_value: unknown;
  new_value: unknown;
}

export interface AuditLogRow {
  id: string;
  table_name: string;
  row_id: string;
  action: 'INSERT' | 'UPDATE' | 'DELETE';
  actor_id: string | null;
  actor_name?: string | null;
  actor_role?: string | null;
  at: string;
  request_id: string | null;
  diffs: FieldDiff[];
  old_values: Record<string, unknown> | null;
  new_values: Record<string, unknown> | null;
}

export interface AuditLogResponse {
  total: number;
  items: AuditLogRow[];
  limit: number;
  offset: number;
}

export interface GsActivityItem {
  id: string;
  category: 'STATUS' | 'AUDIT' | 'STOCK' | 'DOCUMENT' | 'COMMERCIAL' | 'NOTIFICATION';
  title: string;
  description: string | null;
  actor_id: string | null;
  actor_name: string | null;
  at: string;
  step_code: string | null;
  source_table: string | null;
  entity_id: string | null;
  action: string | null;
  diffs: FieldDiff[];
  metadata: Record<string, unknown>;
}

export interface GsActivityResponse {
  gs_id: string;
  total: number;
  items: GsActivityItem[];
}

export interface UserActivityItem {
  id: string;
  user_id: string;
  activity_type: string;
  description: string | null;
  ip_address: string | null;
  user_agent: string | null;
  created_at: string;
}

export interface UserActivityResponse {
  user_id: string;
  total: number;
  items: UserActivityItem[];
}

export interface AuditFilterParams {
  table_name?: string | undefined;
  actor_id?: string | undefined;
  action?: string | undefined;
  from_date?: string | undefined;
  to_date?: string | undefined;
  request_id?: string | undefined;
  limit?: number | undefined;
  offset?: number | undefined;
}

export const auditApi = {
  fetchAuditLog: async (params: AuditFilterParams = {}): Promise<AuditLogResponse> => {
    const qs = new URLSearchParams();
    if (params.table_name) qs.set('table_name', params.table_name);
    if (params.actor_id) qs.set('actor_id', params.actor_id);
    if (params.action) qs.set('action', params.action);
    if (params.from_date) qs.set('from_date', params.from_date);
    if (params.to_date) qs.set('to_date', params.to_date);
    if (params.request_id) qs.set('request_id', params.request_id);
    if (params.limit !== undefined) qs.set('limit', String(params.limit));
    if (params.offset !== undefined) qs.set('offset', String(params.offset));
    const queryStr = qs.toString();
    return apiRequest<AuditLogResponse>(`/audit${queryStr ? `?${queryStr}` : ''}`);
  },

  fetchAuditTables: async (): Promise<string[]> => {
    return apiRequest<string[]>('/audit/tables');
  },

  fetchGsActivity: async (gsId: string, category?: string): Promise<GsActivityResponse> => {
    const qs = category ? `?category=${encodeURIComponent(category)}` : '';
    return apiRequest<GsActivityResponse>(`/gs/${gsId}/activity${qs}`);
  },

  fetchUserActivity: async (userId: string, limit: number = 50): Promise<UserActivityResponse> => {
    return apiRequest<UserActivityResponse>(`/users/${userId}/activity?limit=${String(limit)}`);
  },

  getAuditExportUrl: (params: AuditFilterParams = {}): string => {
    const qs = new URLSearchParams();
    if (params.table_name) qs.set('table_name', params.table_name);
    if (params.actor_id) qs.set('actor_id', params.actor_id);
    if (params.action) qs.set('action', params.action);
    if (params.from_date) qs.set('from_date', params.from_date);
    if (params.to_date) qs.set('to_date', params.to_date);
    if (params.request_id) qs.set('request_id', params.request_id);
    return `/api/v1/audit/export?${qs.toString()}`;
  },
};
