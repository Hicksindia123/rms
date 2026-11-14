import { useCallback, useEffect, useMemo, useState } from 'react';
import { Plus } from 'lucide-react';

import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  Input,
  LoadingState,
  Modal,
  Select,
} from '@/components/ui';
import { useAuth } from '@/features/auth/useAuth';
import './users.css';
import { useApiQuery } from '@/hooks/useApiQuery';
import { toApiError, type ApiError } from '@/lib/api/client';

import {
  ACTIONS,
  moduleLabel,
  rolesApi,
  type CataloguePermission,
  type Role,
  type RolePermission,
  type Scope,
} from './api';

type Grants = Record<string, Scope>; // key "module.action"

const SCOPES: Array<{ value: Scope; label: string }> = [
  { value: 'all', label: 'All records' },
  { value: 'department', label: 'Own department' },
  { value: 'own', label: 'Own records' },
];

function toGrants(rows: RolePermission[]): Grants {
  return Object.fromEntries(rows.map((r) => [`${r.module_code}.${r.action}`, r.scope]));
}

function sameGrants(a: Grants, b: Grants): boolean {
  const ka = Object.keys(a);
  return ka.length === Object.keys(b).length && ka.every((k) => a[k] === b[k]);
}

/** P1-05 roles & permission matrix (modules × actions with scope). The backend enforces every
 *  rule: system roles stay, SUPER_ADMIN is locked, no editing a role you hold yourself. */
export function PermissionMatrixView() {
  const { can, me } = useAuth();
  const isSuperAdmin = me?.profile.is_super_admin ?? false;
  const canCreate = isSuperAdmin || can('roles', 'create');
  const canEdit = isSuperAdmin || can('roles', 'edit');
  const canDelete = isSuperAdmin || can('roles', 'delete');
  const canConfigure = isSuperAdmin || can('roles', 'configure');
  const myRoleCodes = useMemo(() => new Set(me?.roles.map((r) => r.code) ?? []), [me]);

  const fetchRoles = useCallback(() => rolesApi.list(), []);
  const roles = useApiQuery(fetchRoles);
  const fetchCatalogue = useCallback(() => rolesApi.catalogue(), []);
  const catalogue = useApiQuery(fetchCatalogue);

  const [roleId, setRoleId] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [dialog, setDialog] = useState<{ mode: 'create' } | { mode: 'edit'; role: Role } | null>(
    null,
  );
  const [notice, setNotice] = useState<string | null>(null);

  const selected = roles.data?.find((r) => r.id === roleId) ?? roles.data?.[0] ?? null;

  const choose = (id: string) => {
    if (dirty && !window.confirm('Discard your unsaved permission changes?')) return;
    setDirty(false);
    setNotice(null);
    setRoleId(id);
  };

  if (roles.error) return <ErrorState error={roles.error} onRetry={roles.reload} />;
  if (catalogue.error) return <ErrorState error={catalogue.error} onRetry={catalogue.reload} />;
  if (!roles.data || !catalogue.data) return <LoadingState label="Loading roles…" />;

  return (
    <div className="masters">
      <header>
        <h1 className="masters__title">Roles &amp; Permissions</h1>
        <p className="masters__subtitle">What each role can see and do</p>
      </header>

      <div className="roles-layout">
        <aside className="roles-list" aria-label="Roles">
          <div className="roles-list__pick">
            <Select
              aria-label="Role"
              value={selected?.id ?? ''}
              options={roles.data.map((r) => ({ value: r.id, label: r.name }))}
              onChange={(e) => {
                choose(e.target.value);
              }}
            />
          </div>
          <ul className="roles-list__items">
            {roles.data.map((r) => (
              <li key={r.id}>
                <button
                  type="button"
                  className="roles-list__item"
                  aria-current={selected?.id === r.id}
                  onClick={() => {
                    choose(r.id);
                  }}
                >
                  <span>{r.name}</span>
                  <span className="roles-list__count">{r.user_count}</span>
                </button>
              </li>
            ))}
          </ul>
          {canCreate && (
            <Button
              type="button"
              onClick={() => {
                setDialog({ mode: 'create' });
              }}
            >
              <Plus size={16} aria-hidden="true" /> New role
            </Button>
          )}
        </aside>

        <section className="roles-detail">
          {notice && (
            <p className="masters-notice" role="status">
              {notice}
            </p>
          )}
          {selected ? (
            <RoleMatrix
              key={selected.id}
              role={selected}
              catalogue={catalogue.data}
              readOnlyReason={
                !canConfigure
                  ? 'You can view this matrix but not change it.'
                  : selected.code === 'SUPER_ADMIN'
                    ? 'The Super Admin role always holds every permission.'
                    : !isSuperAdmin && myRoleCodes.has(selected.code)
                      ? 'You hold this role, so you cannot change its permissions.'
                      : null
              }
              canEdit={canEdit}
              canDelete={canDelete && !selected.is_system && selected.user_count === 0}
              onDirty={setDirty}
              onEdit={() => {
                setDialog({ mode: 'edit', role: selected });
              }}
              onSaved={(msg) => {
                setDirty(false);
                setNotice(msg);
                roles.reload();
              }}
              onDeleted={(msg) => {
                setDirty(false);
                setNotice(msg);
                setRoleId(null);
                roles.reload();
              }}
            />
          ) : (
            <EmptyState title="No roles" />
          )}
        </section>
      </div>

      {dialog && (
        <RoleDialog
          role={dialog.mode === 'edit' ? dialog.role : null}
          onClose={() => {
            setDialog(null);
          }}
          onSaved={(msg, role) => {
            setDialog(null);
            setNotice(msg);
            roles.reload();
            setRoleId(role.id);
          }}
        />
      )}
    </div>
  );
}

