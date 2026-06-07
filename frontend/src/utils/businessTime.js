/**
 * Business calendar dates in America/New_York.
 * Schedule dates are calendar days (YYYY-MM-DD), not UTC instants — avoid toISOString().slice(0,10).
 */

export const BUSINESS_TIMEZONE = "America/New_York";

/** YYYY-MM-DD for a Date interpreted in the business timezone. */
export function ymdInBusinessTz(date = new Date()) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: BUSINESS_TIMEZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(date);
  const y = parts.find((p) => p.type === "year")?.value;
  const m = parts.find((p) => p.type === "month")?.value;
  const d = parts.find((p) => p.type === "day")?.value;
  return `${y}-${m}-${d}`;
}

export function businessTodayYmd() {
  return ymdInBusinessTz(new Date());
}

/** Add calendar days to a YYYY-MM-DD string (stable via UTC noon). */
export function addDaysYmd(ymd, days) {
  if (!ymd) return businessTodayYmd();
  const [y, m, d] = ymd.split("-").map((x) => parseInt(x, 10));
  const dt = new Date(Date.UTC(y, m - 1, d + days, 12, 0, 0));
  return ymdInBusinessTz(dt);
}

/** Monday-based day index 0=Mon … 6=Sun for a calendar date. */
export function dayOfWeekMon0(ymd) {
  const [y, m, d] = ymd.split("-").map((x) => parseInt(x, 10));
  const dow = new Date(Date.UTC(y, m - 1, d, 12, 0, 0)).getUTCDay();
  return dow === 0 ? 6 : dow - 1;
}

/**
 * First day of the work week containing ymd.
 * weekStartsOn: 0=Monday … 6=Sunday (matches payroll schedule settings).
 */
export function weekStartFromDate(ymd, weekStartsOn = 0) {
  const mon0 = dayOfWeekMon0(ymd);
  const delta = (mon0 - weekStartsOn + 7) % 7;
  return addDaysYmd(ymd, -delta);
}

export function weekEndFromStart(weekStartYmd) {
  return addDaysYmd(weekStartYmd, 6);
}

/** Readable label: Mon, Jun 8 */
export function formatDateShortLabel(ymd) {
  if (!ymd) return "—";
  const [y, m, d] = ymd.split("-").map((x) => parseInt(x, 10));
  if (!y || !m || !d) return ymd;
  const dt = new Date(y, m - 1, d);
  return dt.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
}

/** Week range label using configured week boundaries. */
export function formatWeekRangeLabel(weekStartYmd, weekEndYmd) {
  return `${formatDateShortLabel(weekStartYmd)} – ${formatDateShortLabel(weekEndYmd)}`;
}
