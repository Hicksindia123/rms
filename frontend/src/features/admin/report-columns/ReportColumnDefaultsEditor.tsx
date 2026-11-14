import { useCallback, useMemo, useState } from 'react';

import {
  Button,
  Checkbox,
  EmptyState,
  ErrorState,
  Input,
  LoadingState,
  Select,
} from '@/components/ui';
import { useApiQuery } from '@/hooks/useApiQuery';
import { apiRequest, toApiError, type ApiError } from '@/lib/api/client';
import {
  reportsApi,
  type ReportDefinition,
  type ReportGroup,
  type RoleColumnDefaults,
} from '@/features/reports/api';

interface RoleRef {
  code: string;
  name: string;
}

interface Loaded {
  groups: ReportGroup[];
  roles: RoleRef[];
  defaults: RoleColumnDefaults[];
}

/** §10 "Report columns": default visible columns per report per role (config_change_log). */
export function ReportColumnDefaultsEditor() {
  const fetcher = useCallback(
    async (): Promise<Loaded> => ({
      groups: await reportsApi.catalogue(),
      roles: await apiRequest<RoleRef[]>('/admin/report-column-defaults/roles'),
      defaults: await reportsApi.roleDefaults(),
    }),
    [],
  );
  const loaded = useApiQuery<Loaded>(fetcher);
  const [report, setReport] = useState('');
  const [role, setRole] = useState('');

  if (loaded.error) {
    return (
      <ErrorState
        title="Report column defaults could not be loaded"
        error={{
          message: loaded.error.message,
          code: loaded.error.code,
          requestId: loaded.error.requestId,
        }}
        onRetry={loaded.reload}
      />
    );
  }
  if (!loaded.data) return <LoadingState label="Loading report column defaults…" />;
  const { groups, roles, defaults } = loaded.data;
  const reports = groups.flatMap((g) => g.reports);

  return (
    <div className="page">
      <h2 className="page__title">Report columns</h2>
      <p className="page__subtitle">
        Choose the columns each role sees by default. A user&apos;s own column choice still wins.
      </p>
      <div className="report-admin__pickers">
        <div>
          <label className="form-label" htmlFor="rcd-report">
            Report
          </label>
          <Select
            id="rcd-report"
            value={report}
            placeholder="Choose a report…"
            options={reports.map((r) => ({ value: r.code, label: `${r.code} ${r.title}` }))}
            onChange={(e) => {
              setReport(e.target.value);
            }}
          />
        </div>
        <div>
          <label className="form-label" htmlFor="rcd-role">
            Role
          </label>
          <Select
            id="rcd-role"
            value={role}
            placeholder="Choose a role…"
            options={roles.map((r) => ({ value: r.code, label: r.name }))}
            onChange={(e) => {
              setRole(e.target.value);
            }}
          />
        </div>
      </div>
      {report && role ? (
        <DefaultsForm
          key={`${report}|${role}`}
          report={report}
          role={role}
          current={defaults.find((d) => d.report_code === report && d.role_code === role) ?? null}
          onSaved={loaded.reload}
        />
      ) : (
        <EmptyState
          title="Choose a report and a role"
          hint={`${String(defaults.length)} role default(s) are set across all reports.`}
        />
      )}
    </div>
  );
}

function DefaultsForm({
  report,
  role,
  current,
  onSaved,
}: {
  report: string;
  role: string;
  current: RoleColumnDefaults | null;
  onSaved: () => void;
}) {
  const fetcher = useCallback(() => reportsApi.definition(report), [report]);
  const def = useApiQuery<ReportDefinition>(fetcher);
  if (def.error) {
    return (
      <ErrorState
        error={{ message: def.error.message, code: def.error.code, requestId: def.error.requestId }}
        onRetry={def.reload}
      />
    );
  }
  if (!def.data) return <LoadingState />;
  return (
    <DefaultsChecklist definition={def.data} role={role} current={current} onSaved={onSaved} />
  );
}

function DefaultsChecklist({
  definition,
  role,
  current,
  onSaved,
}: {
  definition: ReportDefinition;
  role: string;
  current: RoleColumnDefaults | null;
  onSaved: () => void;
}) {
  const initial = useMemo(
    () =>
      new Set(
        current ? current.columns : definition.columns.filter((c) => c.default).map((c) => c.key),
      ),
    [current, definition],
  );
  const [chosen, setChosen] = useState<Set<string>>(initial);
  const [reason, setReason] = useState('');
  const [error, setError] = useState<ApiError | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const ordered = definition.columns.map((c) => c.key).filter((k) => chosen.has(k));

  const run = (fn: () => Promise<unknown>, message: string) => {
    setBusy(true);
    setError(null);
    setSaved(null);
    fn().then(
      () => {
        setBusy(false);
        setSaved(message);
        onSaved();
      },
      (err: unknown) => {
        setBusy(false);
        setError(toApiError(err));
      },
    );
  };

  return (
    <section className="report-admin__form" aria-label="Default columns">
      <p className="page__subtitle">
        {current
          ? 'This role has its own default.'
          : 'No role default yet: users of this role see the report default below.'}
      </p>
      {error ? (
        <ErrorState
          error={{ message: error.message, code: error.code, requestId: error.requestId }}
        />
      ) : null}
      {saved ? (
        <p role="status" className="report-admin__saved">
          {saved}
        </p>
      ) : null}
      <fieldset className="column-chooser">
        <legend className="sr-only">Default columns</legend>
        {definition.columns.map((c) => (
          <Checkbox
            key={c.key}
            id={`rcd-${c.key}`}
            label={c.label}
            checked={chosen.has(c.key)}
            onChange={(e) => {
              const next = new Set(chosen);
              if (e.target.checked) next.add(c.key);
              else next.delete(c.key);
              setChosen(next);
            }}
          />
        ))}
      </fieldset>
      <label className="form-label" htmlFor="rcd-reason">
        Reason (optional, kept in the configuration history)
      </label>
      <Input
        id="rcd-reason"
        value={reason}
        maxLength={500}
        onChange={(e) => {
          setReason(e.target.value);
        }}
      />
      <div className="report-admin__actions">
        <Button
          type="button"
          variant="primary"
          isLoading={busy}
          disabled={ordered.length === 0}
          onClick={() => {
            run(
              () => reportsApi.saveRoleDefaults(definition.code, role, ordered, reason.trim()),
              'Default columns saved.',
            );
          }}
        >
          Save default
        </Button>
        {current ? (
          <Button
            type="button"
            variant="secondary"
            disabled={busy}
            onClick={() => {
              run(
                () => reportsApi.deleteRoleDefaults(definition.code, role, reason.trim()),
                'Role default removed.',
              );
            }}
          >
            Remove role default
          </Button>
        ) : null}
      </div>
    </section>
  );
}
