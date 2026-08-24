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
