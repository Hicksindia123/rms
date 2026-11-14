import { useCallback, useMemo, useState } from 'react';
import { ArrowDown, ArrowUp, GripVertical, Plus, Trash2 } from 'lucide-react';

import { Button, EmptyState, ErrorState, LoadingState } from '@/components/ui';
import { orderForDevice } from '@/features/dashboard/layout';
import {
  dashboardApi,
  type CatalogueItem,
  type PermissionRef,
  type RoleLayout,
  type WidgetSize,
} from '@/features/dashboard/api';
import { useApiQuery } from '@/hooks/useApiQuery';
import { toApiError, type ApiError } from '@/lib/api/client';

/**
 * Admin → Dashboard layouts (P4-01, master plan §10 "Dashboard widgets"): choose, order (drag or
 * the arrow buttons) and size the widgets of each role's landing dashboard, with a desktop / phone
 * preview. Saving writes config_change_log on the server. Widgets the role's permissions do not
 * allow can be placed but are flagged: its users will not see them (the API filters them out).
 */

interface Entry {
  code: string;
  size: WidgetSize;
}

interface Data {
  catalogue: CatalogueItem[];
  layouts: RoleLayout[];
}

const SIZE_LABELS: Record<WidgetSize, string> = { S: 'Small', M: 'Medium', L: 'Wide' };

function missingFor(item: CatalogueItem | undefined, grants: Set<string>): PermissionRef[] {
  return (item?.requires ?? []).filter((p) => !grants.has(`${p.module}.${p.action}`));
}

