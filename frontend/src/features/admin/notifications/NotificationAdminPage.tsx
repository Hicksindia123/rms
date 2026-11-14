import { useCallback, useEffect, useMemo, useState } from 'react';
import { Lock, Mail, MailX } from 'lucide-react';

import { Badge, Button, EmptyState, ErrorState, LoadingState } from '@/components/ui';
import { formatDateTime } from '@/features/goods-slips/format';
import {
  notificationAdminApi,
  type Channel,
  type DeliveryLog,
  type EmailStatus,
  type EscalationRule,
  type EscalationRuleInput,
  type EventType,
  type Lookups,
  type Priority,
  type Rule,
  type RuleInput,
  type Template,
  type TemplatePreview,
} from '@/features/notifications/api';
import { PartyEmailSettingsEditor } from '@/features/party-notifications/PartyEmailSettingsEditor';
import { useApiQuery } from '@/hooks/useApiQuery';
import { toApiError, type ApiError } from '@/lib/api/client';

/**
 * Admin → Notifications (P4-03, master plan §10 "Notifications"): event → recipients → channel
 * rules, SLA escalation levels (DEC-30, seeded disabled), versioned email templates with preview,
 * and the delivery log. SMTP settings live in the backend env and are shown read-only.
 * Phase 9 (AMD-20): the Party email tab edits the template / auto-send of emails to parties.
 */

type Tab = 'rules' | 'escalations' | 'templates' | 'log' | 'party-email';

interface Base {
  status: EmailStatus;
  lookups: Lookups;
  events: EventType[];
}

const reasonOrNull = (r: string) => (r.trim() ? r.trim() : null);

export function NotificationAdminPage() {
  const fetcher = useCallback(async (): Promise<Base> => {
    const [status, lookups, events] = await Promise.all([
      notificationAdminApi.emailStatus(),
      notificationAdminApi.lookups(),
      notificationAdminApi.eventTypes(),
    ]);
    return { status, lookups, events };
  }, []);
  const base = useApiQuery<Base>(fetcher);
  const [tab, setTab] = useState<Tab>('rules');

  if (base.error) {
    return (
      <div className="page">
        <ErrorState
          error={base.error}
          onRetry={base.reload}
          title="Could not load notification settings"
        />
      </div>
    );
  }
  if (!base.data) {
    return (
      <div className="page">
        <LoadingState label="Loading notification settings…" />
      </div>
    );
  }
  const { status } = base.data;
  return (
    <div className="page">
      <h1 className="page__title">Notifications</h1>
      <p className="page__subtitle">
        Who is told about each event, on which channel, and when overdue work escalates. Every
        change is recorded in the config history.
      </p>
      <SmtpStatus status={status} />
      <div className="tabs tabs--wrap" role="tablist" aria-label="Notification settings">
        {(
          [
            ['rules', 'Rules'],
            ['escalations', 'Escalations'],
            ['templates', 'Email templates'],
            ['log', 'Delivery log'],
            ['party-email', 'Party email'],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            role="tab"
            className="tabs__tab"
            aria-selected={tab === id}
            onClick={() => {
              setTab(id);
            }}
          >
            {label}
          </button>
        ))}
      </div>
      {tab === 'rules' ? <RulesEditor base={base.data} /> : null}
      {tab === 'escalations' ? <EscalationEditor lookups={base.data.lookups} /> : null}
      {tab === 'templates' ? <TemplateEditor events={base.data.events} /> : null}
      {tab === 'log' ? <DeliveryLogView /> : null}
      {tab === 'party-email' ? (
        // The page is reached with notifications.configure; the server enforces it on save.
        <PartyEmailSettingsEditor canEdit />
      ) : null}
    </div>
  );
}

function SmtpStatus({ status }: { status: EmailStatus }) {
  return (
    <div
      className={status.enabled ? 'notif-smtp notif-smtp--on' : 'banner'}
      role="status"
      data-testid="smtp-status"
      style={{ marginBottom: '1rem' }}
    >
      {status.enabled ? (
        <Mail size={18} aria-hidden="true" />
      ) : (
        <MailX size={18} aria-hidden="true" />
      )}
      <span>
        {status.enabled ? (
          <>
            Email channel <strong>enabled</strong>: {status.host}:{status.port} ({status.security}),
            from {status.sender}. Read-only: SMTP is configured in the backend environment.
          </>
        ) : (
          <>
            Email channel <strong>disabled</strong>: {status.reason}. EMAIL deliveries are recorded
            as skipped (see the delivery log), never silently dropped.
          </>
        )}
      </span>
    </div>
  );
}

