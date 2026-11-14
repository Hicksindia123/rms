import { apiDownload, apiRequest } from '@/lib/api/client';

/** P4-02 reports API (backend app/modules/reports). */

export type ColumnType =
  | 'text'
  | 'code'
  | 'int'
  | 'decimal'
  | 'money'
  | 'hours'
  | 'days'
  | 'percent'
  | 'date'
  | 'datetime'
  | 'bool';
export type FilterType = 'date' | 'text' | 'enum' | 'uuid' | 'bool';
export type SortDir = 'asc' | 'desc';
export type CellValue = string | number | boolean | null;

export interface ReportSummary {
  code: string;
  title: string;
  description: string | null;
  can_export: boolean;
}

export interface ReportGroup {
  code: string;
  title: string;
  reports: ReportSummary[];
}

export interface FilterChoice {
  value: string;
  label: string;
}

export interface ReportFilter {
  key: string;
  label: string;
  type: FilterType;
  choices: FilterChoice[];
  default: string | null;
  required: boolean;
}

export interface ReportColumn {
  key: string;
  label: string;
  type: ColumnType;
  default: boolean;
  total: 'sum' | 'avg' | 'max' | 'count_true' | 'ratio' | null;
  has_link: boolean;
  card: number;
  sortable: boolean;
}

export interface SavedFilter {
  id: string;
  name: string;
  params: Record<string, string>;
  is_default: boolean;
  created_at: string;
}

export interface ReportDefinition {
  code: string;
  group_code: string;
  group_title: string;
  title: string;
  description: string | null;
  columns: ReportColumn[];
  filters: ReportFilter[];
  default_sort: { key: string; dir: SortDir };
  visible_columns: string[];
  column_source: 'user' | 'role' | 'default';
  column_source_role: string | null;
  saved_filters: SavedFilter[];
  can_export: boolean;
  scope: 'all' | 'department' | 'own';
  page_size: number;
}

export type ReportRow = Record<string, CellValue> & { _links?: Record<string, string> };

export interface ReportData {
  code: string;
  page: number;
  page_size: number;
  total: number;
  sort: { key: string; dir: SortDir };
  applied: Record<string, string | boolean>;
  rows: ReportRow[];
  totals: Record<string, CellValue>;
  generated_at: string;
}

export interface ReportPrint {
  code: string;
  title: string;
  description: string | null;
  branding: { app_name: string; logo_url: string | null; primary_color: string | null };
  filters_used: { label: string; value: string }[];
  generated_by: string;
  generated_at: string;
  timezone: string;
  columns: ReportColumn[];
  rows: Record<string, CellValue>[];
  totals: Record<string, CellValue>;
  total_rows: number;
  printed_rows: number;
  truncated: boolean;
}

export interface ColumnPref {
  report_code: string;
  visible_columns: string[];
  column_source: 'user' | 'role' | 'default';
  column_source_role: string | null;
}

export interface RoleColumnDefaults {
  report_code: string;
  report_title: string;
  role_code: string;
  role_name: string;
  columns: string[];
  updated_at: string | null;
}

/** Report query parameters: filter keys plus page, page_size, sort, dir, columns. */
export type ReportParams = Record<string, string>;

const enc = encodeURIComponent;

export const reportsApi = {
  catalogue: () => apiRequest<ReportGroup[]>('/reports'),
  definition: (code: string) => apiRequest<ReportDefinition>(`/reports/${enc(code)}`),
  data: (code: string, params: ReportParams) =>
    apiRequest<ReportData>(`/reports/${enc(code)}/data`, { query: params }),
  print: (code: string, params: ReportParams) =>
    apiRequest<ReportPrint>(`/reports/${enc(code)}/print`, { query: params }),
  exportFile: (code: string, format: 'csv' | 'xlsx', params: ReportParams) =>
    apiDownload(
      `/reports/${enc(code)}/export`,
      { ...params, format },
      `${code}-${new Date().toISOString().slice(0, 10)}.${format}`,
    ),
  saveColumns: (code: string, columns: string[]) =>
    apiRequest<ColumnPref>(`/reports/${enc(code)}/columns`, { method: 'PUT', body: { columns } }),
  resetColumns: (code: string) =>
    apiRequest<ColumnPref>(`/reports/${enc(code)}/columns`, { method: 'DELETE' }),
  saveFilter: (code: string, body: { name: string; params: ReportParams; is_default: boolean }) =>
    apiRequest<SavedFilter>(`/reports/${enc(code)}/saved-filters`, { method: 'POST', body }),
  deleteFilter: (code: string, id: string) =>
    apiRequest<undefined>(`/reports/${enc(code)}/saved-filters/${enc(id)}`, { method: 'DELETE' }),
  roleDefaults: () => apiRequest<RoleColumnDefaults[]>('/admin/report-column-defaults'),
  saveRoleDefaults: (code: string, role: string, columns: string[], reason: string) =>
    apiRequest<RoleColumnDefaults>(`/admin/report-column-defaults/${enc(code)}/${enc(role)}`, {
      method: 'PUT',
      body: { columns, reason: reason || null },
    }),
  deleteRoleDefaults: (code: string, role: string, reason: string) =>
    apiRequest<undefined>(`/admin/report-column-defaults/${enc(code)}/${enc(role)}`, {
      method: 'DELETE',
      query: { reason },
    }),
};
