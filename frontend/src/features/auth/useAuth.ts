import { createContext, useContext } from 'react';
import type { Session } from '@supabase/supabase-js';

export interface MePermission {
  module_code: string;
  action: string;
  scope: string;
}

/** GET /api/v1/me (backend/app/modules/auth/schemas.py). */
export interface Me {
  profile: {
    id: string;
    email: string | null;
    full_name: string;
    is_super_admin: boolean;
    /** P1-05 / DEC-50: an admin-issued temporary password must be replaced first. */
    must_change_password?: boolean;
  };
  roles: Array<{ code: string; name: string }>;
  permissions: MePermission[];
  step_codes: string[];
}

export interface AuthState {
  status: 'loading' | 'signed-out' | 'signed-in' | 'error';
  session: Session | null;
  me: Me | null;
  error: string | null;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  /** Re-read GET /me (after the user changed their own profile or password). */
  reloadMe: () => Promise<void>;
  can: (module: string, action: string) => boolean;
}

export const AuthContext = createContext<AuthState | null>(null);

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>');
  return ctx;
}
