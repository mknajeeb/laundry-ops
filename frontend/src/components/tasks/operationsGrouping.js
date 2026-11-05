import { formatDashboardDate } from "./taskDashboardFormat";

function ymdParts(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value || "").slice(0, 10));
  if (!match) return null;
  return { year: Number(match[1]), month: Number(match[2]), day: Number(match[3]), ymd: match[0] };
}

/** Monday-start business week. Chart buckets stay on their own Sunday week. */
export function operationsBucket(businessDate, groupBy) {
  const parts = ymdParts(businessDate);
  if (!parts) return { key: "undated", kind: "undated", start: "" };
  const mode = String(groupBy || "daily").toLowerCase();
  if (mode === "monthly") {
    return { key: `${parts.ymd.slice(0, 7)}`, kind: "monthly", start: `${parts.ymd.slice(0, 7)}-01` };
  }
  if (mode === "weekly") {
    const utc = new Date(Date.UTC(parts.year, parts.month - 1, parts.day));
    const weekday = utc.getUTCDay();
    const delta = weekday === 0 ? 6 : weekday - 1;
    utc.setUTCDate(utc.getUTCDate() - delta);
    const start = utc.toISOString().slice(0, 10);
    return { key: start, kind: "weekly", start };
  }
  return { key: parts.ymd, kind: "daily", start: parts.ymd };
}

export function operationsBucketLabel(bucket, weekOf = "Week of") {
  if (!bucket || bucket.kind === "undated") return "Undated";
  if (bucket.kind === "weekly") return `${weekOf} ${formatDashboardDate(bucket.start)}`;
  if (bucket.kind === "monthly") return formatDashboardDate(bucket.start).replace(/ \d+,/, "");
  return formatDashboardDate(bucket.start);
}

export function groupOperations(rows, groupBy) {
  const ordered = [...(rows || [])].sort((left, right) =>
    String(left?.business_date || "").localeCompare(String(right?.business_date || "")),
  );
  const buckets = [];
  const index = new Map();
  for (const row of ordered) {
    const bucket = operationsBucket(row?.business_date, groupBy);
    let current = index.get(bucket.key);
    if (!current) {
      current = { ...bucket, rows: [] };
      index.set(bucket.key, current);
      buckets.push(current);
    }
    current.rows.push(row);
  }
  return buckets;
}
