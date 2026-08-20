/** Display helpers — blank (not entered) vs intentional zero. */

export function todayEtIso() {
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

/** Summary display: null/undefined → em dash; 0 → $0.00 */
export function fmtMoney(v, { empty = "—", compact = false } = {}) {
  if (v == null || v === "" || Number.isNaN(Number(v))) return empty;
  const n = Number(v);
  if (compact && Math.abs(n) >= 1000) {
    return `$${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
  }
  return `$${n.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

/** Input display: null → blank string; 0 → "0" */
export function moneyToInput(v) {
  if (v == null || v === "") return "";
  return String(v);
}

/**
 * Parse editable money. Blank → null (not entered).
 * Explicit "0" → 0.
 */
export function parseMoneyInput(v) {
  const s = String(v ?? "").trim();
  if (!s) return null;
  const n = Number(s.replace(/[^0-9.-]/g, ""));
  return Number.isFinite(n) ? n : null;
}

export function netCashTone(v) {
  if (v == null) return "neutral";
  const n = Number(v);
  if (n < 0) return "negative";
  if (n > 0) return "positive";
  return "neutral";
}

export const CASH_PERIODS = [
  { id: "today", label: "Today" },
  { id: "week", label: "Week" },
  { id: "month", label: "Month" },
  { id: "custom", label: "Custom" },
];

export const DASH_PERIODS = [
  { id: "today", label: "Today" },
  { id: "yesterday", label: "Yesterday" },
  { id: "week", label: "Week" },
  { id: "previous_week", label: "Previous Week" },
  { id: "month", label: "Month" },
  { id: "previous_month", label: "Previous Month" },
  { id: "custom", label: "Custom" },
];

export const CASH_PERIODS_FULL = DASH_PERIODS;

