import { useCallback, useState } from 'react';
import { Lock } from 'lucide-react';

import { Button, ErrorState, LoadingState } from '@/components/ui';
import { useApiQuery } from '@/hooks/useApiQuery';
import { toApiError, type ApiError } from '@/lib/api/client';

import { notificationsApi, type EmailMode, type Preferences } from './api';

/**
 * Notification preferences (P4-03): email opt-out per event (mandatory events are locked on) and
 * immediate vs daily-digest email. In-app notifications are always delivered.
 */
export function NotificationPreferencesPage() {
  const fetcher = useCallback(() => notificationsApi.preferences(), []);
  const query = useApiQuery<Preferences>(fetcher);
  const [draft, setDraft] = useState<Record<string, boolean>>({});
  const [mode, setMode] = useState<EmailMode | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<ApiError | null>(null);
  const [saved, setSaved] = useState(false);

  if (query.error) {
    return (
      <div className="page page--narrow">
        <ErrorState error={query.error} onRetry={query.reload} title="Could not load preferences" />
      </div>
    );
  }
  const data = query.data;
  if (!data) {
    return (
      <div className="page page--narrow">
        <LoadingState label="Loading preferences…" />
      </div>
    );
  }

  const dirty = Object.keys(draft).length > 0 || (mode !== null && mode !== data.email_mode);
  const effectiveMode = mode ?? data.email_mode;
  const byCategory = new Map<string, typeof data.items>();
  for (const item of data.items) {
    const list = byCategory.get(item.category) ?? [];
    list.push(item);
    byCategory.set(item.category, list);
  }

  const save = async () => {
    setSaving(true);
    setSaveError(null);
    setSaved(false);
    try {
      const out = await notificationsApi.savePreferences({
        email: draft,
        ...(mode ? { email_mode: mode } : {}),
      });
      query.setData(out);
      setDraft({});
      setMode(null);
      setSaved(true);
    } catch (err) {
      setSaveError(toApiError(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="page page--narrow">
      <h1 className="page__title">Notification preferences</h1>
      <p className="page__subtitle">
        In-app notifications are always delivered. Choose which events also reach you by email.
      </p>

      {data.email_channel.enabled ? null : (
        <p className="banner" role="status" data-testid="email-disabled-banner">
          Email is disabled on this server (SMTP is not configured). Your choices are saved and
          apply once an administrator configures email.
        </p>
      )}

      <section className="dash-card" style={{ margin: '1rem 0' }}>
        <h2 className="dash-card__title">Email delivery</h2>
        <p className="dash-muted" style={{ margin: '0.25rem 0 0.75rem' }}>
          Address: {data.email_address ?? 'no email address on your profile'}
        </p>
        <fieldset className="notif-mode">
          <legend className="form-label">How should emails arrive?</legend>
          {(
            [
              ['IMMEDIATE', 'Immediately, one email per notification'],
              ['DAILY_DIGEST', 'Once a day, as a digest (mandatory alerts still arrive at once)'],
            ] as const
          ).map(([value, label]) => (
            <label key={value} className="notif-filters__check">
              <input
                type="radio"
                name="email_mode"
                value={value}
                checked={effectiveMode === value}
                onChange={() => {
                  setMode(value);
                  setSaved(false);
                }}
              />
              {label}
            </label>
          ))}
        </fieldset>
      </section>

      {[...byCategory.entries()].map(([category, items]) => (
        <section key={category} className="dash-card" style={{ marginBottom: '1rem' }}>
          <h2 className="dash-card__title">
            {category.charAt(0) + category.slice(1).toLowerCase()}
          </h2>
          <ul className="notif-prefs">
            {items.map((item) => {
              const checked = item.is_mandatory
                ? true
                : (draft[item.event_type] ?? item.email_enabled);
              return (
                <li key={item.event_type} className="notif-prefs__row">
                  <label className="notif-filters__check" style={{ flex: 1 }}>
                    <input
                      type="checkbox"
                      checked={checked}
                      disabled={item.is_mandatory}
                      aria-describedby={`pref-${item.event_type}`}
                      onChange={(e) => {
                        // Unchanged-from-saved prefs are dropped from the draft; changed ones kept.
                        const next = Object.fromEntries(
                          Object.entries(draft).filter(([k]) => k !== item.event_type),
                        );
                        if (e.target.checked !== item.email_enabled) {
                          next[item.event_type] = e.target.checked;
                        }
                        setDraft(next);
                        setSaved(false);
                      }}
                    />
                    <span>
                      {item.label}
                      <span id={`pref-${item.event_type}`} className="notif-item__body">
                        {item.is_mandatory ? (
                          <>
                            <Lock size={12} aria-hidden="true" /> Mandatory — cannot be switched off
                          </>
                        ) : item.email_rule_active ? (
                          (item.description ?? '')
                        ) : (
                          'No email rule is active for this event yet.'
                        )}
                      </span>
                    </span>
                  </label>
                </li>
              );
            })}
          </ul>
        </section>
      ))}

      {saveError ? <ErrorState error={saveError} title="Could not save preferences" /> : null}
      {saved ? (
        <p role="status" className="dash-chip" style={{ background: 'var(--color-success-bg)' }}>
          Preferences saved.
        </p>
      ) : null}
      <div className="sticky-submit">
        <Button
          type="button"
          variant="primary"
          disabled={!dirty || saving}
          onClick={() => void save()}
        >
          {saving ? 'Saving…' : 'Save preferences'}
        </Button>
      </div>
    </div>
  );
}
