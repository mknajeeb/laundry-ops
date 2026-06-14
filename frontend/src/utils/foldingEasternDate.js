/** America/New_York calendar helpers for folding filters. */

const TZ = "America/New_York";

function partsInEastern(d = new Date()) {
  const fmt = new Intl.DateTimeFormat("en-US", {
    timeZone: TZ,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    weekday: "short",
  });
  const map = {};
  for (const p of fmt.formatToParts(d)) {
    if (p.type !== "literal") map[p.type] = p.value;
  }
  return map;
}

export function easternIsoDate(d = new Date()) {
  const p = partsInEastern(d);
  return `${p.year}-${p.month}-${p.day}`;
}

export function easternWeekdayIndex(d = new Date()) {
  const p = partsInEastern(d);
  const w = String(p.weekday || "Mon").slice(0, 3);
  const idx = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 }[w];
  return idx ?? 1;
}

/** Monday-based week containing `d` (Eastern calendar). */
export function defaultWeekRangeEastern(d = new Date()) {
  const iso = easternIsoDate(d);
  const [y, m, day] = iso.split("-").map(Number);
  const anchor = new Date(Date.UTC(y, m - 1, day, 12, 0, 0));
  const wd = easternWeekdayIndex(d);
  const mondayOffset = (wd + 6) % 7;
  const start = new Date(anchor);
  start.setUTCDate(anchor.getUTCDate() - mondayOffset);
  const end = new Date(start);
  end.setUTCDate(start.getUTCDate() + 6);
  return { start: easternIsoDate(start), end: easternIsoDate(end) };
}

export function todayRangeEastern() {
  const t = easternIsoDate();
  return { start: t, end: t };
}

export function yesterdayRangeEastern() {
  const today = easternIsoDate();
  const [y, m, d] = today.split("-").map(Number);
  const anchor = new Date(Date.UTC(y, m - 1, d, 12, 0, 0));
  anchor.setUTCDate(anchor.getUTCDate() - 1);
  const iso = easternIsoDate(anchor);
  return { start: iso, end: iso };
}

/** Inclusive ET calendar range ending today (e.g. 7 → today and prior 6 days). */
export function lastNDaysRangeEastern(dayCount) {
  const end = easternIsoDate();
  const n = Math.max(1, Number(dayCount) || 1);
  const [y, m, d] = end.split("-").map(Number);
  const anchor = new Date(Date.UTC(y, m - 1, d, 12, 0, 0));
  anchor.setUTCDate(anchor.getUTCDate() - (n - 1));
  return { start: easternIsoDate(anchor), end };
}

export function monthRangeEastern(d = new Date()) {
  const p = partsInEastern(d);
  const y = Number(p.year);
  const m = Number(p.month);
  const start = `${y}-${String(m).padStart(2, "0")}-01`;
  const lastDay = new Date(Date.UTC(y, m, 0, 12, 0, 0));
  return { start, end: easternIsoDate(lastDay) };
}

export function formatAppliedRangeSummary({ dateStart, dateEnd, preset }) {
  const fmt = (iso) => {
    if (!iso) return "";
    const [y, mo, da] = iso.split("-").map(Number);
    return new Date(y, mo - 1, da).toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  };
  if (dateStart === dateEnd) {
    return `Showing folding work date: ${fmt(dateStart)} ET`;
  }
  if (preset === "week") {
    return `Showing current week: ${fmt(dateStart)}–${fmt(dateEnd)} ET`;
  }
  return `Showing ${fmt(dateStart)} – ${fmt(dateEnd)} ET`;
}
