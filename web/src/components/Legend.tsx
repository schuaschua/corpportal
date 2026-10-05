import { mergeClasses } from '@fluentui/react-components';
import { useLegend } from './styles';

export function Legend({ forecastLabel = 'Forecast', threshold = true }: { forecastLabel?: string; threshold?: boolean }) {
  const s = useLegend();
  return (
    <div className={s.legend}>
      <span className={s.item}><span className={s.swatch} />Actual</span>
      <span className={s.item}><span className={mergeClasses(s.swatch, s.dashed)} />{forecastLabel}</span>
      {threshold && <span className={s.item}><span className={mergeClasses(s.swatch, s.threshold)} />Payroll threshold</span>}
    </div>
  );
}
