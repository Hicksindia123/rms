import { useCallback, useEffect, useRef, useState } from 'react';
import { Bell } from 'lucide-react';
import { REALTIME_SUBSCRIBE_STATES } from '@supabase/supabase-js';

import { Button } from '@/components/ui';
import { formatDateTime } from '@/features/goods-slips/format';
import { toApiError, type ApiError } from '@/lib/api/client';
import { getSupabase, isSupabaseConfigured } from '@/lib/supabase';

import { notificationsApi, type AppNotification, type NotificationList } from './api';

export type { AppNotification } from './api';

/**
 * Header bell (P2-03, P4-03). The list comes from the API (§6.1: business data via FastAPI);
 * Supabase Realtime only signals that a row was inserted for this user (RLS user_id = auth.uid()).
 */
export function NotificationBell({
  userId,
  onOpen,
  onViewAll,
}: {
  userId: string;
  onOpen: (n: AppNotification) => void;
  onViewAll: () => void;
}) {
  const [data, setData] = useState<NotificationList | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [open, setOpen] = useState(false);
  const [live, setLive] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);

  const load = useCallback(() => {
    notificationsApi.mine({ limit: 30 }).then(
      (res) => {
        setData(res);
        setError(null);
      },
      (err: unknown) => {
        setError(toApiError(err));
      },
    );
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!isSupabaseConfigured()) return;
    const supabase = getSupabase();
    const channel = supabase
      .channel(`notifications:${userId}`)
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
        setLive(status === REALTIME_SUBSCRIBE_STATES.SUBSCRIBED);
      });
    return () => {
      void supabase.removeChannel(channel);
    };
  }, [userId, load]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const unread = data?.unread_count ?? 0;

  const choose = (n: AppNotification) => {
    setOpen(false);
    if (!n.read_at) {
      notificationsApi.read(n.id).then(load, (err: unknown) => {
        setError(toApiError(err));
      });
    }
    onOpen(n);
  };

  return (
    <div className="bell" ref={panelRef}>
      <button
        type="button"
        className="bell__button"
        aria-label={`Notifications${unread ? ` (${String(unread)} unread)` : ''}`}
        aria-expanded={open}
        data-testid="notification-bell"
        data-live={live ? 'true' : 'false'}
        onClick={() => {
          setOpen((o) => !o);
          if (!open) load();
        }}
      >
        <Bell size={18} aria-hidden="true" />
        {unread > 0 ? (
          <span className="bell__count" data-testid="notification-count">
            {unread > 99 ? '99+' : unread}
          </span>
        ) : null}
      </button>
      {open ? (
        <div className="bell__panel" role="dialog" aria-label="Notifications">
          <div className="bell__panel-head">
            <strong>Notifications</strong>
            {unread > 0 ? (
              <Button
                type="button"
                size="sm"
                variant="ghost"
                onClick={() => {
                  notificationsApi.readAll().then(load, (err: unknown) => {
                    setError(toApiError(err));
                  });
                }}
              >
                Mark all read
              </Button>
            ) : null}
          </div>
          {error ? (
            <p role="alert" className="form-control__error" style={{ padding: '0 0.75rem' }}>
              {error.message}
              {error.requestId ? ` (Request ID: ${error.requestId})` : ''}{' '}
              <Button type="button" size="sm" variant="ghost" onClick={load}>
                Retry
              </Button>
            </p>
          ) : null}
          {!data && !error ? <p className="bell__empty">Loading…</p> : null}
          {data && data.items.length === 0 ? (
            <p className="bell__empty">No notifications yet.</p>
          ) : null}
          <div className="bell__footer">
            <Button
              type="button"
              size="sm"
              variant="ghost"
              data-testid="notification-view-all"
              onClick={() => {
                setOpen(false);
                onViewAll();
              }}
            >
              View all notifications
            </Button>
          </div>
          <ul className="bell__list">
            {data?.items.map((n) => (
              <li key={n.id}>
                <button
                  type="button"
                  className={`bell__item${n.read_at ? '' : ' bell__item--unread'}${
                    n.priority === 'HIGH' ? ' bell__item--high' : ''
                  }`}
                  onClick={() => {
                    choose(n);
                  }}
                >
                  <span className="bell__title">{n.title}</span>
                  {n.body ? <span className="bell__body">{n.body}</span> : null}
                  <span className="bell__time">{formatDateTime(n.created_at)}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
