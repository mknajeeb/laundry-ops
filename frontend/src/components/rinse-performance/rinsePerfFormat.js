import { VEEWASH_BRAND } from "../../theme/veewashBrand";

export const METRICS = [
  { key: "lbs_hr", label: "Folding Speed", unit: "lb/hr" },
  { key: "bags_hr", label: "Bags/hr", unit: "bags/hr" },
  { key: "pounds", label: "Pounds", unit: "lb" },
  { key: "bags", label: "Bags / Orders", unit: "bags" },
  { key: "hours", label: "Hours", unit: "hr" },
];

export const PERIODS = [
  { key: "today", label: "Today" },
  { key: "yesterday", label: "Yesterday" },
  { key: "this_week", label: "This Week" },
  { key: "last_week", label: "Last Week" },
  { key: "last_7_days", label: "Last 7 Days" },
  { key: "last_30_days", label: "Last 30 Days" },
  { key: "custom", label: "Custom" },
];

export const COMPARES = [
  { key: "none", label: "None" },
  { key: "previous_period", label: "Previous Period" },
  { key: "previous_week", label: "Previous Week" },
  { key: "previous_4_weeks", label: "Previous 4 Weeks" },
];

export const VIEWS = [
  { key: "overview", label: "Overview" },
  { key: "role", label: "By Role" },
  { key: "employee", label: "By Employee" },
  { key: "daily", label: "Daily" },
];

export function fmtRate(v, digits = 1) {
  if (v == null || !Number.isFinite(Number(v))) return "—";
  return Number(v).toFixed(digits);
}

export function fmtInt(v) {
  if (v == null || !Number.isFinite(Number(v))) return "—";
  return Math.round(Number(v)).toLocaleString("en-US");
}

export function fmtDelta(v, digits = 1) {
  if (v == null || !Number.isFinite(Number(v))) return "—";
  const n = Number(v);
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(digits)}`;
}

export function deltaTone(delta) {
  if (!delta || delta.absolute == null || !Number.isFinite(Number(delta.absolute))) {
    return VEEWASH_BRAND.inkMuted;
  }
  if (Number(delta.absolute) > 0) return VEEWASH_BRAND.primaryDark;
  if (Number(delta.absolute) < 0) return "#a16207";
  return VEEWASH_BRAND.inkMuted;
}

export function formatDeltaBadge(delta) {
  if (!delta || delta.display === "—" || delta.absolute == null) return "—";
  const abs = Number(delta.absolute);
  const sign = abs > 0 ? "↑" : abs < 0 ? "↓" : "";
  if (delta.percent == null) return `${sign} ${fmtDelta(abs)}`.trim();
  const pctSign = abs > 0 ? "+" : "";
  return `${sign} ${pctSign}${Number(delta.percent).toFixed(1)}% vs prior`;
}

export function statusLabel(status) {
  const s = String(status || "").toUpperCase();
  if (s === "APPROVED") return "Approved";
  if (s === "PARTIALLY_APPROVED") return "Partially Approved";
  if (s === "NEEDS_APPROVAL") return "Needs Approval";
  if (s === "EXCLUDED") return "Excluded";
  return s || "—";
}

export function metricDigits(metricKey) {
  if (metricKey === "bags" || metricKey === "pounds") return 0;
  if (metricKey === "hours") return 1;
  return 1;
}

export function vsTone(vs) {
  if (vs == null || !Number.isFinite(Number(vs))) return VEEWASH_BRAND.inkMuted;
  if (Number(vs) >= 0) return VEEWASH_BRAND.primaryDark;
  return "#a16207";
}

export function etTodayYmd() {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());
  const get = (t) => parts.find((p) => p.type === t)?.value;
  return `${get("year")}-${get("month")}-${get("day")}`;
}

export function cardSx(extra = {}) {
  return {
    p: 1.25,
    borderColor: VEEWASH_BRAND.borderSoft,
    borderRadius: VEEWASH_BRAND.radius,
    background: "#fff",
    boxShadow: "0 1px 2px rgba(15, 23, 42, 0.04)",
    ...extra,
  };
}
