import { apiRequest } from '@/lib/api/client';

/** P4-03 notifications API (backend app/modules/notifications). */

export type Priority = 'LOW' | 'NORMAL' | 'HIGH';
export type Channel = 'IN_APP' | 'EMAIL';
export type EmailMode = 'IMMEDIATE' | 'DAILY_DIGEST';

export interface AppNotification {
  id: string;
  type: string;
  title: string;
  body: string | null;
  entity_type: string | null;
  entity_id: string | null;
  /** LOW | NORMAL | HIGH */
  priority: string;
  read_at: string | null;
  created_at: string;
  event_type?: string | null;
  gs_id?: string | null;
}

export interface NotificationList {
  items: AppNotification[];
  unread_count: number;
  total: number;
}

export interface NotificationFilter {
  unread_only?: boolean | undefined;
  event_type?: string | undefined;
  priority?: Priority | undefined;
  limit?: number | undefined;
  offset?: number | undefined;
}

export interface EmailStatus {
  enabled: boolean;
  host: string | null;
  port: number;
  sender: string | null;
  security: string;
  reason: string | null;
}

export interface PreferenceItem {
  event_type: string;
  label: string;
  description: string | null;
  category: string;
  is_mandatory: boolean;
  email_enabled: boolean;
  email_rule_active: boolean;
}

export interface Preferences {
  email_channel: EmailStatus;
  email_address: string | null;
  email_mode: EmailMode;
  items: PreferenceItem[];
}

export interface EventType {
  code: string;
  label: string;
  description: string | null;
  category: string;
  default_priority: Priority;
  is_mandatory: boolean;
  source_ref: string | null;
  sort_order: number;
}

export interface RuleInput {
  event_type: string;
  name: string;
  include_context_recipients: boolean;
  include_step_assignees: boolean;
  recipient_role_codes: string[];
  recipient_user_ids: string[];
  channels: Channel[];
  priority: Priority | null;
  is_active: boolean;
  reason?: string | null;
}

export interface Rule extends Omit<RuleInput, 'reason'> {
  id: string;
  event_label: string;
  is_mandatory: boolean;
  created_at: string;
  updated_at: string;
}

export interface Template {
  id: string;
  event_type: string;
  event_label: string | null;
  channel: string;
  version_no: number;
  subject: string;
  body: string;
  status: string;
  change_reason: string | null;
  published_at: string;
  created_by: string | null;
}

export interface TemplatePreview {
  subject: string;
  body: string;
  placeholders: string[];
  unknown_placeholders: string[];
}

export interface EscalationRuleInput {
  workflow_step_id: string;
  after_hours: number;
  notify_role_code: string | null;
  notify_user_id: string | null;
  is_active: boolean;
  reason?: string | null;
}

export interface EscalationRule {
  id: string;
  workflow_step_id: string;
  step_code: string;
  step_label: string;
  sla_hours: number | null;
  workflow_code: string;
  workflow_version_id: string;
  workflow_version_no: number;
  workflow_version_status: string;
  after_hours: number;
  level_no: number;
  notify_role_code: string | null;
  notify_role_name: string | null;
  notify_user_id: string | null;
  notify_user_name: string | null;
  is_active: boolean;
  updated_at: string;
}

export interface Lookups {
  roles: Array<{ code: string; name: string }>;
  users: Array<{ id: string; full_name: string; email: string | null }>;
  steps: Array<{
    id: string;
    code: string;
    label: string;
    sla_hours: number | null;
    workflow_code: string;
    version_no: number;
    version_status: string;
  }>;
}

export interface Delivery {
  id: string;
  event_id: string;
  event_type: string;
  event_label: string;
  title: string;
  user_id: string;
  user_name: string;
  channel: Channel;
  status: 'PENDING' | 'DIGEST' | 'SENT' | 'SKIPPED' | 'FAILED';
  skip_reason: string | null;
  attempts: number;
  last_error: string | null;
  email_to: string | null;
  sent_at: string | null;
  created_at: string;
}

export interface DeliveryLog {
  items: Delivery[];
  outbox: Record<string, number>;
  deliveries: Record<string, number>;
  email_channel: EmailStatus;
}

