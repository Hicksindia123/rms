import { useCallback, useMemo, useState } from 'react';
import { ArrowDown, ArrowUp, Plus, Save, X } from 'lucide-react';

import { PageHeader } from '@/components/erp';
import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  Input,
  LoadingState,
  Select,
} from '@/components/ui';
import { useApiQuery } from '@/hooks/useApiQuery';
import { toApiError, type ApiError } from '@/lib/api/client';

import {
  fetchJourneyConfig,
  saveJourneyStep,
  saveRoleJourney,
  type JourneyConfig,
  type JourneyStep,
} from './api';

/**
 * Admin -> Role Journeys (change plan Phase 10, AMD-22, DEC-49): which journey steps and tools each
 * role sees, in the order of its working journey, and the labels / hints of each entry. Every
 * change needs a reason and is written to the config change log. Entries of an on-hold module
 * (setting features.on_hold, AMD-21) stay assigned but are hidden from the menu.
 */
export function RoleJourneysPage({ canEdit }: { canEdit: boolean }) {
  const fetcher = useCallback(() => fetchJourneyConfig(), []);
  const { data, error, loading, reload, setData } = useApiQuery(fetcher);

  return (
    <div className="page" style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
      <PageHeader
        title="Role Journeys"
        subtitle="The menu of each role, in the order of its working journey"
      />
      {error ? (
        <ErrorState error={error} onRetry={reload} title="Could not load the role journeys" />
      ) : loading || !data ? (
        <LoadingState label="Loading role journeys…" />
      ) : (
        <>
          <RoleEditor config={data} canEdit={canEdit} onSaved={setData} />
          <StepCatalogue config={data} canEdit={canEdit} onSaved={setData} />
        </>
      )}
    </div>
  );
}