function RoleMatrix({
  role,
  catalogue,
  readOnlyReason,
  canEdit,
  canDelete,
  onDirty,
  onEdit,
  onSaved,
  onDeleted,
}: {
  role: Role;
  catalogue: CataloguePermission[];
  readOnlyReason: string | null;
  canEdit: boolean;
  canDelete: boolean;
  onDirty: (dirty: boolean) => void;
  onEdit: () => void;
  onSaved: (msg: string) => void;
  onDeleted: (msg: string) => void;
}) {
  const fetchPermissions = useCallback(() => rolesApi.permissions(role.id), [role.id]);
  const saved = useApiQuery(fetchPermissions);
  const [grants, setGrants] = useState<Grants | null>(null);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  const original = useMemo(() => toGrants(saved.data ?? []), [saved.data]);
  const current = grants ?? original;
  const dirty = grants !== null && !sameGrants(grants, original);
  const readOnly = readOnlyReason !== null;

  useEffect(() => {
    onDirty(dirty);
  }, [dirty, onDirty]);

  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault();
    };
    window.addEventListener('beforeunload', warn);
    return () => {
      window.removeEventListener('beforeunload', warn);
    };
  }, [dirty]);

  const modules = useMemo(() => {
    const map = new Map<string, Set<string>>();
    for (const p of catalogue) {
      map.set(p.module_code, (map.get(p.module_code) ?? new Set()).add(p.action));
    }
    return [...map.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [catalogue]);
  const actions = useMemo(
    () => ACTIONS.filter((a) => catalogue.some((p) => p.action === a)),
    [catalogue],
  );

  const rowScope = (module: string): Scope | '' => {
    const scopes = new Set(
      Object.entries(current)
        .filter(([k]) => k.startsWith(`${module}.`))
        .map(([, s]) => s),
    );
    return scopes.size === 1 ? ([...scopes][0] ?? '') : scopes.size === 0 ? 'all' : '';
  };

  const toggle = (module: string, action: string, on: boolean) => {
    const key = `${module}.${action}`;
    const next: Grants = Object.fromEntries(Object.entries(current).filter(([k]) => k !== key));
    if (on) next[key] = rowScope(module) || 'all';
    setGrants(next);
  };

  const setScope = (module: string, scope: Scope) => {
    const next = { ...current };
    for (const k of Object.keys(next)) if (k.startsWith(`${module}.`)) next[k] = scope;
    setGrants(next);
  };

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const body: RolePermission[] = Object.entries(current).map(([k, scope]) => {
        const [module_code = '', action = ''] = k.split('.');
        return { module_code, action, scope };
      });
      await rolesApi.replacePermissions(role.id, body, reason.trim() || null);
      setGrants(null);
      setReason('');
      saved.reload();
      onSaved(`Saved permissions for ${role.name}. Users see the change after a refresh.`);
    } catch (err) {
      setError(toApiError(err));
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!window.confirm(`Delete the role ${role.name}?`)) return;
    setBusy(true);
    setError(null);
    try {
      await rolesApi.remove(role.id);
      onDeleted(`Deleted ${role.name}.`);
    } catch (err) {
      setError(toApiError(err));
      setBusy(false);
    }
  };

  if (saved.error) return <ErrorState error={saved.error} onRetry={saved.reload} />;
  if (!saved.data) return <LoadingState label="Loading permissions…" />;

  return (
    <div className="roles-matrix">
      <div className="roles-matrix__head">
        <div>
          <h2 className="roles-matrix__title">
            {role.name} {role.is_system && <Badge variant="neutral">System</Badge>}
          </h2>
          <p className="masters-row__meta">
            {role.code} · {role.user_count} {role.user_count === 1 ? 'user' : 'users'}
            {role.description ? ` · ${role.description}` : ''}
          </p>
        </div>
        <div className="user-form__inline">
          {canEdit && (
            <Button type="button" size="sm" onClick={onEdit}>
              Rename
            </Button>
          )}
          {canDelete && (
            <Button
              type="button"
              size="sm"
              variant="danger"
              disabled={busy}
              onClick={() => {
                void remove();
              }}
            >
              Delete
            </Button>
          )}
        </div>
      </div>

      {readOnlyReason && <p className="masters-row__meta">{readOnlyReason}</p>}

      {/* Desktop: grid with sticky header. */}
      <div className="perm-grid" role="region" aria-label={`Permissions of ${role.name}`}>
        <table>
          <thead>
            <tr>
              <th scope="col">Module</th>
              {actions.map((a) => (
                <th key={a} scope="col">
                  {a}
                </th>
              ))}
              <th scope="col">Scope</th>
            </tr>
          </thead>
          <tbody>
            {modules.map(([module, available]) => (
              <tr key={module}>
                <th scope="row">{moduleLabel(module)}</th>
                {actions.map((a) => (
                  <td key={a}>
                    {available.has(a) && (
                      <input
                        type="checkbox"
                        aria-label={`${moduleLabel(module)} ${a}`}
                        checked={`${module}.${a}` in current}
                        disabled={readOnly}
                        onChange={(e) => {
                          toggle(module, a, e.target.checked);
                        }}
                      />
                    )}
                  </td>
                ))}
                <td>
                  <ScopeSelect
                    value={rowScope(module)}
                    disabled={readOnly}
                    onChange={(s) => {
                      setScope(module, s);
                    }}
                    label={`${moduleLabel(module)} scope`}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Phones: one accordion per module. */}
      <div className="perm-accordion">
        {modules.map(([module, available]) => {
          const count = [...available].filter((a) => `${module}.${a}` in current).length;
          return (
            <details key={module} className="perm-accordion__item">
              <summary>
                <span>{moduleLabel(module)}</span>
                <span className="roles-list__count">{count}</span>
              </summary>
              <div className="perm-accordion__body">
                {actions
                  .filter((a) => available.has(a))
                  .map((a) => (
                    <label key={a} className="perm-accordion__check">
                      <input
                        type="checkbox"
                        checked={`${module}.${a}` in current}
                        disabled={readOnly}
                        onChange={(e) => {
                          toggle(module, a, e.target.checked);
                        }}
                      />
                      <span>{a}</span>
                    </label>
                  ))}
                <ScopeSelect
                  value={rowScope(module)}
                  disabled={readOnly}
                  onChange={(s) => {
                    setScope(module, s);
                  }}
                  label={`${moduleLabel(module)} scope`}
                />
              </div>
            </details>
          );
        })}
      </div>

      {!readOnly && (
        <div className="roles-matrix__save">
          <Input
            aria-label="Reason for the change"
            placeholder="Reason for the change (optional)"
            value={reason}
            maxLength={500}
            onChange={(e) => {
              setReason(e.target.value);
            }}
          />
          <div className="user-form__inline">
            <Button
              type="button"
              disabled={!dirty || busy}
              onClick={() => {
                setGrants(null);
              }}
            >
              Discard
            </Button>
            <Button
              type="button"
              variant="primary"
              isLoading={busy}
              disabled={!dirty}
              onClick={() => {
                void save();
              }}
            >
              Save permissions
            </Button>
          </div>
        </div>
      )}
      {error && (
        <p className="user-form__error" role="alert">
          {error.message}
          {error.requestId ? ` (ref ${error.requestId})` : ''}
        </p>
      )}
    </div>
  );
}

function ScopeSelect({
  value,
  disabled,
  onChange,
  label,
}: {
  value: Scope | '';
  disabled: boolean;
  onChange: (scope: Scope) => void;
  label: string;
}) {
  return (
    <select
      className="perm-scope"
      aria-label={label}
      value={value}
      disabled={disabled}
      onChange={(e) => {
        onChange(e.target.value as Scope);
      }}
    >
      {value === '' && <option value="">Mixed</option>}
      {SCOPES.map((s) => (
        <option key={s.value} value={s.value}>
          {s.label}
        </option>
      ))}
    </select>
  );
}

function RoleDialog({
  role,
  onClose,
  onSaved,
}: {
  role: Role | null;
  onClose: () => void;
  onSaved: (msg: string, role: Role) => void;
}) {
  const [code, setCode] = useState('');
  const [name, setName] = useState(role?.name ?? '');
  const [description, setDescription] = useState(role?.description ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const out = role
        ? await rolesApi.update(role.id, {
            name: name.trim(),
            description: description.trim() || null,
          })
        : await rolesApi.create({
            code: code.trim(),
            name: name.trim(),
            description: description.trim() || null,
          });
      onSaved(
        role ? `Saved ${out.name}.` : `Created ${out.name}. Now choose its permissions.`,
        out,
      );
    } catch (err) {
      setError(toApiError(err));
      setBusy(false);
    }
  };

  const valid = name.trim().length > 0 && (role !== null || code.trim().length >= 2);
  return (
    <Modal
      isOpen
      onClose={onClose}
      title={role ? `Rename ${role.name}` : 'New role'}
      footer={
        <>
          <Button type="button" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button
            type="button"
            variant="primary"
            isLoading={busy}
            disabled={!valid}
            onClick={() => {
              void submit();
            }}
          >
            Save
          </Button>
        </>
      }
    >
      <div className="masters-form">
        {role ? (
          <p className="masters-row__meta">
            Code: <strong>{role.code}</strong> (cannot be changed)
          </p>
        ) : (
          <label className="masters-field">
            <span className="form-label">
              Code<span className="required-star">*</span>
            </span>
            <Input
              id="role-code"
              value={code}
              maxLength={60}
              placeholder="e.g. QUALITY_INSPECTOR"
              onChange={(e) => {
                setCode(e.target.value.toUpperCase());
              }}
            />
          </label>
        )}
        <label className="masters-field">
          <span className="form-label">
            Name<span className="required-star">*</span>
          </span>
          <Input
            id="role-name"
            value={name}
            maxLength={120}
            onChange={(e) => {
              setName(e.target.value);
            }}
          />
        </label>
        <label className="masters-field">
          <span className="form-label">Description</span>
          <Input
            id="role-description"
            value={description}
            maxLength={500}
            onChange={(e) => {
              setDescription(e.target.value);
            }}
          />
        </label>
        {error && (
          <p className="user-form__error" role="alert">
            {error.message}
            {error.requestId ? ` (ref ${error.requestId})` : ''}
          </p>
        )}
      </div>
    </Modal>
  );
}