const q = (f: NotificationFilter): Record<string, string> => {
  const out: Record<string, string> = {};
  if (f.unread_only) out.unread_only = 'true';
  if (f.event_type) out.event_type = f.event_type;
  if (f.priority) out.priority = f.priority;
  if (f.limit !== undefined) out.limit = String(f.limit);
  if (f.offset !== undefined) out.offset = String(f.offset);
  return out;
};

export const notificationsApi = {
  mine: (filter: NotificationFilter = { limit: 30 }) =>
    apiRequest<NotificationList>('/notifications/mine', { query: q(filter) }),
  read: (id: string) =>
    apiRequest<{ updated: number }>(`/notifications/${encodeURIComponent(id)}/read`, {
      method: 'POST',
    }),
  readAll: () => apiRequest<{ updated: number }>('/notifications/read-all', { method: 'POST' }),
  preferences: () => apiRequest<Preferences>('/notifications/preferences'),
  savePreferences: (body: { email_mode?: EmailMode; email?: Record<string, boolean> }) =>
    apiRequest<Preferences>('/notifications/preferences', { method: 'PUT', body }),
};

const ADMIN = '/admin/notifications';

export const notificationAdminApi = {
  emailStatus: () => apiRequest<EmailStatus>(`${ADMIN}/email-status`),
  lookups: () => apiRequest<Lookups>(`${ADMIN}/lookups`),
  eventTypes: () => apiRequest<EventType[]>(`${ADMIN}/event-types`),
  saveEventType: (
    code: string,
    body: Pick<EventType, 'label' | 'description' | 'default_priority' | 'is_mandatory'> & {
      reason?: string | null;
    },
  ) =>
    apiRequest<EventType>(`${ADMIN}/event-types/${encodeURIComponent(code)}`, {
      method: 'PUT',
      body,
    }),
  rules: () => apiRequest<Rule[]>(`${ADMIN}/rules`),
  createRule: (body: RuleInput) => apiRequest<Rule>(`${ADMIN}/rules`, { method: 'POST', body }),
  updateRule: (id: string, body: RuleInput) =>
    apiRequest<Rule>(`${ADMIN}/rules/${encodeURIComponent(id)}`, { method: 'PUT', body }),
  deleteRule: (id: string, reason: string | null) =>
    apiRequest<undefined>(`${ADMIN}/rules/${encodeURIComponent(id)}`, {
      method: 'DELETE',
      body: { reason },
    }),
  templates: () => apiRequest<Template[]>(`${ADMIN}/templates`),
  templateVersions: (eventType: string) =>
    apiRequest<Template[]>(`${ADMIN}/templates/${encodeURIComponent(eventType)}/versions`),
  saveTemplate: (
    eventType: string,
    body: { subject: string; body: string; reason?: string | null },
  ) =>
    apiRequest<Template>(`${ADMIN}/templates/${encodeURIComponent(eventType)}`, {
      method: 'PUT',
      body,
    }),
  preview: (body: { event_type: string; subject: string; body: string }) =>
    apiRequest<TemplatePreview>(`${ADMIN}/templates/preview`, { method: 'POST', body }),
  escalationRules: () => apiRequest<EscalationRule[]>(`${ADMIN}/escalation-rules`),
  createEscalationRule: (body: EscalationRuleInput) =>
    apiRequest<EscalationRule>(`${ADMIN}/escalation-rules`, { method: 'POST', body }),
  updateEscalationRule: (id: string, body: EscalationRuleInput) =>
    apiRequest<EscalationRule>(`${ADMIN}/escalation-rules/${encodeURIComponent(id)}`, {
      method: 'PUT',
      body,
    }),
  deleteEscalationRule: (id: string, reason: string | null) =>
    apiRequest<undefined>(`${ADMIN}/escalation-rules/${encodeURIComponent(id)}`, {
      method: 'DELETE',
      body: { reason },
    }),
  deliveries: (filter: { status?: string; channel?: string; limit?: number; offset?: number }) => {
    const query: Record<string, string> = {};
    for (const [k, v] of Object.entries(filter))
      if (v !== undefined && v !== '') query[k] = String(v);
    return apiRequest<DeliveryLog>(`${ADMIN}/deliveries`, { query });
  },
};
