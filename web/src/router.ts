// A few paths, no router library: history API + popstate. nginx falls back to index.html.
import { useSyncExternalStore } from 'react';

const listeners = new Set<() => void>();
const notify = () => listeners.forEach((l) => l());

if (typeof window !== 'undefined') window.addEventListener('popstate', notify);

export function navigate(path: string): void {
  if (window.location.pathname === path) return;
  window.history.pushState(null, '', path);
  notify();
}

export function usePath(): string {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => window.location.pathname,
  );
}

export type Route =
  | { page: 'dashboard' }
  | { page: 'accounts'; accountId: number | null }
  | { page: 'payments' }
  | { page: 'forecast' };

export function parseRoute(path: string): Route {
  const acct = /^\/accounts(?:\/(\d+))?\/?$/.exec(path);
  if (acct) return { page: 'accounts', accountId: acct[1] ? Number(acct[1]) : null };
  if (/^\/payments\/?$/.test(path)) return { page: 'payments' };
  if (/^\/forecast\/?$/.test(path)) return { page: 'forecast' };
  return { page: 'dashboard' };
}
