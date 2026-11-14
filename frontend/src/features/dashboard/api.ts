import { apiRequest } from '@/lib/api/client';

/** P4-01 dashboards API (backend app/modules/dashboards). */

export type WidgetSize = 'S' | 'M' | 'L';
export type WidgetPriority = 'action' | 'insight';

export interface RoleRef {
  code: string;
  name: string;
}

export interface LayoutWidget {
  code: string;
  title: string;
  description: string | null;
  size: WidgetSize;
  priority: WidgetPriority;
  live: boolean;
}

export interface Dashboard {
  role: RoleRef | null;
  available_roles: RoleRef[];
  widgets: LayoutWidget[];
  hidden_widget_count: number;
  poll_seconds: number;
}

export interface WidgetData<T = Record<string, unknown>> {
  code: string;
  title: string;
  generated_at: string;
  cached: boolean;
  data: T;
}

export interface PermissionRef {
  module: string;
  action: string;
}

export interface CatalogueItem {
  code: string;
  title: string;
  description: string | null;
  default_size: WidgetSize;
  priority: WidgetPriority;
  is_active: boolean;
  requires: PermissionRef[];
}

export interface LayoutEntry {
  code: string;
  title: string;
  size: WidgetSize;
  allowed_for_role: boolean;
  missing: PermissionRef[];
}

export interface RoleLayout {
  role: RoleRef;
  has_layout: boolean;
  widgets: LayoutEntry[];
  role_permissions: PermissionRef[];
  updated_at: string | null;
  updated_by_name: string | null;
}

// --- widget data shapes --------------------------------------------------------------------------
export interface StepCount {
  step_code: string;
  step_label: string | null;
  count: number;
  overdue: number;
  oldest_created_at: string | null;
}
export interface MyTasksData {
  total: number;
  overdue: number;
  by_step: StepCount[];
}
export interface StatusCount {
  status: string;
  count: number;
  avg_age_days: number;
}
export interface GsPipelineData {
  total_open: number;
  by_status: StatusCount[];
}
export interface GateTodayData {
  date: string;
  count: number;
  boxes: number;
  missing_documentation: number;
}
export interface GsQueueData {
  statuses: string[];
  count: number;
  oldest_created_at: string | null;
}
export interface ContainerAuditData {
  today: string;
  today_status: string;
  window_from: string;
  window_to: string;
  window_days: number;
  confirmed_on_time: number;
  confirmed_late: number;
  missed_or_pending: number;
  compliance_pct: number;
}
export interface PendencyData {
  open_count: number;
  open_qty: number;
  blocking_count: number;
  oldest_opened_at: string | null;
}
export interface TransfersData {
  awaiting_acceptance: number;
  in_discrepancy: number;
  oldest_awaiting_at: string | null;
}
export interface TechnicianWipData {
  open_batches: number;
  pieces_with_technicians: number;
  oldest_age_days: number | null;
  avg_age_days: number | null;
  by_status: StatusCount[];
}
export interface BatteryData {
  total_balance: number;
  consumed_7d: number;
  consumed_30d: number;
  by_type: Array<{ code: string; name: string; balance: number }>;
}
export interface DismantlingData {
  queue_lots: number;
  queue_qty: number;
  recovered_30d: number;
  recovered_by_type: Array<{ part_type: string; label: string; qty: number }>;
}
export interface FunctionalStockData {
  total_rows: number;
  total_qty: number;
  by_condition: Array<{ key: string; rows: number; qty: number }>;
}
export interface NonFunctionalStockData {
  non_functional_rows: number;
  non_functional_qty: number;
  spare_parts_visible: boolean;
  spare_parts_rows: number | null;
  spare_parts_qty: number | null;
}
export interface HazardData {
  rows: number;
  qty: number;
}
export interface CnPipelineData {
  awaiting_credit_gs: number;
  draft: number;
  verified: number;
  issued_30d: number;
}
export interface CnIssuedData {
  months: number;
  types: Array<{ code: string; label: string }>;
  rows: Array<{ month: string; cn_type_code: string; count: number; value: number }>;
  total_count: number;
  total_value: number;
}
export interface GsTrendData {
  weeks: number;
  rows: Array<{ week_start: string; opened: number; closed: number }>;
}
export interface AccountsQueueData {
  count: number;
  oldest_created_at: string | null;
}
export interface AdminHealthData {
  window_days: number;
  users_active: number;
  users_inactive: number;
  logins: number;
  users_logged_in: number;
  config_changes: number;
  guard_violations: number;
  guard_violations_by_code: Array<{ guard_code: string; count: number }>;
  job_runs: number;
  failed_jobs: number;
  last_failed_job: string | null;
  last_failed_at: string | null;
}

export const dashboardApi = {
  mine: (role?: string) => apiRequest<Dashboard>('/dashboard', { query: role ? { role } : {} }),
  widget: <T>(code: string, params?: Record<string, string | number>) =>
    apiRequest<WidgetData<T>>(`/dashboard/widgets/${encodeURIComponent(code)}`, {
      query: params ?? {},
    }),
  catalogue: () => apiRequest<CatalogueItem[]>('/admin/dashboard-widgets'),
  layouts: () => apiRequest<RoleLayout[]>('/admin/dashboard-layouts'),
  saveLayout: (
    roleCode: string,
    widgets: Array<{ code: string; size: WidgetSize }>,
    reason: string | null,
  ) =>
    apiRequest<RoleLayout>(`/admin/dashboard-layouts/${encodeURIComponent(roleCode)}`, {
      method: 'PUT',
      body: { widgets, reason },
    }),
  deleteLayout: (roleCode: string, reason: string | null) =>
    apiRequest<undefined>(`/admin/dashboard-layouts/${encodeURIComponent(roleCode)}`, {
      method: 'DELETE',
      query: { reason },
    }),
};
