import { useCallback, useMemo, useState } from 'react';
import { MapPin, Pencil, Plus, Star, Users } from 'lucide-react';

import { PageHeader } from '@/components/erp';
import {
  Badge,
  Button,
  Checkbox,
  EmptyState,
  ErrorState,
  Input,
  LoadingState,
  Modal,
} from '@/components/ui';
import { useApiQuery } from '@/hooks/useApiQuery';
import { toApiError, type ApiError } from '@/lib/api/client';

import {
  createStore,
  fetchStoreMapping,
  fetchStores,
  saveStoreMapping,
  updateStore,
  type IntermediateStore,
  type MappingConflict,
  type StoreMapping,
} from './api';
import './intermediate-stores.css';

export interface IntermediateStoresPageProps {
  canCreate: boolean;
  canEdit: boolean;
  canConfigure: boolean;
}

/**
 * Admin -> Intermediate Stores (Phase P1, DEC-61): the stores (OP / DT / RI ...), the users who
 * hold each store role, and which categories / sub-categories each store owns. Exactly one active
 * store is the default for products no mapping covers. Store names, codes and the mapping all come
 * from the API (DB configuration).
 */
export function IntermediateStoresPage({
  canCreate,
  canEdit,
  canConfigure,
}: IntermediateStoresPageProps) {
  const fetcher = useCallback(() => fetchStores(), []);
  const { data, error, loading, reload, setData } = useApiQuery(fetcher);
  const [notice, setNotice] = useState<string | null>(null);
  const [actionError, setActionError] = useState<ApiError | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [renaming, setRenaming] = useState<IntermediateStore | null>(null);
  const [mapping, setMapping] = useState<IntermediateStore | null>(null);

  const refresh = (message: string) => {
    fetchStores().then(
      (stores) => {
        setData(stores);
        setNotice(message);
      },
      (err: unknown) => {
        setActionError(toApiError(err));
      },
    );
  };

  const patch = (
    store: IntermediateStore,
    body: Parameters<typeof updateStore>[1],
    done: string,
  ) => {
    setBusyId(store.id);
    setActionError(null);
    setNotice(null);
    updateStore(store.id, body).then(
      () => {
        setBusyId(null);
        refresh(done);
      },
      (err: unknown) => {
        setBusyId(null);
        setActionError(toApiError(err));
      },
    );
  };

  return (
    <div className="page istore-page">
      <PageHeader
        title="Intermediate Stores"
        subtitle="Stores that receive goods by product category, and the users of each store"
        actions={
          canCreate ? (
            <Button
              type="button"
              variant="primary"
              onClick={() => {
                setAdding(true);
              }}
            >
              <Plus size={16} aria-hidden="true" /> Add store
            </Button>
          ) : undefined
        }
      />

      {notice ? (
        <p className="istore-notice" role="status">
          {notice}
        </p>
      ) : null}
      {actionError ? <ErrorState error={actionError} title="The change was not saved" /> : null}

      {error ? (
        <ErrorState error={error} onRetry={reload} title="Could not load the Intermediate Stores" />
      ) : loading || !data ? (
        <LoadingState label="Loading Intermediate Stores…" />
      ) : data.length === 0 ? (
        <EmptyState
          title="No Intermediate Stores"
          hint={
            canCreate
              ? 'Add the first store; it becomes the default store.'
              : 'An administrator adds the stores.'
          }
        />
      ) : (
        <ul className="istore-list">
          {data.map((s) => (
            <li key={s.id} className="card istore-card" data-testid={`istore-${s.code}`}>
              <div className="istore-card__head">
                <h2 className="istore-card__title">{s.name}</h2>
                <span className="istore-badges">
                  <Badge variant="neutral">{s.code}</Badge>
                  {s.is_default ? <Badge variant="info">Default store</Badge> : null}
                  {s.is_active ? (
                    <Badge variant="success">Active</Badge>
                  ) : (
                    <Badge variant="warning">Inactive</Badge>
                  )}
                </span>
              </div>
              <dl className="istore-facts">
                <div>
                  <dt>Role</dt>
                  <dd>{s.role.code}</dd>
                </div>
                <div>
                  <dt>
                    <MapPin size={14} aria-hidden="true" /> Location
                  </dt>
                  <dd>{s.location.code}</dd>
                </div>
                <div>
                  <dt>Mapped</dt>
                  <dd>
                    {s.category_count} categor{s.category_count === 1 ? 'y' : 'ies'},{' '}
                    {s.subcategory_count} sub-categor{s.subcategory_count === 1 ? 'y' : 'ies'}
                    {s.is_default ? ' + everything unmapped' : ''}
                  </dd>
                </div>
              </dl>
              <div className="istore-users">
                <p className="istore-users__title">
                  <Users size={14} aria-hidden="true" /> Users with this store role
                </p>
                {s.users.length === 0 ? (
                  <p className="istore-muted">
                    Nobody holds this role yet. Assign it in Administration → Users.
                  </p>
                ) : (
                  <ul className="istore-users__list">
                    {s.users.map((u) => (
                      <li key={u.id}>
                        {u.full_name}
                        {u.email ? <span className="istore-muted"> · {u.email}</span> : null}
                        {u.is_active ? null : <Badge variant="warning">Inactive user</Badge>}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              {canEdit || canConfigure ? (
                <div className="istore-actions">
                  {canConfigure ? (
                    <Button
                      type="button"
                      variant="secondary"
                      onClick={() => {
                        setMapping(s);
                      }}
                    >
                      Map categories
                    </Button>
                  ) : null}
                  {canEdit ? (
                    <>
                      <Button
                        type="button"
                        variant="outline"
                        onClick={() => {
                          setRenaming(s);
                        }}
                      >
                        <Pencil size={16} aria-hidden="true" /> Rename
                      </Button>
                      {!s.is_default && s.is_active ? (
                        <Button
                          type="button"
                          variant="outline"
                          disabled={busyId === s.id}
                          onClick={() => {
                            patch(s, { is_default: true }, `${s.name} is now the default store.`);
                          }}
                        >
                          <Star size={16} aria-hidden="true" /> Make default
                        </Button>
                      ) : null}
                      {s.is_default ? null : (
                        <Button
                          type="button"
                          variant={s.is_active ? 'ghost' : 'outline'}
                          disabled={busyId === s.id}
                          onClick={() => {
                            patch(
                              s,
                              { is_active: !s.is_active },
                              `${s.name} is now ${s.is_active ? 'inactive' : 'active'}.`,
                            );
                          }}
                        >
                          {s.is_active ? 'Deactivate' : 'Activate'}
                        </Button>
                      )}
                    </>
                  ) : null}
                </div>
              ) : null}
              {s.is_default && canEdit ? (
                <p className="istore-muted">
                  The default store cannot be deactivated. Make another store the default first.
                </p>
              ) : null}
            </li>
          ))}
        </ul>
      )}

      {adding ? (
        <StoreFormModal
          mode="create"
          onClose={() => {
            setAdding(false);
          }}
          onSaved={(s) => {
            setAdding(false);
            refresh(`Created ${s.name} with role ${s.role.code} and location ${s.location.code}.`);
          }}
        />
      ) : null}
      {renaming ? (
        <StoreFormModal
          mode="rename"
          store={renaming}
          onClose={() => {
            setRenaming(null);
          }}
          onSaved={(s) => {
            setRenaming(null);
            refresh(`Saved ${s.name}.`);
          }}
        />
      ) : null}
      {mapping ? (
        <MappingModal
          store={mapping}
          onClose={() => {
            setMapping(null);
          }}
          onSaved={(m) => {
            setMapping(null);
            refresh(`Saved the category mapping of ${m.store.name}.`);
          }}
        />
      ) : null}
    </div>
  );
}

// --- add / rename --------------------------------------------------------------------------------

function StoreFormModal({
  mode,
  store,
  onClose,
  onSaved,
}: {
  mode: 'create' | 'rename';
  store?: IntermediateStore;
  onClose: () => void;
  onSaved: (s: IntermediateStore) => void;
}) {
  const [code, setCode] = useState('');
  const [name, setName] = useState(store?.name ?? '');
  const [sortOrder, setSortOrder] = useState(String(store?.sort_order ?? 100));
  const [makeDefault, setMakeDefault] = useState(false);
  const [reason, setReason] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<ApiError | null>(null);

  const order = Number(sortOrder);
  const codeOk = mode === 'rename' || /^[A-Z][A-Z0-9_]{0,19}$/.test(code.trim().toUpperCase());
  const valid = codeOk && name.trim() !== '' && Number.isInteger(order) && order >= 0;

  const submit = () => {
    setSaving(true);
    setSaveError(null);
    const r = reason.trim() || null;
    const call =
      mode === 'create'
        ? createStore({
            code: code.trim().toUpperCase(),
            name: name.trim(),
            sort_order: order,
            is_default: makeDefault,
            reason: r,
          })
        : updateStore(store?.id ?? '', { name: name.trim(), sort_order: order, reason: r });
    call.then(
      (s) => {
        setSaving(false);
        onSaved(s);
      },
      (err: unknown) => {
        setSaving(false);
        setSaveError(toApiError(err));
      },
    );
  };

  return (
    <Modal
      isOpen
      onClose={onClose}
      title={mode === 'create' ? 'Add Intermediate Store' : `Rename ${store?.name ?? ''}`}
      footer={
        <>
          <Button type="button" variant="ghost" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button
            type="button"
            variant="primary"
            disabled={!valid || saving}
            isLoading={saving}
            onClick={submit}
          >
            {mode === 'create' ? 'Create store' : 'Save'}
          </Button>
        </>
      }
    >
      <div className="istore-form">
        {mode === 'create' ? (
          <div>
            <label htmlFor="istore-code" className="form-label">
              Code
            </label>
            <Input
              id="istore-code"
              value={code}
              maxLength={20}
              autoCapitalize="characters"
              onChange={(e) => {
                setCode(e.target.value);
              }}
              helperText={`Cannot be changed later. Creates role and location ISTORE_${
                code.trim().toUpperCase() || '<CODE>'
              }.`}
              error={code && !codeOk ? 'Start with a letter; use A–Z, 0–9 and _' : undefined}
            />
          </div>
        ) : (
          <p className="istore-muted">
            Code {store?.code} (fixed). The role and location are renamed too.
          </p>
        )}
        <div>
          <label htmlFor="istore-name" className="form-label">
            Name
          </label>
          <Input
            id="istore-name"
            value={name}
            maxLength={120}
            onChange={(e) => {
              setName(e.target.value);
            }}
          />
        </div>
        <div>
          <label htmlFor="istore-order" className="form-label">
            Sort order
          </label>
          <Input
            id="istore-order"
            type="number"
            inputMode="numeric"
            min={0}
            value={sortOrder}
            onChange={(e) => {
              setSortOrder(e.target.value);
            }}
          />
        </div>
        {mode === 'create' ? (
          <Checkbox
            id="istore-default"
            label="Make this the default store (takes every product no mapping covers)"
            checked={makeDefault}
            onChange={(e) => {
              setMakeDefault(e.target.checked);
            }}
          />
        ) : null}
        <div>
          <label htmlFor="istore-reason" className="form-label">
            Reason (optional, kept in the config history)
          </label>
          <Input
            id="istore-reason"
            value={reason}
            maxLength={500}
            onChange={(e) => {
              setReason(e.target.value);
            }}
          />
        </div>
        {saveError ? <ErrorState error={saveError} title="Not saved" /> : null}
      </div>
    </Modal>
  );
}

// --- category mapping ----------------------------------------------------------------------------

interface Selection {
  cats: ReadonlySet<string>;
  subs: ReadonlySet<string>;
}

function MappingModal({
  store,
  onClose,
  onSaved,
}: {
  store: IntermediateStore;
  onClose: () => void;
  onSaved: (m: StoreMapping) => void;
}) {
  const fetcher = useCallback(() => fetchStoreMapping(store.id), [store.id]);
  const { data, error, loading, reload } = useApiQuery(fetcher);
  const [draft, setDraft] = useState<Selection | null>(null);
  const [confirmMove, setConfirmMove] = useState(false);
  const [reason, setReason] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<ApiError | null>(null);

  const selection: Selection = useMemo(
    () =>
      draft ??
      (data
        ? { cats: new Set(data.category_ids), subs: new Set(data.subcategory_ids) }
        : { cats: new Set<string>(), subs: new Set<string>() }),
    [draft, data],
  );

  // (Sub-)categories ticked here that another store owns today: saving moves them (conflicts).
  const conflicts: MappingConflict[] = useMemo(() => {
    if (!data) return [];
    const out: MappingConflict[] = [];
    for (const c of data.tree) {
      if (selection.cats.has(c.id) && c.store && c.store.id !== store.id) {
        out.push({
          kind: 'CATEGORY',
          id: c.id,
          code: c.code,
          name: c.name,
          store_code: c.store.code,
          store_name: c.store.name,
        });
      }
      for (const s of c.subcategories) {
        if (selection.subs.has(s.id) && s.store && s.store.id !== store.id) {
          out.push({
            kind: 'SUBCATEGORY',
            id: s.id,
            code: s.code,
            name: `${c.name} / ${s.name}`,
            store_code: s.store.code,
            store_name: s.store.name,
          });
        }
      }
    }
    return out;
  }, [data, selection, store.id]);

  const toggle = (
    kind: 'cats' | 'subs',
    id: string,
    on: boolean,
    owner: StoreMapping['store'] | null,
  ) => {
    const next = new Set(selection[kind]);
    if (on) next.add(id);
    else next.delete(id);
    setDraft({ ...selection, [kind]: next });
    // A new conflict needs a fresh confirmation of the move.
    if (on && owner && owner.id !== store.id) setConfirmMove(false);
  };

  const save = () => {
    setSaving(true);
    setSaveError(null);
    saveStoreMapping(store.id, {
      category_ids: [...selection.cats],
      subcategory_ids: [...selection.subs],
      reassign: confirmMove,
      reason: reason.trim() || null,
    }).then(
      (m) => {
        setSaving(false);
        onSaved(m);
      },
      (err: unknown) => {
        setSaving(false);
        setSaveError(toApiError(err));
      },
    );
  };

  const blocked = conflicts.length > 0 && !confirmMove;

  return (
    <Modal
      isOpen
      size="lg"
      onClose={onClose}
      title={`Categories of ${store.name}`}
      footer={
        <>
          <Button type="button" variant="ghost" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button
            type="button"
            variant="primary"
            disabled={!data || saving || blocked}
            isLoading={saving}
            onClick={save}
          >
            Save mapping
          </Button>
        </>
      }
    >
      {error ? (
        <ErrorState error={error} onRetry={reload} title="Could not load the mapping" />
      ) : loading || !data ? (
        <LoadingState label="Loading categories…" />
      ) : data.tree.length === 0 ? (
        <EmptyState
          title="No product categories"
          hint="Add categories in Administration → Masters."
        />
      ) : (
        <div className="istore-form">
          <p className="istore-muted">
            A sub-category mapping wins over its category. Products of categories that no store owns
            go to the default store
            {data.default_store ? ` (${data.default_store.name})` : ''}.
          </p>
          <ul className="istore-tree" aria-label="Categories and sub-categories">
            {data.tree.map((c) => (
              <li key={c.id}>
                <div className="istore-tree__row">
                  <Checkbox
                    id={`map-cat-${c.id}`}
                    checked={selection.cats.has(c.id)}
                    onChange={(e) => {
                      toggle('cats', c.id, e.target.checked, c.store);
                    }}
                    label={
                      <span className="istore-tree__label">
                        <strong>{c.name}</strong>
                        <OwnerBadge owner={c.store} storeId={store.id} />
                        {c.is_active ? null : <Badge variant="neutral">Inactive</Badge>}
                      </span>
                    }
                  />
                </div>
                {c.subcategories.length > 0 ? (
                  <ul className="istore-tree__subs">
                    {c.subcategories.map((s) => (
                      <li key={s.id} className="istore-tree__row">
                        <Checkbox
                          id={`map-sub-${s.id}`}
                          checked={selection.subs.has(s.id)}
                          onChange={(e) => {
                            toggle('subs', s.id, e.target.checked, s.store);
                          }}
                          label={
                            <span className="istore-tree__label">
                              {s.name}
                              <OwnerBadge owner={s.store} storeId={store.id} />
                              {s.is_active ? null : <Badge variant="neutral">Inactive</Badge>}
                            </span>
                          }
                        />
                      </li>
                    ))}
                  </ul>
                ) : null}
              </li>
            ))}
          </ul>

          {conflicts.length > 0 ? (
            <div className="istore-conflicts" role="alert">
              <p>
                <strong>Already mapped to another store:</strong>
              </p>
              <ul>
                {conflicts.map((c) => (
                  <li key={c.id}>
                    {c.name} — now {c.store_name}
                  </li>
                ))}
              </ul>
              <Checkbox
                id="map-confirm-move"
                label={`Move ${conflicts.length === 1 ? 'it' : 'them'} to ${store.name}`}
                checked={confirmMove}
                onChange={(e) => {
                  setConfirmMove(e.target.checked);
                }}
              />
            </div>
          ) : null}

          <div>
            <label htmlFor="map-reason" className="form-label">
              Reason (optional, kept in the config history)
            </label>
            <Input
              id="map-reason"
              value={reason}
              maxLength={500}
              onChange={(e) => {
                setReason(e.target.value);
              }}
            />
          </div>
          {saveError ? <ErrorState error={saveError} title="Mapping not saved" /> : null}
        </div>
      )}
    </Modal>
  );
}

function OwnerBadge({ owner, storeId }: { owner: StoreMapping['store'] | null; storeId: string }) {
  if (!owner) return null;
  if (owner.id === storeId) return <Badge variant="success">This store</Badge>;
  return <Badge variant="warning">{owner.name}</Badge>;
}
