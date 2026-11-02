/** Minutes on the clock that no role segment and no completed break covers.

Payable hours stay clock span minus breaks. A gap here is still paid; the role
rows alone will not add up to the hours column until this time is shown.
*/

function wallEpochMs(value) {
  const m = String(value ?? "")
    .trim()
    .match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?/);
  if (!m) return null;
  return Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +(m[6] || 0));
}

function mergeIntervals(intervals) {
  const sorted = intervals
    .filter(([a, b]) => a != null && b != null && b > a)
    .sort((x, y) => x[0] - y[0]);
  const out = [];
  for (const [start, end] of sorted) {
    const last = out[out.length - 1];
    if (!last || start > last[1]) out.push([start, end]);
    else last[1] = Math.max(last[1], end);
  }
  return out;
}

export function onClockUnassignedSeconds(record) {
  const segments = Array.isArray(record?.role_segments) ? record.role_segments : [];
  if (!segments.length) return 0;
  const start = wallEpochMs(record?.clock_in_at);
  const end = wallEpochMs(record?.clock_out_at);
  if (start == null || end == null || end <= start) return 0;

  const covered = [];
  for (const seg of segments) {
    covered.push([wallEpochMs(seg.started_at), wallEpochMs(seg.ended_at)]);
  }
  for (const br of record?.breaks || []) {
    if (String(br?.status || "") === "open") continue;
    covered.push([wallEpochMs(br.break_start_at), wallEpochMs(br.break_end_at)]);
  }
  let cursor = start;
  let uncovered = 0;
  for (const [a, b] of mergeIntervals(covered)) {
    const from = Math.max(a, start);
    const to = Math.min(b, end);
    if (from > cursor) uncovered += from - cursor;
    if (to > cursor) cursor = to;
  }
  if (end > cursor) uncovered += end - cursor;
  return Math.round(uncovered / 1000);
}

export function formatOnClockUnassignedNote(record) {
  const seconds = onClockUnassignedSeconds(record);
  if (seconds < 60) return "";
  const minutes = Math.round(seconds / 60);
  return `Includes ${minutes} min on the clock with no role`;
}
