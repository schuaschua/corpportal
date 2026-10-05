// Money arrives from the API as fixed-point strings ("1780000.00"). It is parsed into integer
// fils (BigInt) and formatted with Intl.NumberFormat('en-AE'); totals never go through floats.

const MINUS = '−';
const groups = new Intl.NumberFormat('en-AE', { useGrouping: true, maximumFractionDigits: 0 });

export function toFils(amount: string): bigint {
  const m = /^\s*([+-])?(\d+)(?:\.(\d{1,2}))?\s*$/.exec(amount);
  if (!m) throw new Error(`Not a money amount: ${amount}`);
  const fils = BigInt(m[2]) * 100n + BigInt((m[3] ?? '').padEnd(2, '0'));
  return m[1] === '-' ? -fils : fils;
}

function body(fils: bigint): string {
  const abs = fils < 0n ? -fils : fils;
  const whole = groups.format(abs / 100n);
  const cents = abs % 100n;
  return cents === 0n ? `AED ${whole}` : `AED ${whole}.${cents.toString().padStart(2, '0')}`;
}

/** `AED 1,900,000`, `−AED 120,000`; decimals only when there are fils. */
export function formatAED(amount: string | null | undefined): string {
  if (amount == null) return '—';
  const fils = toFils(amount);
  return fils < 0n ? `${MINUS}${body(fils)}` : body(fils);
}

/** Signed for ledger lines: `+AED 590,000`, `−AED 225,000`. */
export function formatSignedAED(amount: string): string {
  const fils = toFils(amount);
  return fils < 0n ? `${MINUS}${body(fils)}` : `+${body(fils)}`;
}

/** Short chart label: `AED 1.9m`, `AED 450k`. Display only. */
export function formatShortAED(fils: bigint): string {
  const sign = fils < 0n ? MINUS : '';
  const abs = fils < 0n ? -fils : fils;
  const dirham = abs / 100n;
  if (dirham >= 1_000_000n) {
    const tenths = (dirham + 50_000n) / 100_000n; // round to 0.1m
    const s = tenths % 10n === 0n ? `${tenths / 10n}` : `${tenths / 10n}.${tenths % 10n}`;
    return `${sign}AED ${s}m`;
  }
  if (dirham >= 1_000n) return `${sign}AED ${(dirham + 500n) / 1_000n}k`;
  return `${sign}AED ${dirham}`;
}

/** For chart geometry only (pixel positions), never for totals. */
export function toChartNumber(amount: string): number {
  return Number(toFils(amount)) / 100;
}

/** Validates a user-typed amount ("450,000" or "450000.00") and returns the API string. */
export function parseAmountInput(raw: string): string | null {
  const cleaned = raw.replace(/[,\s]/g, '').replace(/^AED/i, '');
  if (!/^\d+(\.\d{1,2})?$/.test(cleaned)) return null;
  const fils = toFils(cleaned);
  if (fils <= 0n) return null;
  return `${fils / 100n}.${(fils % 100n).toString().padStart(2, '0')}`;
}
