// One image, every environment: values come from /config.js (written from env at container
// start) and fall back to the build-time VITE_* variables for `npm run dev`.

export type AuthMode = 'dev' | 'entra';

interface RuntimeConfig {
  authMode?: string;
  lineageUrl?: string;
  entraClientId?: string;
  entraAuthority?: string;
  entraKnownAuthority?: string;
  entraApiScope?: string;
}

declare global {
  interface Window {
    __PORTAL_CONFIG__?: RuntimeConfig;
  }
}

function pick(runtime: string | undefined, build: string | undefined, fallback = ''): string {
  return (runtime && runtime.trim()) || (build && build.trim()) || fallback;
}

export function loadConfig() {
  const rt = (typeof window !== 'undefined' && window.__PORTAL_CONFIG__) || {};
  const env = import.meta.env;
  const mode = pick(rt.authMode, env.VITE_AUTH_MODE, 'entra').toLowerCase();
  return {
    authMode: (mode === 'dev' ? 'dev' : 'entra') as AuthMode, // anything else fails closed to Entra
    lineageUrl: pick(rt.lineageUrl, env.VITE_LINEAGE_URL),
    entraClientId: pick(rt.entraClientId, env.VITE_ENTRA_CLIENT_ID),
    entraAuthority: pick(rt.entraAuthority, env.VITE_ENTRA_AUTHORITY),
    entraKnownAuthority: pick(rt.entraKnownAuthority, env.VITE_ENTRA_KNOWN_AUTHORITY),
    entraApiScope: pick(rt.entraApiScope, env.VITE_ENTRA_API_SCOPE),
  };
}

export const config = loadConfig();
