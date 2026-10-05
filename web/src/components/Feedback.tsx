import { MessageBar, MessageBarBody, Skeleton, SkeletonItem, makeStyles } from '@fluentui/react-components';
import type { ApiError } from '../api';

const useStyles = makeStyles({
  bar: { marginBottom: '16px' },
  rows: { display: 'flex', flexDirection: 'column', gap: '10px' },
});

/**
 * Error MessageBar for a failed load. "Unavailable" is left to the Shell's global warning
 * bar, which retries every 5 s.
 */
export function ErrorBar({ error }: { error: ApiError | undefined }) {
  const s = useStyles();
  if (!error || error.kind === 'unavailable') return null;
  return (
    <MessageBar intent="error" className={s.bar}>
      <MessageBarBody>{error.message}</MessageBarBody>
    </MessageBar>
  );
}

export function SkeletonRows({ rows = 4, label = 'Loading' }: { rows?: number; label?: string }) {
  const s = useStyles();
  return (
    <Skeleton aria-label={label} className={s.rows}>
      {Array.from({ length: rows }, (_, i) => (
        <SkeletonItem key={i} size={20} />
      ))}
    </Skeleton>
  );
}
