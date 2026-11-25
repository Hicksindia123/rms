import { createClient, type SupabaseClient } from '@supabase/supabase-js';

// §6.1 / CLAUDE.md rule h-i: supabase-js is used only for the auth session (and later Realtime /
// signed uploads). Only the public URL and anon key reach the browser.
const env = import.meta.env as Record<string, string | undefined>;
const rawUrl = env.VITE_SUPABASE_URL ?? '';
const anonKey = env.VITE_SUPABASE_ANON_KEY ?? '';

function resolveSupabaseUrl(): string {
  if (
    rawUrl &&
    typeof window !== 'undefined' &&
    window.location.hostname &&
    window.location.hostname !== 'localhost' &&
    window.location.hostname !== '127.0.0.1'
  ) {
    return rawUrl
      .replace('127.0.0.1', window.location.hostname)
      .replace('localhost', window.location.hostname);
  }
  return rawUrl;
}

let client: SupabaseClient | null = null;

/** Same key supabase-js derives by default (`sb-<first host label>-auth-token`), set explicitly so
 *  existing sessions stay valid and the app can clear it when a server sign-out fails. */
function authStorageKey(): string {
  const firstLabel = new URL(resolveSupabaseUrl()).hostname.split('.')[0] ?? '';
  return `sb-${firstLabel}-auth-token`;
}

/** Remove the persisted auth session from this browser only (no server call). Used when the
 *  server-side session is already gone: auth-js 2.69 then returns AuthSessionMissingError from
 *  signOut() and keeps the stale local session, leaving the user unable to sign out. */
export function clearLocalAuthSession(): void {
  const key = authStorageKey();
  window.localStorage.removeItem(key);
  window.localStorage.removeItem(`${key}-code-verifier`);
  window.localStorage.removeItem(`${key}-user`);
}

export function isSupabaseConfigured(): boolean {
  return rawUrl.length > 0 && anonKey.length > 0;
}

export function getSupabase(): SupabaseClient {
  if (!isSupabaseConfigured()) {
    throw new Error(
      'VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY must be set in frontend/.env.local',
    );
  }
  const effectiveUrl = resolveSupabaseUrl();
  client ??= createClient(effectiveUrl, anonKey, {
    auth: { persistSession: true, autoRefreshToken: true, storageKey: authStorageKey() },
  });
  return client;
}
