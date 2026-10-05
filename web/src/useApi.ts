import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { ApiError, reachableStore, regionStore } from './api';

export const useRegion = () => useSyncExternalStore(regionStore.subscribe, regionStore.get);
export const useReachable = () => useSyncExternalStore(reachableStore.subscribe, reachableStore.get);

export interface ApiState<T> {
  data: T | undefined;
  error: ApiError | undefined;
  loading: boolean;
  reload: () => void;
}

/**
 * Loads `fetcher` on mount and whenever `key` changes; refreshes silently every `refreshMs`.
 * After a failed "unavailable" load it reloads as soon as the bank is reachable again
 * (the Shell probes every 5 s while it isn't).
 */
export function useApi<T>(key: string | null, fetcher: () => Promise<T>, refreshMs?: number): ApiState<T> {
  const [data, setData] = useState<T>();
  const [error, setError] = useState<ApiError>();
  const [loading, setLoading] = useState(key !== null);
  const seq = useRef(0);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const load = useCallback(() => {
    if (key === null) return;
    const mine = ++seq.current;
    fetcherRef
      .current()
      .then((d) => {
        if (mine !== seq.current) return;
        setData(d);
        setError(undefined);
      })
      .catch((e: unknown) => {
        if (mine !== seq.current) return;
        setError(e instanceof ApiError ? e : new ApiError('unavailable', 0, String(e)));
      })
      .finally(() => {
        if (mine === seq.current) setLoading(false);
      });
  }, [key]);

  useEffect(() => {
    setData(undefined);
    setError(undefined);
    setLoading(key !== null);
    load();
    return () => {
      seq.current++; // ignore responses that land after unmount or a key change
    };
  }, [key, load]);

  useEffect(() => {
    if (!refreshMs || key === null) return;
    const id = setInterval(load, refreshMs);
    return () => clearInterval(id);
  }, [key, load, refreshMs]);

  const reachable = useReachable();
  useEffect(() => {
    if (reachable && error?.kind === 'unavailable') load();
  }, [reachable, error, load]);

  return { data, error, loading, reload: load };
}
