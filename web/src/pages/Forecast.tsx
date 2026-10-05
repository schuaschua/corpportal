import { accountsApi, insightsApi } from '../api';
import { ErrorBar, SkeletonRows } from '../components/Feedback';
import { Legend } from '../components/Legend';
import { LineChart, type ChartPoint } from '../components/LineChart';
import { useShared } from '../components/styles';
import { fmtWeekday } from '../format';
import { formatShortAED, toChartNumber, toFils } from '../money';
import type { Dashboard, Forecast as ForecastData } from '../types';
import { useApi } from '../useApi';

const version = (v: string) => (/^\d/.test(v) ? `v${v}` : v);

export function Forecast() {
  const shared = useShared();
  const fc = useApi('forecast', () => insightsApi<ForecastData>('/forecast'));
  const dash = useApi('dashboard', () => accountsApi<Dashboard>('/dashboard'));
  const f = fc.data;
  const payroll = dash.data?.payroll_due;

  // Label the lowest forecast day from the API strings, not the chart numbers.
  const minLabel = (p: ChartPoint) => {
    const point = f?.points.find((x) => x.date === p.date);
    if (!point) return '';
    const fils = toFils(point.predicted);
    let text = `${fmtWeekday(point.date)}: ${formatShortAED(fils)}`;
    if (payroll && fils < toFils(payroll.amount)) text += ` (${formatShortAED(fils - toFils(payroll.amount))})`;
    return text;
  };

  return (
    <section>
      <h1 className={shared.h1}>Cash forecast</h1>
      <p className={shared.sub}>
        Next 30 days, excl. Reserve
        {f?.model ? ` · Model: ${f.model.name} ${version(f.model.version)} (MLflow, Unity Catalog)` : ''} · Trained on synthetic data
      </p>
      <ErrorBar error={fc.error ?? dash.error} />
      <div className={shared.card}>
        {!f || !dash.data ? (
          <SkeletonRows rows={8} label="Loading forecast" />
        ) : f.points.length === 0 ? (
          <p className={shared.tip}>No forecast yet. It appears after the first model run.</p>
        ) : (
          <>
            <LineChart
              label="30-day cash forecast"
              width={900}
              height={260}
              band
              actual={dash.data.trend.slice(-10).map((p) => ({ date: p.date, value: toChartNumber(p.non_reserve) }))}
              forecast={f.points.map((p) => ({
                date: p.date,
                value: toChartNumber(p.predicted),
                lower: toChartNumber(p.lower),
                upper: toChartNumber(p.upper),
              }))}
              threshold={payroll ? { value: toChartNumber(payroll.amount), label: `Payroll threshold ${formatShortAED(toFils(payroll.amount))}` } : undefined}
              minLabel={minLabel}
            />
            <Legend forecastLabel="Forecast (range shaded)" threshold={!!payroll} />
          </>
        )}
      </div>
    </section>
  );
}
