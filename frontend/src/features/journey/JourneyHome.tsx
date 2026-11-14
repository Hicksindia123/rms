import { useCallback } from 'react';
import { ArrowLeft, ArrowRight } from 'lucide-react';

import { Badge, Button, EmptyState, ErrorState, LoadingState } from '@/components/ui';
import { age } from '@/features/goods-slips/format';
import { useApiQuery } from '@/hooks/useApiQuery';

import { fetchJourneyQueue, type JourneyEntry, type MyJourney } from './api';
import { EntryIcon, entryPath, itemPath } from './screens';

/**
 * My Work home (change plan Phase 10, AMD-22): the user's journey steps in order, with the count
 * waiting at each step and the next GS to act on. One primary action: the next GS of the first
 * step that has work.
 */
export function JourneyBoard({
  journey,
  now,
  onNavigate,
}: {
  journey: MyJourney;
  /** When the journey was fetched (stable ages between renders). */
  now: number;
  onNavigate: (path: string) => void;
}) {
  const steps = journey.entries.filter((e) => e.kind === 'STEP');
  if (steps.length === 0) return null;
  const firstBusy = steps.find((s) => (s.count ?? 0) > 0)?.code ?? null;

  return (
    <section
      aria-labelledby="journey-title"
      style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}
    >
      <h2 id="journey-title" className="mywork-group__title">
        <span>My journey</span>
      </h2>
      <ol className="journey-steps" data-testid="journey-steps">
        {steps.map((s, i) => (
          <JourneyStepCard
            key={s.code}
            step={s}
            index={i + 1}
            primary={s.code === firstBusy || (firstBusy === null && s.queue_code === null)}
            now={now}
            onNavigate={onNavigate}
          />
        ))}
      </ol>
    </section>
  );
}

function JourneyStepCard({
  step,
  index,
  primary,
  now,
  onNavigate,
}: {
  step: JourneyEntry;
  index: number;
  primary: boolean;
  now: number;
  onNavigate: (path: string) => void;
}) {
  const hasQueue = step.queue_code !== null;
  const count = step.count ?? 0;
  return (
    <li
      className={`journey-step${count > 0 ? ' journey-step--busy' : ''}`}
      data-testid="journey-step"
      data-step={step.code}
    >
      <div className="journey-step__head">
        <h3 className="journey-step__title">
          <span className="journey-step__no" aria-hidden="true">
            {index}
          </span>
          <EntryIcon code={step.code} size={16} />
          <span>{step.label}</span>
        </h3>
        {hasQueue ? (
          <span className="journey-step__count" aria-label={`${String(count)} waiting`}>
            {count}
          </span>
        ) : null}
      </div>
      {step.hint ? <p className="journey-step__hint">{step.hint}</p> : null}
      {step.next ? (
        <span className="journey-step__next">
          Next: <strong>{step.next.gs_no}</strong>
          {step.next.party_name ? ` · ${step.next.party_name}` : ''}
          {step.next.since ? ` · waiting ${age(step.next.since, now)}` : ''}
        </span>
      ) : hasQueue ? (
        <span className="journey-step__next dash-muted">Nothing waiting</span>
      ) : null}
      <div className="journey-step__actions">
        {!hasQueue ? (
          <Button
            type="button"
            variant={primary ? 'primary' : 'secondary'}
            onClick={() => {
              onNavigate(entryPath(step));
            }}
          >
            Start <ArrowRight size={14} aria-hidden="true" />
          </Button>
        ) : null}
        {step.next ? (
          <Button
            type="button"
            variant={primary ? 'primary' : 'secondary'}
            onClick={() => {
              if (step.next) onNavigate(itemPath(step.item_screen_key, step.next));
            }}
            aria-label={`Open next ${step.label}: ${step.next.gs_no}`}
          >
            Open next <ArrowRight size={14} aria-hidden="true" />
          </Button>
        ) : null}
        {hasQueue && count > 0 ? (
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              onNavigate(entryPath(step));
            }}
            aria-label={`View all ${String(count)} at ${step.label}`}
          >
            View all
          </Button>
        ) : null}
      </div>
    </li>
  );
}

/** One journey step's GS list (oldest first), for steps without their own queue page. */
export function JourneyQueueView({
  code,
  onNavigate,
}: {
  code: string;
  onNavigate: (path: string) => void;
}) {
  const fetcher = useCallback(
    () => fetchJourneyQueue(code).then((q) => ({ q, at: Date.now() })),
    [code],
  );
  const { data, error, loading, reload } = useApiQuery(fetcher);
  const back = (
    <Button
      type="button"
      variant="ghost"
      onClick={() => {
        onNavigate('/mywork');
      }}
    >
      <ArrowLeft size={16} aria-hidden="true" /> My Work
    </Button>
  );

  if (error) {
    return (
      <>
        {back}
        <ErrorState error={error} onRetry={reload} title="Could not load this step" />
      </>
    );
  }
  if (loading || !data) return <LoadingState label="Loading…" />;
  const { q, at } = data;
  return (
    <section style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
      <div>{back}</div>
      <h2 className="mywork-group__title">
        <span>{q.label}</span>
        <Badge variant="info">{q.total}</Badge>
      </h2>
      {q.hint ? <p className="journey-step__hint">{q.hint}</p> : null}
      {q.items.length === 0 ? (
        <EmptyState
          title="Nothing waiting at this step"
          hint="New goods slips appear here when they reach it."
        />
      ) : (
        <ul className="mywork-cards">
          {q.items.map((item, i) => (
            <li
              key={`${item.gs_id}-${item.target_id}`}
              className="mywork-card"
              data-testid="journey-queue-item"
            >
              <div className="mywork-card__main">
                <span style={{ fontWeight: 700, wordBreak: 'break-all' }}>{item.gs_no}</span>
                <span style={{ fontSize: '0.875rem', color: '#334155' }}>
                  {item.party_name}
                  {item.station_name ? ` · ${item.station_name}` : ''}
                </span>
                {item.since ? (
                  <span className="dash-muted">Waiting {age(item.since, at)}</span>
                ) : null}
              </div>
              <div className="mywork-card__actions">
                <Button
                  type="button"
                  variant={i === 0 ? 'primary' : 'secondary'}
                  onClick={() => {
                    onNavigate(itemPath(q.item_screen_key, item));
                  }}
                  aria-label={`Open ${item.gs_no}`}
                >
                  Open <ArrowRight size={14} aria-hidden="true" />
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
      {q.total > q.items.length ? (
        <p className="dash-muted">
          Showing the {q.items.length} waiting longest of {q.total}.
        </p>
      ) : null}
    </section>
  );
}
