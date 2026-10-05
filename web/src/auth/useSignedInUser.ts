import { useEffect, useState } from 'react';
import { accountsApi, ApiError } from '../api';
import type { Me } from '../types';
import type { AuthStatus } from './AuthContext';

/** Loads /me for `identity` (a username or Entra account id) once auth headers are in place. */
export function useSignedInUser(identity: string | null) {
  const [me, setMe] = useState<Me | null>(null);
  const [status, setStatus] = useState<AuthStatus>(identity ? 'loading' : 'signed-out');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!identity) {
      setMe(null);
      setStatus('signed-out');
      return;
    }
    let live = true;
    setStatus('loading');
    const attempt = () =>
      accountsApi<Me>('/me')
        .then((m) => {
          if (!live) return;
          setMe(m);
          setError(null);
          setStatus('signed-in');
        })
        .catch((e: unknown) => {
          if (!live) return;
          if (e instanceof ApiError && e.kind === 'unavailable') {
            timer = setTimeout(attempt, 5000); // bank unreachable: keep trying
            return;
          }
          setMe(null);
          setError(e instanceof Error ? e.message : String(e));
          setStatus('signed-out');
        });
    let timer: ReturnType<typeof setTimeout> | undefined;
    attempt();
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [identity]);

  return { me, status, error };
}
