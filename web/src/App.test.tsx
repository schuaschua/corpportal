import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { TRACE_REFRESH_MS } from './components/BehindTheScenes';
import { RETRY_MS } from './components/Shell';
import { DASHBOARD, mockApi, payment, renderApp } from './test/harness';

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('Dashboard', () => {
  it("shows Northwind's KPIs, the payroll line and unusual payments", async () => {
    mockApi({});
    renderApp('priya');
    expect(await screen.findByText('AED 5,800,000')).toBeTruthy();
    expect(screen.getByText('AED 1,780,000')).toBeTruthy();
    expect(screen.getByText('−AED 120,000')).toBeTruthy();
    expect(screen.getByText('Payroll due Thu 8 Oct: AED 1,900,000')).toBeTruthy();
    expect(screen.getByText('Harbour Freight Co')).toBeTruthy();
    expect(screen.getByText('Priya Nair · Treasurer')).toBeTruthy();
    expect(screen.getByTestId('region-badge').textContent).toContain('Serving from: local');
  });
});

describe('Payments', () => {
  it('disables Approve and Reject on a payment you created', async () => {
    mockApi({ 'GET /api/payments/payments': { body: { payments: [payment()] } } });
    renderApp('priya', '/payments');
    const approve = await screen.findByRole('button', { name: 'Approve' });
    expect(approve.getAttribute('aria-disabled')).toBe('true');
    expect(screen.getByRole('button', { name: 'Reject' }).getAttribute('aria-disabled')).toBe('true');
    expect(screen.getAllByText("You can't approve a payment you created.").length).toBeGreaterThan(0);
    expect(screen.getByText('Awaiting approval from Tom Okafor')).toBeTruthy();
  });

  it('lets another approver approve; the row moves to History as Executed', async () => {
    let executed = false;
    const fetchMock = mockApi({
      'GET /api/payments/payments': () => ({
        body: { payments: [executed
          ? payment({ status: 'EXECUTED', awaiting_approval_from: [], decided_by: { id: 2, name: 'Tom Okafor' }, decided_at: '2026-10-05T03:52:00', executed_at: '2026-10-05T03:52:00' })
          : payment()] },
      }),
      'POST /api/payments/payments/10482/approve': () => {
        executed = true;
        return { body: payment({ status: 'EXECUTED', awaiting_approval_from: [] }) };
      },
    });
    renderApp('tom', '/payments');
    fireEvent.click(await screen.findByRole('button', { name: 'Approve' }));
    const history = await screen.findByRole('table', { name: 'History' });
    expect(await within(history).findByText('Executed')).toBeTruthy();
    expect(screen.getByText('PAY-10482 executed.')).toBeTruthy();
    expect(screen.queryByRole('table', { name: 'Awaiting approval' })).toBeNull();
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(true);
  });

  it("shows the API's message when approval conflicts (409)", async () => {
    mockApi({
      'GET /api/payments/payments': { body: { payments: [payment()] } },
      'POST /api/payments/payments/10482/approve': { status: 409, body: { detail: 'This payment has already been decided.' } },
    });
    renderApp('tom', '/payments');
    fireEvent.click(await screen.findByRole('button', { name: 'Approve' }));
    expect(await screen.findByText('This payment has already been decided.')).toBeTruthy();
  });
});

describe('Errors and region', () => {
  it("shows the access message when a deep link hits another company's account", async () => {
    mockApi({}); // /accounts/5/transactions is not Northwind's: 404
    renderApp('priya', '/accounts/5');
    expect(await screen.findByText("You don't have access to that company's data.")).toBeTruthy();
    expect(screen.getByText('Operating')).toBeTruthy(); // her own accounts still show
  });

  it('warns while the bank is unreachable, retries every 5 s and clears on success', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let down = true;
    mockApi({ 'GET /api/accounts/dashboard': () => (down ? { status: 503, body: null } : { body: DASHBOARD }) });
    renderApp('priya');
    expect(await screen.findByText("Can't reach the bank right now. Retrying…")).toBeTruthy();
    down = false;
    await act(() => vi.advanceTimersByTimeAsync(RETRY_MS));
    await waitFor(() => expect(screen.queryByText("Can't reach the bank right now. Retrying…")).toBeNull());
    expect(await screen.findByText('AED 5,800,000')).toBeTruthy();
  });

  it('updates the live region badge when X-Served-From changes', async () => {
    let region = 'westus3';
    mockApi({}, { region: () => region });
    renderApp('priya');
    const badge = await screen.findByTestId('region-badge');
    expect(badge.getAttribute('aria-live')).toBe('polite');
    await waitFor(() => expect(badge.textContent).toBe('Serving from: West US 3'));
    region = 'northcentralus';
    fireEvent.click(screen.getByRole('link', { name: 'Accounts' }));
    await waitFor(() => expect(badge.textContent).toBe('Serving from: North Central US'));
    expect(badge.querySelector('[data-flash="1"]')).toBeTruthy();
  });
});

describe('Behind the scenes', () => {
  it("ticks the lake stages from the payment's trace and counts down to the next batch", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true, now: new Date('2026-10-05T03:53:00Z') });
    const executed = payment({ status: 'EXECUTED', awaiting_approval_from: [], decided_by: { id: 2, name: 'Tom Okafor' }, decided_at: '2026-10-05T03:52:00', executed_at: '2026-10-05T03:52:00' });
    let stages = [{ stage: 'ledger', at: '2026-10-05T03:52:00' }, { stage: 'event_hubs', at: '2026-10-05T03:52:02' }];
    mockApi({
      'GET /api/payments/payments': { body: { payments: [executed] } },
      'GET /api/accounts/pipeline/trace/10482': () => ({
        body: { payment_id: 10482, status: 'EXECUTED', stages, last_batch_at: '2026-10-05T03:52:30', next_batch_at: '2026-10-05T03:54:30' },
      }),
    });
    renderApp('priya');
    fireEvent.click(await screen.findByRole('button', { name: 'Behind the scenes' }));
    await waitFor(() => expect(screen.getByTestId('stage-event_hubs').getAttribute('data-done')).toBe('true'));
    expect(screen.getByTestId('stage-bronze').getAttribute('data-done')).toBe('false');
    expect(await screen.findByText(/^Next batch in 01:(30|29)$/)).toBeTruthy();

    stages = [...stages, ...['bronze', 'silver', 'gold', 'serving'].map((stage) => ({ stage, at: '2026-10-05T03:54:40' }))];
    await act(() => vi.advanceTimersByTimeAsync(TRACE_REFRESH_MS));
    await waitFor(() => expect(screen.getByTestId('stage-serving').getAttribute('data-done')).toBe('true'));
    expect(screen.getByText('In the portal figures since 07:54')).toBeTruthy();
  });
});
