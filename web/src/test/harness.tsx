import { FluentProvider, webLightTheme } from '@fluentui/react-components';
import { render } from '@testing-library/react';
import { vi } from 'vitest';
import { reachableStore, regionStore } from '../api';
import { App } from '../App';
import { DevAuthProvider } from '../auth/DevAuthProvider';
import type { Dashboard, Forecast, Me, Payment } from '../types';

export const USERS: Record<string, Me> = {
  priya: { id: 1, username: 'priya', display_name: 'Priya Nair', title: 'Treasurer', role: 'initiator', email: 'priya@example.test', company: { id: 1, name: 'Northwind Logistics LLC' } },
  tom: { id: 2, username: 'tom', display_name: 'Tom Okafor', title: 'CFO', role: 'approver', email: 'tom@example.test', company: { id: 1, name: 'Northwind Logistics LLC' } },
};

const account = (id: number, name: string, kind: string, balance: string) => ({
  id, name, kind, iban: `AE07 0331 0000 0000 0000 00${id}`, currency: 'AED', balance, updated_at: '2026-10-05T03:00:00',
});
export const ACCOUNTS = [
  account(1, 'Operating', 'operating', '2860000.00'),
  account(2, 'Reserve', 'reserve', '2240000.00'),
  account(3, 'Payroll', 'payroll', '150000.00'),
  account(4, 'Collections', 'collections', '550000.00'),
];

export const DASHBOARD: Dashboard = {
  company: { id: 1, name: 'Northwind Logistics LLC' },
  currency: 'AED',
  as_of: '2026-10-05',
  total_cash: '5800000.00',
  available: '1780000.00',
  scheduled_out_7d: '1830000.00',
  forecast_low: '-120000.00',
  payroll_due: { date: '2026-10-08', amount: '1900000.00' },
  refreshed_at: '2026-10-05T03:45:00',
  trend: Array.from({ length: 30 }, (_, i) => ({
    date: `2026-09-${String(i + 1).padStart(2, '0')}`.replace('2026-09-31', '2026-10-01'),
    total_cash: '5800000.00',
    available: `${1700000 + i * 1000}.00`,
    non_reserve: `${3500000 + i * 1000}.00`,
  })),
  anomalies: [{ id: 1, payment_id: 900, occurred_at: '2026-10-02T06:00:00', counterparty: 'Harbour Freight Co', amount: '225000.00', score: '0.91', reason: "Unusual: 4× this supplier's average" }],
  operational: { total_cash: '5800000.00', available: '1780000.00', accounts: ACCOUNTS },
};

export const FORECAST: Forecast = {
  company: { id: 1, name: 'Northwind Logistics LLC' },
  currency: 'AED',
  model: { name: 'cash_forecast', version: '1' },
  generated_at: '2026-10-05T03:45:00',
  points: Array.from({ length: 30 }, (_, i) => ({
    date: new Date(Date.UTC(2026, 9, 5 + i)).toISOString().slice(0, 10),
    predicted: '1800000.00', lower: '1700000.00', upper: '1900000.00',
  })),
};

export function payment(over: Partial<Payment> = {}): Payment {
  return {
    id: 10482, status: 'AWAITING_APPROVAL', amount: '450000.00', currency: 'AED', value_date: '2026-10-05',
    reference: 'Payroll top-up', from_account: { id: 2, name: 'Reserve' }, to_account: { id: 1, name: 'Operating' },
    beneficiary: null, created_by: { id: 1, name: 'Priya Nair' }, created_at: '2026-10-05T03:50:00',
    decided_by: null, decided_at: null, executed_at: null, awaiting_approval_from: ['Tom Okafor'], anomaly: null,
    ...over,
  };
}

type Reply = { status?: number; body?: unknown; fail?: boolean };
export type Routes = Record<string, Reply | ((call: { url: string; init?: RequestInit }) => Reply)>;

/** Stubs fetch. Keys are "METHOD /path" (query ignored). `region` is the X-Served-From of every reply. */
export function mockApi(routes: Routes, opts: { region?: () => string } = {}) {
  const defaults: Routes = {
    'GET /api/accounts/me': ({ init }) => {
      const u = new Headers(init?.headers).get('X-Demo-User') ?? '';
      return USERS[u] ? { body: USERS[u] } : { status: 401, body: { detail: 'Sign in to continue.' } };
    },
    'GET /api/accounts/dashboard': { body: DASHBOARD },
    'GET /api/insights/forecast': { body: FORECAST },
    'GET /api/accounts/accounts': { body: { accounts: ACCOUNTS } },
    'GET /api/payments/beneficiaries': { body: { beneficiaries: [{ id: 1, name: 'Harbour Freight Co', iban: 'AE07', category: 'freight' }] } },
    'GET /api/payments/payments': { body: { payments: [] } },
  };
  const all = { ...defaults, ...routes };
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const key = `${init?.method ?? 'GET'} ${url.split('?')[0]}`;
    const route = all[key];
    const reply: Reply = typeof route === 'function' ? route({ url, init }) : route ?? { status: 404, body: { detail: "You don't have access to that company's data." } };
    if (reply.fail) throw new TypeError('Failed to fetch');
    return new Response(JSON.stringify(reply.body ?? null), {
      status: reply.status ?? 200,
      headers: { 'Content-Type': 'application/json', 'X-Served-From': opts.region?.() ?? 'local' },
    });
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

export function renderApp(user: string, path = '/dashboard') {
  regionStore.set(null);
  reachableStore.set(true);
  window.history.pushState(null, '', path);
  return render(
    <FluentProvider theme={webLightTheme}>
      <DevAuthProvider initialUser={user}>
        <App />
      </DevAuthProvider>
    </FluentProvider>,
  );
}
