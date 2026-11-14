import { useCallback, useEffect, useMemo, useState } from 'react';
import { ArrowRight, RefreshCw } from 'lucide-react';
import { REALTIME_SUBSCRIBE_STATES } from '@supabase/supabase-js';

import { Button, EmptyState, ErrorState, LoadingState } from '@/components/ui';
import { useApiQuery } from '@/hooks/useApiQuery';
import { toApiError } from '@/lib/api/client';
import { getSupabase, isSupabaseConfigured } from '@/lib/supabase';

import { dashboardApi, type Dashboard, type LayoutWidget, type WidgetData } from './api';
import { orderForDevice, WIDGET_LINKS } from './layout';
import { WidgetBody } from './widgets';

const ROLE_KEY = 'rms.dashboard.role';
const PHONE_QUERY = '(max-width: 639px)';

function readRole(): string | null {
  try {
    return window.localStorage.getItem(ROLE_KEY);
  } catch {
    return null; // storage blocked (private window): fall back to the primary role
  }
}

function clearRole(): void {
  try {
    window.localStorage.removeItem(ROLE_KEY);
  } catch {
    // storage blocked: nothing remembered
  }
}

function writeRole(role: string): void {
  try {
    window.localStorage.setItem(ROLE_KEY, role);
  } catch {
    // storage blocked: the choice simply is not remembered
  }
}

function useIsPhone(): boolean {
  const [phone, setPhone] = useState(() => window.matchMedia(PHONE_QUERY).matches);
  useEffect(() => {
    const mq = window.matchMedia(PHONE_QUERY);
    const onChange = () => {
      setPhone(mq.matches);
    };
    mq.addEventListener('change', onChange);
    return () => {
      mq.removeEventListener('change', onChange);
    };
  }, []);
  return phone;
}

function WidgetCard({
  widget,
  tick,
  liveTick,
}: {
  widget: LayoutWidget;
  tick: number;
  liveTick: number;
}) {
  const fetcher = useCallback(() => dashboardApi.widget<unknown>(widget.code), [widget.code]);
  const query = useApiQuery<WidgetData<unknown>>(fetcher);
  const { reload } = query;

  useEffect(() => {
    if (tick > 0) reload();
  }, [tick, reload]);
  useEffect(() => {
    if (widget.live && liveTick > 0) reload();
  }, [widget.live, liveTick, reload]);

  const link = WIDGET_LINKS[widget.code];
  const headingId = `widget-${widget.code}`;
  return (
    <section
      className={`dash-card dash-card--${widget.size}`}
      aria-labelledby={headingId}
      data-testid={`widget-${widget.code}`}
    >
      <header className="dash-card__head">
        <h2 id={headingId} className="dash-card__title">
          {widget.title}
        </h2>
        {link ? (
          <a className="dash-card__open" href={`#${link}`} aria-label={`Open ${widget.title}`}>
            Open <ArrowRight size={14} aria-hidden="true" />
          </a>
        ) : null}
      </header>
      {query.error ? (
        <ErrorState error={query.error} onRetry={reload} title="Could not load this widget" />
      ) : !query.data ? (
        <div className="dash-skeleton" role="status" aria-label={`Loading ${widget.title}`} />
      ) : (
        <>
          <WidgetBody code={widget.code} data={query.data.data} />
          <p className="dash-card__foot">
            Updated{' '}
            {new Date(query.data.generated_at).toLocaleTimeString(undefined, {
              hour: '2-digit',
              minute: '2-digit',
            })}
          </p>
        </>
      )}
    </section>
  );
}

/** Role landing dashboard (P4-01, GET /dashboard). */
export function DashboardPage({ userId }: { userId: string }) {
  const [role, setRole] = useState<string | null>(readRole);
  const [tick, setTick] = useState(0);
  const [liveTick, setLiveTick] = useState(0);
  const [live, setLive] = useState(false);
  const phone = useIsPhone();

  const fetcher = useCallback(async () => {
    try {
      return await dashboardApi.mine(role ?? undefined);
    } catch (err) {
      // A remembered role the user no longer holds: forget it and land on the primary role.
      if (role && toApiError(err).code === 'ROLE_NOT_HELD') {
        clearRole();
        return dashboardApi.mine();
      }
      throw err;
    }
  }, [role]);
  const query = useApiQuery<Dashboard>(fetcher);
  const dash = query.data;
  const { reload } = query;

  const pollSeconds = dash?.poll_seconds ?? 60;
  useEffect(() => {
    const id = window.setInterval(() => {
      if (!document.hidden) setTick((t) => t + 1);
    }, pollSeconds * 1000);
    return () => {
      window.clearInterval(id);
    };
  }, [pollSeconds]);

  // Live task counts: own-row notifications (RLS-safe) trigger an immediate refresh of live widgets.
  useEffect(() => {
    if (!isSupabaseConfigured()) return;
    const supabase = getSupabase();
    const channel = supabase
      .channel(`dashboard:${userId}`)
      .on(
        'postgres_changes',
        {
          event: 'INSERT',
          schema: 'public',
          table: 'notifications',
          filter: `user_id=eq.${userId}`,
        },
        () => {
          setLiveTick((t) => t + 1);
        },
      )
      .subscribe((status) => {
        setLive(status === REALTIME_SUBSCRIBE_STATES.SUBSCRIBED);
      });
    return () => {
      void supabase.removeChannel(channel);
    };
  }, [userId]);

  const widgets = useMemo(() => orderForDevice(dash?.widgets ?? [], phone), [dash, phone]);

  return (
    <div className="page dash-page">
      <div className="dash-page__head">
        <div>
          <h1 className="page__title">Dashboard</h1>
          <p className="page__subtitle">
            {dash?.role ? `${dash.role.name} · ` : ''}
            {live ? 'Live task updates' : `Refreshes every ${String(pollSeconds)} s`}
          </p>
        </div>
        <div className="dash-page__actions">
          {dash && dash.available_roles.length > 1 ? (
            <label className="dash-role">
              <span className="form-label">View as</span>
              <select
                className="input"
                value={dash.role?.code ?? ''}
                onChange={(e) => {
                  writeRole(e.target.value);
                  setRole(e.target.value);
                }}
              >
                {dash.available_roles.map((r) => (
                  <option key={r.code} value={r.code}>
                    {r.name}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          <Button
            type="button"
            variant="secondary"
            onClick={() => {
              reload();
              setTick((t) => t + 1);
            }}
          >
            <RefreshCw size={16} aria-hidden="true" /> Refresh
          </Button>
        </div>
      </div>

      {query.error ? (
        <ErrorState error={query.error} onRetry={reload} title="Could not load your dashboard" />
      ) : !dash ? (
        <LoadingState label="Loading dashboard…" />
      ) : !dash.role ? (
        <EmptyState
          title="No role assigned"
          hint="Your account has no role yet. Ask an administrator to assign one."
        />
      ) : widgets.length === 0 ? (
        <EmptyState
          title="No widgets on this dashboard"
          hint={
            dash.hidden_widget_count > 0
              ? 'The widgets configured for this role need permissions you do not have.'
              : 'An administrator can add widgets for this role in Admin → Dashboard layouts.'
          }
        />
      ) : (
        <div className="dash-grid">
          {widgets.map((w) => (
            <WidgetCard key={w.code} widget={w} tick={tick} liveTick={liveTick} />
          ))}
        </div>
      )}
    </div>
  );
}
