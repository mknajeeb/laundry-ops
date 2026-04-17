/** Wall-calendar date in US Eastern (handles DST). Returns YYYY-MM-DD for `date` (default: now). */
const EASTERN_TZ = "America/New_York";

export function formatYmdInEastern(date = new Date()) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: EASTERN_TZ,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);
}

/** Today’s calendar date in US Eastern (YYYY-MM-DD). */
export function getTodayYmdEastern() {
  return formatYmdInEastern(new Date());
}

export function easternTzLabel() {
  return "America/New_York (EST/EDT)";
}
