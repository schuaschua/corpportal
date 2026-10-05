import {
  Avatar,
  Button,
  Menu,
  MenuDivider,
  MenuGroup,
  MenuGroupHeader,
  MenuItem,
  MenuItemRadio,
  MenuList,
  MenuPopover,
  MenuTrigger,
  MessageBar,
  MessageBarBody,
  makeStyles,
  mergeClasses,
  tokens,
} from '@fluentui/react-components';
import {
  ArrowSwap20Regular,
  ArrowTrending20Regular,
  Board20Regular,
  BuildingBank20Regular,
  ChevronDown16Regular,
} from '@fluentui/react-icons';
import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { accountsApi, UNAVAILABLE_MESSAGE } from '../api';
import { DEMO_USERS, useAuth } from '../auth/AuthContext';
import { navigate, type Route } from '../router';
import type { Me } from '../types';
import { useReachable } from '../useApi';
import { BehindTheScenes, OpenBehindTheScenes } from './BehindTheScenes';
import { RegionBadge } from './RegionBadge';
import { colors } from './styles';

/** While the bank is unreachable the Shell probes it this often; pages reload on recovery. */
export const RETRY_MS = 5000;

const useStyles = makeStyles({
  root: { minHeight: '100vh', backgroundColor: tokens.colorNeutralBackground2, color: tokens.colorNeutralForeground1 },
  synth: {
    height: '24px',
    backgroundColor: colors.synthetic,
    fontSize: tokens.fontSizeBase200,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    borderBottom: '1px solid #F2E2A0',
  },
  topbar: {
    height: '48px',
    backgroundColor: tokens.colorNeutralBackground1,
    borderBottom: `1px solid ${tokens.colorNeutralStroke2}`,
    display: 'flex',
    alignItems: 'center',
    padding: '0 16px',
    gap: '16px',
  },
  company: { color: colors.muted, borderLeft: `1px solid ${tokens.colorNeutralStroke2}`, paddingLeft: '16px' },
  spacer: { flex: 1 },
  user: { fontSize: tokens.fontSizeBase200, fontWeight: tokens.fontWeightRegular },
  body: { display: 'flex', minHeight: 'calc(100vh - 72px)' },
  nav: {
    width: '240px',
    flex: 'none',
    backgroundColor: tokens.colorNeutralBackground1,
    borderRight: `1px solid ${tokens.colorNeutralStroke2}`,
    padding: '12px 8px',
    display: 'flex',
    flexDirection: 'column',
    gap: '2px',
  },
  navItem: {
    display: 'flex',
    alignItems: 'center',
    gap: '10px',
    padding: '8px 12px',
    borderRadius: tokens.borderRadiusMedium,
    color: tokens.colorNeutralForeground1,
    textDecoration: 'none',
    ':hover': { backgroundColor: tokens.colorNeutralBackground1Hover },
  },
  navActive: {
    backgroundColor: '#EBF3FC',
    color: tokens.colorBrandForeground1,
    fontWeight: tokens.fontWeightSemibold,
    ':hover': { backgroundColor: '#EBF3FC' },
  },
  main: { flex: 1, padding: '24px', minWidth: 0 },
  bar: { marginBottom: '16px' },
});

export function Logo() {
  return (
    <div style={{ fontWeight: 600, display: 'flex', alignItems: 'center', gap: 8 }}>
      <i style={{ width: 20, height: 20, borderRadius: 4, background: tokens.colorBrandBackground, display: 'inline-block' }} />
      Contoso Digital Bank
    </div>
  );
}

export function SyntheticBanner() {
  const s = useStyles();
  return <div className={s.synth} role="note">Synthetic data: PoC environment. Not a real bank.</div>;
}

const NAV: { page: Route['page']; path: string; label: string; icon: ReactNode }[] = [
  { page: 'dashboard', path: '/dashboard', label: 'Dashboard', icon: <Board20Regular /> },
  { page: 'accounts', path: '/accounts', label: 'Accounts', icon: <BuildingBank20Regular /> },
  { page: 'payments', path: '/payments', label: 'Payments', icon: <ArrowSwap20Regular /> },
  { page: 'forecast', path: '/forecast', label: 'Forecast', icon: <ArrowTrending20Regular /> },
];

function UserMenu({ me }: { me: Me }) {
  const s = useStyles();
  const auth = useAuth();
  return (
    <Menu
      checkedValues={{ user: [me.username] }}
      onCheckedValueChange={(_, d) => d.checkedItems[0] && auth.switchUser(d.checkedItems[0])}
    >
      <MenuTrigger disableButtonEnhancement>
        <Button appearance="subtle" className={s.user} icon={<Avatar name={me.display_name} size={28} color="brand" />}>
          {me.display_name} · {me.title} <ChevronDown16Regular />
        </Button>
      </MenuTrigger>
      <MenuPopover>
        <MenuList>
          {auth.mode === 'dev' ? (
            <MenuGroup>
              <MenuGroupHeader>Switch user (PoC only)</MenuGroupHeader>
              {DEMO_USERS.map((u) => (
                <MenuItemRadio key={u.username} name="user" value={u.username}>
                  {u.name}
                </MenuItemRadio>
              ))}
            </MenuGroup>
          ) : (
            <MenuItem onClick={() => auth.switchUser()}>Switch user (PoC only)</MenuItem>
          )}
          <MenuDivider />
          <MenuItem onClick={auth.signOut}>Sign out</MenuItem>
        </MenuList>
      </MenuPopover>
    </Menu>
  );
}

export function Shell({ me, route, children }: { me: Me; route: Route; children: ReactNode }) {
  const s = useStyles();
  const reachable = useReachable();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const openDrawer = useCallback(() => setDrawerOpen(true), []);

  // Can't reach the bank: retry every 5 s; a success flips `reachable` and pages reload.
  useEffect(() => {
    if (reachable) return;
    const id = setInterval(() => void accountsApi('/me').catch(() => undefined), RETRY_MS);
    return () => clearInterval(id);
  }, [reachable]);

  return (
    <OpenBehindTheScenes.Provider value={openDrawer}>
      <div className={s.root}>
        <SyntheticBanner />
        <header className={s.topbar}>
          <Logo />
          <div className={s.company}>{me.company.name}</div>
          <div className={s.spacer} />
          <RegionBadge />
          <UserMenu me={me} />
        </header>
        <div className={s.body}>
          <nav className={s.nav} aria-label="Main">
            {NAV.map((n) => (
              <a
                key={n.page}
                href={n.path}
                className={mergeClasses(s.navItem, route.page === n.page && s.navActive)}
                aria-current={route.page === n.page ? 'page' : undefined}
                onClick={(e) => {
                  e.preventDefault();
                  navigate(n.path);
                }}
              >
                {n.icon}
                {n.label}
              </a>
            ))}
          </nav>
          <main className={s.main}>
            {!reachable && (
              <MessageBar intent="warning" className={s.bar}>
                <MessageBarBody>{UNAVAILABLE_MESSAGE}</MessageBarBody>
              </MessageBar>
            )}
            {children}
          </main>
        </div>
        <BehindTheScenes open={drawerOpen} onClose={() => setDrawerOpen(false)} />
      </div>
    </OpenBehindTheScenes.Provider>
  );
}
