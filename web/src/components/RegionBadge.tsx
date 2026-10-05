import { makeStyles, mergeClasses, tokens } from '@fluentui/react-components';
import { useEffect, useRef, useState } from 'react';
import { regionName } from '../format';
import { useRegion } from '../useApi';
import { colors } from './styles';

const useStyles = makeStyles({
  badge: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: '6px',
    border: `1px solid ${tokens.colorNeutralStroke1}`,
    borderRadius: tokens.borderRadiusCircular,
    padding: '2px 10px',
    fontSize: tokens.fontSizeBase200,
    lineHeight: tokens.lineHeightBase200,
    backgroundColor: tokens.colorNeutralBackground1,
    whiteSpace: 'nowrap',
  },
  dot: { width: '8px', height: '8px', borderRadius: '50%', backgroundColor: colors.success },
  flash: {
    animationName: {
      '0%': { transform: 'scale(1)', opacity: 1 },
      '50%': { transform: 'scale(1.9)', opacity: 0.4 },
      '100%': { transform: 'scale(1)', opacity: 1 },
    },
    animationDuration: '900ms',
    animationIterationCount: 1,
  },
});

/** The region that served the most recent API response (X-Served-From). Always visible. */
export function RegionBadge() {
  const s = useStyles();
  const region = useRegion();
  const previous = useRef(region);
  const [flashes, setFlashes] = useState(0);

  useEffect(() => {
    if (previous.current !== null && region !== previous.current) setFlashes((n) => n + 1);
    previous.current = region;
  }, [region]);

  return (
    <span className={s.badge} aria-live="polite" data-testid="region-badge">
      {/* re-keyed on each change so the dot flashes once */}
      <span key={flashes} className={mergeClasses(s.dot, flashes > 0 && s.flash)} data-flash={flashes} aria-hidden />
      Serving from: {region ? regionName(region) : '…'}
    </span>
  );
}
