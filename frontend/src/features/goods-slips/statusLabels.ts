import { useEffect, useState } from 'react';

import { apiRequest } from '@/lib/api/client';

import { humanize } from './format';

/** AMD-08: goods-slip status labels from the GS_STATUS option set (codes never change). */
interface StatusLabel {
  code: string;
  label: string;
}

let cache: Promise<Map<string, string>> | null = null;

function load(): Promise<Map<string, string>> {
  cache ??= apiRequest<StatusLabel[]>('/gs/lookups/statuses')
    .then((rows) => new Map(Array.isArray(rows) ? rows.map((r) => [r.code, r.label]) : []))
    .catch((err: unknown) => {
      // Allow a retry on the next use; until then the code is shown in words.
      console.error('Status labels could not be loaded', err);
      cache = null;
      return new Map<string, string>();
    });
  return cache;
}

/** Label lookup; falls back to the code in words while loading or if the lookup failed. */
export function useStatusLabels(): (code: string) => string {
  const [labels, setLabels] = useState<Map<string, string> | null>(null);
  useEffect(() => {
    let live = true;
    void load().then((m) => {
      if (live) setLabels(m);
    });
    return () => {
      live = false;
    };
  }, []);
  return (code: string) => labels?.get(code) ?? humanize(code);
}

/** Test helper: forget the cached labels. */
export function resetStatusLabelCache(): void {
  cache = null;
}
