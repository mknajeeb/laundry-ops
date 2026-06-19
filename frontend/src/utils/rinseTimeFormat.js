/** Rinse portal / scan datetimes: America/New_York wall time in API (ISO with offset). */

const ET = "America/New_York";

/** True when string has explicit offset or UTC Z (safe for Date.parse → ET). Rejects GMT. */
export function hasExplicitTzOffset(value) {
  const s = String(value ?? "").trim();
  if (!s) return false;
  if (/\bGMT\b/i.test(s)) return false;
  if (/Z$/i.test(s)) return true;
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

/** Laundry Ops business display: America/New_York with explicit ET label. */
export function formatBusinessDateTime(value, { withYear = false } = {}) {
  if (!value) return "—";
  const s = String(value).trim();
  if (/\bGMT\b/i.test(s)) return "—";
  if (!hasExplicitTzOffset(s)) return "—";
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return "—";
  const formatted = d.toLocaleString("en-US", {
    timeZone: ET,
    month: "short",
    day: "numeric",
    ...(withYear ? { year: "numeric" } : {}),
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  });
  return normalizeEtSuffix(formatted);
}

/** Force EDT/EST labels to ET for consistent Eastern display. */
export function normalizeEtSuffix(label) {
  if (label == null || label === "" || label === "—") return label ?? "—";
  return String(label).replace(/\b(EDT|EST)\b/gi, "ET").trim();
}

const FRIENDLY_ET_RE = /^[A-Za-z]{3}\s+\d{1,2},\s+\d{1,2}:\d{2}\s+(AM|PM)\s+ET$/i;

/** Friendly Eastern display for UI: Jun 17, 5:21 AM ET */
export function formatFriendlyEtWall(value) {
  if (value == null || value === "") return "—";
  const s = String(value).trim();
  if (!s || s === "—") return "—";
  if (FRIENDLY_ET_RE.test(s)) return normalizeEtSuffix(s);

  const stripped = s.replace(/\s+ET$/i, "").trim();

  // UTC / ISO with Z or explicit offset — convert to America/New_York first.
  if (/Z$/i.test(stripped) || /\+00:00$/i.test(stripped) || hasExplicitTzOffset(stripped)) {
    const converted = formatBusinessDateTime(stripped);
    if (converted !== "—") return converted;
  }

  const naive = formatNaiveEtWallDateTime(stripped);
  if (naive) return naive;

  const isoNaive = stripped.match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{1,2}):(\d{2})/);
  if (isoNaive) {
    return formatNaiveEtWallDateTime(
      `${isoNaive[1]}-${isoNaive[2]}-${isoNaive[3]} ${isoNaive[4]}:${isoNaive[5]}`,
    );
  }

  return "—";
}

/** Scan timeline display — friendly ET; prefers portal raw text when present. */
export function formatFriendlyScanTime(ev) {
  const raw = String(ev?.time_scanned_raw ?? "").trim();
  if (raw) {
    const friendly = formatFriendlyEtWall(raw);
    if (friendly !== "—") return friendly;
  }
  return formatFriendlyEtWall(ev?.scanned_at_parsed || ev?.time_scanned_et);
}

/** ISO-style Eastern wall: YYYY-MM-DD HH:MM:SS ET (matches backend _format_et_display). */
export function formatIsoEtWall(value) {
  if (value == null || value === "") return "—";
  const s = String(value).trim();
  if (s === "—") return s;
  if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} ET$/i.test(s)) return s;
  if (/\bET$/i.test(s)) return normalizeEtSuffix(s);

  const naive = s.match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?/);
  if (naive && !hasExplicitTzOffset(s)) {
    const sec = naive[6] ?? "00";
    return `${naive[1]}-${naive[2]}-${naive[3]} ${naive[4]}:${naive[5]}:${sec} ET`;
  }
  if (hasExplicitTzOffset(s)) {
    const d = new Date(s);
    if (Number.isNaN(d.getTime())) return "—";
    const parts = new Intl.DateTimeFormat("en-US", {
      timeZone: ET,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    }).formatToParts(d);
    const pick = (t) => parts.find((p) => p.type === t)?.value ?? "00";
    return `${pick("year")}-${pick("month")}-${pick("day")} ${pick("hour")}:${pick("minute")}:${pick("second")} ET`;
  }
  return normalizeEtSuffix(/\bET\b/i.test(s) ? s : `${s} ET`);
}

/** Long Eastern display for scan timeline rows. */
export function formatLongEtWall(value) {
  if (value == null || value === "") return "—";
  const s = String(value).trim();
  if (/\b(AM|PM)\b/i.test(s) && /\bET\b/i.test(s)) return normalizeEtSuffix(s);

  const iso = formatIsoEtWall(value);
  if (iso === "—") {
    if (/\b(AM|PM)\b/i.test(s)) return normalizeEtSuffix(/\bET\b/i.test(s) ? s : `${s} ET`);
    return "—";
  }
  const m = iso.match(/^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2}) ET$/);
  if (!m) return iso;
  const [, y, mo, d, h24, mi] = m;
  const date = new Date(Number(y), Number(mo) - 1, Number(d));
  const weekday = date.toLocaleString("en-US", { weekday: "long" });
  const month = date.toLocaleString("en-US", { month: "long" });
  const hour24 = Number(h24);
  const hour12 = hour24 % 12 || 12;
  const ampm = hour24 >= 12 ? "PM" : "AM";
  return `${weekday}, ${month} ${Number(d)}, ${y} ${hour12}:${mi} ${ampm} ET`;
}

/** @deprecated alias — prefer formatBusinessDateTime */
export function formatRinseApiDateTime(value, opts = {}) {
  return formatBusinessDateTime(value, opts);
}

/** Prefer portal raw text; fall back to Eastern ISO from API. */
export function formatRinseScanTime(ev) {
  const raw = String(ev?.time_scanned_raw ?? "").trim();
  if (raw) {
    if (/\b(EDT|EST|ET)\b/i.test(raw)) return normalizeEtSuffix(raw);
    return `${raw} ET`;
  }
  const parsed = ev?.scanned_at_parsed;
  if (parsed && hasExplicitTzOffset(parsed)) {
    return formatLongEtWall(parsed);
  }
  if (parsed) return formatIsoEtWall(parsed);
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

/** Normalize GET /rinse/bags/:id/scan-events body (raw array or wrapped). */
export function parseRinseBagScanEventsResponse(data) {
  if (Array.isArray(data)) return data;
  return data?.events || data?.scan_events || [];
}