// --------------------------------------------------------------------------------------------
// Rules
// --------------------------------------------------------------------------------------------

const emptyRule = (eventType: string): RuleInput => ({
  event_type: eventType,
  name: '',
  include_context_recipients: true,
  include_step_assignees: false,
  recipient_role_codes: [],
  recipient_user_ids: [],
  channels: ['IN_APP'],
  priority: null,
  is_active: true,
});

function RulesEditor({ base }: { base: Base }) {
  const fetcher = useCallback(() => notificationAdminApi.rules(), []);
  const rules = useApiQuery<Rule[]>(fetcher);
  const [eventFilter, setEventFilter] = useState('');
  const [editing, setEditing] = useState<{ id: string | null; value: RuleInput } | null>(null);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const roleName = useMemo(
    () => new Map(base.lookups.roles.map((r) => [r.code, r.name])),
    [base.lookups.roles],
  );
  const userName = useMemo(
    () => new Map(base.lookups.users.map((u) => [u.id, u.full_name])),
    [base.lookups.users],
  );

  if (rules.error) return <ErrorState error={rules.error} onRetry={rules.reload} />;
  if (!rules.data) return <LoadingState label="Loading rules…" />;
  const shown = rules.data.filter((r) => !eventFilter || r.event_type === eventFilter);

  const run = async (fn: () => Promise<unknown>, done: string) => {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await fn();
      setEditing(null);
      setReason('');
      setMessage(done);
      rules.reload();
    } catch (err) {
      setError(toApiError(err));
    } finally {
      setBusy(false);
    }
  };

  const toggle = (r: Rule) =>
    run(
      () =>
        notificationAdminApi.updateRule(r.id, {
          event_type: r.event_type,
          name: r.name,
          include_context_recipients: r.include_context_recipients,
          include_step_assignees: r.include_step_assignees,
          recipient_role_codes: r.recipient_role_codes,
          recipient_user_ids: r.recipient_user_ids,
          channels: r.channels,
          priority: r.priority,
          is_active: !r.is_active,
          reason: reasonOrNull(reason),
        }),
      r.is_active ? `Disabled "${r.name}".` : `Enabled "${r.name}".`,
    );

  return (
    <section aria-label="Notification rules">
      <div className="notif-filters">
        <label className="notif-filters__field">
          <span className="form-label">Event</span>
          <select
            className="input"
            value={eventFilter}
            onChange={(e) => {
              setEventFilter(e.target.value);
            }}
          >
            <option value="">All events</option>
            {base.events.map((ev) => (
              <option key={ev.code} value={ev.code}>
                {ev.label}
              </option>
            ))}
          </select>
        </label>
        <label className="notif-filters__field">
          <span className="form-label">Reason for changes (optional)</span>
          <input
            className="input"
            value={reason}
            maxLength={500}
            onChange={(e) => {
              setReason(e.target.value);
            }}
          />
        </label>
        <Button
          type="button"
          variant="primary"
          onClick={() => {
            setEditing({ id: null, value: emptyRule(eventFilter || base.events[0]?.code || '') });
          }}
        >
          Add rule
        </Button>
      </div>
      {message ? (
        <p role="status" className="dash-chip" style={{ background: 'var(--color-success-bg)' }}>
          {message}
        </p>
      ) : null}
      {error ? <ErrorState error={error} title="Could not save" /> : null}

      {editing ? (
        <RuleForm
          base={base}
          value={editing.value}
          isNew={editing.id === null}
          busy={busy}
          onChange={(value) => {
            setEditing({ ...editing, value });
          }}
          onCancel={() => {
            setEditing(null);
          }}
          onSave={() => {
            const body = { ...editing.value, reason: reasonOrNull(reason) };
            void run(
              () =>
                editing.id
                  ? notificationAdminApi.updateRule(editing.id, body)
                  : notificationAdminApi.createRule(body),
              'Rule saved.',
            );
          }}
        />
      ) : null}

      {shown.length === 0 ? (
        <EmptyState title="No rules" hint="Events without an active rule notify nobody." />
      ) : (
        <ul className="notif-rules">
          {shown.map((r) => (
            <li key={r.id} className="dash-card notif-rule" data-testid={`rule-${r.event_type}`}>
              <div className="notif-rule__head">
                <strong>{r.event_label}</strong>
                {r.is_mandatory ? (
                  <Badge variant="warning">
                    <Lock size={10} aria-hidden="true" /> Mandatory
                  </Badge>
                ) : null}
                <Badge variant={r.is_active ? 'success' : 'neutral'}>
                  {r.is_active ? 'Active' : 'Inactive'}
                </Badge>
              </div>
              <div className="dash-muted">{r.name}</div>
              <div className="notif-rule__meta">
                To:{' '}
                {[
                  r.include_context_recipients ? 'event recipients' : null,
                  r.include_step_assignees ? 'open step assignees' : null,
                  ...r.recipient_role_codes.map((c) => roleName.get(c) ?? c),
                  ...r.recipient_user_ids.map((u) => userName.get(u) ?? u),
                ]
                  .filter(Boolean)
                  .join(', ')}
                {' · '}
                {r.channels.map((c) => (c === 'IN_APP' ? 'In-app' : 'Email')).join(' + ')}
                {r.priority ? ` · ${r.priority}` : ''}
              </div>
              <div className="notif-rule__actions">
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setEditing({
                      id: r.id,
                      value: {
                        event_type: r.event_type,
                        name: r.name,
                        include_context_recipients: r.include_context_recipients,
                        include_step_assignees: r.include_step_assignees,
                        recipient_role_codes: r.recipient_role_codes,
                        recipient_user_ids: r.recipient_user_ids,
                        channels: r.channels,
                        priority: r.priority,
                        is_active: r.is_active,
                      },
                    });
                  }}
                >
                  Edit
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  disabled={busy}
                  onClick={() => void toggle(r)}
                >
                  {r.is_active ? 'Disable' : 'Enable'}
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  disabled={busy}
                  onClick={() => {
                    if (!window.confirm(`Delete the rule "${r.name}"?`)) return;
                    void run(
                      () => notificationAdminApi.deleteRule(r.id, reasonOrNull(reason)),
                      'Rule deleted.',
                    );
                  }}
                >
                  Delete
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function RuleForm({
  base,
  value,
  isNew,
  busy,
  onChange,
  onCancel,
  onSave,
}: {
  base: Base;
  value: RuleInput;
  isNew: boolean;
  busy: boolean;
  onChange: (v: RuleInput) => void;
  onCancel: () => void;
  onSave: () => void;
}) {
  const set = <K extends keyof RuleInput>(k: K, v: RuleInput[K]) => {
    onChange({ ...value, [k]: v });
  };
  const toggleIn = <T,>(list: T[], item: T): T[] =>
    list.includes(item) ? list.filter((x) => x !== item) : [...list, item];
  return (
    <form
      className="dash-card notif-form"
      aria-label={isNew ? 'New rule' : 'Edit rule'}
      onSubmit={(e) => {
        e.preventDefault();
        onSave();
      }}
    >
      <h2 className="dash-card__title">{isNew ? 'New rule' : 'Edit rule'}</h2>
      <label className="notif-filters__field">
        <span className="form-label">Event</span>
        <select
          className="input"
          value={value.event_type}
          onChange={(e) => {
            set('event_type', e.target.value);
          }}
        >
          {base.events.map((ev) => (
            <option key={ev.code} value={ev.code}>
              {ev.label}
            </option>
          ))}
        </select>
      </label>
      <label className="notif-filters__field">
        <span className="form-label">Name</span>
        <input
          className="input"
          required
          maxLength={120}
          value={value.name}
          onChange={(e) => {
            set('name', e.target.value);
          }}
        />
      </label>
      <fieldset className="notif-mode">
        <legend className="form-label">Recipients</legend>
        <label className="notif-filters__check">
          <input
            type="checkbox"
            checked={value.include_context_recipients}
            onChange={(e) => {
              set('include_context_recipients', e.target.checked);
            }}
          />
          The event&apos;s own recipients (named by the business step)
        </label>
        <label className="notif-filters__check">
          <input
            type="checkbox"
            checked={value.include_step_assignees}
            onChange={(e) => {
              set('include_step_assignees', e.target.checked);
            }}
          />
          Assignees of the goods slip&apos;s open step
        </label>
        <label className="notif-filters__field">
          <span className="form-label">Roles</span>
          <select
            className="input"
            multiple
            size={5}
            value={value.recipient_role_codes}
            onChange={(e) => {
              set(
                'recipient_role_codes',
                Array.from(e.target.selectedOptions, (o) => o.value),
              );
            }}
          >
            {base.lookups.roles.map((r) => (
              <option key={r.code} value={r.code}>
                {r.name}
              </option>
            ))}
          </select>
        </label>
        <label className="notif-filters__field">
          <span className="form-label">Specific users</span>
          <select
            className="input"
            multiple
            size={5}
            value={value.recipient_user_ids}
            onChange={(e) => {
              set(
                'recipient_user_ids',
                Array.from(e.target.selectedOptions, (o) => o.value),
              );
            }}
          >
            {base.lookups.users.map((u) => (
              <option key={u.id} value={u.id}>
                {u.full_name}
              </option>
            ))}
          </select>
        </label>
      </fieldset>
      <fieldset className="notif-mode">
        <legend className="form-label">Channels</legend>
        {(['IN_APP', 'EMAIL'] as Channel[]).map((c) => (
          <label key={c} className="notif-filters__check">
            <input
              type="checkbox"
              checked={value.channels.includes(c)}
              onChange={() => {
                set('channels', toggleIn(value.channels, c));
              }}
            />
            {c === 'IN_APP' ? 'In-app' : 'Email'}
          </label>
        ))}
      </fieldset>
      <label className="notif-filters__field">
        <span className="form-label">Priority</span>
        <select
          className="input"
          value={value.priority ?? ''}
          onChange={(e) => {
            set('priority', (e.target.value || null) as Priority | null);
          }}
        >
          <option value="">As published by the event</option>
          <option value="HIGH">High</option>
          <option value="NORMAL">Normal</option>
          <option value="LOW">Low</option>
        </select>
      </label>
      <label className="notif-filters__check">
        <input
          type="checkbox"
          checked={value.is_active}
          onChange={(e) => {
            set('is_active', e.target.checked);
          }}
        />
        Active
      </label>
      <div className="notif-rule__actions">
        <Button type="submit" variant="primary" disabled={busy || value.channels.length === 0}>
          Save rule
        </Button>
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

// --------------------------------------------------------------------------------------------
// Escalations (DEC-30)
// --------------------------------------------------------------------------------------------

function EscalationEditor({ lookups }: { lookups: Lookups }) {
  const fetcher = useCallback(() => notificationAdminApi.escalationRules(), []);
  const rules = useApiQuery<EscalationRule[]>(fetcher);
  const [form, setForm] = useState<(EscalationRuleInput & { id: string | null }) | null>(null);
  const [reason, setReason] = useState('');
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  if (rules.error) return <ErrorState error={rules.error} onRetry={rules.reload} />;
  if (!rules.data) return <LoadingState label="Loading escalation rules…" />;

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      setForm(null);
      rules.reload();
    } catch (err) {
      setError(toApiError(err));
    } finally {
      setBusy(false);
    }
  };
  const input = (
    r: EscalationRule,
    patch: Partial<EscalationRuleInput> = {},
  ): EscalationRuleInput => ({
    workflow_step_id: r.workflow_step_id,
    after_hours: r.after_hours,
    notify_role_code: r.notify_role_code,
    notify_user_id: r.notify_user_id,
    is_active: r.is_active,
    reason: reasonOrNull(reason),
    ...patch,
  });

  return (
    <section aria-label="Escalation rules">
      <p className="dash-muted" style={{ marginTop: 0 }}>
        A level fires once per open task, <em>after</em> the step&apos;s SLA is breached by the
        given hours (DEC-30: seeded disabled). Levels are numbered by their hours among the
        step&apos;s active rules.
      </p>
      <div className="notif-filters">
        <label className="notif-filters__field">
          <span className="form-label">Reason for changes (optional)</span>
          <input
            className="input"
            value={reason}
            maxLength={500}
            onChange={(e) => {
              setReason(e.target.value);
            }}
          />
        </label>
        <Button
          type="button"
          variant="primary"
          onClick={() => {
            setForm({
              id: null,
              workflow_step_id: lookups.steps[0]?.id ?? '',
              after_hours: 1,
              notify_role_code: lookups.roles[0]?.code ?? null,
              notify_user_id: null,
              is_active: false,
            });
          }}
        >
          Add level
        </Button>
      </div>
      {error ? <ErrorState error={error} title="Could not save" /> : null}
      {form ? (
        <form
          className="dash-card notif-form"
          aria-label="Escalation level"
          onSubmit={(e) => {
            e.preventDefault();
            const { id, ...body } = form;
            const payload = { ...body, reason: reasonOrNull(reason) };
            void run(() =>
              id
                ? notificationAdminApi.updateEscalationRule(id, payload)
                : notificationAdminApi.createEscalationRule(payload),
            );
          }}
        >
          <label className="notif-filters__field">
            <span className="form-label">Workflow step</span>
            <select
              className="input"
              value={form.workflow_step_id}
              onChange={(e) => {
                setForm({ ...form, workflow_step_id: e.target.value });
              }}
            >
              {lookups.steps.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.workflow_code} v{s.version_no} · {s.label}
                  {s.sla_hours !== null ? ` (SLA ${String(s.sla_hours)} h)` : ' (no SLA)'}
                </option>
              ))}
            </select>
          </label>
          <label className="notif-filters__field">
            <span className="form-label">Hours after the SLA breach</span>
            <input
              className="input"
              type="number"
              min={0.01}
              step={0.01}
              required
              value={form.after_hours}
              onChange={(e) => {
                setForm({ ...form, after_hours: Number(e.target.value) });
              }}
            />
          </label>
          <label className="notif-filters__field">
            <span className="form-label">Notify role</span>
            <select
              className="input"
              value={form.notify_role_code ?? ''}
              onChange={(e) => {
                setForm({
                  ...form,
                  notify_role_code: e.target.value || null,
                  notify_user_id: e.target.value ? null : form.notify_user_id,
                });
              }}
            >
              <option value="">— a specific user instead —</option>
              {lookups.roles.map((r) => (
                <option key={r.code} value={r.code}>
                  {r.name}
                </option>
              ))}
            </select>
          </label>
          {form.notify_role_code ? null : (
            <label className="notif-filters__field">
              <span className="form-label">Notify user</span>
              <select
                className="input"
                required
                value={form.notify_user_id ?? ''}
                onChange={(e) => {
                  setForm({ ...form, notify_user_id: e.target.value || null });
                }}
              >
                <option value="">Choose a user</option>
                {lookups.users.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.full_name}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label className="notif-filters__check">
            <input
              type="checkbox"
              checked={form.is_active}
              onChange={(e) => {
                setForm({ ...form, is_active: e.target.checked });
              }}
            />
            Active
          </label>
          <div className="notif-rule__actions">
            <Button type="submit" variant="primary" disabled={busy}>
              Save level
            </Button>
            <Button
              type="button"
              variant="ghost"
              onClick={() => {
                setForm(null);
              }}
            >
              Cancel
            </Button>
          </div>
        </form>
      ) : null}
      {rules.data.length === 0 ? (
        <EmptyState title="No escalation levels" />
      ) : (
        <div className="table-responsive">
          <table className="table">
            <thead>
              <tr>
                <th>Step</th>
                <th>Level</th>
                <th>After breach</th>
                <th>Notify</th>
                <th>Status</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {rules.data.map((r) => (
                <tr key={r.id}>
                  <td>
                    {r.step_label}
                    <div className="dash-muted">
                      {r.workflow_code} v{r.workflow_version_no}
                      {r.sla_hours !== null ? ` · SLA ${String(r.sla_hours)} h` : ''}
                    </div>
                  </td>
                  <td>{r.level_no}</td>
                  <td>{r.after_hours} h</td>
                  <td>{r.notify_role_name ?? r.notify_user_name}</td>
                  <td>
                    <Badge variant={r.is_active ? 'success' : 'neutral'}>
                      {r.is_active ? 'Active' : 'Inactive'}
                    </Badge>
                  </td>
                  <td style={{ whiteSpace: 'nowrap' }}>
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      disabled={busy}
                      onClick={() =>
                        void run(() =>
                          notificationAdminApi.updateEscalationRule(
                            r.id,
                            input(r, { is_active: !r.is_active }),
                          ),
                        )
                      }
                    >
                      {r.is_active ? 'Disable' : 'Enable'}
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      onClick={() => {
                        setForm({ id: r.id, ...input(r) });
                      }}
                    >
                      Edit
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

// --------------------------------------------------------------------------------------------
// Email templates
// --------------------------------------------------------------------------------------------

function TemplateEditor({ events }: { events: EventType[] }) {
  const fetcher = useCallback(() => notificationAdminApi.templates(), []);
  const templates = useApiQuery<Template[]>(fetcher);
  const [code, setCode] = useState(events[0]?.code ?? '');
  const current = templates.data?.find((t) => t.event_type === code);
  const [subject, setSubject] = useState<string | null>(null);
  const [body, setBody] = useState<string | null>(null);
  const [reason, setReason] = useState('');
  const [preview, setPreview] = useState<TemplatePreview | null>(null);
  const [versions, setVersions] = useState<Template[]>([]);
  const [error, setError] = useState<ApiError | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const subj = subject ?? current?.subject ?? '';
  const text = body ?? current?.body ?? '';

  useEffect(() => {
    if (!code) return;
    let active = true;
    notificationAdminApi.templateVersions(code).then(
      (v) => {
        if (active) setVersions(v);
      },
      (err: unknown) => {
        if (active) setError(toApiError(err));
      },
    );
    return () => {
      active = false;
    };
  }, [code, current?.version_no]);

  useEffect(() => {
    if (!code || !subj.trim() || !text.trim()) return;
    let active = true;
    const timer = window.setTimeout(() => {
      notificationAdminApi.preview({ event_type: code, subject: subj, body: text }).then(
        (p) => {
          if (active) setPreview(p);
        },
        (err: unknown) => {
          if (active) setError(toApiError(err));
        },
      );
    }, 300);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [code, subj, text]);

  if (templates.error) return <ErrorState error={templates.error} onRetry={templates.reload} />;
  if (!templates.data) return <LoadingState label="Loading templates…" />;

  const save = async () => {
    setError(null);
    setMessage(null);
    try {
      const saved = await notificationAdminApi.saveTemplate(code, {
        subject: subj,
        body: text,
        reason: reasonOrNull(reason),
      });
      setSubject(null);
      setBody(null);
      setReason('');
      setMessage(`Published version ${String(saved.version_no)}.`);
      templates.reload();
    } catch (err) {
      setError(toApiError(err));
    }
  };

  return (
    <section aria-label="Email templates" className="notif-templates">
      <div className="notif-form">
        <label className="notif-filters__field">
          <span className="form-label">Event</span>
          <select
            className="input"
            value={code}
            onChange={(e) => {
              setCode(e.target.value);
              setSubject(null);
              setBody(null);
              setPreview(null);
              setMessage(null);
            }}
          >
            {events.map((ev) => (
              <option key={ev.code} value={ev.code}>
                {ev.label}
              </option>
            ))}
          </select>
        </label>
        <p className="dash-muted" style={{ margin: 0 }}>
          Current: v{current?.version_no ?? '—'}
          {current ? `, published ${formatDateTime(current.published_at)}` : ''}
        </p>
        <label className="notif-filters__field">
          <span className="form-label">Subject</span>
          <input
            className="input"
            value={subj}
            maxLength={300}
            onChange={(e) => {
              setSubject(e.target.value);
            }}
          />
        </label>
        <label className="notif-filters__field">
          <span className="form-label">Body (plain text)</span>
          <textarea
            className="input"
            rows={10}
            value={text}
            onChange={(e) => {
              setBody(e.target.value);
            }}
          />
        </label>
        {preview ? (
          <p className="dash-muted" style={{ margin: 0 }}>
            Placeholders: {preview.placeholders.map((p) => `{${p}}`).join(' ')}
          </p>
        ) : null}
        <label className="notif-filters__field">
          <span className="form-label">Reason (optional)</span>
          <input
            className="input"
            value={reason}
            maxLength={500}
            onChange={(e) => {
              setReason(e.target.value);
            }}
          />
        </label>
        {error ? <ErrorState error={error} title="Template problem" /> : null}
        {message ? (
          <p role="status" className="dash-chip" style={{ background: 'var(--color-success-bg)' }}>
            {message}
          </p>
        ) : null}
        <Button
          type="button"
          variant="primary"
          disabled={subject === null && body === null}
          onClick={() => void save()}
        >
          Publish new version
        </Button>
      </div>
      <div className="dash-card" aria-label="Preview" data-testid="template-preview">
        <h2 className="dash-card__title">Preview (sample data)</h2>
        {preview ? (
          <>
            {preview.unknown_placeholders.length ? (
              <p className="banner">
                Unknown placeholders: {preview.unknown_placeholders.map((p) => `{${p}}`).join(', ')}
              </p>
            ) : null}
            <p>
              <strong>Subject:</strong> {preview.subject}
            </p>
            <pre className="notif-preview">{preview.body}</pre>
          </>
        ) : (
          <LoadingState label="Rendering…" />
        )}
        {versions.length > 1 ? (
          <details>
            <summary>Version history ({versions.length})</summary>
            <ul>
              {versions.map((v) => (
                <li key={v.id}>
                  v{v.version_no} · {v.status} · {formatDateTime(v.published_at)}
                  {v.change_reason ? ` · ${v.change_reason}` : ''}
                </li>
              ))}
            </ul>
          </details>
        ) : null}
      </div>
    </section>
  );
}

// --------------------------------------------------------------------------------------------
// Delivery log
// --------------------------------------------------------------------------------------------

function DeliveryLogView() {
  const [status, setStatus] = useState('');
  const [channel, setChannel] = useState('');
  const fetcher = useCallback(
    () => notificationAdminApi.deliveries({ status, channel, limit: 100 }),
    [status, channel],
  );
  const log = useApiQuery<DeliveryLog>(fetcher);
  return (
    <section aria-label="Delivery log">
      <div className="notif-filters">
        <label className="notif-filters__field">
          <span className="form-label">Channel</span>
          <select
            className="input"
            value={channel}
            onChange={(e) => {
              setChannel(e.target.value);
            }}
          >
            <option value="">All</option>
            <option value="IN_APP">In-app</option>
            <option value="EMAIL">Email</option>
          </select>
        </label>
        <label className="notif-filters__field">
          <span className="form-label">Status</span>
          <select
            className="input"
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
            }}
          >
            <option value="">All</option>
            {['SENT', 'PENDING', 'DIGEST', 'SKIPPED', 'FAILED'].map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <Button type="button" variant="ghost" onClick={log.reload}>
          Refresh
        </Button>
      </div>
      {log.error ? <ErrorState error={log.error} onRetry={log.reload} /> : null}
      {!log.data && !log.error ? <LoadingState label="Loading deliveries…" /> : null}
      {log.data ? (
        <>
          <p className="dash-muted">
            Outbox: {log.data.outbox.PENDING ?? 0} pending · {log.data.outbox.FAILED ?? 0} failed ·{' '}
            {log.data.outbox.DISPATCHED ?? 0} dispatched
          </p>
          {log.data.items.length === 0 ? (
            <EmptyState title="No deliveries match" />
          ) : (
            <div className="table-responsive">
              <table className="table">
                <thead>
                  <tr>
                    <th>When</th>
                    <th>Event</th>
                    <th>To</th>
                    <th>Channel</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {log.data.items.map((d) => (
                    <tr key={d.id}>
                      <td>{formatDateTime(d.created_at)}</td>
                      <td>
                        {d.title || d.event_label}
                        <div className="dash-muted">{d.event_label}</div>
                      </td>
                      <td>
                        {d.user_name}
                        {d.email_to ? <div className="dash-muted">{d.email_to}</div> : null}
                      </td>
                      <td>{d.channel === 'IN_APP' ? 'In-app' : 'Email'}</td>
                      <td>
                        <Badge
                          variant={
                            d.status === 'SENT'
                              ? 'success'
                              : d.status === 'FAILED'
                                ? 'danger'
                                : d.status === 'SKIPPED'
                                  ? 'warning'
                                  : 'info'
                          }
                        >
                          {d.status}
                        </Badge>
                        {d.skip_reason ? <div className="dash-muted">{d.skip_reason}</div> : null}
                        {d.last_error ? <div className="dash-muted">{d.last_error}</div> : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      ) : null}
    </section>
  );
}
