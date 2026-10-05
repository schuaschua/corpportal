import { makeStyles, mergeClasses, Skeleton, SkeletonItem, Table, TableBody, TableCell, TableRow, tokens } from '@fluentui/react-components';
import { accountsApi, insightsApi } from '../api';
import { BehindTheScenesButton } from '../components/BehindTheScenes';
import { ErrorBar, SkeletonRows } from '../components/Feedback';
import { Legend } from '../components/Legend';
import { LineChart } from '../components/LineChart';
import { AnomalyFlag } from '../components/Pills';
import { colors, useShared } from '../components/styles';
import { fmtLongDay, fmtTime, fmtWeekday, gulfDay, greeting } from '../format';
import { formatAED, formatShortAED, toChartNumber, toFils } from '../money';
import type { Dashboard as DashboardData, Forecast, Me } from '../types';
import { useApi } from '../useApi';

export const DASHBOARD_REFRESH_MS = 30_000;

const useStyles = makeStyles({
  grid3: { display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '16px', marginBottom: '16px' },
  grid2: { display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '16px' },
  label: { fontSize: tokens.fontSizeBase200, color: colors.muted },
  value: { fontSize: '28px', lineHeight: '36px', fontWeight: tokens.fontWeightSemibold, margin: '4px 0', fontVariantNumeric: 'tabular-nums' },
  delta: { color: colors.muted },
  alert: { color: colors.danger },
  live: { fontSize: tokens.fontSizeBase200, color: colors.muted, marginTop: '6px' },
});

function Kpi({ label, value, delta, alert, live }: { label: string; value: string; delta: string; alert?: boolean; live?: string }) {
  const s = useStyles();
  const shared = useShared();
  return (
    <div className={shared.card} role="group" aria-label={label}>
      <div className={s.label}>{label}</div>
      <div className={s.value}>{value}</div>
      <div className={mergeClasses(s.delta, alert && s.alert)}>{delta}</div>
      {live && <div className={s.live}>{live}</div>}
    </div>
  );
}

export function Dashboard({ me }: { me: Me }) {
  const s = useStyles();
  const shared = useShared();
  const dash = useApi('dashboard', () => accountsApi<DashboardData>('/dashboard'), DASHBOARD_REFRESH_MS);
  const fc = useApi('forecast', () => insightsApi<Forecast>('/forecast'), DASHBOARD_REFRESH_MS);
  const d = dash.data;
  const firstName = me.display_name.split(' ')[0];

  const payroll = d?.payroll_due;
  const short = payroll && d?.available != null ? toFils(d.available) < toFils(payroll.amount) : false;

  return (
    <section>
      <div className={shared.headRow}>
        <div>
          <h1 className={shared.h1}>{greeting()}, {firstName}</h1>
          <p className={shared.sub}>
            {d?.as_of ? fmtLongDay(d.as_of) : ' '}
            {d?.refreshed_at ? ` · Figures as of ${fmtTime(d.refreshed_at)}` : ''}
          </p>
        </div>
        <BehindTheScenesButton />
      </div>
      <ErrorBar error={dash.error} />

      {!d ? (
        <div className={s.grid3} aria-busy>
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className={shared.card} aria-label="Loading figures">
              <SkeletonItem size={12} style={{ width: '50%' }} />
              <SkeletonItem size={36} style={{ margin: '8px 0' }} />
              <SkeletonItem size={16} />
            </Skeleton>
          ))}
        </div>
      ) : (
        <div className={s.grid3}>
          <Kpi
            label="Total cash"
            value={formatAED(d.total_cash)}
            delta={`Across ${d.operational.accounts.length} accounts`}
            live={`Live ledger now: ${formatAED(d.operational.total_cash)}`}
          />
          <Kpi
            label="Available (excl. Reserve) after scheduled payments"
            value={formatAED(d.available)}
            delta={
              payroll
                ? `Payroll due ${fmtWeekday(payroll.date)}: ${formatAED(payroll.amount)}${short ? '' : ' · covered ✓'}`
                : 'No payroll due in the next 7 days'
            }
            alert={short}
            live={`Live ledger now: ${formatAED(d.operational.available)}`}
          />
          <Kpi
            label="7-day forecast low"
            value={formatAED(d.forecast_low)}
            delta={payroll ? `${fmtWeekday(payroll.date)}, after payroll` : 'Next 7 days'}
          />
        </div>
      )}

      <div className={s.grid2}>
        <div className={shared.card}>
          <h3 className={shared.cardTitle}>Liquidity excl. Reserve: last 30 days and next 14</h3>
          {!d || !fc.data ? (
            <SkeletonRows rows={6} label="Loading chart" />
          ) : (
            <>
              <LineChart
                label="Balance excluding Reserve: last 30 days and 14-day forecast"
                width={600}
                height={180}
                // Same basis as the forecast (non-Reserve balance), so the two lines meet at Today.
                actual={d.trend.slice(-30).map((p) => ({ date: p.date, value: toChartNumber(p.non_reserve) }))}
                forecast={fc.data.points.slice(0, 14).map((p) => ({ date: p.date, value: toChartNumber(p.predicted) }))}
                threshold={payroll ? { value: toChartNumber(payroll.amount), label: `Payroll ${formatShortAED(toFils(payroll.amount))}` } : undefined}
              />
              <Legend threshold={!!payroll} />
            </>
          )}
        </div>
        <div className={shared.card}>
          <h3 className={shared.cardTitle}>Unusual payments</h3>
          {!d ? (
            <SkeletonRows rows={3} />
          ) : d.anomalies.length === 0 ? (
            <p className={shared.tip}>No unusual payments in the last 30 days.</p>
          ) : (
            <Table size="small" aria-label="Unusual payments">
              <TableBody>
                {d.anomalies.map((a) => (
                  <TableRow key={a.id}>
                    <TableCell>
                      <div>{a.counterparty}</div>
                      <div className={shared.tip}>{fmtWeekday(gulfDay(a.occurred_at))}</div>
                      <div className={shared.tip}>{a.reason}. Score {a.score}.</div>
                    </TableCell>
                    <TableCell className={shared.num}>
                      <div style={{ textAlign: 'right' }}>
                        <div>{formatAED(a.amount)}</div>
                        <AnomalyFlag score={a.score} reason={a.reason} />
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </div>
      </div>
    </section>
  );
}
