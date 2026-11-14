/** Presentation helpers for Management → Performance (no business logic). */

export function fmtRate(v, digits = 1) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  return Number(v).toFixed(digits);
}

export function fmtLbs(v, { compact = false } = {}) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  const n = Number(v);
  if (compact) {
    return `${n.toLocaleString(undefined, { maximumFractionDigits: 0 })} lb`;
  }
  return `${n.toLocaleString(undefined, { maximumFractionDigits: 0 })} lb`;
}

export function fmtHours(v, digits = 1) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  return Number(v).toFixed(digits);
}

export function fmtDelta(pct) {
  if (pct == null || Number.isNaN(Number(pct))) return null;
  const n = Number(pct);
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(0)}%`;
}

export function fmtCount(n) {
  if (n == null || Number.isNaN(Number(n))) return "0";
  return Number(n).toLocaleString(undefined, { maximumFractionDigits: 0 });
}

function firstNumber(...values) {
  for (const value of values) {
    if (value == null || value === "") continue;
    const n = Number(value);
    if (!Number.isNaN(n)) return n;
  }
  return null;
}

/** Recorded employee-day totals. Rate is total pounds / total hours. */
export function recordedDay(employee) {
  const bags = firstNumber(
    employee?.recorded_orders_completed,
    employee?.all_visible_orders_completed,
    employee?.orders_completed
  );
  const pounds = firstNumber(
    employee?.recorded_total_pre_lbs,
    employee?.all_visible_total_pre_lbs,
    employee?.total_pre_lbs
  );
  const hours = firstNumber(
    employee?.recorded_performance_hours,
    employee?.all_visible_performance_hours,
    employee?.performance_hours,
    employee?.session_hours
  );
  let rate = firstNumber(employee?.recorded_lbs_per_hour, employee?.combined_lbs_per_hour);
  if (rate == null && hours != null && hours > 0 && pounds != null) {
    rate = pounds / hours;
  }
  if (rate == null) rate = firstNumber(employee?.lbs_per_hour);
  return {
    bags: bags ?? 0,
    pounds: pounds ?? 0,
    hours,
    rate,
  };
}
