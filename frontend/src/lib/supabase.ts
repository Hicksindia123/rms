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
    return rawUrl.replace('127.0.0.1', window.location.hostname).replace('localhost', window.location.hostname);
  }
  return rawUrl;
}

let client: SupabaseClient | null = null;

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
    auth: { persistSession: true, autoRefreshToken: true },
  });
  return client;
}