function RoleEditor({
  config,
  canEdit,
  onSaved,
}: {
  config: JourneyConfig;
  canEdit: boolean;
  onSaved: (c: JourneyConfig) => void;
}) {
  const [roleCode, setRoleCode] = useState(config.roles[0]?.role_code ?? '');
  const role = config.roles.find((r) => r.role_code === roleCode);
  const [draft, setDraft] = useState<{ role: string; codes: string[] } | null>(null);
  const codes = draft && draft.role === roleCode ? draft.codes : (role?.step_codes ?? []);
  const [addCode, setAddCode] = useState('');
  const [reason, setReason] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<ApiError | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  const byCode = useMemo(() => new Map(config.steps.map((s) => [s.code, s])), [config.steps]);
  const dirty = draft !== null && draft.role === roleCode;
  const available = config.steps.filter((s) => !codes.includes(s.code));

  const change = (next: string[]) => {
    setDraft({ role: roleCode, codes: next });
    setSaved(null);
  };
  const move = (i: number, d: -1 | 1) => {
    const next = [...codes];
    const [x] = next.splice(i, 1);
    if (x) next.splice(i + d, 0, x);
    change(next);
  };

  const save = () => {
    setSaving(true);
    setSaveError(null);
    saveRoleJourney(roleCode, codes, reason.trim()).then(
      (r) => {
        onSaved({
          ...config,
          roles: config.roles.map((x) => (x.role_code === r.role_code ? r : x)),
        });
        setDraft(null);
        setReason('');
        setSaving(false);
        setSaved(`Saved the journey of ${r.role_name}.`);
      },
      (err: unknown) => {
        setSaveError(toApiError(err));
        setSaving(false);
      },
    );
  };

  if (config.roles.length === 0) {
    return <EmptyState title="No roles" hint="Roles are created in User Management." />;
  }

  return (
    <section className="card" style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
      <h2 className="mywork-group__title">
        <span>Journey per role</span>
      </h2>
      <label htmlFor="journey-role" className="form-label">
        Role
      </label>
      <Select
        id="journey-role"
        value={roleCode}
        placeholder="-- Select a role --"
        options={config.roles.map((r) => ({ value: r.role_code, label: r.role_name }))}
        onChange={(e) => {
          setRoleCode(e.target.value);
          setSaved(null);
          setSaveError(null);
        }}
      />

      {codes.length === 0 ? (
        <EmptyState title="This role has no menu entries" hint="Add steps or tools below." />
      ) : (
        <ol className="mywork-cards" style={{ gridTemplateColumns: 'minmax(0, 1fr)' }}>
          {codes.map((code, i) => {
            const s = byCode.get(code);
            const onHold = s?.feature_code ? config.on_hold.includes(s.feature_code) : false;
            return (
              <li key={code} className="mywork-card" data-testid="role-journey-entry">
                <div className="mywork-card__main">
                  <span style={{ fontWeight: 600 }}>
                    {i + 1}. {s?.label ?? code}
                  </span>
                  <span style={{ display: 'flex', gap: '0.375rem', flexWrap: 'wrap' }}>
                    <Badge variant={s?.kind === 'STEP' ? 'info' : 'neutral'}>
                      {s?.kind === 'STEP' ? 'Journey step' : 'Tool'}
                    </Badge>
                    {onHold ? <Badge variant="warning">On hold: hidden</Badge> : null}
                    {s && !s.is_active ? <Badge variant="neutral">Inactive</Badge> : null}
                  </span>
                </div>
                {canEdit ? (
                  <div className="mywork-card__actions">
                    <Button
                      type="button"
                      variant="ghost"
                      disabled={i === 0}
                      onClick={() => {
                        move(i, -1);
                      }}
                      aria-label={`Move ${s?.label ?? code} up`}
                    >
                      <ArrowUp size={16} aria-hidden="true" />
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      disabled={i === codes.length - 1}
                      onClick={() => {
                        move(i, 1);
                      }}
                      aria-label={`Move ${s?.label ?? code} down`}
                    >
                      <ArrowDown size={16} aria-hidden="true" />
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      onClick={() => {
                        change(codes.filter((c) => c !== code));
                      }}
                      aria-label={`Remove ${s?.label ?? code}`}
                    >
                      <X size={16} aria-hidden="true" />
                    </Button>
                  </div>
                ) : null}
              </li>
            );
          })}
        </ol>
      )}

      {canEdit ? (
        <>
          {available.length > 0 ? (
            <div
              style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', alignItems: 'flex-end' }}
            >
              <div style={{ flex: '1 1 220px', minWidth: 0 }}>
                <label htmlFor="journey-add" className="form-label">
                  Add a step or tool
                </label>
                <Select
                  id="journey-add"
                  value={addCode}
                  placeholder="-- Select --"
                  options={available.map((s) => ({
                    value: s.code,
                    label: `${s.label} (${s.kind === 'STEP' ? 'step' : 'tool'})`,
                  }))}
                  onChange={(e) => {
                    setAddCode(e.target.value);
                  }}
                />
              </div>
              <Button
                type="button"
                variant="outline"
                disabled={!addCode}
                onClick={() => {
                  change([...codes, addCode]);
                  setAddCode('');
                }}
              >
                <Plus size={16} aria-hidden="true" /> Add
              </Button>
            </div>
          ) : null}
          <label htmlFor="journey-reason" className="form-label">
            Reason for the change
          </label>
          <Input
            id="journey-reason"
            value={reason}
            maxLength={500}
            onChange={(e) => {
              setReason(e.target.value);
            }}
            placeholder="e.g. Aman also receives from departments"
          />
          {saveError ? <ErrorState error={saveError} title="Could not save" /> : null}
          {saved ? (
            <p role="status" style={{ margin: 0, color: 'var(--color-success)' }}>
              {saved}
            </p>
          ) : null}
          <div>
            <Button
              type="button"
              variant="primary"
              disabled={!dirty || reason.trim().length < 3 || saving}
              onClick={save}
            >
              <Save size={16} aria-hidden="true" /> {saving ? 'Saving…' : 'Save journey'}
            </Button>
          </div>
        </>
      ) : null}
    </section>
  );
}

