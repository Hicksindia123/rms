import { useCallback, useMemo, useState } from 'react';
import { KeyRound, Plus, Trash2, UserCheck, UserX } from 'lucide-react';

import {
  Badge,
  Button,
  Checkbox,
  Drawer,
  ErrorState,
  Input,
  LoadingState,
  Modal,
  Select,
} from '@/components/ui';
import { useApiQuery } from '@/hooks/useApiQuery';
import { toApiError, type ApiError } from '@/lib/api/client';

import {
  moduleLabel,
  rolesApi,
  usersApi,
  type AdminUser,
  type Department,
  type OverrideInput,
  type Role,
} from './api';

interface Props {
  user: AdminUser | null;
  roles: Role[];
  rolesError: ApiError | null;
  departments: Department[];
  canEdit: boolean;
  isSuperAdmin: boolean;
  selfId: string | null;
  onClose: () => void;
  onSaved: (message: string, user?: AdminUser) => void;
}

type Tab = 'profile' | 'access';

/** Random temporary password that satisfies the policy (letters + digits, 12 chars). */
function generatePassword(): string {
  const letters = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz';
  const digits = '23456789';
  const all = letters + digits;
  const bytes = new Uint32Array(12);
  crypto.getRandomValues(bytes);
  const chars = Array.from(bytes, (b, i) => {
    const set = i === 0 ? letters : i === 1 ? digits : all;
    return set[b % set.length] ?? 'x';
  });
  return chars.join('');
}

function ErrorLine({ error }: { error: ApiError | null }) {
  if (!error) return null;
  return (
    <p className="user-form__error" role="alert">
      {error.message}
      {error.requestId ? ` (ref ${error.requestId})` : ''}
    </p>
  );
}

export function UserDrawer(props: Props) {
  const { user, onClose } = props;
  const [tab, setTab] = useState<Tab>('profile');
  const title = user ? user.full_name : 'Add user';
  return (
    <Drawer
      isOpen
      onClose={onClose}
      title={title}
      {...(user?.email ? { subtitle: user.email } : {})}
    >
      {user && (
        <div className="tabs" role="tablist" aria-label="User details">
          {(['profile', 'access'] as const).map((t) => (
            <button
              key={t}
              type="button"
              role="tab"
              className="tabs__tab"
              aria-selected={tab === t}
              onClick={() => {
                setTab(t);
              }}
            >
              {t === 'profile' ? 'Profile' : 'Access'}
            </button>
          ))}
        </div>
      )}
      {user && tab === 'access' ? (
        <AccessTab user={user} canEdit={props.canEdit && user.id !== props.selfId} />
      ) : (
        <ProfileTab {...props} />
      )}
    </Drawer>
  );
}

