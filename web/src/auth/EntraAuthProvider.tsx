import {
  InteractionRequiredAuthError,
  InteractionStatus,
  PublicClientApplication,
  type AccountInfo,
} from '@azure/msal-browser';
import { MsalProvider, useMsal } from '@azure/msal-react';
import { useMemo, type ReactNode } from 'react';
import { setAuthHeaders } from '../api';
import { config } from '../config';
import { AuthContext, type Auth } from './AuthContext';
import { useSignedInUser } from './useSignedInUser';

const scopes = () => (config.entraApiScope ? [config.entraApiScope] : []);

/** Creates and initialises MSAL, completing any login redirect that brought us back here. */
export async function createMsal(): Promise<PublicClientApplication> {
  if (!config.entraClientId || !config.entraAuthority) {
    throw new Error('Entra sign-in is not configured (VITE_ENTRA_CLIENT_ID, VITE_ENTRA_AUTHORITY).');
  }
  const msal = new PublicClientApplication({
    auth: {
      clientId: config.entraClientId,
      authority: config.entraAuthority,
      knownAuthorities: config.entraKnownAuthority ? [config.entraKnownAuthority] : [],
      redirectUri: window.location.origin + '/',
      postLogoutRedirectUri: window.location.origin + '/',
    },
    cache: { cacheLocation: 'sessionStorage' },
  });
  await msal.initialize();
  const result = await msal.handleRedirectPromise();
  const account = result?.account ?? msal.getAllAccounts()[0];
  if (account) msal.setActiveAccount(account);
  return msal;
}

function EntraAuth({ children }: { children: ReactNode }) {
  const { instance, inProgress } = useMsal();
  const account: AccountInfo | null = instance.getActiveAccount() ?? instance.getAllAccounts()[0] ?? null;
  const ready = account && inProgress === InteractionStatus.None;

  setAuthHeaders(async (): Promise<Record<string, string>> => {
    const active = instance.getActiveAccount() ?? instance.getAllAccounts()[0];
    if (!active) return {};
    try {
      const { accessToken } = await instance.acquireTokenSilent({ scopes: scopes(), account: active });
      return { Authorization: `Bearer ${accessToken}` };
    } catch (e) {
      if (e instanceof InteractionRequiredAuthError) {
        await instance.acquireTokenRedirect({ scopes: scopes(), account: active });
      }
      throw e;
    }
  });

  const { me, status, error } = useSignedInUser(ready ? account.homeAccountId : null);

  const auth = useMemo<Auth>(
    () => ({
      mode: 'entra',
      status: inProgress !== InteractionStatus.None && !me ? 'loading' : status,
      me,
      error,
      signIn: () => void instance.loginRedirect({ scopes: scopes() }),
      switchUser: () => void instance.loginRedirect({ scopes: scopes(), prompt: 'select_account' }),
      signOut: () => void instance.logoutRedirect(),
    }),
    [instance, inProgress, me, status, error],
  );

  return <AuthContext.Provider value={auth}>{children}</AuthContext.Provider>;
}

/** AUTH_MODE=entra: Entra External ID sign-in and a bearer token on every API call. */
export function EntraAuthProvider({ msal, children }: { msal: PublicClientApplication; children: ReactNode }) {
  return (
    <MsalProvider instance={msal}>
      <EntraAuth>{children}</EntraAuth>
    </MsalProvider>
  );
}
