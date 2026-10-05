import {
  Button,
  Dropdown,
  Field,
  Input,
  makeStyles,
  MessageBar,
  MessageBarBody,
  Option,
  OptionGroup,
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  Tooltip,
} from '@fluentui/react-components';
import { useEffect, useState, type FormEvent } from 'react';
import { ApiError, accountsApi, paymentsApi } from '../api';
import { BehindTheScenesButton } from '../components/BehindTheScenes';
import { ErrorBar, SkeletonRows } from '../components/Feedback';
import { AnomalyFlag, StatusPill, statusText } from '../components/Pills';
import { useShared } from '../components/styles';
import { fmtDay, gulfDay, paymentRef, todayGulf } from '../format';
import { formatAED, parseAmountInput } from '../money';
import type { Account, Beneficiary, Me, Payment } from '../types';
import { useApi } from '../useApi';

export const SELF_APPROVAL_MESSAGE = "You can't approve a payment you created.";
const APPROVER_ONLY_MESSAGE = 'Only an approver can approve payments.';

const useStyles = makeStyles({
  row: { display: 'flex', gap: '16px', alignItems: 'flex-start' },
  form: { width: '340px', flex: 'none', display: 'flex', flexDirection: 'column', gap: '12px' },
  lists: { flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: '16px' },
  actions: { display: 'flex', gap: '8px', flexWrap: 'wrap' },
});

type Notice = { intent: 'success' | 'error'; text: string } | null;

function destination(p: Payment): string {
  if (p.beneficiary) return p.beneficiary.name;
  if (p.to_account) return `${p.to_account.name} (own account)`;
  return '';
}