function ProfileTab({
  user,
  roles,
  rolesError,
  departments,
  canEdit,
  isSuperAdmin,
  selfId,
  onSaved,
  onClose,
}: Props) {
  const isSelf = user !== null && user.id === selfId;
  const editable = canEdit && (!user?.is_super_admin || isSuperAdmin);
  const [fullName, setFullName] = useState(user?.full_name ?? '');
  const [email, setEmail] = useState(user?.email ?? '');
  const [employeeCode, setEmployeeCode] = useState(user?.employee_code ?? '');
  const [phone, setPhone] = useState(user?.phone ?? '');
  const [departmentId, setDepartmentId] = useState(user?.department?.id ?? '');
  const [roleCodes, setRoleCodes] = useState<string[]>(
    (user?.roles ?? []).map((r) => r.code).filter((c) => c !== 'SUPER_ADMIN'),
  );
  const [superAdmin, setSuperAdmin] = useState(user?.is_super_admin ?? false);
  const [password, setPassword] = useState(user ? '' : generatePassword());
  const [mustChange, setMustChange] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [dialog, setDialog] = useState<'deactivate' | 'reactivate' | 'reset' | null>(null);

  const assignable = roles.filter((r) => r.code !== 'SUPER_ADMIN');
  const toggleRole = (code: string, on: boolean) => {
    setRoleCodes((prev) => (on ? [...prev, code] : prev.filter((c) => c !== code)));
  };

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      if (user) {
        const out = await usersApi.update(user.id, {
          full_name: fullName.trim(),
          employee_code: employeeCode.trim() || null,
          phone: phone.trim() || null,
          department_id: departmentId || null,
          ...(isSelf ? {} : { role_codes: roleCodes }),
          ...(isSuperAdmin && !isSelf ? { is_super_admin: superAdmin } : {}),
        });
        onSaved(`Saved ${out.full_name}.`, out);
      } else {
        const out = await usersApi.create({
          email: email.trim(),
          full_name: fullName.trim(),
          employee_code: employeeCode.trim() || null,
          phone: phone.trim() || null,
          department_id: departmentId || null,
          role_codes: roleCodes,
          is_super_admin: isSuperAdmin && superAdmin,
          initial_password: password,
          must_change_password: mustChange,
        });
        onSaved(`Added ${out.full_name}. Share the initial password with them securely.`, out);
        onClose();
      }
    } catch (err) {
      setError(toApiError(err));
    } finally {
      setBusy(false);
    }
  };

  const valid =
    fullName.trim().length > 0 && (user !== null || (email.includes('@') && password.length >= 8));

  return (
    <div className="user-form">
      {user && !editable && (
        <p className="masters-row__meta">
          {user.is_super_admin && !isSuperAdmin
            ? 'Only a Super Admin can change a Super Admin.'
            : 'You can view this user but not change it.'}
        </p>
      )}
      <label className="masters-field">
        <span className="form-label">
          Full name<span className="required-star">*</span>
        </span>
        <Input
          id="user-full-name"
          value={fullName}
          maxLength={200}
          disabled={!editable}
          onChange={(e) => {
            setFullName(e.target.value);
          }}
        />
      </label>
      {!user && (
        <label className="masters-field">
          <span className="form-label">
            Email<span className="required-star">*</span>
          </span>
          <Input
            id="user-email"
            type="email"
            value={email}
            autoComplete="off"
            onChange={(e) => {
              setEmail(e.target.value);
            }}
          />
        </label>
      )}
      <div className="user-form__row">
        <label className="masters-field">
          <span className="form-label">Employee code</span>
          <Input
            id="user-employee-code"
            value={employeeCode}
            maxLength={50}
            disabled={!editable}
            onChange={(e) => {
              setEmployeeCode(e.target.value);
            }}
          />
        </label>
        <label className="masters-field">
          <span className="form-label">Phone</span>
          <Input
            id="user-phone"
            type="tel"
            value={phone}
            maxLength={30}
            disabled={!editable}
            onChange={(e) => {
              setPhone(e.target.value);
            }}
          />
        </label>
      </div>
      <label className="masters-field">
        <span className="form-label">Department</span>
        <Select
          id="user-department"
          value={departmentId}
          placeholder="No department"
          disabled={!editable}
          options={departments.map((d) => ({ value: d.id, label: d.name }))}
          onChange={(e) => {
            setDepartmentId(e.target.value);
          }}
        />
      </label>

      <fieldset className="user-form__roles" disabled={!editable || isSelf}>
        <legend className="form-label">Roles</legend>
        {isSelf && <p className="masters-row__meta">You cannot change your own roles.</p>}
        {rolesError ? (
          <ErrorLine error={rolesError} />
        ) : (
          assignable.map((r) => (
            <Checkbox
              key={r.id}
              id={`role-${r.code}`}
              label={r.name}
              checked={roleCodes.includes(r.code)}
              onChange={(e) => {
                toggleRole(r.code, e.target.checked);
              }}
            />
          ))
        )}
        {isSuperAdmin && (
          <Checkbox
            id="user-super-admin"
            label="Super Admin (full access; system guards still apply)"
            checked={superAdmin}
            disabled={isSelf}
            onChange={(e) => {
              setSuperAdmin(e.target.checked);
            }}
          />
        )}
      </fieldset>

      {!user && (
        <>
          <label className="masters-field">
            <span className="form-label">
              Initial password<span className="required-star">*</span>
            </span>
            <div className="user-form__inline">
              <Input
                id="user-initial-password"
                value={password}
                autoComplete="new-password"
                onChange={(e) => {
                  setPassword(e.target.value);
                }}
              />
              <Button
                type="button"
                onClick={() => {
                  setPassword(generatePassword());
                }}
              >
                Generate
              </Button>
            </div>
          </label>
          <Checkbox
            id="user-must-change"
            label="Ask the user to set their own password at first sign-in"
            checked={mustChange}
            onChange={(e) => {
              setMustChange(e.target.checked);
            }}
          />
        </>
      )}

      <ErrorLine error={error} />

      {editable && (
        <div className="user-form__actions">
          <Button
            type="button"
            variant="primary"
            isLoading={busy}
            disabled={!valid}
            onClick={() => {
              void submit();
            }}
          >
            {user ? 'Save changes' : 'Create user'}
          </Button>
        </div>
      )}

      {user && editable && !isSelf && (
        <section className="user-form__account" aria-label="Account actions">
          <h3 className="form-label">Account</h3>
          <div className="user-form__inline">
            <Button
              type="button"
              onClick={() => {
                setDialog('reset');
              }}
            >
              <KeyRound size={16} aria-hidden="true" /> Reset password
            </Button>
            {user.is_active ? (
              <Button
                type="button"
                variant="danger"
                onClick={() => {
                  setDialog('deactivate');
                }}
              >
                <UserX size={16} aria-hidden="true" /> Deactivate
              </Button>
            ) : (
              <Button
                type="button"
                onClick={() => {
                  setDialog('reactivate');
                }}
              >
                <UserCheck size={16} aria-hidden="true" /> Reactivate
              </Button>
            )}
          </div>
        </section>
      )}

      {user && dialog && (
        <AccountDialog
          user={user}
          kind={dialog}
          onClose={() => {
            setDialog(null);
          }}
          onDone={(msg, out) => {
            setDialog(null);
            onSaved(msg, out);
          }}
        />
      )}
    </div>
  );
}

