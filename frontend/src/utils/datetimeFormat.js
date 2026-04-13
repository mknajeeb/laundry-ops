const ISO_DATE_PREFIX_RE = /^(\d{4}-\d{2}-\d{2})/;

/**
 * yyyy-MM-dd for <input type="date"> from API values (ISO datetimes, RFC strings, DATE columns).
 */
export function toDateInputValue(value) {
  if (value == null || value === "") return "";
  const s = String(value).trim();
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return s;
  const head = s.match(ISO_DATE_PREFIX_RE);
  if (head) return head[1];
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return "";
  const y = d.getUTCFullYear();
  const m = String(d.getUTCMonth() + 1).padStart(2, "0");
  const day = String(d.getUTCDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/**
 * Human-readable calendar date for labels/tables (falls back to raw string if unparsable).
 */
export function formatCalendarDateLabel(value) {
  const v = toDateInputValue(value);
  if (!v) {
    const raw = String(value ?? "").trim();
    return raw || "—";
  }
  const [y, mo, d] = v.split("-").map((x) => parseInt(x, 10));
  if (!y || !mo || !d) return String(value ?? "");
  return new Date(y, mo - 1, d).toLocaleDateString(undefined, { dateStyle: "medium" });
}

/**
 * Display API timestamps in US Eastern (America/New_York, EST/EDT).
 * Expects ISO strings from the API with UTC offset (Z or +00:00).
 */
export function formatEasternDateTime(iso) {
  if (iso == null || iso === "") return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  return d.toLocaleString("en-US", {
    timeZone: "America/New_York",
    month: "numeric",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
    hour12: true,
    timeZoneName: "short",
  });
}
