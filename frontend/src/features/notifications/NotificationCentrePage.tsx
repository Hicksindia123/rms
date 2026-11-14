import { useCallback, useEffect, useState } from 'react';
import { REALTIME_SUBSCRIBE_STATES } from '@supabase/supabase-js';

import { Badge, Button, EmptyState, ErrorState, LoadingState } from '@/components/ui';
import { formatDateTime } from '@/features/goods-slips/format';
import { toApiError, type ApiError } from '@/lib/api/client';
import { getSupabase, isSupabaseConfigured } from '@/lib/supabase';

import {
  notificationsApi,
  type AppNotification,
  type NotificationList,
  type Priority,
} from './api';

const PAGE = 25;

/**
 * Notification centre (P4-03): all of the signed-in user's notifications with filters (unread,
 * event, priority), mark read / mark all read and deep links. Realtime inserts refresh the list.
 */
export function NotificationCentrePage({
  userId,
  onOpen,
  onPreferences,
}: {
  userId: string;
  onOpen: (n: AppNotification) => boolean;
  onPreferences: () => void;
}) {
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [priority, setPriority] = useState<Priority | ''>('');
  const [eventType, setEventType] = useState('');
  const [limit, setLimit] = useState(PAGE);
  const [data, setData] = useState<NotificationList | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [actionError, setActionError] = useState<ApiError | null>(null);
  const [eventTypes, setEventTypes] = useState<Array<{ code: string; label: string }>>([]);

  const load = useCallback(() => {
    notificationsApi
      .mine({
        unread_only: unreadOnly,
        priority: priority || undefined,
        event_type: eventType || undefined,
        limit: Math.min(limit, 100),
        offset: 0,
      })
      .then(
        (res) => {
          setData(res);
          setError(null);
        },
        (err: unknown) => {
          setError(toApiError(err));
        },
      );
  }, [unreadOnly, priority, eventType, limit]);

  useEffect(() => {
    load();
  }, [load]);

  // Event filter options: the user's own catalogue view (labels come from configuration).
  useEffect(() => {
    notificationsApi.preferences().then(
      (p) => {
        setEventTypes(p.items.map((i) => ({ code: i.event_type, label: i.label })));
      },
      (err: unknown) => {
        setActionError(toApiError(err));
      },
    );
  }, []);

  useEffect(() => {
    if (!isSupabaseConfigured()) return;
    const supabase = getSupabase();
    const channel = supabase
      .channel(`notification-centre:${userId}`)
      .on(
        'postgres_changes',
        {
          event: 'INSERT',
          schema: 'public',
          table: 'notifications',
          filter: `user_id=eq.${userId}`,
        },
        () => {
          load();
        },
      )
      .subscribe((status) => {
        if (status === REALTIME_SUBSCRIBE_STATES.CHANNEL_ERROR) load();
      });
    return () => {
      void supabase.removeChannel(channel);
    };
  }, [userId, load]);

  const act = (p: Promise<unknown>) => {
    setActionError(null);
    p.then(load, (err: unknown) => {
      setActionError(toApiError(err));
    });
  };

  const open = (n: AppNotification) => {
    if (!n.read_at) act(notificationsApi.read(n.id));
    onOpen(n);
  };

  return (
    <div className="page">
      <div className="notif-head">
        <div>
          <h1 className="page__title">Notifications</h1>
          <p className="page__subtitle">
            {data ? `${String(data.unread_count)} unread` : 'Your alerts and workflow updates.'}
          </p>
        </div>
        <div className="notif-head__actions">
          <Button type="button" variant="ghost" onClick={onPreferences}>
            Preferences
          </Button>
          <Button
            type="button"
            variant="primary"
            disabled={!data || data.unread_count === 0}
            onClick={() => {
              act(notificationsApi.readAll());
            }}
          >
            Mark all read
          </Button>
        </div>
      </div>

      <div className="notif-filters" role="group" aria-label="Filters">
        <label className="notif-filters__check">
          <input
            type="checkbox"
            checked={unreadOnly}
            onChange={(e) => {
              setUnreadOnly(e.target.checked);
              setLimit(PAGE);
            }}
          />
          Unread only
        </label>
        <label className="notif-filters__field">
          <span className="form-label">Event</span>
          <select
            className="input"
            value={eventType}
            onChange={(e) => {
              setEventType(e.target.value);
              setLimit(PAGE);
            }}
          >
            <option value="">All events</option>
            {eventTypes.map((t) => (
              <option key={t.code} value={t.code}>
                {t.label}
              </option>
            ))}
          </select>
        </label>
        <label className="notif-filters__field">
          <span className="form-label">Priority</span>
          <select
            className="input"
            value={priority}
            onChange={(e) => {
              setPriority(e.target.value as Priority | '');
              setLimit(PAGE);
            }}
          >
            <option value="">Any</option>
            <option value="HIGH">High</option>
            <option value="NORMAL">Normal</option>
            <option value="LOW">Low</option>
          </select>
        </label>
      </div>

      {actionError ? <ErrorState error={actionError} title="Action failed" /> : null}
      {error ? (
        <ErrorState error={error} onRetry={load} title="Could not load notifications" />
      ) : !data ? (
        <LoadingState label="Loading notifications…" />
      ) : data.items.length === 0 ? (
        <EmptyState
          title="No notifications"
          hint={
            unreadOnly || priority || eventType
              ? 'Nothing matches these filters.'
              : 'Alerts about your work will appear here.'
          }
        />
      ) : (
        <>
          <ul className="notif-list" data-testid="notification-list">
            {data.items.map((n) => (
              <li
                key={n.id}
                className={`notif-item${n.read_at ? '' : ' notif-item--unread'}${
                  n.priority === 'HIGH' ? ' notif-item--high' : ''
                }`}
              >
                <button
                  type="button"
                  className="notif-item__main"
                  onClick={() => {
                    open(n);
                  }}
                >
                  <span className="notif-item__title">{n.title}</span>
                  {n.body ? <span className="notif-item__body">{n.body}</span> : null}
                  <span className="notif-item__meta">
                    {formatDateTime(n.created_at)}
                    {n.priority === 'HIGH' ? <Badge variant="danger">High</Badge> : null}
                    {n.read_at ? null : <Badge variant="info">New</Badge>}
                  </span>
                </button>
                {n.read_at ? null : (
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    aria-label={`Mark "${n.title}" read`}
                    onClick={() => {
                      act(notificationsApi.read(n.id));
                    }}
                  >
                    Mark read
                  </Button>
                )}
              </li>
            ))}
          </ul>
          <p className="page__subtitle" style={{ marginTop: '0.75rem' }}>
            Showing {data.items.length} of {data.total}
          </p>
          {data.items.length < data.total && limit < 100 ? (
            <Button
              type="button"
              variant="ghost"
              onClick={() => {
                setLimit((l) => Math.min(l + PAGE, 100));
              }}
            >
              Load more
            </Button>
          ) : null}
        </>
      )}
    </div>
  );
}