function AccountDialog({
  user,
  kind,
  onClose,
  onDone,
}: {
  user: AdminUser;
  kind: 'deactivate' | 'reactivate' | 'reset';
  onClose: () => void;
  onDone: (message: string, user: AdminUser) => void;
}) {
  const [reason, setReason] = useState('');
  const [password, setPassword] = useState(generatePassword);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  const titles = {
    deactivate: `Deactivate ${user.full_name}`,
    reactivate: `Reactivate ${user.full_name}`,
    reset: `Reset password for ${user.full_name}`,
  } as const;

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = reason.trim();
      if (kind === 'deactivate') {
        onDone(
          `${user.full_name} was deactivated and signed out.`,
          await usersApi.deactivate(user.id, r),
        );
      } else if (kind === 'reactivate') {
        onDone(`${user.full_name} can sign in again.`, await usersApi.reactivate(user.id, r));
      } else {
        onDone(
          `Temporary password set for ${user.full_name}. They must change it at next sign-in.`,
          await usersApi.resetPassword(user.id, password, r),
        );
      }
    } catch (err) {
      setError(toApiError(err));
      setBusy(false);
    }
  };

  const valid = reason.trim().length >= 3 && (kind !== 'reset' || password.length >= 8);
  return (
    <Modal
      isOpen
      onClose={onClose}
      title={titles[kind]}
      footer={
        <>
          <Button type="button" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button
            type="button"
            variant={kind === 'deactivate' ? 'danger' : 'primary'}
            isLoading={busy}
            disabled={!valid}
            onClick={() => {
              void submit();
            }}
          >
            {kind === 'deactivate'
              ? 'Deactivate'
              : kind === 'reactivate'
                ? 'Reactivate'
                : 'Set password'}
          </Button>
        </>
      }
    >
      <div className="masters-form">
        {kind === 'deactivate' && (
          <p className="masters-row__meta">
            The user is signed out and can no longer use RMS. Their history is kept.
          </p>
        )}
        {kind === 'reset' && (
          <label className="masters-field">
            <span className="form-label">Temporary password</span>
            <div className="user-form__inline">
              <Input
                id="reset-password-value"
                value={password}
                autoComplete="new-password"
                onChange={(e) => {
                  setPassword(e.target.value);
                }}
              />
              <Button
                type="button"
                onClick={() => {
                  setPassword(generatePassword());
                }}
              >
                Generate
              </Button>
            </div>
          </label>
        )}
        <label className="masters-field">
          <span className="form-label">
            Reason<span className="required-star">*</span>
          </span>
          <Input
            id="account-reason"
            value={reason}
            maxLength={500}
            onChange={(e) => {
              setReason(e.target.value);
            }}
          />
        </label>
        <ErrorLine error={error} />
      </div>
    </Modal>
  );
}

interface DraftOverride extends OverrideInput {
  key: string;
}

