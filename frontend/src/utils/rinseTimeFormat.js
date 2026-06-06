/** Rinse portal / scan datetimes: America/New_York wall time in API (ISO with offset). */

const ET = "America/New_York";

/** True when string has explicit offset (safe for Date.parse). Rejects GMT / bare Z. */
export function hasExplicitTzOffset(value) {
  const s = String(value ?? "").trim();
  if (!s) return false;
  if (/\bGMT\b/i.test(s)) return false;
  if (/Z$/i.test(s) && !/[+-]\d{2}:\d{2}$/.test(s)) return false;
  return /[+-]\d{2}:\d{2}$/.test(s) || /[+-]\d{4}$/.test(s);
}

export function parseRinseApiInstant(value) {
  const s = String(value ?? "").trim();
  if (!hasExplicitTzOffset(s)) return Number.NaN;
  const t = Date.parse(s);
  return Number.isFinite(t) ? t : Number.NaN;
}

/** Display naive Rinse/DB wall time (already Eastern) without browser-local drift. */
export function formatNaiveEtWallDateTime(value) {
  const s = String(value ?? "").trim();
  const m = s.match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{1,2}):(\d{2})/);
  if (!m) return null;
  const [, y, mo, d, h, mi] = m;
  const monthIdx = Number(mo) - 1;
  const dayNum = Number(d);
  const hour24 = Number(h);
  const hour12 = hour24 % 12 || 12;
  const ampm = hour24 >= 12 ? "PM" : "AM";
  const monthLabel = new Date(Number(y), monthIdx, dayNum).toLocaleString("en-US", { month: "short" });
  return `${monthLabel} ${dayNum}, ${hour12}:${mi} ${ampm} ET`;
}

/** System/job timestamps from API (UTC stored, serialized with ET offset). */
export const formatSystemDateTime = formatBusinessDateTime;

/** Laundry Ops business display: America/New_York with EDT/EST label. */
export function formatBusinessDateTime(value, { withYear = false } = {}) {
  if (!value) return "—";
  const s = String(value).trim();
  if (/\bGMT\b/i.test(s)) return "—";
  if (!hasExplicitTzOffset(s)) return "—";
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("en-US", {
    timeZone: ET,
    month: "short",
    day: "numeric",
    ...(withYear ? { year: "numeric" } : {}),
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  });
}

/** @deprecated alias — prefer formatBusinessDateTime */
export function formatRinseApiDateTime(value, opts = {}) {
  return formatBusinessDateTime(value, opts);
}

/** Prefer portal raw text; fall back to Eastern ISO from API. */
export function formatRinseScanTime(ev) {
  const raw = String(ev?.time_scanned_raw ?? "").trim();
  if (raw) {
    if (/\b(EDT|EST|ET)\b/i.test(raw)) return raw;
    return `${raw} ET`;
  }
  const parsed = ev?.scanned_at_parsed;
  if (parsed && hasExplicitTzOffset(parsed)) {
    return formatBusinessDateTime(parsed);
  }
  if (parsed) return String(parsed);
  return "—";
}

export function compareRinseScanEvents(a, b) {
  const ta = parseRinseApiInstant(a?.scanned_at_parsed);
  const tb = parseRinseApiInstant(b?.scanned_at_parsed);
  if (Number.isFinite(ta) && Number.isFinite(tb) && ta !== tb) return ta - tb;
  const ai = Number.isFinite(Number(a?.scan_index)) ? Number(a.scan_index) : 0;
  const bi = Number.isFinite(Number(b?.scan_index)) ? Number(b.scan_index) : 0;
  if (ai !== bi) return ai - bi;
  return (Number(a?.id) || 0) - (Number(b?.id) || 0);
}

export function sortRinseScanEvents(events) {
  return [...(events || [])].sort(compareRinseScanEvents);
}