export function DashboardLayoutEditor() {
  const fetcher = useCallback(async (): Promise<Data> => {
    const [catalogue, layouts] = await Promise.all([
      dashboardApi.catalogue(),
      dashboardApi.layouts(),
    ]);
    return { catalogue, layouts };
  }, []);
  const query = useApiQuery<Data>(fetcher);
  const [roleCode, setRoleCode] = useState<string>('');
  const [draft, setDraft] = useState<Entry[] | null>(null);
  const [reason, setReason] = useState('');
  const [preview, setPreview] = useState<'desktop' | 'phone'>('desktop');
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<ApiError | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  const data = query.data;
  const selected = data?.layouts.find((l) => l.role.code === roleCode) ?? data?.layouts[0];
  const catalogue = useMemo(() => new Map((data?.catalogue ?? []).map((c) => [c.code, c])), [data]);
  const grants = useMemo(
    () => new Set((selected?.role_permissions ?? []).map((p) => `${p.module}.${p.action}`)),
    [selected],
  );
  const entries: Entry[] =
    draft ?? (selected?.widgets ?? []).map((w) => ({ code: w.code, size: w.size }));
  const dirty = draft !== null;

  const update = (next: Entry[]) => {
    setDraft(next);
    setSaved(null);
  };
  const move = (from: number, to: number) => {
    if (to < 0 || to >= entries.length || from === to) return;
    const next = [...entries];
    const [item] = next.splice(from, 1);
    if (item) next.splice(to, 0, item);
    update(next);
  };
  const selectRole = (code: string) => {
    if (dirty && !window.confirm('Discard unsaved changes to this layout?')) return;
    setRoleCode(code);
    setDraft(null);
    setReason('');
    setSaved(null);
    setSaveError(null);
  };

  const replaceLayout = (layout: RoleLayout | null, role: string) => {
    if (!data) return;
    query.setData({
      ...data,
      layouts: data.layouts.map((l) =>
        l.role.code === role
          ? (layout ?? { ...l, has_layout: false, widgets: [], updated_at: null })
          : l,
      ),
    });
  };

  const save = async () => {
    if (!selected) return;
    setSaving(true);
    setSaveError(null);
    try {
      const out = await dashboardApi.saveLayout(
        selected.role.code,
        entries,
        reason.trim() ? reason.trim() : null,
      );
      replaceLayout(out, selected.role.code);
      setDraft(null);
      setReason('');
      setSaved(`Saved the ${selected.role.name} dashboard.`);
    } catch (err) {
      setSaveError(toApiError(err));
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!selected?.has_layout) return;
    if (
      !window.confirm(
        `Remove the ${selected.role.name} dashboard? Its users will see an empty dashboard.`,
      )
    )
      return;
    setSaving(true);
    setSaveError(null);
    try {
      await dashboardApi.deleteLayout(selected.role.code, reason.trim() ? reason.trim() : null);
      replaceLayout(null, selected.role.code);
      setDraft(null);
      setReason('');
      setSaved(`Removed the ${selected.role.name} dashboard.`);
    } catch (err) {
      setSaveError(toApiError(err));
    } finally {
      setSaving(false);
    }
  };

  if (query.error) {
    return (
      <div className="page">
        <ErrorState error={query.error} onRetry={query.reload} title="Could not load layouts" />
      </div>
    );
  }
  if (!data || !selected) {
    return (
      <div className="page">
        <LoadingState label="Loading dashboard layouts…" />
      </div>
    );
  }

  const available = data.catalogue.filter(
    (c) => c.is_active && !entries.some((e) => e.code === c.code),
  );
  const previewWidgets = orderForDevice(
    entries.map((e) => ({
      code: e.code,
      title: catalogue.get(e.code)?.title ?? e.code,
      description: null,
      size: e.size,
      priority: catalogue.get(e.code)?.priority ?? 'insight',
      live: false,
    })),
    preview === 'phone',
  );

  return (
    <div className="page">
      <h1 className="page__title">Dashboard layouts</h1>
      <p className="page__subtitle">
        Choose and order the widgets each role lands on. Changes are recorded in the config history.
      </p>

      <label className="dash-role" style={{ maxWidth: 360, marginBottom: '1rem' }}>
        <span className="form-label">Role</span>
        <select
          className="input"
          aria-label="Role"
          value={selected.role.code}
          onChange={(e) => {
            selectRole(e.target.value);
          }}
        >
          {data.layouts.map((l) => (
            <option key={l.role.code} value={l.role.code}>
              {l.role.name}
              {l.has_layout ? '' : ' (no layout)'}
            </option>
          ))}
        </select>
      </label>

      {saved ? (
        <p
          role="status"
          className="dash-chip"
          style={{
            display: 'inline-block',
            background: 'var(--color-success-bg)',
            color: '#065f46',
          }}
        >
          {saved}
        </p>
      ) : null}
      {saveError ? <ErrorState error={saveError} title="Could not save the layout" /> : null}

      <div className="dash-editor">
        <section aria-labelledby="layout-widgets" className="dash-card">
          <h2 id="layout-widgets" className="dash-card__title">
            Widgets ({entries.length})
          </h2>
          {entries.length === 0 ? (
            <EmptyState
              title="No widgets"
              hint="Add widgets below. Without widgets this role lands on an empty dashboard."
            />
          ) : (
            <ol className="dash-editor__list" aria-label="Widget order">
              {entries.map((e, i) => {
                const item = catalogue.get(e.code);
                const missing = missingFor(item, grants);
                const title = item?.title ?? e.code;
                return (
                  <li
                    key={e.code}
                    draggable
                    data-testid={`layout-item-${e.code}`}
                    className={`dash-editor__item${missing.length ? ' dash-editor__item--blocked' : ''}${
                      dragIndex === i ? ' dash-editor__item--dragging' : ''
                    }`}
                    onDragStart={(ev) => {
                      setDragIndex(i);
                      ev.dataTransfer.effectAllowed = 'move';
                    }}
                    onDragOver={(ev) => {
                      ev.preventDefault();
                    }}
                    onDrop={(ev) => {
                      ev.preventDefault();
                      if (dragIndex !== null) move(dragIndex, i);
                      setDragIndex(null);
                    }}
                    onDragEnd={() => {
                      setDragIndex(null);
                    }}
                  >
                    <GripVertical
                      size={18}
                      aria-hidden="true"
                      style={{ color: 'var(--color-muted)' }}
                    />
                    <span className="dash-editor__name">
                      {i + 1}. {title}
                      {missing.length ? (
                        <span className="dash-muted" style={{ display: 'block', fontWeight: 400 }}>
                          Hidden for this role — needs{' '}
                          {missing.map((p) => `${p.module}.${p.action}`).join(', ')}
                        </span>
                      ) : null}
                    </span>
                    <select
                      className="input"
                      aria-label={`Size of ${title}`}
                      value={e.size}
                      style={{ width: 'auto', minHeight: 44 }}
                      onChange={(ev) => {
                        update(
                          entries.map((x) =>
                            x.code === e.code ? { ...x, size: ev.target.value as WidgetSize } : x,
                          ),
                        );
                      }}
                    >
                      {(['S', 'M', 'L'] as const).map((s) => (
                        <option key={s} value={s}>
                          {SIZE_LABELS[s]}
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      className="dash-editor__icon"
                      aria-label={`Move ${title} up`}
                      disabled={i === 0}
                      onClick={() => {
                        move(i, i - 1);
                      }}
                    >
                      <ArrowUp size={16} aria-hidden="true" />
                    </button>
                    <button
                      type="button"
                      className="dash-editor__icon"
                      aria-label={`Move ${title} down`}
                      disabled={i === entries.length - 1}
                      onClick={() => {
                        move(i, i + 1);
                      }}
                    >
                      <ArrowDown size={16} aria-hidden="true" />
                    </button>
                    <button
                      type="button"
                      className="dash-editor__icon"
                      aria-label={`Remove ${title}`}
                      onClick={() => {
                        update(entries.filter((x) => x.code !== e.code));
                      }}
                    >
                      <Trash2 size={16} aria-hidden="true" />
                    </button>
                  </li>
                );
              })}
            </ol>
          )}

          {available.length > 0 ? (
            <label className="dash-role">
              <span className="form-label">Add a widget</span>
              <select
                className="input"
                value=""
                onChange={(ev) => {
                  const item = catalogue.get(ev.target.value);
                  if (item) update([...entries, { code: item.code, size: item.default_size }]);
                }}
              >
                <option value="">Choose a widget…</option>
                {available.map((c) => (
                  <option key={c.code} value={c.code}>
                    {c.title}
                    {missingFor(c, grants).length ? ' (not visible to this role)' : ''}
                  </option>
                ))}
              </select>
            </label>
          ) : null}

          <label className="dash-role">
            <span className="form-label">Reason for the change (optional)</span>
            <input
              className="input"
              value={reason}
              maxLength={500}
              onChange={(ev) => {
                setReason(ev.target.value);
              }}
            />
          </label>
          <div className="dash-page__actions">
            <Button
              type="button"
              variant="primary"
              disabled={!dirty || saving}
              onClick={() => {
                void save();
              }}
            >
              <Plus size={16} aria-hidden="true" /> Save layout
            </Button>
            {dirty ? (
              <Button
                type="button"
                variant="secondary"
                disabled={saving}
                onClick={() => {
                  setDraft(null);
                }}
              >
                Discard changes
              </Button>
            ) : null}
            {selected.has_layout && !dirty ? (
              <Button
                type="button"
                variant="secondary"
                disabled={saving}
                onClick={() => {
                  void remove();
                }}
              >
                Remove layout
              </Button>
            ) : null}
          </div>
          {selected.updated_at ? (
            <p className="dash-card__foot">
              Last changed {new Date(selected.updated_at).toLocaleString()}
              {selected.updated_by_name ? ` by ${selected.updated_by_name}` : ''}
            </p>
          ) : null}
        </section>

        <section aria-labelledby="layout-preview" className="dash-card">
          <div className="dash-card__head">
            <h2 id="layout-preview" className="dash-card__title">
              Preview
            </h2>
            <div role="group" aria-label="Preview device" style={{ display: 'flex', gap: 4 }}>
              {(['desktop', 'phone'] as const).map((d) => (
                <button
                  key={d}
                  type="button"
                  className="dash-link-button"
                  aria-pressed={preview === d}
                  style={preview === d ? { background: 'var(--color-bg)' } : undefined}
                  onClick={() => {
                    setPreview(d);
                  }}
                >
                  {d === 'desktop' ? 'Desktop' : 'Phone'}
                </button>
              ))}
            </div>
          </div>
          {previewWidgets.length === 0 ? (
            <EmptyState title="Empty dashboard" hint="This role would see no widgets." />
          ) : (
            <div
              className={`dash-preview${preview === 'phone' ? ' dash-preview--phone' : ''}`}
              style={
                preview === 'phone' ? { maxWidth: 360, margin: '0 auto', width: '100%' } : undefined
              }
            >
              <div
                className="dash-grid"
                style={preview === 'phone' ? { gridTemplateColumns: 'minmax(0,1fr)' } : undefined}
              >
                {previewWidgets.map((w) => {
                  const blocked = missingFor(catalogue.get(w.code), grants).length > 0;
                  return (
                    <div
                      key={w.code}
                      className={`dash-card dash-card--${w.size}${blocked ? ' dash-editor__item--blocked' : ''}`}
                      style={preview === 'phone' ? { gridColumn: 'auto' } : undefined}
                    >
                      <span className="dash-card__title">{w.title}</span>
                      <span className="dash-muted">
                        {SIZE_LABELS[w.size]}
                        {w.priority === 'action' ? ' · actionable' : ''}
                        {blocked ? ' · hidden for this role' : ''}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