function AccessTab({ user, canEdit }: { user: AdminUser; canEdit: boolean }) {
  const fetchOverrides = useCallback(() => usersApi.overrides(user.id), [user.id]);
  const overrides = useApiQuery(fetchOverrides);
  const fetchEffective = useCallback(() => usersApi.effectivePermissions(user.id), [user.id]);
  const effective = useApiQuery(fetchEffective);
  const fetchCatalogue = useCallback(() => rolesApi.catalogue(), []);
  const catalogue = useApiQuery(fetchCatalogue);

  const [draft, setDraft] = useState<DraftOverride[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const rows: DraftOverride[] = useMemo(
    () =>
      draft ??
      (overrides.data ?? []).map((o) => ({
        key: o.id,
        module_code: o.module_code,
        action: o.action,
        effect: o.effect,
        reason: o.reason,
        expires_at: o.expires_at ? o.expires_at.slice(0, 10) : null,
      })),
    [draft, overrides.data],
  );
  const permissionOptions = (catalogue.data ?? []).map((p) => ({
    value: `${p.module_code}.${p.action}`,
    label: `${moduleLabel(p.module_code)} · ${p.action}`,
  }));

  const update = (key: string, patch: Partial<DraftOverride>) => {
    setDraft(rows.map((r) => (r.key === key ? { ...r, ...patch } : r)));
    setNotice(null);
  };

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await usersApi.replaceOverrides(
        user.id,
        rows.map((r) => ({
          module_code: r.module_code,
          action: r.action,
          effect: r.effect,
          reason: r.reason.trim(),
          expires_at: r.expires_at ? new Date(`${r.expires_at}T23:59:59`).toISOString() : null,
        })),
      );
      setDraft(null);
      setNotice('Access saved.');
      overrides.reload();
      effective.reload();
    } catch (err) {
      setError(toApiError(err));
    } finally {
      setBusy(false);
    }
  };

  const grouped = useMemo(() => {
    const map = new Map<string, string[]>();
    for (const p of effective.data?.permissions ?? []) {
      const label = p.scope === 'all' ? p.action : `${p.action} (${p.scope})`;
      map.set(p.module_code, [...(map.get(p.module_code) ?? []), label]);
    }
    return [...map.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [effective.data]);

  if (overrides.error) return <ErrorState error={overrides.error} onRetry={overrides.reload} />;
  if (overrides.loading || !overrides.data) return <LoadingState label="Loading access…" />;

  const valid = rows.every((r) => r.module_code && r.action && r.reason.trim().length >= 3);
  return (
    <div className="user-form">
      <section aria-label="Permission overrides">
        <h3 className="form-label">Exceptions to the user’s roles</h3>
        <p className="masters-row__meta">
          A deny always wins over a role. Expired exceptions are ignored.
        </p>
        {catalogue.error && <ErrorLine error={catalogue.error} />}
        {rows.length === 0 && <p className="masters-row__meta">No exceptions.</p>}
        <ul className="user-overrides">
          {rows.map((r) => (
            <li key={r.key} className="user-override">
              <Select
                aria-label="Permission"
                value={r.module_code ? `${r.module_code}.${r.action}` : ''}
                placeholder="Choose permission"
                disabled={!canEdit}
                options={permissionOptions}
                onChange={(e) => {
                  const [m = '', a = ''] = e.target.value.split('.');
                  update(r.key, { module_code: m, action: a });
                }}
              />
              <Select
                aria-label="Effect"
                value={r.effect}
                disabled={!canEdit}
                options={[
                  { value: 'grant', label: 'Allow' },
                  { value: 'deny', label: 'Deny' },
                ]}
                onChange={(e) => {
                  update(r.key, { effect: e.target.value as 'grant' | 'deny' });
                }}
              />
              <Input
                aria-label="Reason"
                placeholder="Reason"
                value={r.reason}
                disabled={!canEdit}
                onChange={(e) => {
                  update(r.key, { reason: e.target.value });
                }}
              />
              <Input
                aria-label="Expires on"
                type="date"
                value={r.expires_at ?? ''}
                disabled={!canEdit}
                onChange={(e) => {
                  update(r.key, { expires_at: e.target.value || null });
                }}
              />
              {canEdit && (
                <Button
                  type="button"
                  variant="ghost"
                  aria-label="Remove exception"
                  onClick={() => {
                    setDraft(rows.filter((x) => x.key !== r.key));
                  }}
                >
                  <Trash2 size={16} aria-hidden="true" />
                </Button>
              )}
            </li>
          ))}
        </ul>
        {canEdit && (
          <div className="user-form__inline">
            <Button
              type="button"
              onClick={() => {
                setDraft([
                  ...rows,
                  {
                    key: `new-${String(Date.now())}`,
                    module_code: '',
                    action: '',
                    effect: 'grant',
                    reason: '',
                    expires_at: null,
                  },
                ]);
              }}
            >
              <Plus size={16} aria-hidden="true" /> Add exception
            </Button>
            <Button
              type="button"
              variant="primary"
              isLoading={busy}
              disabled={draft === null || !valid}
              onClick={() => {
                void save();
              }}
            >
              Save access
            </Button>
          </div>
        )}
        <ErrorLine error={error} />
        {notice && (
          <p className="masters-notice" role="status">
            {notice}
          </p>
        )}
      </section>

      <section aria-label="Effective permissions" className="user-effective">
        <h3 className="form-label">What this user can do</h3>
        {effective.error ? (
          <ErrorState error={effective.error} onRetry={effective.reload} />
        ) : !effective.data ? (
          <LoadingState label="Calculating…" />
        ) : effective.data.is_super_admin ? (
          <p className="masters-row__meta">
            <Badge variant="info">Super Admin</Badge> Every permission. System guards still apply.
          </p>
        ) : grouped.length === 0 ? (
          <p className="masters-row__meta">No permissions.</p>
        ) : (
          <dl className="user-effective__list">
            {grouped.map(([module, actions]) => (
              <div key={module} className="user-effective__row">
                <dt>{moduleLabel(module)}</dt>
                <dd>{actions.join(', ')}</dd>
              </div>
            ))}
          </dl>
        )}
      </section>
    </div>
  );
}
