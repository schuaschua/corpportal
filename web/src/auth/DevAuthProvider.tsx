import { useCallback, useMemo, useState, type ReactNode } from 'react';
import { setAuthHeaders } from '../api';
import { AuthContext, type Auth } from './AuthContext';
import { useSignedInUser } from './useSignedInUser';

const KEY = 'corportal.demoUser';

function readStored(): string | null {
  try {
    return window.sessionStorage.getItem(KEY);
  } catch {
    return null;
  }
}

function store(username: string | null) {
  try {
    if (username) window.sessionStorage.setItem(KEY, username);
    else window.sessionStorage.removeItem(KEY);
  } catch {
    /* private window: the session just won't survive a reload */
  }
}

/** AUTH_MODE=dev: the caller is whoever X-Demo-User names (local compose only). */
export function DevAuthProvider({ children, initialUser }: { children: ReactNode; initialUser?: string }) {
  const [username, setUsername] = useState<string | null>(() => initialUser ?? readStored());

  // Set during render so the header is in place before any child effect fetches.
  setAuthHeaders(async (): Promise<Record<string, string>> => (username ? { 'X-Demo-User': username } : {}));

  const { me, status, error } = useSignedInUser(username);

  const choose = useCallback((next?: string) => {
    const u = (next ?? 'priya').toLowerCase();
    store(u);
    setUsername(u);
  }, []);

  const auth = useMemo<Auth>(
    () => ({
      mode: 'dev',
      status,
      me,
      error,
      signIn: choose,
      switchUser: choose,
      signOut: () => {
        store(null);
        setUsername(null);
      },
    }),
    [status, me, error, choose],
  );

  return <AuthContext.Provider value={auth}>{children}</AuthContext.Provider>;
}
