/** Period math and coverage for the Operations Planner. Times are Eastern wall clocks. */

export const DAY_ORDER = [1, 2, 3, 4, 5, 6, 0];
export const DAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
export const BREAK_OVERLAP_CAP = 3;

export function clockMinutes(value) {
  const text = String(value || "").slice(0, 5);
  const match = /^(\d{2}):(\d{2})$/.exec(text);
  if (!match) return null;
  const hour = Number(match[1]);
  const minute = Number(match[2]);
  if (hour > 23 || minute > 59) return null;
  return hour * 60 + minute;
}

export function spanMinutes(start, end) {
  const begin = clockMinutes(start);
  const finish = clockMinutes(end);
  if (begin == null || finish == null || begin === finish) return null;
  return (finish <= begin ? finish + 24 * 60 : finish) - begin;
}

export function addMinutes(start, minutes) {
  const begin = clockMinutes(start);
  if (begin == null) return start;
  const total = (begin + minutes) % (24 * 60);
  const hour = Math.floor(total / 60);
  const minute = total % 60;
  return `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
}

export function shiftHours(shift) {
  const grossMin = spanMinutes(shift?.start_time, shift?.end_time) || 0;
  const slots = Array.isArray(shift?.break_slots) ? shift.break_slots : [];
  let timedMin = 0;
  if (!slots.length) timedMin = Math.max(0, Number(shift?.break_minutes) || 0);
  for (const slot of slots) {
    if (slot?.timed === false) continue;
    timedMin += spanMinutes(slot.start_time, slot.end_time) || 0;
  }
  return {
    gross: Math.round((grossMin / 60) * 10000) / 10000,
    net: Math.round((Math.max(0, grossMin - timedMin) / 60) * 10000) / 10000,
    timedBreak: Math.round((timedMin / 60) * 10000) / 10000,
  };
}

/** Moving a shift keeps its length. */
export function movedShift(shift, { dayOfWeek = shift.day_of_week, startTime = shift.start_time } = {}) {
  const duration = spanMinutes(shift.start_time, shift.end_time);
  const start = startTime || shift.start_time;
  return {
    ...shift,
    day_of_week: dayOfWeek,
    start_time: start,
    end_time: duration == null ? shift.end_time : addMinutes(start, duration),
  };
}

export function entriesForPeriod(entries, { mode, day }) {
  if (mode !== "day") return entries || [];
  return (entries || []).filter((entry) => Number(entry.day_of_week) === Number(day));
}

export function hourCoverage(entries, hour) {
  const begin = hour * 60;
  const end = begin + 60;
  const scheduled = [];
  const onBreak = [];
  for (const entry of entries || []) {
    const start = clockMinutes(entry.start_time);
    let finish = clockMinutes(entry.end_time);
    if (start == null || finish == null) continue;
    if (finish <= start) finish += 24 * 60;
    if (start >= end || finish <= begin) continue;
    scheduled.push(entry);
    const timed = (entry.break_slots || []).some((slot) => {
      if (slot?.timed === false) return false;
      const slotStart = clockMinutes(slot.start_time);
      let slotEnd = clockMinutes(slot.end_time);
      if (slotStart == null || slotEnd == null) return false;
      if (slotEnd <= slotStart) slotEnd += 24 * 60;
      return slotStart < end && begin < slotEnd;
    });
    if (timed) onBreak.push(entry);
  }
  const breakIds = new Set(onBreak.map((entry) => entry.user_id));
  return {
    hour,
    scheduled,
    onBreak,
    available: scheduled.filter((entry) => !breakIds.has(entry.user_id)),
  };
}

export function overlappingBreakCount(entries) {
  const pieces = [];
  for (const entry of entries || []) {
    for (const slot of entry.break_slots || []) {
      if (slot?.timed === false) continue;
      const start = clockMinutes(slot.start_time);
      let end = clockMinutes(slot.end_time);
      if (start == null || end == null) continue;
      if (end <= start) end += 24 * 60;
      pieces.push({ user: entry.user_id, start, end });
    }
  }
  const points = [...new Set(pieces.flatMap((piece) => [piece.start, piece.end]))].sort((a, b) => a - b);
  let max = 0;
  for (let index = 0; index < points.length - 1; index += 1) {
    const left = points[index];
    const right = points[index + 1];
    const users = new Set(
      pieces.filter((piece) => piece.start <= left && piece.end >= right).map((piece) => piece.user),
    );
    max = Math.max(max, users.size);
  }
  return max;
}

function taskBucket(status) {
  const value = String(status || "");
  if (value === "pending_approval") return "awaiting";
  if (value === "approved") return "verified";
  if (value === "completed") return "completed";
  if (value === "in_progress") return "inProgress";
  return "pending";
}

/** A shared activity group counts once. Each employee still has their own row. */
export function taskRollup(responsibilities) {
  const groups = new Map();
  for (const row of responsibilities || []) {
    const key = row.assignment_group_id || `solo:${row.id || `${row.user_id}:${row.role}`}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(row);
  }
  const counts = { pending: 0, inProgress: 0, awaiting: 0, verified: 0, completed: 0, total: 0 };
  const people = { pending: 0, inProgress: 0, awaiting: 0, verified: 0, completed: 0, total: 0 };
  for (const members of groups.values()) {
    const buckets = members.map((member) => taskBucket(member.status));
    let bucket = "pending";
    if (buckets.includes("inProgress")) bucket = "inProgress";
    else if (buckets.includes("awaiting")) bucket = "awaiting";
    else if (buckets.every((item) => item === "verified")) bucket = "verified";
    else if (buckets.every((item) => item === "verified" || item === "completed")) bucket = "completed";
    counts[bucket] += 1;
    counts.total += 1;
    for (const item of buckets) {
      people[item] += 1;
      people.total += 1;
    }
  }
  return { groups: groups.size, counts, people };
}

export function placePopover(anchor, size, viewport) {
  const margin = 8;
  let top = anchor.bottom + margin;
  let left = anchor.left;
  if (top + size.height > viewport.height - margin) top = Math.max(margin, anchor.top - size.height - margin);
  if (left + size.width > viewport.width - margin) left = Math.max(margin, viewport.width - size.width - margin);
  if (left < margin) left = margin;
  if (top < margin) top = margin;
  return { top, left };
}

export function autoScrollDelta(pointerY, rect, edge = 48) {
  if (pointerY < rect.top + edge) return -20;
  if (pointerY > rect.bottom - edge) return 20;
  return 0;
}

export function periodLabel(mode, weekLabel, dayName) {
  return mode === "day" ? dayName : weekLabel;
}
