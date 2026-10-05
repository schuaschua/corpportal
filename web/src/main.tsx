import { FluentProvider, webLightTheme } from '@fluentui/react-components';
import { StrictMode, type ReactNode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import { DevAuthProvider } from './auth/DevAuthProvider';
import { config } from './config';

const root = createRoot(document.getElementById('root')!);

const render = (tree: ReactNode) =>
  root.render(
    <StrictMode>
      <FluentProvider theme={webLightTheme}>{tree}</FluentProvider>
    </StrictMode>,
  );

async function boot() {
  if (config.authMode === 'dev') {
    render(<DevAuthProvider><App /></DevAuthProvider>);
    return;
  }
  try {
    const { createMsal, EntraAuthProvider } = await import('./auth/EntraAuthProvider');
    const msal = await createMsal();
    render(<EntraAuthProvider msal={msal}><App /></EntraAuthProvider>);
  } catch (e) {
    render(<p style={{ padding: 24 }}>Sign-in is unavailable: {e instanceof Error ? e.message : String(e)}</p>);
  }
}

void boot();
