// Fetch wrapper: adds the caller's auth headers, records the region that served every
// response (X-Served-From) and tracks whether the bank is reachable.

export const DENIED_MESSAGE = "You don't have access to that company's data.";
export const UNAVAILABLE_MESSAGE = "Can't reach the bank right now. Retrying…";

export type ApiErrorKind = 'unavailable' | 'denied' | 'unauthenticated' | 'rejected';

export class ApiError extends Error {
  constructor(
    readonly kind: ApiErrorKind,
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

// ------------------------------------------------------------------ tiny stores

type Listener = () => void;

function store<T>(initial: T) {
  let value = initial;
  const listeners = new Set<Listener>();
  return {
    get: () => value,
    set(next: T) {
      if (Object.is(next, value)) return;
      value = next;
      listeners.forEach((l) => l());
    },
    subscribe(l: Listener) {
      listeners.add(l);
      return () => listeners.delete(l);
    },
  };
}

/** Region of the most recent API response that carried X-Served-From. */
export const regionStore = store<string | null>(null);
/** false while the last call could not reach the bank (network error or 5xx). */
export const reachableStore = store<boolean>(true);

// ------------------------------------------------------------------ auth headers

type HeaderProvider = () => Promise<Record<string, string>>;
let authHeaders: HeaderProvider = async () => ({});

export function setAuthHeaders(provider: HeaderProvider): void {
  authHeaders = provider;
}

// ------------------------------------------------------------------ fetch

function detailOf(body: unknown): string | null {
  if (!body || typeof body !== 'object' || !('detail' in body)) return null;
  const detail = (body as { detail: unknown }).detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    // FastAPI validation errors: [{loc, msg}, ...]
    return detail
      .map((d) => (d && typeof d === 'object' && 'msg' in d ? String((d as { msg: unknown }).msg) : ''))
      .filter(Boolean)
      .join(' ')
      .replace(/^Value error, /, '');
  }
  return null;
}

export async function apiFetch<T>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
  let auth: Record<string, string>;
  try {
    auth = await authHeaders();
  } catch {
    throw new ApiError('unauthenticated', 401, 'Your session has expired. Sign in again.');
  }
  const headers: Record<string, string> = { Accept: 'application/json', ...auth };
  if (init.body !== undefined) headers['Content-Type'] = 'application/json';

  let res: Response;
  try {
    res = await fetch(path, {
      method: init.method ?? 'GET',
      headers,
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
      cache: 'no-store',
    });
  } catch {
    reachableStore.set(false);
    throw new ApiError('unavailable', 0, UNAVAILABLE_MESSAGE);
  }

  const region = res.headers.get('X-Served-From');
  if (region) regionStore.set(region);

  if (res.status >= 500) {
    reachableStore.set(false);
    throw new ApiError('unavailable', res.status, UNAVAILABLE_MESSAGE);
  }
  reachableStore.set(true);

  const body: unknown = res.status === 204 ? null : await res.json().catch(() => null);
  if (res.ok) return body as T;
  if (res.status === 404) throw new ApiError('denied', 404, DENIED_MESSAGE);
  if (res.status === 401) throw new ApiError('unauthenticated', 401, detailOf(body) ?? 'Sign in to continue.');
  throw new ApiError('rejected', res.status, detailOf(body) ?? 'The bank could not complete that request.');
}

export const accountsApi = <T>(path: string) => apiFetch<T>(`/api/accounts${path}`);
export const paymentsApi = <T>(path: string, init?: { method?: string; body?: unknown }) =>
  apiFetch<T>(`/api/payments${path}`, init);
export const insightsApi = <T>(path: string) => apiFetch<T>(`/api/insights${path}`);
