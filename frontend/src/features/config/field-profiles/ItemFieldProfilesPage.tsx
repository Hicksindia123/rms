import { useCallback, useMemo, useState } from 'react';
import { ArrowDown, ArrowUp, Plus, ShieldCheck, X } from 'lucide-react';

import {
  AsyncCombobox,
  Badge,
  Button,
  Checkbox,
  EmptyState,
  ErrorState,
  Input,
  LoadingState,
  Select,
  type ComboboxOption,
} from '@/components/ui';
import { useAuth } from '@/features/auth/useAuth';
import { mastersApi } from '@/features/masters/api';
import { useApiQuery } from '@/hooks/useApiQuery';
import { newIdempotencyKey, toApiError, type ApiError } from '@/lib/api/client';

import {
  fieldProfilesApi,
  type FieldGroup,
  type GroupProfile,
  type ItemField,
  type ResolvedField,
  type ScopeProfile,
  type ScopeSelection,
} from './api';

type Tab = 'categorisation' | 'departments' | 'actions';

/** Guards shown read-only on this screen (they apply to item fields; never configurable). */
const RELATED_GUARDS = ['G-05', 'G-07', 'G-18'];

/**
 * Item Field Profiles (change plan 2026-11-12 Phase 4; AMD-10, AMD-11, AMD-16).
 * Pick Category -> (optional) Sub-Category -> (optional) Product; per group, the most specific
 * level with its own fields wins. Inherited fields are shown greyed with "Override here".
 * Every label and code comes from the API (DB configuration); nothing business-specific is
 * hard-coded here.
 */
