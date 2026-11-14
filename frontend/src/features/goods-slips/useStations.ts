import { useCallback, useRef, useState } from 'react';

import { gsApi, type LookupItem } from './api';
import { getStationsForState } from './indiaData';

export type PartySelection =
  | { kind: 'existing'; id: string; name: string; stateId: string | null; stationId: string | null }
  | { kind: 'provisional'; name: string; stateId: string; stationId: string };

export interface StationCache {
  load: (stateId: string) => void;
  get: (stateId: string | null | undefined) => LookupItem[];
}

/** Loads the station list of a state, backed by API + All India static dataset fallback. */
export function useStations(statesList?: LookupItem[]): StationCache {
  const cache = useRef(new Map<string, LookupItem[]>());
  const [, force] = useState(0);

  const resolveStaticStations = useCallback(
    (stateId: string): LookupItem[] => {
      const stateItem = statesList?.find(
        (s) =>
          s.id === stateId ||
          s.name.trim().toLowerCase() === stateId.trim().toLowerCase() ||
          (s.code && s.code.trim().toLowerCase() === stateId.trim().toLowerCase()),
      );
      const stateName = stateItem?.name ?? stateId;
      return getStationsForState(stateName);
    },
    [statesList],
  );

  const load = useCallback(
    (stateId: string) => {
      if (!stateId) return;
      const existing = cache.current.get(stateId);
      if (existing && existing.length > 0) return;

      const staticList = resolveStaticStations(stateId);
      if (staticList.length > 0) {
        cache.current.set(stateId, staticList);
        force((n) => n + 1);
      }

      // If stateId is a UUID, attempt to load from API for database-linked stations
      const isUuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
        stateId,
      );
      if (isUuid) {
        gsApi
          .stations(stateId)
          .then((rows) => {
            const staticList = resolveStaticStations(stateId);
            const stationMap = new Map<string, LookupItem>();
            // 1. Always include all stations from comprehensive All-India dataset
            for (const item of staticList) {
              stationMap.set(item.name.trim().toLowerCase(), item);
            }
            // 2. Overwrite / enrich with API rows so database UUIDs take precedence for matched records
            for (const row of rows || []) {
              if (row && row.name) {
                stationMap.set(row.name.trim().toLowerCase(), row);
              }
            }
            const merged = Array.from(stationMap.values()).sort((a, b) =>
              a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }),
            );
            cache.current.set(stateId, merged);
            force((n) => n + 1);
          })
          .catch((err: unknown) => {
            console.warn('Station API lookup fallback to static dataset', err);
          });
      }
    },
    [resolveStaticStations],
  );

  const get = useCallback(
    (stateId: string | null | undefined) => {
      if (!stateId) return [];
      const cached = cache.current.get(stateId);
      if (cached && cached.length > 0) return cached;
      return resolveStaticStations(stateId);
    },
    [resolveStaticStations],
  );

  return { load, get };
}
