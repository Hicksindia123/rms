import { useCallback, useState } from 'react';
import { Plus } from 'lucide-react';

import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  Input,
  LoadingState,
  Select,
} from '@/components/ui';
import { useAuth } from '@/features/auth/useAuth';
import './users.css';
import { useApiQuery } from '@/hooks/useApiQuery';

import { rolesApi, usersApi, type AdminUser, type UserListQuery } from './api';
import { DepartmentsPanel } from './DepartmentsPanel';
import { UserDrawer } from './UserDrawer';

const PAGE_SIZE = 25;

type Tab = 'users' | 'departments';
type Open = { mode: 'create' } | { mode: 'edit'; user: AdminUser } | null;

/** P1-05 user administration: users (create, edit, roles, status, password, overrides) and
 *  departments. Every value comes from the users/roles API; the backend enforces every rule. */
export function UsersView() {
  const { can, me } = useAuth();
  const isSuperAdmin = me?.profile.is_super_admin ?? false;
  const canCreate = isSuperAdmin || can('users', 'create');
  const canEdit = isSuperAdmin || can('users', 'edit');
  const canConfigure = isSuperAdmin || can('users', 'configure');
  const canViewRoles = isSuperAdmin || can('roles', 'view');

  const [tab, setTab] = useState<Tab>('users');
  const [query, setQuery] = useState<UserListQuery>({ page: 1, page_size: PAGE_SIZE, status: '' });
  const [search, setSearch] = useState('');
  const [open, setOpen] = useState<Open>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const fetchUsers = useCallback(() => usersApi.list(query), [query]);
  const users = useApiQuery(fetchUsers);
  const fetchDepartments = useCallback(() => usersApi.departments(), []);
  const departments = useApiQuery(fetchDepartments);
  const fetchRoles = useCallback(
    () => (canViewRoles ? rolesApi.list() : Promise.resolve([])),
    [canViewRoles],
  );
  const roles = useApiQuery(fetchRoles);

  const setFilter = (patch: Partial<UserListQuery>) => {
    setQuery((q) => ({ ...q, ...patch, page: 1 }));
  };

  const saved = (msg: string, user?: AdminUser) => {
    setNotice(msg);
    users.reload();
    departments.reload();
    if (user && open?.mode === 'edit') setOpen({ mode: 'edit', user });
  };

  const tabs: Array<{ id: Tab; label: string }> = [
    { id: 'users', label: 'Users' },
    { id: 'departments', label: 'Departments' },
  ];

  const page = users.data;
  const from = page && page.total > 0 ? (page.page - 1) * page.page_size + 1 : 0;
  const to = page ? Math.min(page.page * page.page_size, page.total) : 0;

  return (
    <div className="masters">
      <header>
        <h1 className="masters__title">User Management</h1>
        <p className="masters__subtitle">People, roles, access and departments</p>
      </header>

      <div className="tabs tabs--wrap" role="tablist" aria-label="User management">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            className="tabs__tab"
            aria-selected={tab === t.id}
            onClick={() => {
              setTab(t.id);
              setNotice(null);
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'departments' ? (
        <DepartmentsPanel canConfigure={canConfigure} onChanged={users.reload} />
      ) : (
        <div className="masters-panel">
          <form
            className="filters"
            onSubmit={(e) => {
              e.preventDefault();
              setFilter({ search: search.trim() });
            }}
          >
            <label className="masters-field">
              <span className="form-label">Search</span>
              <Input
                id="user-search"
                type="search"
                placeholder="Name, email or employee code"
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                }}
                onBlur={() => {
                  if ((query.search ?? '') !== search.trim()) setFilter({ search: search.trim() });
                }}
              />
            </label>
            {canViewRoles && (
              <label className="masters-field">
                <span className="form-label">Role</span>
                <Select
                  id="user-filter-role"
                  value={query.role ?? ''}
                  placeholder="All roles"
                  options={(roles.data ?? []).map((r) => ({ value: r.code, label: r.name }))}
                  onChange={(e) => {
                    setFilter({ role: e.target.value });
                  }}
                />
              </label>
            )}
            <label className="masters-field">
              <span className="form-label">Department</span>
              <Select
                id="user-filter-department"
                value={query.department_id ?? ''}
                placeholder="All departments"
                options={(departments.data ?? []).map((d) => ({ value: d.id, label: d.name }))}
                onChange={(e) => {
                  setFilter({ department_id: e.target.value });
                }}
              />
            </label>
            <label className="masters-field">
              <span className="form-label">Status</span>
              <Select
                id="user-filter-status"
                value={query.status ?? ''}
                placeholder="All"
                options={[
                  { value: 'active', label: 'Active' },
                  { value: 'inactive', label: 'Inactive' },
                ]}
                onChange={(e) => {
                  setFilter({ status: e.target.value as 'active' | 'inactive' | '' });
                }}
              />
            </label>
            {canCreate && (
              <div className="masters-field masters-field--action">
                <Button
                  type="button"
                  variant="primary"
                  onClick={() => {
                    setNotice(null);
                    setOpen({ mode: 'create' });
                  }}
                >
                  <Plus size={16} aria-hidden="true" /> Add user
                </Button>
              </div>
            )}
          </form>

          {notice && (
            <p className="masters-notice" role="status">
              {notice}
            </p>
          )}

          {users.error ? (
            <ErrorState error={users.error} onRetry={users.reload} />
          ) : users.loading || !page ? (
            <LoadingState label="Loading users…" />
          ) : page.items.length === 0 ? (
            <EmptyState
              title="No users found"
              hint={
                query.search || query.role || query.department_id || query.status
                  ? 'Try different filters.'
                  : 'Add the first user with “Add user”.'
              }
            />
          ) : (
            <>
              <ul className="masters-list">
                {page.items.map((u) => (
                  <li key={u.id} className="masters-row">
                    <div className="masters-row__main">
                      <div className="masters-row__title">
                        <span>{u.full_name}</span>
                        {u.is_super_admin && <Badge variant="info">Super Admin</Badge>}
                        {!u.is_active && <Badge variant="neutral">Inactive</Badge>}
                        {u.must_change_password && u.is_active && (
                          <Badge variant="warning">Password change pending</Badge>
                        )}
                      </div>
                      <div className="masters-row__meta">
                        {[u.email, u.employee_code, u.department?.name].filter(Boolean).join(' · ')}
                      </div>
                      {u.roles.length > 0 && (
                        <div className="user-roles">
                          {u.roles
                            .filter((r) => r.code !== 'SUPER_ADMIN')
                            .map((r) => (
                              <Badge key={r.id} variant="default">
                                {r.name}
                              </Badge>
                            ))}
                        </div>
                      )}
                    </div>
                    <Button
                      type="button"
                      size="sm"
                      className="masters-row__action"
                      onClick={() => {
                        setNotice(null);
                        setOpen({ mode: 'edit', user: u });
                      }}
                    >
                      {canEdit ? 'Manage' : 'View'}
                    </Button>
                  </li>
                ))}
              </ul>
              <nav className="user-pager" aria-label="Pages">
                <span>
                  {from}–{to} of {page.total}
                </span>
                <div className="user-pager__buttons">
                  <Button
                    type="button"
                    size="sm"
                    disabled={page.page <= 1}
                    onClick={() => {
                      setQuery((q) => ({ ...q, page: q.page - 1 }));
                    }}
                  >
                    Previous
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    disabled={to >= page.total}
                    onClick={() => {
                      setQuery((q) => ({ ...q, page: q.page + 1 }));
                    }}
                  >
                    Next
                  </Button>
                </div>
              </nav>
            </>
          )}
        </div>
      )}

      {open && (
        <UserDrawer
          key={open.mode === 'edit' ? open.user.id : 'new'}
          user={open.mode === 'edit' ? open.user : null}
          roles={roles.data ?? []}
          rolesError={roles.error}
          departments={(departments.data ?? []).filter(
            (d) => d.is_active || (open.mode === 'edit' && open.user.department?.id === d.id),
          )}
          canEdit={open.mode === 'create' ? canCreate : canEdit}
          isSuperAdmin={isSuperAdmin}
          selfId={me?.profile.id ?? null}
          onClose={() => {
            setOpen(null);
          }}
          onSaved={saved}
        />
      )}
    </div>
  );
}