export function ItemFieldProfilesPage() {
  const { can, me } = useAuth();
  const isSuperAdmin = me?.profile.is_super_admin ?? false;
  const canEdit = isSuperAdmin || can('config', 'configure');

  const [categoryId, setCategoryId] = useState('');
  const [subcategoryId, setSubcategoryId] = useState('');
  const [productId, setProductId] = useState('');
  const [tab, setTab] = useState<Tab>('categorisation');

  const fetchCategories = useCallback(() => mastersApi.categories(), []);
  const categories = useApiQuery(fetchCategories);

  const fetchSubs = useCallback(
    () => (categoryId ? mastersApi.subcategories(categoryId, false) : Promise.resolve([])),
    [categoryId],
  );
  const subs = useApiQuery(fetchSubs);

  const loadProducts = useCallback(
    async (q: string): Promise<ComboboxOption[]> => {
      if (!categoryId) return [];
      const page = await mastersApi.products({
        q,
        category_id: categoryId,
        subcategory_id: subcategoryId || null,
        page: 1,
        page_size: 20,
      });
      return page.items.map((p) => ({
        value: p.id,
        label: p.name,
        sublabel: [p.code, p.subcategory_name].filter(Boolean).join(' · '),
      }));
    },
    [categoryId, subcategoryId],
  );

  const selection = useMemo<ScopeSelection | null>(
    () =>
      categoryId
        ? {
            category_id: categoryId,
            subcategory_id: subcategoryId || null,
            product_id: productId || null,
          }
        : null,
    [categoryId, subcategoryId, productId],
  );

  const fetchProfile = useCallback(
    () => (selection ? fieldProfilesApi.scope(selection) : Promise.resolve(null)),
    [selection],
  );
  const profile = useApiQuery(fetchProfile);

  const tabs: Array<{ id: Tab; label: string }> = [
    { id: 'categorisation', label: 'Categorisation' },
    { id: 'departments', label: 'Departments' },
    { id: 'actions', label: 'Actions' },
  ];

  return (
    <div className="masters ifp">
      <header>
        <h1 className="masters__title">Item Field Profiles</h1>
        <p className="masters__subtitle">
          Category → Sub-Category → Product. The most specific level with its own fields wins.
          {profile.data?.version_no != null &&
            ` · Config version ${String(profile.data.version_no)}`}
        </p>
      </header>

      {categories.error ? (
        <ErrorState error={categories.error} onRetry={categories.reload} />
      ) : !categories.data ? (
        <LoadingState label="Loading categories…" />
      ) : (
        <div className="filters ifp-scope">
          <label className="masters-field">
            <span className="form-label">
              Category<span className="required-star">*</span>
            </span>
            <Select
              id="ifp-category"
              value={categoryId}
              placeholder="Choose a category"
              options={categories.data.map((c) => ({ value: c.id, label: c.name }))}
              onChange={(e) => {
                setCategoryId(e.target.value);
                setSubcategoryId('');
                setProductId('');
              }}
            />
          </label>
          <label className="masters-field">
            <span className="form-label">Sub-Category (optional)</span>
            <Select
              id="ifp-subcategory"
              value={subcategoryId}
              placeholder="Whole category"
              disabled={!categoryId || subs.loading}
              options={(subs.data ?? []).map((s) => ({ value: s.id, label: s.name }))}
              onChange={(e) => {
                setSubcategoryId(e.target.value);
                setProductId('');
              }}
            />
          </label>
          <div className="masters-field">
            <span className="form-label" aria-hidden="true">
              Product (optional)
            </span>
            <AsyncCombobox
              key={`${categoryId}:${subcategoryId}`}
              id="ifp-product"
              name="product"
              ariaLabel="Product (optional)"
              value={productId}
              placeholder={categoryId ? 'Search products…' : 'Choose a category first'}
              disabled={!categoryId}
              loadOptions={loadProducts}
              onChange={setProductId}
            />
          </div>
        </div>
      )}

      {subs.error && <ErrorState error={subs.error} onRetry={subs.reload} />}

      {!selection ? (
        <EmptyState
          title="Choose a category"
          hint="Then optionally a sub-category or a product to see and override its fields."
        />
      ) : profile.error ? (
        <ErrorState error={profile.error} onRetry={profile.reload} />
      ) : profile.loading || !profile.data ? (
        <LoadingState label="Loading profile…" />
      ) : (
        <>
          <nav className="ifp-chain" aria-label="Selected level">
            {profile.data.chain.map((c, i, chain) => (
              <span key={c.scope_id} className="ifp-chain__item">
                {i > 0 && <span aria-hidden="true">›</span>}
                <Badge variant={i === chain.length - 1 ? 'info' : 'neutral'}>{c.name}</Badge>
              </span>
            ))}
          </nav>

          <div className="tabs tabs--wrap" role="tablist" aria-label="Field groups">
            {tabs.map((t) => (
              <button
                key={t.id}
                type="button"
                role="tab"
                className="tabs__tab"
                aria-selected={tab === t.id}
                onClick={() => {
                  setTab(t.id);
                }}
              >
                {t.label}
              </button>
            ))}
          </div>

          <div role="tabpanel" className="masters-panel">
            {tab === 'categorisation' && (
              <>
                <GroupEditor
                  key={`${profile.data.scope.scope_id}:CATEGORISATION`}
                  group="CATEGORISATION"
                  title="Quantity buckets"
                  hint="The counted quantity of each item is split across these buckets."
                  profile={profile.data}
                  selection={selection}
                  canEdit={canEdit}
                  onSaved={profile.setData}
                />
                <GroupEditor
                  key={`${profile.data.scope.scope_id}:ITEM_COUNT`}
                  group="ITEM_COUNT"
                  title="Item counts"
                  hint="Separate numeric counts recorded per item (not buckets)."
                  profile={profile.data}
                  selection={selection}
                  canEdit={canEdit}
                  onSaved={profile.setData}
                />
              </>
            )}
            {tab === 'departments' && (
              <GroupEditor
                key={`${profile.data.scope.scope_id}:DEPARTMENT`}
                group="DEPARTMENT"
                title="Departments"
                hint="Where the Replacement Manager can route goods of this level."
                profile={profile.data}
                selection={selection}
                canEdit={canEdit}
                onSaved={profile.setData}
              />
            )}
            {tab === 'actions' && (
              <GroupEditor
                key={`${profile.data.scope.scope_id}:ACTION`}
                group="ACTION"
                title="Actions"
                hint="Final RM actions the quantity can be split across."
                profile={profile.data}
                selection={selection}
                canEdit={canEdit}
                onSaved={profile.setData}
              />
            )}
          </div>
        </>
      )}

      <GuardsNote />
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
interface DraftRow {
  field_id: string;
  code: string;
  label: string;
  is_included: boolean;
}

function flagBadges(
  f: Pick<
    ResolvedField,
    'is_wastage' | 'returns_to_routing' | 'requires_cn' | 'requires_challan' | 'system_behavior'
  >,
) {
  return (
    <>
      {f.is_wastage && <Badge variant="warning">Wastage</Badge>}
      {f.returns_to_routing && <Badge variant="info">To routing</Badge>}
      {f.requires_cn && <Badge variant="info">Needs CN</Badge>}
      {f.requires_challan && <Badge variant="info">Needs challan</Badge>}
      {f.system_behavior === 'HAZARD' && <Badge variant="danger">Hazard (locked)</Badge>}
    </>
  );
}

function GroupEditor({
  group,
  title,
  hint,
  profile,
  selection,
  canEdit,
  onSaved,
}: {
  group: FieldGroup;
  title: string;
  hint: string;
  profile: ScopeProfile;
  selection: ScopeSelection;
  canEdit: boolean;
  onSaved: (p: ScopeProfile) => void;
}) {
  const g = profile.groups.find((x) => x.field_group === group) as GroupProfile;
  const atCategory = profile.scope.scope_type === 'CATEGORY';
  const hasOwn = g.overridden || atCategory;

  const [draft, setDraft] = useState<DraftRow[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const startEdit = (fromInherited: boolean) => {
    setNotice(null);
    setError(null);
    setDraft(
      fromInherited
        ? g.inherited.map((f) => ({
            field_id: f.field_id,
            code: f.code,
            label: f.label,
            is_included: true,
          }))
        : g.own.map((a) => ({
            field_id: a.field_id,
            code: a.code,
            label: a.label,
            is_included: a.is_included,
          })),
    );
  };

  const save = async (rows: DraftRow[], msg: string) => {
    setBusy(true);
    setError(null);
    try {
      const out = await fieldProfilesApi.setOverride(
        group,
        selection,
        rows.map((r, i) => ({
          field_id: r.field_id,
          is_included: r.is_included,
          sort_order: (i + 1) * 10,
        })),
      );
      setDraft(null);
      setNotice(msg);
      onSaved(out);
    } catch (err) {
      setError(toApiError(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="ifp-group" aria-labelledby={`ifp-${group}`}>
      <div className="ifp-group__head">
        <div>
          <h2 id={`ifp-${group}`} className="ifp-group__title">
            {title}
          </h2>
          <p className="masters-row__meta">{hint}</p>
        </div>
        {!draft && canEdit && (
          <div className="ifp-group__actions">
            {hasOwn ? (
              <Button
                type="button"
                size="sm"
                onClick={() => {
                  startEdit(false);
                }}
              >
                Edit
              </Button>
            ) : (
              <Button
                type="button"
                size="sm"
                variant="primary"
                onClick={() => {
                  startEdit(true);
                }}
              >
                Override here
              </Button>
            )}
            {g.overridden && !atCategory && (
              <Button
                type="button"
                size="sm"
                isLoading={busy}
                onClick={() => {
                  void save([], 'Override removed: this level inherits again.');
                }}
              >
                Use inherited
              </Button>
            )}
          </div>
        )}
      </div>

      {notice && (
        <p className="masters-notice" role="status">
          {notice}
        </p>
      )}
      {error && <ErrorState error={error} title="Could not save" />}

      {draft ? (
        <DraftEditor
          group={group}
          rows={draft}
          busy={busy}
          onChange={setDraft}
          onCancel={() => {
            setDraft(null);
            setError(null);
          }}
          onSave={() => {
            void save(draft, `Saved ${title.toLowerCase()} for ${profile.scope.name}.`);
          }}
        />
      ) : hasOwn ? (
        g.own.length === 0 ? (
          <EmptyState
            title="No fields at this level"
            hint={canEdit ? 'Use Edit to add fields.' : 'An administrator can add fields.'}
          />
        ) : (
          <ul className="masters-list">
            {g.own.map((a) => {
              const eff = g.effective.find((e) => e.field_id === a.field_id);
              return (
                <li
                  key={a.field_id}
                  className={`masters-row${a.is_included ? '' : ' ifp-row--excluded'}`}
                >
                  <div className="masters-row__main">
                    <div className="masters-row__title">
                      <span>{a.label}</span>
                      <Badge variant="neutral">{a.code}</Badge>
                      {!a.is_included && <Badge variant="warning">Excluded</Badge>}
                      {!a.field_is_active && <Badge variant="neutral">Inactive</Badge>}
                      {eff && flagBadges(eff)}
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
        )
      ) : g.inherited.length === 0 ? (
        <EmptyState
          title="Nothing inherited"
          hint={
            canEdit
              ? 'Use Override here to add fields at this level.'
              : 'No fields are set above this level.'
          }
        />
      ) : (
        <>
          <p className="masters-row__meta">
            Inherited from {g.inherited_from ? g.inherited_from.name : 'a higher level'}
          </p>
          <ul className="masters-list ifp-list--inherited" aria-label={`${title} (inherited)`}>
            {g.inherited.map((f) => (
              <li key={f.field_id} className="masters-row">
                <div className="masters-row__main">
                  <div className="masters-row__title">
                    <span>{f.label}</span>
                    <Badge variant="neutral">{f.code}</Badge>
                    {flagBadges(f)}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

function DraftEditor({
  group,
  rows,
  busy,
  onChange,
  onCancel,
  onSave,
}: {
  group: FieldGroup;
  rows: DraftRow[];
  busy: boolean;
  onChange: (rows: DraftRow[]) => void;
  onCancel: () => void;
  onSave: () => void;
}) {
  const fetchLibrary = useCallback(() => fieldProfilesApi.fields(group), [group]);
  const library = useApiQuery(fetchLibrary);
  const [addId, setAddId] = useState('');

  const available = (library.data ?? []).filter(
    (f) => f.is_active && !rows.some((r) => r.field_id === f.id),
  );

  const move = (i: number, d: -1 | 1) => {
    const next = [...rows];
    const j = i + d;
    const a = next[i];
    const b = next[j];
    if (!a || !b) return;
    next[i] = b;
    next[j] = a;
    onChange(next);
  };

  const add = (f: ItemField) => {
    onChange([...rows, { field_id: f.id, code: f.code, label: f.label, is_included: true }]);
  };

  return (
    <div className="masters-form">
      {rows.length === 0 ? (
        <p className="masters-row__meta">
          No fields yet. Add an existing field or create a new one.
        </p>
      ) : (
        <ul className="masters-list">
          {rows.map((r, i) => (
            <li
              key={r.field_id}
              className={`masters-row ifp-edit-row${r.is_included ? '' : ' ifp-row--excluded'}`}
            >
              <div className="masters-row__main">
                <div className="masters-row__title">
                  <span>{r.label}</span>
                  <Badge variant="neutral">{r.code}</Badge>
                </div>
                <Checkbox
                  id={`ifp-inc-${r.field_id}`}
                  label="Included"
                  checked={r.is_included}
                  onChange={(e) => {
                    onChange(
                      rows.map((x) =>
                        x.field_id === r.field_id ? { ...x, is_included: e.target.checked } : x,
                      ),
                    );
                  }}
                />
              </div>
              <div className="ifp-row-tools">
                <Button
                  type="button"
                  size="sm"
                  className="ifp-icon-btn"
                  aria-label={`Move ${r.label} up`}
                  disabled={i === 0}
                  onClick={() => {
                    move(i, -1);
                  }}
                >
                  <ArrowUp size={16} aria-hidden="true" />
                </Button>
                <Button
                  type="button"
                  size="sm"
                  className="ifp-icon-btn"
                  aria-label={`Move ${r.label} down`}
                  disabled={i === rows.length - 1}
                  onClick={() => {
                    move(i, 1);
                  }}
                >
                  <ArrowDown size={16} aria-hidden="true" />
                </Button>
                <Button
                  type="button"
                  size="sm"
                  className="ifp-icon-btn"
                  aria-label={`Remove ${r.label}`}
                  onClick={() => {
                    onChange(rows.filter((x) => x.field_id !== r.field_id));
                  }}
                >
                  <X size={16} aria-hidden="true" />
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}

      {library.error ? (
        <ErrorState error={library.error} onRetry={library.reload} />
      ) : (
        <div className="masters-form__pair ifp-add">
          <label className="masters-field">
            <span className="form-label">Add existing field</span>
            <Select
              id={`ifp-add-${group}`}
              value={addId}
              placeholder={
                library.loading
                  ? 'Loading…'
                  : available.length
                    ? 'Choose a field'
                    : 'All fields added'
              }
              disabled={library.loading || available.length === 0}
              options={available.map((f) => ({ value: f.id, label: `${f.label} (${f.code})` }))}
              onChange={(e) => {
                setAddId(e.target.value);
              }}
            />
          </label>
          <div className="masters-field masters-field--action">
            <Button
              type="button"
              disabled={!addId}
              onClick={() => {
                const f = available.find((x) => x.id === addId);
                if (f) add(f);
                setAddId('');
              }}
            >
              <Plus size={16} aria-hidden="true" /> Add
            </Button>
          </div>
        </div>
      )}

      <NewFieldForm
        group={group}
        onCreated={(f) => {
          add(f);
          library.reload();
        }}
      />

      <div className="ifp-save">
        <Button type="button" onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
        <Button type="button" variant="primary" isLoading={busy} onClick={onSave}>
          Save
        </Button>
      </div>
    </div>
  );
}

/** Inline "create new label" (AMD-10). The code is derived by the backend and is immutable. */
function NewFieldForm({
  group,
  onCreated,
}: {
  group: FieldGroup;
  onCreated: (f: ItemField) => void;
}) {
  const [label, setLabel] = useState('');
  const [flags, setFlags] = useState({
    is_wastage: false,
    returns_to_routing: false,
    requires_cn: false,
    requires_challan: false,
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  // One key per label typed: a double click or a retry is not created twice (G-16 pattern).
  const [idemKey, setIdemKey] = useState(newIdempotencyKey);

  const flagOptions: Array<{ key: keyof typeof flags; label: string }> =
    group === 'ACTION'
      ? [
          { key: 'requires_cn', label: 'Needs CN details' },
          { key: 'requires_challan', label: 'Needs challan details' },
        ]
      : group === 'CATEGORISATION' || group === 'DEPARTMENT'
        ? [
            { key: 'is_wastage', label: 'Wastage' },
            { key: 'returns_to_routing', label: 'Goes to RM routing' },
          ]
        : [];

  const create = async () => {
    setBusy(true);
    setError(null);
    try {
      const f = await fieldProfilesApi.createField(
        { field_group: group, label: label.trim(), ...flags },
        idemKey,
      );
      onCreated(f);
      setLabel('');
      setFlags({
        is_wastage: false,
        returns_to_routing: false,
        requires_cn: false,
        requires_challan: false,
      });
      setIdemKey(newIdempotencyKey());
    } catch (err) {
      setError(toApiError(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="ifp-new">
      <div className="masters-form__pair">
        <label className="masters-field">
          <span className="form-label">Create new field</span>
          <Input
            id={`ifp-new-${group}`}
            value={label}
            maxLength={120}
            placeholder="Label, e.g. as used on the floor"
            onChange={(e) => {
              setLabel(e.target.value);
              setIdemKey(newIdempotencyKey());
            }}
          />
        </label>
        <div className="masters-field masters-field--action">
          <Button
            type="button"
            isLoading={busy}
            disabled={label.trim().length === 0}
            onClick={() => {
              void create();
            }}
          >
            <Plus size={16} aria-hidden="true" /> Create
          </Button>
        </div>
      </div>
      {flagOptions.length > 0 && (
        <div className="ifp-flags">
          {flagOptions.map((o) => (
            <Checkbox
              key={o.key}
              id={`ifp-flag-${group}-${o.key}`}
              label={o.label}
              checked={flags[o.key]}
              onChange={(e) => {
                setFlags({ ...flags, [o.key]: e.target.checked });
                setIdemKey(newIdempotencyKey());
              }}
            />
          ))}
        </div>
      )}
      {error && <ErrorState error={error} title="Could not create the field" />}
    </div>
  );
}

/** System guards stay read-only (CLAUDE.md rule c): shown from the guard catalogue API. */
function GuardsNote() {
  const fetchGuards = useCallback(() => fieldProfilesApi.guards(), []);
  const guards = useApiQuery(fetchGuards);
  const related = (guards.data ?? []).filter((g) => RELATED_GUARDS.includes(g.code));
  return (
    <details className="ifp-guards">
      <summary>
        <ShieldCheck size={16} aria-hidden="true" /> System guards (read-only)
      </summary>
      {guards.error ? (
        <ErrorState error={guards.error} onRetry={guards.reload} />
      ) : guards.loading ? (
        <LoadingState label="Loading guards…" />
      ) : (
        <ul className="ifp-guards__list">
          {related.map((g) => (
            <li key={g.code}>
              <strong>{g.code}</strong> {g.name}: {g.statement}
            </li>
          ))}
          <li>
            Field codes never change and every change is versioned; a goods slip keeps the version
            it was categorised under.
          </li>
        </ul>
      )}
    </details>
  );
}
