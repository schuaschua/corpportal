import { createContext, useContext } from 'react';
import type { AuthMode } from '../config';
import type { Me } from '../types';

export type AuthStatus = 'signed-out' | 'loading' | 'signed-in';

export interface DemoUser {
  username: string;
  name: string;
}

/** PoC-only user switcher (dev mode). */
export const DEMO_USERS: DemoUser[] = [
  { username: 'priya', name: 'Priya Nair' },
  { username: 'tom', name: 'Tom Okafor' },
  { username: 'omar', name: 'Omar Haddad' },
];

export interface Auth {
  mode: AuthMode;
  status: AuthStatus;
  me: Me | null;
  /** Shown on the Login screen after a failed sign-in. */
  error: string | null;
  /** dev: the demo username; entra: ignored (redirects to Microsoft sign-in). */
  signIn: (username?: string) => void;
  /** dev: switches the X-Demo-User; entra: re-runs login with prompt=select_account. */
  switchUser: (username?: string) => void;
  signOut: () => void;
}

export const AuthContext = createContext<Auth | null>(null);

export function useAuth(): Auth {
  const auth = useContext(AuthContext);
  if (!auth) throw new Error('useAuth outside AuthProvider');
  return auth;
}
