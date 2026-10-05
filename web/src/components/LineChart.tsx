// Inline SVG line chart (DESIGN.md: no chart library). Actual balance solid, forecast dashed
// with an optional shaded band, a "Today" marker and an optional payroll threshold.
// Numbers here only place pixels; figures shown as text are formatted from the API strings.

import { tokens } from '@fluentui/react-components';
import { fmtDay } from '../format';
import { colors } from './styles';

export interface ChartPoint {
  date: string;
  value: number;
  lower?: number;
  upper?: number;
}

interface Props {
  label: string;
  width: number;
  height: number;
  actual: ChartPoint[];
  forecast: ChartPoint[];
  band?: boolean;
  threshold?: { value: number; label: string };
  /** Text next to the lowest forecast point, e.g. "Thu 8 Oct: AED 1.78m". */
  minLabel?: (p: ChartPoint) => string;
}

const DAY = 86_400_000;
const PAD = { top: 24, right: 8, bottom: 22, left: 8 };

export function LineChart({ label, width, height, actual, forecast, band, threshold, minLabel }: Props) {
  const all = [...actual, ...forecast];
  if (all.length < 2) return null;

  const t = (d: string) => Date.parse(`${d.slice(0, 10)}T00:00:00Z`);
  const t0 = Math.min(...all.map((p) => t(p.date)));
  const t1 = Math.max(...all.map((p) => t(p.date)));
  const values = all.flatMap((p) => [p.value, ...(band ? [p.lower ?? p.value, p.upper ?? p.value] : [])]);
  if (threshold) values.push(threshold.value);
  let lo = Math.min(...values);
  let hi = Math.max(...values);
  const pad = (hi - lo || Math.abs(hi) || 1) * 0.08;
  lo -= pad;
  hi += pad;

  const x = (d: string) => PAD.left + ((t(d) - t0) / Math.max(t1 - t0, DAY)) * (width - PAD.left - PAD.right);
  const y = (v: number) => PAD.top + (1 - (v - lo) / (hi - lo)) * (height - PAD.top - PAD.bottom);
  const pts = (ps: ChartPoint[], f: (p: ChartPoint) => number) => ps.map((p) => `${x(p.date).toFixed(1)},${y(f(p)).toFixed(1)}`).join(' ');

  const today = actual.length ? actual[actual.length - 1].date : forecast[0].date;
  const low = forecast.length ? forecast.reduce((m, p) => (p.value < m.value ? p : m), forecast[0]) : null;
  const brand = tokens.colorBrandBackground;
  const muted = '#616161';
  const base = height - PAD.bottom;

  return (
    <svg viewBox={`0 0 ${width} ${height}`} width="100%" height={height} role="img" aria-label={label}>
      <line x1={0} y1={base} x2={width} y2={base} stroke="#E0E0E0" />
      {threshold && (
        <g>
          <line x1={0} y1={y(threshold.value)} x2={width} y2={y(threshold.value)} stroke={colors.danger} strokeDasharray="3 3" />
          <text x={4} y={y(threshold.value) - 6} fontSize={11} fill={colors.danger}>{threshold.label}</text>
        </g>
      )}
      {band && forecast.length > 1 && (
        <polygon
          fill={brand}
          fillOpacity={0.1}
          points={`${pts(forecast, (p) => p.upper ?? p.value)} ${pts([...forecast].reverse(), (p) => p.lower ?? p.value)}`}
        />
      )}
      {actual.length > 1 && <polyline fill="none" stroke={brand} strokeWidth={2} points={pts(actual, (p) => p.value)} />}
      {forecast.length > 1 && (
        <polyline fill="none" stroke={brand} strokeWidth={2} strokeDasharray="6 4" points={pts(forecast, (p) => p.value)} />
      )}
      <line x1={x(today)} y1={PAD.top - 8} x2={x(today)} y2={base} stroke={muted} strokeDasharray="2 3" />
      <text x={x(today) + 4} y={PAD.top} fontSize={11} fill={muted}>Today</text>
      {low && minLabel && (
        <g>
          <circle cx={x(low.date)} cy={y(low.value)} r={3} fill={colors.danger} />
          <text
            x={x(low.date) + (x(low.date) > width * 0.7 ? -6 : 6)}
            y={Math.min(y(low.value) + 16, base - 4)}
            fontSize={11}
            fill={colors.danger}
            textAnchor={x(low.date) > width * 0.7 ? 'end' : 'start'}
          >
            {minLabel(low)}
          </text>
        </g>
      )}
      <text x={PAD.left} y={height - 6} fontSize={11} fill={muted}>{fmtDay(all[0].date)}</text>
      <text x={width - PAD.right} y={height - 6} fontSize={11} fill={muted} textAnchor="end">
        {fmtDay(all.reduce((m, p) => (t(p.date) > t(m.date) ? p : m)).date)}
      </text>
    </svg>
  );
}
