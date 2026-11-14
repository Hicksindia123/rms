import { apiRequest } from '@/lib/api/client';

// Shapes mirror backend/app/modules/users/schemas.py and roles/schemas.py (P1-05).

export interface RoleRef {
  id: string;
  code: string;
  name: string;
}

export interface DepartmentRef {
  id: string;
  code: string;
  name: string;
}

export interface AdminUser {
  id: string;
  email: string | null;
  full_name: string;
  employee_code: string | null;
  phone: string | null;
  department: DepartmentRef | null;
  is_active: boolean;
  is_super_admin: boolean;
  must_change_password: boolean;
  roles: RoleRef[];
  created_at: string;
  updated_at: string;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface UserCreateInput {
  email: string;
  full_name: string;
  employee_code?: string | null;
  phone?: string | null;
  department_id?: string | null;
  role_codes: string[];
  is_super_admin: boolean;
  initial_password: string;
  must_change_password: boolean;
}

export interface UserUpdateInput {
  full_name?: string;
  employee_code?: string | null;
  phone?: string | null;
  department_id?: string | null;
  role_codes?: string[];
  is_super_admin?: boolean;
  reason?: string;
}

export interface Department {
  id: string;
  code: string;
  name: string;
  is_active: boolean;
  user_count: number;
}

export interface Override {
  id: string;
  module_code: string;
  action: string;
  effect: 'grant' | 'deny';
  reason: string;
  expires_at: string | null;
  is_expired: boolean;
  created_at: string;
}

export interface OverrideInput {
  module_code: string;
  action: string;
  effect: 'grant' | 'deny';
  reason: string;
  expires_at: string | null;
}

export interface EffectivePermissions {
  user_id: string;
  is_super_admin: boolean;
  permissions: Array<{ module_code: string; action: string; scope: string }>;
}

export type Scope = 'own' | 'department' | 'all';

export interface Role {
  id: string;
  code: string;
  name: string;
  description: string | null;
  is_system: boolean;
  user_count: number;
  permission_count: number;
}

export interface CataloguePermission {
  module_code: string;
  action: string;
  description: string | null;
}

export interface RolePermission {
  module_code: string;
  action: string;
  scope: Scope;
}

export interface UserListQuery {
  search?: string;
  role?: string;
  department_id?: string;
  status?: 'active' | 'inactive' | '';
  page: number;
  page_size: number;
}

export const usersApi = {
  list: (q: UserListQuery) =>
    apiRequest<Page<AdminUser>>('/admin/users', {
      query: {
        search: q.search,
        role: q.role,
        department_id: q.department_id,
        status: q.status,
        page: q.page,
        page_size: q.page_size,
      },
    }),
  create: (body: UserCreateInput) =>
    apiRequest<AdminUser>('/admin/users', { method: 'POST', body }),
  update: (id: string, body: UserUpdateInput) =>
    apiRequest<AdminUser>(`/admin/users/${id}`, { method: 'PATCH', body }),
  deactivate: (id: string, reason: string) =>
    apiRequest<AdminUser>(`/admin/users/${id}/deactivate`, { method: 'POST', body: { reason } }),
  reactivate: (id: string, reason: string) =>
    apiRequest<AdminUser>(`/admin/users/${id}/reactivate`, { method: 'POST', body: { reason } }),
  resetPassword: (id: string, temporary_password: string, reason: string) =>
    apiRequest<AdminUser>(`/admin/users/${id}/reset-password`, {
      method: 'POST',
      body: { temporary_password, reason },
    }),
  effectivePermissions: (id: string) =>
    apiRequest<EffectivePermissions>(`/admin/users/${id}/effective-permissions`),
  overrides: (id: string) => apiRequest<Override[]>(`/admin/users/${id}/overrides`),
  replaceOverrides: (id: string, overrides: OverrideInput[]) =>
    apiRequest<Override[]>(`/admin/users/${id}/overrides`, {
      method: 'PUT',
      body: { overrides },
    }),
  departments: () => apiRequest<Department[]>('/admin/departments'),
  createDepartment: (code: string, name: string) =>
    apiRequest<Department>('/admin/departments', { method: 'POST', body: { code, name } }),
  updateDepartment: (id: string, body: { name?: string; is_active?: boolean }) =>
    apiRequest<Department>(`/admin/departments/${id}`, { method: 'PATCH', body }),
};

export const rolesApi = {
  list: () => apiRequest<Role[]>('/admin/roles'),
  create: (body: { code: string; name: string; description?: string | null }) =>
    apiRequest<Role>('/admin/roles', { method: 'POST', body }),
  update: (id: string, body: { name?: string; description?: string | null }) =>
    apiRequest<Role>(`/admin/roles/${id}`, { method: 'PATCH', body }),
  remove: (id: string) => apiRequest<undefined>(`/admin/roles/${id}`, { method: 'DELETE' }),
  catalogue: () => apiRequest<CataloguePermission[]>('/admin/permissions'),
  permissions: (id: string) => apiRequest<RolePermission[]>(`/admin/roles/${id}/permissions`),
  replacePermissions: (id: string, permissions: RolePermission[], reason: string | null) =>
    apiRequest<RolePermission[]>(`/admin/roles/${id}/permissions`, {
      method: 'PUT',
      body: { permissions, reason },
    }),
};

/** Human label for a module code (codes stay the logic key, rule e). */
export function moduleLabel(code: string): string {
  return code
    .split('_')
    .map((w) => (w[0] ?? '').toUpperCase() + w.slice(1))
    .join(' ');
}

export const ACTIONS = [
  'view',
  'create',
  'edit',
  'approve',
  'delete',
  'export',
  'configure',
] as const;
