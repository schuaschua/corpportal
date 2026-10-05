// Dates: business dates ("2026-10-08") are calendar days; API timestamps are naive UTC and are
// shown in Gulf time, where the demo companies operate.

const TZ = 'Asia/Dubai';

const dayShort = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' });
const dayWeek = new Intl.DateTimeFormat('en-GB', { weekday: 'short', day: 'numeric', month: 'short', timeZone: 'UTC' });
const dayLong = new Intl.DateTimeFormat('en-GB', { weekday: 'long', day: 'numeric', month: 'short', timeZone: 'UTC' });
const dayFull = new Intl.DateTimeFormat('en-GB', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
const clock = new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: TZ });
const gulfDate = new Intl.DateTimeFormat('en-CA', { year: 'numeric', month: '2-digit', day: '2-digit', timeZone: TZ });
const gulfHour = new Intl.DateTimeFormat('en-GB', { hour: 'numeric', hourCycle: 'h23', timeZone: TZ });

const day = (iso: string) => new Date(`${iso.slice(0, 10)}T00:00:00Z`);
/** An API timestamp (naive UTC unless it carries an offset) as a Date. */
export const instant = (iso: string) => new Date(/[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`);

/** "5 Oct" */
export const fmtDay = (iso: string) => dayShort.format(day(iso));
/** "Thu 8 Oct" */
export const fmtWeekday = (iso: string) => dayWeek.format(day(iso));
/** "Monday 5 Oct" */
export const fmtLongDay = (iso: string) => dayLong.format(day(iso));
/** "Mon 5 Oct 2026" */
export const fmtFullDay = (iso: string) => dayFull.format(day(iso));
/** "07:45" in Gulf time */
export const fmtTime = (iso: string) => clock.format(instant(iso));
/** Gulf-time calendar date of a timestamp, "2026-10-05" */
export const gulfDay = (iso: string) => gulfDate.format(instant(iso));
/** Today's date in Gulf time, "2026-10-05" */
export const todayGulf = () => gulfDate.format(new Date());

export function greeting(now = new Date()): string {
  const h = Number(gulfHour.format(now));
  if (h < 12) return 'Good morning';
  if (h < 18) return 'Good afternoon';
  return 'Good evening';
}

export const paymentRef = (id: number) => `PAY-${id}`;

/** Region ids from REGION env to the names people know. Unknown ids are shown as-is. */
const REGIONS: Record<string, string> = {
  westus3: 'West US 3',
  northcentralus: 'North Central US',
  uaenorth: 'UAE North',
  uaecentral: 'UAE Central',
  local: 'local',
};
export const regionName = (id: string) => REGIONS[id.toLowerCase()] ?? id;
