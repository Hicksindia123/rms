import { useCallback, useEffect, useState } from 'react';

import { toApiError, type ApiError } from '@/lib/api/client';

interface QueryState<T> {
  source: (() => Promise<T>) | null;
  reloadKey: number;
  data: T | null;
  error: ApiError | null;
}

export interface ApiQuery<T> {
  data: T | null;
  error: ApiError | null;
  loading: boolean;
  reload: () => void;
  /** Replace the data after a command returned the fresh resource. */
  setData: (data: T) => void;
}

/**
 * Runs `fetcher` (memoise it with useCallback) and exposes loading / error / data / reload.
 * State only changes from the async callbacks, never synchronously inside the effect.
 */
export function useApiQuery<T>(fetcher: () => Promise<T>): ApiQuery<T> {
  const [reloadKey, setReloadKey] = useState(0);
  const [state, setState] = useState<QueryState<T>>({
    source: null,
    reloadKey: -1,
    data: null,
    error: null,
  });

  useEffect(() => {
    let active = true;
    fetcher().then(
      (data) => {
        if (active) setState({ source: fetcher, reloadKey, data, error: null });
      },
      (err: unknown) => {
        if (active) setState((s) => ({ ...s, source: fetcher, reloadKey, error: toApiError(err) }));
      },
    );
    return () => {
      active = false;
    };
  }, [fetcher, reloadKey]);

  const reload = useCallback(() => {
    setReloadKey((k) => k + 1);
  }, []);
  const setData = useCallback((data: T) => {
    setState((s) => ({ ...s, data, error: null }));
  }, []);

  const current = state.source === fetcher && state.reloadKey === reloadKey;
  return {
    data: state.data,
    error: current ? state.error : null,
    loading: !current,
    reload,
    setData,
  };
}
