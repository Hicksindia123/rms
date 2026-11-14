import { useCallback, useEffect, useState } from 'react';

/**
 * Minimal hash router: `#/gs/new`, `#/gs/<id>`, `#/gs/<id>/tag`, `#/mywork` … Deep links and the
 * print view work without a server-side route table, and existing tab navigation keeps working.
 */
export function parseHash(hash: string): string[] {
  return (
    hash.replace(/^#\/?/, '').split('?')[0]?.split('/').filter(Boolean).map(decodeURIComponent) ??
    []
  );
}

/** The query string of the hash route (`#/gs?status=INSPECTION` → status=INSPECTION). */
export function parseHashQuery(hash: string): URLSearchParams {
  const i = hash.indexOf('?');
  return new URLSearchParams(i >= 0 ? hash.slice(i + 1) : '');
}

/** Build a hash path with query parameters (repeated keys for arrays). */
export function hashPath(
  path: string,
  query: Record<string, string | string[] | undefined>,
): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined) continue;
    for (const v of Array.isArray(value) ? value : [value]) params.append(key, v);
  }
  const qs = params.toString();
  return qs ? `${path}?${qs}` : path;
}

export function useHashRoute(): [string[], (path: string) => void] {
  const [segments, setSegments] = useState(() => parseHash(window.location.hash));

  useEffect(() => {
    const onChange = () => {
      setSegments(parseHash(window.location.hash));
    };
    window.addEventListener('hashchange', onChange);
    return () => {
      window.removeEventListener('hashchange', onChange);
    };
  }, []);

  const navigate = useCallback((path: string) => {
    const target = `#${path.startsWith('/') ? path : `/${path}`}`;
    if (window.location.hash === target) {
      setSegments(parseHash(target));
    } else {
      window.location.hash = target;
    }
    window.scrollTo({ top: 0 });
  }, []);

  return [segments, navigate];
}