function StepCatalogue({
  config,
  canEdit,
  onSaved,
}: {
  config: JourneyConfig;
  canEdit: boolean;
  onSaved: (c: JourneyConfig) => void;
}) {
  const [editing, setEditing] = useState<string | null>(null);
  return (
    <section className="card" style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
      <h2 className="mywork-group__title">
        <span>Steps and tools</span>
        <Badge variant="info">{config.steps.length}</Badge>
      </h2>
      <p className="journey-step__hint">
        Labels and hints shown in the menu and on My Work. Codes, screens and queues are fixed.
      </p>
      <ul className="mywork-cards" style={{ gridTemplateColumns: 'minmax(0, 1fr)' }}>
        {config.steps.map((s) =>
          editing === s.code ? (
            <StepEditForm
              key={s.code}
              step={s}
              onCancel={() => {
                setEditing(null);
              }}
              onSaved={(updated) => {
                onSaved({
                  ...config,
                  steps: config.steps.map((x) => (x.code === updated.code ? updated : x)),
                });
                setEditing(null);
              }}
            />
          ) : (
            <li key={s.code} className="mywork-card" data-testid="journey-step-row">
              <div className="mywork-card__main">
                <span style={{ fontWeight: 600 }}>{s.label}</span>
                <span className="dash-muted" style={{ wordBreak: 'break-word' }}>
                  {s.code}
                  {s.hint ? ` · ${s.hint}` : ''}
                </span>
                <span style={{ display: 'flex', gap: '0.375rem', flexWrap: 'wrap' }}>
                  <Badge variant={s.kind === 'STEP' ? 'info' : 'neutral'}>
                    {s.kind === 'STEP' ? 'Journey step' : 'Tool'}
                  </Badge>
                  {s.feature_code && config.on_hold.includes(s.feature_code) ? (
                    <Badge variant="warning">On hold</Badge>
                  ) : null}
                  {!s.is_active ? <Badge variant="neutral">Inactive</Badge> : null}
                </span>
              </div>
              {canEdit ? (
                <div className="mywork-card__actions">
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={() => {
                      setEditing(s.code);
                    }}
                    aria-label={`Edit ${s.label}`}
                  >
                    Edit
                  </Button>
                </div>
              ) : null}
            </li>
          ),
        )}
      </ul>
    </section>
  );
}

function StepEditForm({
  step,
  onCancel,
  onSaved,
}: {
  step: JourneyStep;
  onCancel: () => void;
  onSaved: (s: JourneyStep) => void;
}) {
  const [label, setLabel] = useState(step.label);
  const [hint, setHint] = useState(step.hint ?? '');
  const [active, setActive] = useState(step.is_active);
  const [reason, setReason] = useState('');
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);
  const id = `step-${step.code}`;

  const save = () => {
    setSaving(true);
    setErr(null);
    saveJourneyStep(step.code, {
      label: label.trim(),
      hint: hint.trim() || null,
      is_active: active,
      reason: reason.trim(),
    }).then(onSaved, (e: unknown) => {
      setErr(toApiError(e));
      setSaving(false);
    });
  };

  return (
    <li className="mywork-card" style={{ flexDirection: 'column', alignItems: 'stretch' }}>
      <label htmlFor={`${id}-label`} className="form-label">
        Label
      </label>
      <Input
        id={`${id}-label`}
        value={label}
        maxLength={80}
        onChange={(e) => {
          setLabel(e.target.value);
        }}
      />
      <label htmlFor={`${id}-hint`} className="form-label">
        Hint
      </label>
      <Input
        id={`${id}-hint`}
        value={hint}
        maxLength={200}
        onChange={(e) => {
          setHint(e.target.value);
        }}
      />
      <label style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', minHeight: 44 }}>
        <input
          type="checkbox"
          checked={active}
          onChange={(e) => {
            setActive(e.target.checked);
          }}
        />
        Active (shown in menus)
      </label>
      <label htmlFor={`${id}-reason`} className="form-label">
        Reason for the change
      </label>
      <Input
        id={`${id}-reason`}
        value={reason}
        maxLength={500}
        onChange={(e) => {
          setReason(e.target.value);
        }}
      />
      {err ? <ErrorState error={err} title="Could not save" /> : null}
      <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
        <Button
          type="button"
          variant="primary"
          disabled={!label.trim() || reason.trim().length < 3 || saving}
          onClick={save}
        >
          <Save size={16} aria-hidden="true" /> {saving ? 'Saving…' : 'Save'}
        </Button>
        <Button type="button" variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </li>
  );
}
