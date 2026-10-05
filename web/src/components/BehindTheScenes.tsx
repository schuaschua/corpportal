import {
  Button,
  DrawerBody,
  DrawerHeader,
  DrawerHeaderTitle,
  OverlayDrawer,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { CheckmarkCircle20Filled, Circle20Regular, Dismiss20Regular, Open16Regular } from '@fluentui/react-icons';
import { createContext, useContext, useEffect, useState } from 'react';
import { accountsApi, paymentsApi } from '../api';
import { config } from '../config';
import { fmtTime, instant, paymentRef } from '../format';
import { formatAED } from '../money';
import type { Payment, PipelineStage, PipelineTrace } from '../types';
import { useApi } from '../useApi';
import { SkeletonRows } from './Feedback';
import { colors, useShared } from './styles';

export const OpenBehindTheScenes = createContext<() => void>(() => {});

export function BehindTheScenesButton() {
  const open = useContext(OpenBehindTheScenes);
  return <Button onClick={open}>Behind the scenes</Button>;
}

const useStyles = makeStyles({
  drawer: { width: '360px' },
  steps: { listStyle: 'none', padding: 0, margin: '16px 0' },
  step: {
    display: 'flex',
    gap: '12px',
    padding: '10px 0 10px 16px',
    marginLeft: '9px',
    borderLeft: `2px solid ${tokens.colorNeutralStroke2}`,
    position: 'relative',
  },
  icon: { position: 'absolute', left: '-11px', top: '10px', backgroundColor: tokens.colorNeutralBackground1 },
  done: { color: colors.success },
  pending: { color: colors.muted },
  label: { fontWeight: tokens.fontWeightSemibold },
  pendingLabel: { color: colors.muted },
});

interface Stage {
  key: PipelineStage;
  name: string;
  detail: string;
}

const STAGES: Stage[] = [
  { key: 'event_hubs', name: 'Event Hubs', detail: 'payments topic' },
  { key: 'bronze', name: 'Bronze', detail: 'ADLS · raw event' },
  { key: 'silver', name: 'Silver', detail: 'Validated, matched to account' },
  { key: 'gold', name: 'Gold', detail: 'Cash position, forecast, anomaly score' },
  { key: 'serving', name: 'Serving', detail: 'Portal figures update' },
];

/** How often the drawer re-reads the latest payment and its pipeline trace. */
export const TRACE_REFRESH_MS = 5000;

function summary(p: Payment): string {
  const head = `${paymentRef(p.id)} · ${formatAED(p.amount)}`;
  if (p.status === 'EXECUTED' && p.decided_by) return `${head} · approved by ${p.decided_by.name} ${p.decided_at ? fmtTime(p.decided_at) : ''}`.trim();
  if (p.status === 'REJECTED' && p.decided_by) return `${head} · rejected by ${p.decided_by.name} ${p.decided_at ? fmtTime(p.decided_at) : ''}`.trim();
  return `${head} · awaiting approval`;
}

function ledgerDetail(p: Payment): string {
  if (p.status === 'EXECUTED') return `Azure SQL · ${p.executed_at ? fmtTime(p.executed_at) : ''}`.trim();
  if (p.status === 'REJECTED') return 'Rejected: nothing was posted to the ledger';
  return 'Posts when a second person approves';
}

const mmss = (ms: number) => {
  const total = Math.max(0, Math.ceil(ms / 1000));
  return `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`;
};

/** "Next batch in 03:12", ticking every second towards the API's next_batch_at. */
function NextBatch({ at }: { at: string | null }) {
  const shared = useShared();
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);
  if (!at) return <p className={shared.tip}>Waiting for the first lake batch</p>;
  const left = instant(at).getTime() - now;
  return <p className={shared.tip}>{left > 0 ? `Next batch in ${mmss(left)}` : 'Next batch any moment'}</p>;
}

/**
 * Tracks the latest payment through the ledger and the lake. The lake stages come from
 * accounts-api /pipeline/trace/{id} (written by the outbox relay and the medallion batch),
 * polled every 5 s while the drawer is open.
 */
export function BehindTheScenes({ open, onClose }: { open: boolean; onClose: () => void }) {
  const s = useStyles();
  const shared = useShared();
  const latest = useApi(
    open ? 'bts-latest' : null,
    () => paymentsApi<{ payments: Payment[] }>('/payments?limit=1'),
    TRACE_REFRESH_MS,
  );
  const payment = latest.data?.payments[0];
  const trace = useApi(
    open && payment ? `bts-trace-${payment.id}` : null,
    () => accountsApi<PipelineTrace>(`/pipeline/trace/${payment!.id}`),
    TRACE_REFRESH_MS,
  );
  const stages = trace.data && trace.data.payment_id === payment?.id ? trace.data.stages : [];
  const reached = new Map(stages.map((x) => [x.stage, x.at]));
  const ledgerDone = payment?.status === 'EXECUTED';
  const servedAt = reached.get('serving');

  return (
    <OverlayDrawer
      open={open}
      position="end"
      className={s.drawer}
      onOpenChange={(_, d) => !d.open && onClose()}
      aria-label="Behind the scenes"
    >
      <DrawerHeader>
        <DrawerHeaderTitle
          action={<Button appearance="subtle" aria-label="Close" icon={<Dismiss20Regular />} onClick={onClose} />}
        >
          Behind the scenes
        </DrawerHeaderTitle>
      </DrawerHeader>
      <DrawerBody>
        {latest.loading && !payment ? (
          <SkeletonRows rows={6} />
        ) : !payment ? (
          <p className={shared.tip}>No payments yet. Create one on Payments to follow it here.</p>
        ) : (
          <>
            <p className={shared.tip}>{summary(payment)}</p>
            <ol className={s.steps}>
              <li className={s.step}>
                <span className={s.icon}>
                  {ledgerDone ? <CheckmarkCircle20Filled className={s.done} /> : <Circle20Regular className={s.pending} />}
                </span>
                <div>
                  <div className={ledgerDone ? s.label : s.pendingLabel}>Ledger{ledgerDone ? ' ✓' : ''}</div>
                  <div className={shared.tip}>{ledgerDetail(payment)}</div>
                </div>
              </li>
              {STAGES.map((st) => {
                const at = reached.get(st.key);
                return (
                  <li key={st.key} className={s.step} data-testid={`stage-${st.key}`} data-done={at ? 'true' : 'false'}>
                    <span className={s.icon}>
                      {at ? <CheckmarkCircle20Filled className={s.done} /> : <Circle20Regular className={s.pending} />}
                    </span>
                    <div>
                      <div className={at ? s.label : s.pendingLabel}>{st.name}{at ? ' ✓' : ''}</div>
                      <div className={shared.tip}>{at ? `${st.detail} · ${fmtTime(at)}` : st.detail}</div>
                    </div>
                  </li>
                );
              })}
            </ol>
            {servedAt ? (
              <p className={shared.tip}>In the portal figures since {fmtTime(servedAt)}</p>
            ) : payment.status === 'AWAITING_APPROVAL' ? null : (
              <NextBatch at={trace.data?.next_batch_at ?? null} />
            )}
          </>
        )}
        {config.lineageUrl ? (
          <Button as="a" href={config.lineageUrl} target="_blank" rel="noopener noreferrer" icon={<Open16Regular />} iconPosition="after">
            View lineage in Unity Catalog
          </Button>
        ) : (
          <Button disabled icon={<Open16Regular />} iconPosition="after">View lineage in Unity Catalog</Button>
        )}
      </DrawerBody>
    </OverlayDrawer>
  );
}