function NewPayment({ accounts, beneficiaries, onCreated, onError }: {
  accounts: Account[];
  beneficiaries: Beneficiary[];
  onCreated: (p: Payment) => void;
  onError: (message: string) => void;
}) {
  const s = useStyles();
  const shared = useShared();
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [amount, setAmount] = useState('');
  const [date, setDate] = useState(todayGulf());
  const [reference, setReference] = useState('');
  const [amountError, setAmountError] = useState<string>();
  const [busy, setBusy] = useState(false);

  // Default to the demo's move: Reserve → Operating.
  useEffect(() => {
    if (from || !accounts.length) return;
    const src = accounts.find((a) => a.kind === 'reserve') ?? accounts[0];
    const dst = accounts.find((a) => a.kind === 'operating' && a.id !== src.id);
    setFrom(String(src.id));
    setTo(dst ? `acct:${dst.id}` : beneficiaries[0] ? `ben:${beneficiaries[0].id}` : '');
  }, [accounts, beneficiaries, from]);

  const fromAcct = accounts.find((a) => String(a.id) === from);
  const toLabel = (() => {
    const [kind, id] = to.split(':');
    if (kind === 'acct') {
      const a = accounts.find((x) => String(x.id) === id);
      return a ? `${a.name} (own account)` : '';
    }
    return beneficiaries.find((b) => String(b.id) === id)?.name ?? '';
  })();
  const fromLabel = (a: Account) => `${a.name} · ${formatAED(a.balance)}`;

  async function submit(e: FormEvent) {
    e.preventDefault();
    const value = parseAmountInput(amount);
    if (!value) {
      setAmountError('Enter an amount in AED, for example 450,000.00.');
      return;
    }
    setAmountError(undefined);
    const [kind, id] = to.split(':');
    setBusy(true);
    try {
      const created = await paymentsApi<Payment>('/payments', {
        method: 'POST',
        body: {
          from_account_id: Number(from),
          ...(kind === 'acct' ? { to_account_id: Number(id) } : { beneficiary_id: Number(id) }),
          amount: value,
          value_date: date || undefined,
          reference: reference.trim() || undefined,
        },
      });
      setAmount('');
      setReference('');
      onCreated(created);
    } catch (err) {
      if (err instanceof ApiError && err.kind !== 'unavailable') onError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className={`${shared.card} ${s.form}`} onSubmit={submit} aria-label="New payment">
      <h3 className={shared.cardTitle} style={{ margin: 0 }}>New payment</h3>
      <Field label="From" required>
        <Dropdown
          value={fromAcct ? fromLabel(fromAcct) : ''}
          selectedOptions={from ? [from] : []}
          onOptionSelect={(_, d) => {
            if (!d.optionValue) return;
            setFrom(d.optionValue);
            if (to === `acct:${d.optionValue}`) setTo('');
          }}
        >
          {accounts.map((a) => (
            <Option key={a.id} value={String(a.id)} text={fromLabel(a)}>{fromLabel(a)}</Option>
          ))}
        </Dropdown>
      </Field>
      <Field label="To" required>
        <Dropdown value={toLabel} selectedOptions={to ? [to] : []} onOptionSelect={(_, d) => d.optionValue && setTo(d.optionValue)}>
          <OptionGroup label="Own accounts">
            {accounts.filter((a) => String(a.id) !== from).map((a) => (
              <Option key={a.id} value={`acct:${a.id}`} text={`${a.name} (own account)`}>{`${a.name} (own account)`}</Option>
            ))}
          </OptionGroup>
          <OptionGroup label="Beneficiaries">
            {beneficiaries.map((b) => (
              <Option key={b.id} value={`ben:${b.id}`} text={b.name}>{b.name}</Option>
            ))}
          </OptionGroup>
        </Dropdown>
      </Field>
      <Field label="Amount" required validationMessage={amountError}>
        <Input contentBefore="AED" inputMode="decimal" placeholder="0.00" value={amount} onChange={(_, d) => setAmount(d.value)} />
      </Field>
      <Field label="Date">
        <Input type="date" value={date} onChange={(_, d) => setDate(d.value)} />
      </Field>
      <Field label="Reference">
        <Input maxLength={140} value={reference} onChange={(_, d) => setReference(d.value)} />
      </Field>
      <div>
        <Button appearance="primary" type="submit" disabled={busy || !from || !to}>
          Submit for approval
        </Button>
      </div>
    </form>
  );
}

function Decide({ payment, me, onDecide }: { payment: Payment; me: Me; onDecide: (p: Payment, verb: 'approve' | 'reject') => void }) {
  const s = useStyles();
  const shared = useShared();
  const mine = payment.created_by.id === me.id;
  const approveBlock = mine ? SELF_APPROVAL_MESSAGE : me.role !== 'approver' ? APPROVER_ONLY_MESSAGE : null;
  const rejectBlock = mine ? SELF_APPROVAL_MESSAGE : null;
  const btn = (verb: 'approve' | 'reject', label: string, block: string | null) =>
    block ? (
      <Tooltip content={block} relationship="description" withArrow>
        <Button disabledFocusable>{label}</Button>
      </Tooltip>
    ) : (
      <Button appearance={verb === 'approve' ? 'primary' : 'secondary'} onClick={() => onDecide(payment, verb)}>
        {label}
      </Button>
    );
  return (
    <div>
      <div className={s.actions}>
        {btn('approve', 'Approve', approveBlock)}
        {btn('reject', 'Reject', rejectBlock)}
      </div>
      {mine && <div className={shared.tip} style={{ marginTop: 6 }}>{SELF_APPROVAL_MESSAGE}</div>}
    </div>
  );
}

export function Payments({ me }: { me: Me }) {
  const s = useStyles();
  const shared = useShared();
  const payments = useApi('payments', () => paymentsApi<{ payments: Payment[] }>('/payments?limit=200'));
  const accounts = useApi('accounts', () => accountsApi<{ accounts: Account[] }>('/accounts'));
  const bens = useApi('beneficiaries', () => paymentsApi<{ beneficiaries: Beneficiary[] }>('/beneficiaries'));
  const [notice, setNotice] = useState<Notice>(null);

  const all = payments.data?.payments ?? [];
  const awaiting = all.filter((p) => p.status === 'AWAITING_APPROVAL');
  const history = all.filter((p) => p.status !== 'AWAITING_APPROVAL');

  const refresh = () => {
    payments.reload();
    accounts.reload();
  };

  async function decide(p: Payment, verb: 'approve' | 'reject') {
    try {
      const done = await paymentsApi<Payment>(`/payments/${p.id}/${verb}`, { method: 'POST' });
      setNotice({ intent: 'success', text: `${paymentRef(done.id)} ${statusText(done).toLowerCase()}.` });
    } catch (err) {
      if (err instanceof ApiError && err.kind !== 'unavailable') setNotice({ intent: 'error', text: err.message });
    }
    refresh();
  }

  return (
    <section>
      <div className={shared.headRow}>
        <div>
          <h1 className={shared.h1}>Payments</h1>
          <p className={shared.sub}>Every payment needs a second approver.</p>
        </div>
        <BehindTheScenesButton />
      </div>
      <ErrorBar error={payments.error ?? accounts.error ?? bens.error} />
      {notice && (
        <MessageBar intent={notice.intent} className={shared.message}>
          <MessageBarBody>{notice.text}</MessageBarBody>
        </MessageBar>
      )}

      <div className={s.row}>
        {accounts.data && bens.data ? (
          <NewPayment
            accounts={accounts.data.accounts}
            beneficiaries={bens.data.beneficiaries}
            onCreated={(p) => {
              setNotice({ intent: 'success', text: `${paymentRef(p.id)} created. ${statusText(p)}.` });
              refresh();
            }}
            onError={(text) => setNotice({ intent: 'error', text })}
          />
        ) : (
          <div className={`${shared.card} ${s.form}`}><SkeletonRows rows={6} label="Loading form" /></div>
        )}

        <div className={s.lists}>
          <div className={shared.card}>
            <h3 className={shared.cardTitle}>Awaiting approval</h3>
            {!payments.data ? (
              <SkeletonRows rows={2} />
            ) : awaiting.length === 0 ? (
              <p className={shared.tip}>Nothing is waiting for approval.</p>
            ) : (
              <Table aria-label="Awaiting approval">
                <TableHeader>
                  <TableRow>
                    <TableHeaderCell>Payment</TableHeaderCell>
                    <TableHeaderCell>Created by</TableHeaderCell>
                    <TableHeaderCell className={shared.num}>Amount</TableHeaderCell>
                    <TableHeaderCell>Status</TableHeaderCell>
                    <TableHeaderCell aria-label="Actions" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {awaiting.map((p) => (
                    <TableRow key={p.id}>
                      <TableCell>
                        {paymentRef(p.id)}{p.reference ? ` · ${p.reference}` : ''}
                        <div className={shared.tip}>{p.from_account.name} → {destination(p)}</div>
                      </TableCell>
                      <TableCell>{p.created_by.name}</TableCell>
                      <TableCell className={shared.num}>{formatAED(p.amount)}</TableCell>
                      <TableCell><StatusPill payment={p} /></TableCell>
                      <TableCell><Decide payment={p} me={me} onDecide={decide} /></TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </div>

          <div className={shared.card}>
            <h3 className={shared.cardTitle}>History</h3>
            {!payments.data ? (
              <SkeletonRows rows={5} />
            ) : history.length === 0 ? (
              <p className={shared.tip}>No executed or rejected payments yet.</p>
            ) : (
              <Table aria-label="History" size="small">
                <TableHeader>
                  <TableRow>
                    <TableHeaderCell>Date</TableHeaderCell>
                    <TableHeaderCell>Beneficiary</TableHeaderCell>
                    <TableHeaderCell className={shared.num}>Amount</TableHeaderCell>
                    <TableHeaderCell>Status</TableHeaderCell>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {history.map((p) => {
                    const when = p.executed_at ?? p.decided_at;
                    return (
                      <TableRow key={p.id}>
                        <TableCell>{when ? fmtDay(gulfDay(when)) : p.value_date ? fmtDay(p.value_date) : ''}</TableCell>
                        <TableCell>
                          {destination(p)} {p.anomaly && <AnomalyFlag score={p.anomaly.score} reason={p.anomaly.reason} />}
                        </TableCell>
                        <TableCell className={shared.num}>{formatAED(p.amount)}</TableCell>
                        <TableCell><StatusPill payment={p} /></TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
