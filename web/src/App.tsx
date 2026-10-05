import { makeStyles, Spinner } from '@fluentui/react-components';
import { useAuth } from './auth/AuthContext';
import { Shell } from './components/Shell';
import { Accounts } from './pages/Accounts';
import { Dashboard } from './pages/Dashboard';
import { Forecast } from './pages/Forecast';
import { Login } from './pages/Login';
import { Payments } from './pages/Payments';
import { parseRoute, usePath } from './router';

const useStyles = makeStyles({ wait: { minHeight: '100vh', display: 'grid', placeItems: 'center' } });

export function App() {
  const s = useStyles();
  const auth = useAuth();
  const route = parseRoute(usePath());

  if (auth.status === 'loading' && !auth.me) {
    return <div className={s.wait}><Spinner label="Signing you in…" /></div>;
  }
  if (!auth.me) return <Login />;

  const me = auth.me;
  return (
    <Shell me={me} route={route}>
      {/* Keyed on the user so switching users reloads every screen with their data. */}
      <div key={me.username}>
        {route.page === 'dashboard' && <Dashboard me={me} />}
        {route.page === 'accounts' && <Accounts me={me} accountId={route.accountId} />}
        {route.page === 'payments' && <Payments me={me} />}
        {route.page === 'forecast' && <Forecast />}
      </div>
    </Shell>
  );
}
