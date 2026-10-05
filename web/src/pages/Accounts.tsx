import {
  makeStyles,
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  tokens,
} from '@fluentui/react-components';
import { accountsApi } from '../api';
import { ErrorBar, SkeletonRows } from '../components/Feedback';
import { AnomalyFlag } from '../components/Pills';
import { useShared } from '../components/styles';
import { fmtDay } from '../format';
import { formatAED, formatSignedAED } from '../money';
import { navigate } from '../router';
import type { Account, Dashboard, Me, Transaction } from '../types';
import { useApi } from '../useApi';

const useStyles = makeStyles({
  row: { cursor: 'pointer' },
  selected: { backgroundColor: '#EBF3FC', ':hover': { backgroundColor: '#E1EDFA' } },
  gap: { marginBottom: '16px' },
  mono: { fontVariantNumeric: 'tabular-nums', color: tokens.colorNeutralForeground2 },
});

function description(t: Transaction): string {
  if (t.counterparty && t.description && t.description !== t.counterparty) return `${t.counterparty}: ${t.description}`;
  return t.counterparty ?? t.description ?? '';
}

export function Accounts({ me, accountId }: { me: Me; accountId: number | null }) {
  const s = useStyles();
  const shared = useShared();
  const list = useApi('accounts', () => accountsApi<{ accounts: Account[] }>('/accounts'));
  // Anomaly scores come from the serving layer; used to flag ledger lines.
  const dash = useApi('dashboard', () => accountsApi<Dashboard>('/dashboard'));
  const accounts = list.data?.accounts ?? [];
  const selectedId = accountId ?? accounts[0]?.id ?? null;
  const txns = useApi(
    selectedId === null ? null : `txns-${selectedId}`,
    () => accountsApi<{ account: Account; transactions: Transaction[] }>(`/accounts/${selectedId}/transactions?limit=50`),
  );
  const flags = new Map((dash.data?.anomalies ?? []).filter((a) => a.payment_id != null).map((a) => [a.payment_id, a]));
  const selected = txns.data?.account ?? accounts.find((a) => a.id === selectedId);

  return (
    <section>
      <h1 className={shared.h1}>Accounts</h1>
      <p className={shared.sub}>{list.data ? `${accounts.length} accounts · ${me.company.name}` : ' '}</p>
      <ErrorBar error={list.error} />

      <div className={`${shared.card} ${s.gap}`}>
        {!list.data ? (
          <SkeletonRows rows={4} label="Loading accounts" />
        ) : (
          <Table aria-label="Accounts">
            <TableHeader>
              <TableRow>
                <TableHeaderCell>Account</TableHeaderCell>
                <TableHeaderCell>Number</TableHeaderCell>
                <TableHeaderCell>Currency</TableHeaderCell>
                <TableHeaderCell className={shared.num}>Balance</TableHeaderCell>
              </TableRow>
            </TableHeader>
            <TableBody>
              {accounts.map((a) => {
                const isSel = a.id === selectedId;
                const open = () => navigate(`/accounts/${a.id}`);
                return (
                  <TableRow
                    key={a.id}
                    className={`${s.row} ${isSel ? s.selected : ''}`}
                    aria-selected={isSel}
                    tabIndex={0}
                    onClick={open}
                    onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), open())}
                  >
                    <TableCell>{a.name}</TableCell>
                    <TableCell className={s.mono}>{a.iban}</TableCell>
                    <TableCell>{a.currency}</TableCell>
                    <TableCell className={shared.num}>{formatAED(a.balance)}</TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </div>

      {selectedId !== null && (
        <div className={shared.card}>
          <h3 className={shared.cardTitle}>{selected ? `${selected.name}: recent transactions` : 'Transactions'}</h3>
          <ErrorBar error={txns.error} />
          {txns.error ? null : !txns.data ? (
            <SkeletonRows rows={5} label="Loading transactions" />
          ) : txns.data.transactions.length === 0 ? (
            <p className={shared.tip}>No transactions on this account yet.</p>
          ) : (
            <Table aria-label="Transactions" size="small">
              <TableHeader>
                <TableRow>
                  <TableHeaderCell>Date</TableHeaderCell>
                  <TableHeaderCell>Description</TableHeaderCell>
                  <TableHeaderCell className={shared.num}>Amount</TableHeaderCell>
                  <TableHeaderCell className={shared.num}>Balance</TableHeaderCell>
                </TableRow>
              </TableHeader>
              <TableBody>
                {txns.data.transactions.map((t) => {
                  const flag = t.payment_id != null ? flags.get(t.payment_id) : undefined;
                  return (
                    <TableRow key={t.id}>
                      <TableCell>{fmtDay(t.value_date)}</TableCell>
                      <TableCell>
                        {description(t)} {flag && <AnomalyFlag score={flag.score} reason={flag.reason} />}
                      </TableCell>
                      <TableCell className={shared.num}>{formatSignedAED(t.amount)}</TableCell>
                      <TableCell className={shared.num}>{formatAED(t.balance_after)}</TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </div>
      )}
    </section>
  );
}
