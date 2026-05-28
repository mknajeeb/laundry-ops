import { formatRinseApiDateTime, hasExplicitTzOffset } from "./rinseTimeFormat";

export function formatLaborHours(hours, digits = 1) {
  if (hours == null || hours === "") return "—";
  const n = Number(hours);
  if (!Number.isFinite(n) || n <= 0) return "—";
  return n.toFixed(digits);
}

export function formatPercent(val, digits = 1) {
  if (val == null || val === "") return "—";
  const n = Number(val);
  if (!Number.isFinite(n)) return "—";
  return `${n.toFixed(digits)}%`;
}

export function formatCount(val) {
  if (val == null || val === "") return "—";
  const n = Number(val);
  if (!Number.isFinite(n)) return "—";
  return String(Math.round(n));
}

export function formatFoldingDuration(seconds) {
  const s = Number(seconds);
  if (!Number.isFinite(s) || s <= 0) return "—";
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

export function formatFoldingHours(seconds) {
  const s = Number(seconds);
  if (!Number.isFinite(s) || s <= 0) return "—";
  return (s / 3600).toFixed(2);
}

export function formatRate(val, digits = 2) {
  if (val == null || val === "") return "—";
  const n = Number(val);
  if (!Number.isFinite(n)) return "—";
  return n.toFixed(digits);
}

export function formatLbs(val) {
  if (val == null || val === "") return "—";
  const n = Number(val);
  if (!Number.isFinite(n)) return "—";
  return n.toFixed(1);
}

export function formatDateTime(val) {
  if (!val) return "—";
  const s = String(val).trim();
  if (hasExplicitTzOffset(s)) return formatRinseApiDateTime(s);
  if (/\bGMT\b/i.test(s)) return "—";
  const d = new Date(val);
  if (Number.isNaN(d.getTime())) return String(val);
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

/** Single-line ET wall time for folding tables (no timezone line-wrap). */
export function formatFoldingWallDateTime(val) {
  if (!val) return "—";
  const s = String(val).trim();
  if (/\bGMT\b/i.test(s)) return "—";
  if (hasExplicitTzOffset(s)) {
    const d = new Date(s);
    if (Number.isNaN(d.getTime())) return "—";
    return `${d.toLocaleString("en-US", {
      timeZone: "America/New_York",
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    })} ET`;
  }
  const m = s.match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{1,2}):(\d{2})/);
  if (m) {
    const [, y, mo, d, h, mi] = m;
    const dt = new Date(Number(y), Number(mo) - 1, Number(d), Number(h), Number(mi));
    if (Number.isNaN(dt.getTime())) return s;
    return `${dt.toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    })} ET`;
  }
  const d = new Date(val);
  if (Number.isNaN(d.getTime())) return String(val);
  return `${d.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  })} ET`;
}

export function formatPeriodRange(start, end) {
  if (!start || !end) return "—";
  const fmt = (iso) => {
    const d = new Date(`${iso}T12:00:00`);
    return d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
  };
  return `${fmt(start)} – ${fmt(end)}`;
}

export function isoDateInput(d = new Date()) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export function targetStatusChipColor(status) {
  const s = String(status || "").toLowerCase();
  if (s === "above") return "success";
  if (s === "below") return "error";
  if (s === "mixed") return "warning";
  return "default";
}

export function comparisonArrow(direction) {
  const d = String(direction || "flat").toLowerCase();
  if (d === "up") return "↑";
  if (d === "down") return "↓";
  return "→";
}

export function formatComparison(comp, { suffix = "", invert = false } = {}) {
  if (!comp?.available || comp.delta == null) return "—";
  let dir = comp.direction;
  if (invert) {
    if (dir === "up") dir = "down";
    else if (dir === "down") dir = "up";
  }
  const sign = Number(comp.delta) > 0 ? "+" : "";
  return `${comparisonArrow(dir)} ${sign}${formatRate(comp.delta)}${suffix}`;
}
