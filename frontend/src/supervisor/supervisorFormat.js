export const CATEGORIES = [
  ["approved", "Approved"],
  ["pending", "Pending"],
  ["excluded", "Excluded"],
  ["outside_session", "Outside session"],
  ["nonqualifying", "No qualifying scan"],
  ["unmapped", "Unmapped"],
  ["unresolved", "Unresolved"],
];

export function etToday() {
  try {
    return new Intl.DateTimeFormat("en-CA", {
      timeZone: "America/New_York",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(new Date());
  } catch {
    return new Date().toISOString().slice(0, 10);
  }
}

export function reconciliationCheck(report) {
  const categories = report?.categories || {};
  const sum = CATEGORIES.reduce((total, [key]) => total + Number(categories[key] || 0), 0);
  const completed = Number(report?.total_completed || 0);
  const unaccounted = Number(report?.unaccounted || 0);
  return {
    completed,
    accounted: Number(report?.total_accounted || 0),
    unaccounted,
    sum,
    holds: sum === completed && unaccounted === 0,
  };
}

export function formatRate(value) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  return `${Number(value).toFixed(1)} lb/hr`;
}

export function formatNumber(value) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  return Number(value).toLocaleString("en-US", { maximumFractionDigits: 1 });
}

export function formatBagsRate(value) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  return `${Number(value).toFixed(1)} bags/hr`;
}
