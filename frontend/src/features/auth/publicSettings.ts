import { useEffect, useState } from 'react';

import { apiRequest } from '@/lib/api/client';

/** GET /api/v1/config/settings/public: branding for screens shown before sign-in (rule e). */
export interface PublicSettings {
  app_name: string;
  company_name: string | null;
  branding_primary_color: string;
  branding_logo_url: string | null;
}

let cached: PublicSettings | null = null;

/** Branding values from DB configuration. `null` while loading or when the request failed. */
export function usePublicSettings(): PublicSettings | null {
  const [settings, setSettings] = useState<PublicSettings | null>(cached);
  useEffect(() => {
    if (cached) return;
    let active = true;
    apiRequest<PublicSettings>('/config/settings/public').then(
      (data) => {
        cached = data;
        if (active) setSettings(data);
      },
      (err: unknown) => {
        // The sign-in form works without branding; the failure is still visible in the console.
        console.warn('Public settings unavailable', err);
      },
    );
    return () => {
      active = false;
    };
  }, []);
  return settings;
}
