import { makeStyles, mergeClasses, shorthands, tokens, Tooltip } from '@fluentui/react-components';
import { Warning12Filled } from '@fluentui/react-icons';
import type { Payment } from '../types';
import { colors } from './styles';

const useStyles = makeStyles({
  pill: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: '4px',
    borderRadius: tokens.borderRadiusCircular,
    padding: '1px 8px',
    fontSize: tokens.fontSizeBase200,
    lineHeight: tokens.lineHeightBase200,
    border: `1px solid ${tokens.colorNeutralStroke1}`,
    whiteSpace: 'nowrap',
  },
  ok: { color: colors.success, ...shorthands.borderColor('#9FD89F'), backgroundColor: '#F1FAF1' },
  wait: { color: '#835B00', ...shorthands.borderColor('#F2D97C'), backgroundColor: '#FFFBEB', whiteSpace: 'normal' },
  no: { color: colors.danger, ...shorthands.borderColor('#EEACB2'), backgroundColor: '#FDF3F4' },
  flag: { color: colors.warning, ...shorthands.borderColor('#F4BFAB'), backgroundColor: '#FDF6F3', cursor: 'default' },
});

export function statusText(p: Payment): string {
  if (p.status === 'EXECUTED') return 'Executed';
  if (p.status === 'REJECTED') return 'Rejected';
  return p.awaiting_approval_from.length
    ? `Awaiting approval from ${p.awaiting_approval_from.join(' or ')}`
    : 'Awaiting approval';
}

export function StatusPill({ payment }: { payment: Payment }) {
  const s = useStyles();
  const tone = payment.status === 'EXECUTED' ? s.ok : payment.status === 'REJECTED' ? s.no : s.wait;
  return <span className={mergeClasses(s.pill, tone)}>{statusText(payment)}</span>;
}

/** Orange "Unusual" flag; hover shows the model's score and reason. Never blocks anything. */
export function AnomalyFlag({ score, reason }: { score: string; reason: string }) {
  const s = useStyles();
  return (
    <Tooltip content={`Score ${score}: ${reason}`} relationship="description" withArrow>
      <span className={mergeClasses(s.pill, s.flag)} tabIndex={0}>
        <Warning12Filled aria-hidden /> Unusual
      </span>
    </Tooltip>
  );
}
