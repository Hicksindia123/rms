import { useCallback, useMemo, useState } from 'react';
import { ArrowRight, FileWarning, Search, X } from 'lucide-react';

import { PageHeader } from '@/components/erp';
import { Badge, Button, EmptyState, ErrorState, LoadingState } from '@/components/ui';
import { useAuth } from '@/features/auth/useAuth';
import { AuditBanner } from '@/features/container-audit/AuditBanner';
import type { MyJourney } from '@/features/journey/api';
import { JourneyBoard, JourneyQueueView } from '@/features/journey/JourneyHome';
import { age, humanize } from '@/features/goods-slips/format';
import { useApiQuery } from '@/hooks/useApiQuery';
import { apiRequest } from '@/lib/api/client';

import { dueText, groupTasks, PAGE_SIZE, stepScreen, urgency, type TaskPage } from './tasks';

/**
 * "My Work" home. Change plan Phase 10 (AMD-22): the user's journey steps (count + next GS per
 * step, from GET /me/journey) or one step's GS list (journeyCode), then the open
 * workflow tasks for the user's roles (GET /tasks/mine), by step.
 */
export function MyWorkView({
  stepFilter,
  journeyCode,
  journey,
  journeyFetchedAt = 0,
  onNavigate,
  onOpenAudit,
}: {
  stepFilter?: string | null | undefined;
  journeyCode?: string | null | undefined;
  journey?: MyJourney | null | undefined;
  journeyFetchedAt?: number | undefined;
  onNavigate?: ((path: string) => void) | undefined;
  onOpenAudit?: (() => void) | undefined;
}) {
  const { status } = useAuth();
  const [searchTerm, setSearchTerm] = useState('');
  const signedIn = status === 'signed-in';
  const fetcher = useCallback(
    () =>
      signedIn
        ? apiRequest<TaskPage>('/tasks/mine', {
            query: { status: 'OPEN', page_size: PAGE_SIZE, step_code: stepFilter ?? null },
          }).then((page) => ({ page, fetchedAt: Date.now() }))
        : Promise.resolve(null),
    [signedIn, stepFilter],
  );
  const query = useApiQuery<{ page: TaskPage; fetchedAt: number } | null>(fetcher);
  const data = query.loading ? null : (query.data?.page ?? null);
  // "Now" is when the data arrived, so ages and due chips are stable between renders.
  const now = query.data?.fetchedAt ?? 0;
  const { error, reload } = query;

  const term = searchTerm.trim().toLowerCase();
  const groups = useMemo(() => {
    const items = (data?.items ?? []).filter(
      (t) =>
        !term ||
        t.gs_no.toLowerCase().includes(term) ||
        (t.party_name ?? '').toLowerCase().includes(term),
    );
    return groupTasks(items, now);
  }, [data, term, now]);
  const shown = groups.reduce((n, g) => n + g.tasks.length, 0);
  const overdue = groups.reduce((n, g) => n + g.overdue, 0);
  const filterLabel = stepFilter
    ? (data?.items.find((t) => t.step_code === stepFilter)?.step_label ?? humanize(stepFilter))
    : null;

  return (
    <div className="page" style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
      <PageHeader
        title="My Work"
        subtitle="Where each of your steps stands, and the next goods slip to act on"
      />

      <AuditBanner onOpenAudit={onOpenAudit} />

      {signedIn && journeyCode && onNavigate ? (
        <JourneyQueueView code={journeyCode} onNavigate={onNavigate} />
      ) : null}
      {signedIn && !journeyCode && journey && onNavigate ? (
        <JourneyBoard journey={journey} now={journeyFetchedAt} onNavigate={onNavigate} />
      ) : null}
      {!journeyCode && signedIn ? (
        <h2 className="mywork-group__title">
          <span>Assigned tasks</span>
        </h2>
      ) : null}

      {status === 'loading' ? <LoadingState /> : null}
      {status === 'signed-out' ? (
        <EmptyState title="Sign in to see your tasks" hint="Use Sign In in the menu." />
      ) : null}
      {status === 'error' ? (
        <ErrorState error={{ message: 'Your session could not be loaded. Sign in again.' }} />
      ) : null}

      {signedIn && !journeyCode ? (
        error ? (
          <ErrorState error={error} onRetry={reload} title="Could not load your tasks" />
        ) : !data ? (
          <LoadingState label="Loading tasks…" />
        ) : (
          <>
            <div
              style={{ display: 'flex', flexWrap: 'wrap', gap: '0.75rem', alignItems: 'center' }}
            >
              <div style={{ position: 'relative', flex: '1 1 220px', maxWidth: 360 }}>
                <label htmlFor="search-tasks" className="sr-only">
                  Search assigned tasks
                </label>
                <Search
                  size={16}
                  aria-hidden="true"
                  style={{ position: 'absolute', left: '0.75rem', top: '14px', color: '#94a3b8' }}
                />
                <input
                  id="search-tasks"
                  type="search"
                  className="input"
                  value={searchTerm}
                  onChange={(e) => {
                    setSearchTerm(e.target.value);
                  }}
                  placeholder="Search GS or party..."
                  style={{ paddingLeft: '2.25rem' }}
                />
              </div>
              <span className="dash-muted" style={{ fontSize: '0.875rem' }}>
                {data.total} open{overdue > 0 ? ` · ${String(overdue)} overdue` : ''}
                {data.total > data.items.length
                  ? ` · showing the ${String(data.items.length)} most urgent`
                  : ''}
              </span>
              {stepFilter && onNavigate ? (
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => {
                    onNavigate('/mywork');
                  }}
                  aria-label={`Clear step filter ${filterLabel ?? ''}`}
                >
                  {filterLabel} <X size={14} aria-hidden="true" />
                </Button>
              ) : null}
            </div>

            {shown === 0 ? (
              <EmptyState
                title={term ? 'No tasks match your search' : 'No open tasks'}
                {...(term
                  ? {}
                  : { hint: 'New tasks appear here when a goods slip reaches your step.' })}
              />
            ) : (
              groups.map((g) => (
                <section key={g.code} className="mywork-group" aria-labelledby={`step-${g.code}`}>
                  <h2 id={`step-${g.code}`} className="mywork-group__title">
                    <span>{g.label}</span>
                    <span style={{ display: 'inline-flex', gap: '0.5rem', alignItems: 'center' }}>
                      {g.overdue > 0 ? (
                        <span className="dash-chip dash-chip--danger">{g.overdue} overdue</span>
                      ) : null}
                      <Badge variant="info">{g.tasks.length}</Badge>
                    </span>
                  </h2>
                  <ul className="mywork-cards">
                    {g.tasks.map((t) => {
                      const u = urgency(t, now);
                      const due = dueText(t, u, now);
                      return (
                        <li
                          key={t.id}
                          data-testid="task-card"
                          className={`mywork-card${u === 'normal' ? '' : ` mywork-card--${u}`}`}
                        >
                          <div className="mywork-card__main">
                            <div
                              style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: '0.5rem',
                                flexWrap: 'wrap',
                              }}
                            >
                              <span style={{ fontWeight: 700, wordBreak: 'break-all' }}>
                                {t.gs_no}
                              </span>
                              <Badge variant="info">{t.step_label ?? humanize(t.step_code)}</Badge>
                              {t.missing_documentation ? (
                                <span
                                  role="img"
                                  aria-label="Missing documentation"
                                  title="Missing documentation"
                                >
                                  <FileWarning size={16} color="#d97706" aria-hidden="true" />
                                </span>
                              ) : null}
                              {due ? (
                                <span
                                  className={`dash-chip ${u === 'overdue' ? 'dash-chip--danger' : 'dash-chip--warning'}`}
                                >
                                  {due}
                                </span>
                              ) : null}
                            </div>
                            <span style={{ fontSize: '0.875rem', color: '#334155' }}>
                              {t.party_name}
                              {t.station_name ? ` · ${t.station_name}` : ''}
                            </span>
                            <span className="dash-muted">
                              Cartons: {t.carton_count} · Waiting {age(t.created_at, now)}
                            </span>
                          </div>
                          {onNavigate ? (
                            <div className="mywork-card__actions">
                              <Button
                                type="button"
                                variant="secondary"
                                onClick={() => {
                                  onNavigate(stepScreen(t.step_code, t.gs_id));
                                }}
                                aria-label={`Open ${t.step_label ?? humanize(t.step_code)} for ${t.gs_no}`}
                              >
                                Open <ArrowRight size={14} aria-hidden="true" />
                              </Button>
                              <Button
                                type="button"
                                variant="secondary"
                                onClick={() => {
                                  onNavigate(`/gs/${t.gs_id}`);
                                }}
                                aria-label={`Goods slip ${t.gs_no}`}
                              >
                                GS
                              </Button>
                            </div>
                          ) : null}
                        </li>
                      );
                    })}
                  </ul>
                </section>
              ))
            )}
          </>
        )
      ) : null}
    </div>
  );
}
