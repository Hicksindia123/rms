import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import type { Session } from '@supabase/supabase-js';

import { apiRequest, ApiError } from '@/lib/api/client';
import { clearLocalAuthSession, getSupabase, isSupabaseConfigured } from '@/lib/supabase';

import { AuthContext, type AuthState, type Me } from './useAuth';

const NOT_CONFIGURED = 'Supabase is not configured (VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY).';

/** Supabase auth session (supabase-js) + the RMS profile and permissions from GET /me. */
export function AuthProvider({ children }: { children: ReactNode }) {
  const configured = isSupabaseConfigured();
  const [session, setSession] = useState<Session | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [status, setStatus] = useState<AuthState['status']>(configured ? 'loading' : 'error');
  const [error, setError] = useState<string | null>(configured ? null : NOT_CONFIGURED);

  const loadMe = useCallback(async (s: Session | null) => {
    setSession(s);
    if (!s) {
      setMe(null);
      setStatus('signed-out');
      return;
    }
    try {
      setMe(await apiRequest<Me>('/me'));
      setError(null);
      setStatus('signed-in');
    } catch (err) {
      setMe(null);
      setError(err instanceof ApiError ? `${err.message} (${err.code})` : String(err));
      setStatus('error');
    }
  }, []);

  useEffect(() => {
    if (!configured) return;
    const supabase = getSupabase();
    let active = true;
    void supabase.auth.getSession().then(({ data }) => {
      if (active) void loadMe(data.session);
    });
    const { data } = supabase.auth.onAuthStateChange((event, s) => {
      if (event === 'SIGNED_IN' || event === 'SIGNED_OUT' || event === 'USER_UPDATED') {
        void loadMe(s);
      } else if (event === 'TOKEN_REFRESHED') {
        setSession(s);
      }
    });
    return () => {
      active = false;
      data.subscription.unsubscribe();
    };
  }, [configured, loadMe]);

  const signIn = useCallback(async (email: string, password: string) => {
    const { error: err } = await getSupabase().auth.signInWithPassword({ email, password });
    if (err) throw new Error(err.message);
  }, []);

  const signOut = useCallback(async () => {
    const { error: err } = await getSupabase().auth.signOut();
    if (err) {
      // The server could not end the session (typically 403 session_not_found: it was already
      // revoked by a password reset, timeout or admin action). Signing out must still work on this
      // device, so drop the local session and show the sign-in screen.
      console.warn('Server sign-out failed; clearing the local session instead.', err);
      clearLocalAuthSession();
      await loadMe(null);
    }
  }, [loadMe]);

  const reloadMe = useCallback(async () => {
    await loadMe(session);
  }, [loadMe, session]);

  const can = useCallback(
    (module: string, action: string) =>
      Boolean(
        me &&
        (me.profile.is_super_admin ||
          me.permissions.some((p) => p.module_code === module && p.action === action)),
      ),
    [me],
  );

  const value = useMemo<AuthState>(
    () => ({ status, session, me, error, signIn, signOut, reloadMe, can }),
    [status, session, me, error, signIn, signOut, reloadMe, can],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
