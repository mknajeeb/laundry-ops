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

export const SNAP_MINUTES = 15;

export function snapMinutes(total, step = SNAP_MINUTES) {
  if (!Number.isFinite(total)) return null;
  const snapped = Math.round(total / step) * step;
  return Math.max(0, Math.min(24 * 60, snapped));
}

export function minutesToClock(total) {
  const snapped = snapMinutes(total);
  if (snapped == null) return "";
  const wrapped = snapped % (24 * 60);
  return `${String(Math.floor(wrapped / 60)).padStart(2, "0")}:${String(wrapped % 60).padStart(2, "0")}`;
}

export function pointerToMinutes(clientX, rect, startHour = 6, endHour = 22) {
  if (!rect?.width) return null;
  const span = (endHour - startHour) * 60;
  const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
  return snapMinutes(startHour * 60 + ratio * span);
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

function intervalOverlaps(startText, endText, begin, end) {
  const start = clockMinutes(startText);
  let finish = clockMinutes(endText);
  if (start == null || finish == null) return false;
  if (finish <= start) finish += 24 * 60;
  return start < end && begin < finish;
}

/**
 * Headcount for one role, day, and hour.
 * No matching interval returns null. Null means the hour is not configured.
 * A stored 0 is a real requirement for nobody, and is not the same as null.
 * An older hourly map is used only when this role has no interval rows.
 */
export function requirementFor(requirements, role, day, hour, setting) {
  const rows = (requirements || []).filter((item) => String(item.role || item.role_key || "") === String(role));
  if (rows.length) {
    const begin = hour * 60;
    const end = begin + 60;
    const matches = rows.filter((item) => {
      if (item.day_of_week != null && item.day_of_week !== "" && Number(item.day_of_week) !== Number(day)) return false;
      return intervalOverlaps(item.start_time, item.end_time, begin, end);
    });
    if (!matches.length) return null;
    const count = matches[matches.length - 1].required_headcount;
    if (count == null || count === "") return null;
    const need = Number(count);
    return Number.isFinite(need) ? need : null;
  }
  const hourly = setting?.hourly_headcount?.[hour] ?? setting?.hourly_headcount?.[String(hour)];
  if (hourly == null || hourly === "") return null;
  const need = Number(hourly);
  return Number.isFinite(need) ? need : null;
}

function breakMinutesOf(entry) {
  const slots = (entry?.break_slots || []).filter((slot) => slot?.start_time && slot?.end_time && slot?.timed !== false);
  const timed = slots.reduce((sum, slot) => sum + (spanMinutes(slot.start_time, slot.end_time) || 0), 0);
  const declared = Math.max(0, Number(entry?.break_minutes) || 0);
  return { timed, declared: Math.max(declared, timed) };
}

/**
 * Two hour totals for the same entries.
 * Shift totals add every stored shift. Unique time counts overlapping shifts
 * for the same employee and day once, and one overlap keeps the larger break.
 */
export function scheduleHourReconciliation(entries) {
  const groups = new Map();
  for (const entry of entries || []) {
    const start = clockMinutes(entry.start_time);
    let end = clockMinutes(entry.end_time);
    if (start == null || end == null || start === end) continue;
    if (end <= start) end += 24 * 60;
    const key = `${entry.user_id}:${Number(entry.day_of_week)}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push({ start, end, entry });
  }
  let shiftGross = 0;
  let workedGross = 0;
  let shiftBreak = 0;
  let workedBreak = 0;
  for (const items of groups.values()) {
    for (const item of items) {
      shiftGross += item.end - item.start;
      const breaks = breakMinutesOf(item.entry);
      shiftBreak += breaks.timed || Math.max(0, Number(item.entry.break_minutes) || 0);
    }
    const sorted = [...items].sort((a, b) => a.start - b.start || a.end - b.end);
    const clusters = [];
    for (const item of sorted) {
      const last = clusters[clusters.length - 1];
      if (last && item.start < last.end) {
        last.end = Math.max(last.end, item.end);
        last.items.push(item);
      } else {
        clusters.push({ start: item.start, end: item.end, items: [item] });
      }
    }
    for (const cluster of clusters) {
      const span = cluster.end - cluster.start;
      const timed = Math.max(...cluster.items.map((item) => breakMinutesOf(item.entry).timed));
      const declared = Math.max(...cluster.items.map((item) => breakMinutesOf(item.entry).declared));
      workedGross += span;
      workedBreak += Math.min(span, Math.max(timed, declared));
    }
  }
  const hours = (minutes) => Math.round((minutes / 60) * 10000) / 10000;
  return {
    shiftGross: hours(shiftGross),
    shiftBreak: hours(shiftBreak),
    shiftNet: hours(Math.max(0, shiftGross - shiftBreak)),
    workedGross: hours(workedGross),
    workedBreak: hours(workedBreak),
    workedNet: hours(Math.max(0, workedGross - workedBreak)),
    overlapHours: hours(Math.max(0, shiftGross - workedGross)),
  };
}

/** Timed clock breaks and unscheduled durations are separate. Overlap uses clocks only. */
export function breakAccounting(entries) {
  let timedMinutes = 0;
  let unscheduledMinutes = 0;
  let unscheduledCount = 0;
  for (const entry of entries || []) {
    const slots = (entry.break_slots || []).filter((slot) => slot?.start_time && slot?.end_time && slot?.timed !== false);
    if (slots.length) {
      for (const slot of slots) timedMinutes += spanMinutes(slot.start_time, slot.end_time) || 0;
      continue;
    }
    const minutes = Number(entry.break_minutes) || 0;
    if (minutes > 0) {
      unscheduledMinutes += minutes;
      unscheduledCount += 1;
    }
  }
  return {
    timedHours: timedMinutes / 60,
    unscheduledHours: unscheduledMinutes / 60,
    unscheduledCount,
    overlapKnown: unscheduledCount === 0,
  };
}

/** Required, scheduled, active, and on-break counts for one role during one hour. */
export function roleCoverage(entries, role, hour, required) {
  const begin = hour * 60;
  const end = begin + 60;
  const scheduled = [];
  const onBreak = [];
  for (const entry of entries || []) {
    const segments = (entry.role_assignments || []).filter((item) => item.role === role);
    const covers = segments.length
      ? segments.some((item) => intervalOverlaps(item.start_time, item.end_time, begin, end))
      : entry.role === role && intervalOverlaps(entry.start_time, entry.end_time, begin, end);
    if (!covers) continue;
    scheduled.push(entry);
    const breaking = (entry.break_slots || []).some(
      (slot) => slot?.timed !== false && intervalOverlaps(slot.start_time, slot.end_time, begin, end),
    );
    if (breaking) onBreak.push(entry);
  }
  const breakIds = new Set(onBreak.map((entry) => entry.user_id));
  const available = scheduled.filter((entry) => !breakIds.has(entry.user_id));
  const need = required == null || required === "" ? null : Number(required);
  return {
    hour,
    role,
    scheduled,
    onBreak,
    available,
    required: Number.isFinite(need) ? need : null,
    shortage: Number.isFinite(need) ? Math.max(0, need - available.length) : 0,
    surplus: Number.isFinite(need) ? Math.max(0, available.length - need) : 0,
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
    const buckets = members.map((member) => taskBucket(member.activity_status || member.status));
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
