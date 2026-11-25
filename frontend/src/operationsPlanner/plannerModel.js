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

function roleKey(role) {
  const key = String(role || "").trim().toLowerCase();
  if (key === "folder") return "fold";
  if (key === "operator") return "wash";
  return key;
}

function rolesMatch(left, right) {
  return roleKey(left) === roleKey(right);
}

function wallClock(total) {
  const minutes = Math.round(Number(total) || 0);
  if (minutes === 24 * 60) return "24:00";
  const wrapped = ((minutes % (24 * 60)) + 24 * 60) % (24 * 60);
  return `${String(Math.floor(wrapped / 60)).padStart(2, "0")}:${String(wrapped % 60).padStart(2, "0")}`;
}

function roundHours(minutes) {
  return Math.round((Number(minutes) || 0) * 10000) / 10000;
}

function sameIdList(left, right) {
  return left.length === right.length && left.every((id, index) => id === right[index]);
}

function mergeIntervals(ranges) {
  const merged = [];
  ranges.filter((range) => range && range[1] > range[0]).sort((a, b) => a[0] - b[0]).forEach(([start, end]) => {
    const last = merged[merged.length - 1];
    if (!last || start > last[1]) merged.push([start, end]);
    else if (end > last[1]) last[1] = end;
  });
  return merged;
}

function intervalMinutes(ranges) {
  return mergeIntervals(ranges).reduce((sum, [start, end]) => sum + (end - start), 0);
}

function shiftWindow(entry) {
  const start = clockMinutes(entry?.start_time);
  let end = clockMinutes(entry?.end_time);
  if (start == null || end == null || start === end) return null;
  if (end <= start) end += 24 * 60;
  return { start, end };
}

function placeOnShift(start, end, shiftStart) {
  let open = start < shiftStart ? start + 24 * 60 : start;
  let close = end;
  while (close <= open) close += 24 * 60;
  return [open, close];
}

function clipToShift(start, end, shift) {
  const [open, close] = placeOnShift(start, end, shift.start);
  const left = Math.max(open, shift.start);
  const right = Math.min(close, shift.end);
  return right > left ? [left, right] : null;
}

function roleSegments(entry, shift) {
  const stored = (entry?.role_assignments || []).filter((item) => item?.role && item.start_time && item.end_time);
  if (stored.length) {
    return stored.map((item) => {
      const start = clockMinutes(item.start_time);
      const end = clockMinutes(item.end_time);
      if (start == null || end == null || start === end) return null;
      const clipped = clipToShift(start, end, shift);
      return clipped ? { role: item.role, start: clipped[0], end: clipped[1] } : null;
    }).filter(Boolean);
  }
  const names = String(entry?.role || "").split(",").map((item) => item.trim()).filter(Boolean);
  return names.map((role) => ({ role, start: shift.start, end: shift.end }));
}

function timedBreakIntervals(entry, shift) {
  const slots = Array.isArray(entry?.break_slots) ? entry.break_slots : [];
  return slots.map((slot) => {
    if (!slot?.start_time || !slot?.end_time) return null;
    const start = clockMinutes(slot.start_time);
    const end = clockMinutes(slot.end_time);
    if (start == null || end == null || start === end) return null;
    return clipToShift(start, end, shift);
  }).filter(Boolean);
}

function declaredBreakMinutes(entry, timedMinutes) {
  const slots = Array.isArray(entry?.break_slots) ? entry.break_slots : [];
  const loose = slots.filter((slot) => !slot?.start_time && Number(slot?.minutes) > 0).map((slot) => Number(slot.minutes));
  const same = loose.length > 1 && loose.every((value) => value === loose[0]);
  const fromSlots = same ? loose[0] : loose.reduce((sum, value) => sum + value, 0);
  return Math.max(Math.max(0, Number(entry?.break_minutes) || 0), timedMinutes, fromSlots);
}

/** One employee's day, split where role or break boundaries change. Untimed breaks stay off the pieces. */
function coverageTimelines(entries, day = null) {
  const groups = new Map();
  for (const entry of entries || []) {
    if (day != null && Number(entry?.day_of_week) !== Number(day)) continue;
    const key = `${Number(entry?.user_id)}|${Number(entry?.day_of_week || 0)}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(entry);
  }
  const timelines = [];
  for (const [key, group] of groups) {
    const shifts = group.map((entry) => ({ entry, ...shiftWindow(entry) })).filter((shift) => shift.start != null);
    shifts.sort((a, b) => a.start - b.start || a.end - b.end);
    const segments = shifts.flatMap((shift) => roleSegments(shift.entry, shift));
    const clusters = [];
    for (const shift of shifts) {
      const last = clusters[clusters.length - 1];
      if (last && shift.start < last.end) {
        last.end = Math.max(last.end, shift.end);
        last.shifts.push(shift);
      } else clusters.push({ start: shift.start, end: shift.end, shifts: [shift] });
    }
    const breakRanges = [];
    const untimed = [];
    for (const cluster of clusters) {
      const perShift = cluster.shifts.map((shift) => ({ shift, ranges: timedBreakIntervals(shift.entry, shift) }));
      const ranges = mergeIntervals(perShift.flatMap((item) => item.ranges));
      const clusterTimed = intervalMinutes(ranges);
      let declared = 0;
      for (const item of perShift) {
        declared = Math.max(declared, declaredBreakMinutes(item.shift.entry, intervalMinutes(item.ranges)));
      }
      const deduction = Math.min(cluster.end - cluster.start, Math.max(clusterTimed, declared));
      if (deduction > clusterTimed) untimed.push({ start: cluster.start, end: cluster.end, minutes: deduction - clusterTimed });
      ranges.forEach(([start, end]) => breakRanges.push([start, end]));
    }
    let shiftMinutes = 0;
    let unallocatedUntimedOnce = 0;
    const points = [...new Set([
      ...shifts.flatMap((shift) => [shift.start, shift.end]),
      ...segments.flatMap((segment) => [segment.start, segment.end]),
      ...breakRanges.flatMap((range) => range),
    ])].sort((a, b) => a - b);
    const pieces = [];
    for (let index = 0; index < points.length - 1; index += 1) {
      const start = points[index];
      const end = points[index + 1];
      if (!shifts.some((shift) => shift.start <= start && shift.end >= end)) continue;
      const roles = [...new Set(segments.filter((segment) => segment.start <= start && segment.end >= end).map((segment) => segment.role))];
      pieces.push({
        start,
        end,
        roles,
        onBreak: breakRanges.some(([open, close]) => open <= start && close >= end),
      });
      shiftMinutes += end - start;
    }
    for (const item of untimed) {
      const keys = new Set();
      for (const piece of pieces) {
        if (piece.onBreak || piece.start < item.start || piece.end > item.end) continue;
        if (piece.roles.length) piece.roles.forEach((role) => keys.add(role));
        else keys.add("");
      }
      item.roles = [...keys];
    }
    const parts = new Map();
    const partFor = (role) => {
      if (!parts.has(role)) parts.set(role, { gross: 0, worked: 0, timedBreak: 0, untimedBreak: 0, unallocatedBreak: 0, net: 0 });
      return parts.get(role);
    };
    for (const piece of pieces) {
      const keys = piece.roles.length ? piece.roles : [""];
      const share = (piece.end - piece.start) / 60 / keys.length;
      for (const role of keys) {
        const row = partFor(role);
        row.gross += share;
        if (piece.onBreak) row.timedBreak += share;
        else row.worked += share;
      }
    }
    for (const item of untimed) {
      const hours = item.minutes / 60;
      const named = item.roles.filter(Boolean);
      if (named.length === 1 && item.roles.length === 1) {
        partFor(named[0]).untimedBreak += hours;
      } else if (named.length > 1) {
        unallocatedUntimedOnce += item.minutes;
        named.forEach((role) => {
          const row = partFor(role);
          row.unallocatedBreak += hours;
          row.severalRoleUntimed = (row.severalRoleUntimed || 0) + hours;
        });
      } else if (named.length === 1) {
        unallocatedUntimedOnce += item.minutes;
        const row = partFor(named[0]);
        row.unallocatedBreak += hours;
        row.openTimeUntimed = (row.openTimeUntimed || 0) + hours;
      } else {
        partFor("").untimedBreak += hours;
      }
    }
    for (const row of parts.values()) row.net = row.worked - row.untimedBreak;
    timelines.push({
      userId: Number(key.split("|")[0]),
      pieces,
      parts,
      shiftHours: shiftMinutes / 60,
      unallocatedUntimedOnce,
      assignedRoles: [...new Set(segments.map((segment) => segment.role))],
    });
  }
  return timelines;
}

/**
 * Available staffing for one role between two clocks.
 * A timed break removes the employee only while it overlaps that role.
 * An untimed break is not given a clock, so it never changes these slices.
 */
export function roleAvailability(entries, role, { day = null, start = 0, end = 24 * 60 } = {}) {
  const events = [];
  for (const timeline of coverageTimelines(entries, day)) {
    for (const piece of timeline.pieces) {
      if (!piece.roles.some((item) => rolesMatch(item, role))) continue;
      const open = Math.max(piece.start, start);
      const close = Math.min(piece.end, end);
      if (close <= open) continue;
      events.push({ userId: timeline.userId, start: open, end: close, onBreak: piece.onBreak });
    }
  }
  const points = [...new Set(events.flatMap((event) => [event.start, event.end]))].sort((a, b) => a - b);
  const raw = [];
  for (let index = 0; index < points.length - 1; index += 1) {
    const open = points[index];
    const close = points[index + 1];
    if (close <= open) continue;
    const covering = events.filter((event) => event.start <= open && event.end >= close);
    const scheduledIds = [...new Set(covering.map((event) => event.userId))].sort((a, b) => a - b);
    const onBreakIds = [...new Set(covering.filter((event) => event.onBreak).map((event) => event.userId))].sort((a, b) => a - b);
    const breakSet = new Set(onBreakIds);
    const availableIds = scheduledIds.filter((id) => !breakSet.has(id));
    if (!scheduledIds.length) continue;
    raw.push({
      start: wallClock(open),
      end: wallClock(close),
      scheduled: scheduledIds.length,
      available: availableIds.length,
      onBreak: onBreakIds.length,
      scheduledIds,
      availableIds,
      onBreakIds,
    });
  }
  const slices = [];
  for (const slice of raw) {
    const last = slices[slices.length - 1];
    if (
      last
      && last.end === slice.start
      && sameIdList(last.scheduledIds, slice.scheduledIds)
      && sameIdList(last.availableIds, slice.availableIds)
      && sameIdList(last.onBreakIds, slice.onBreakIds)
    ) last.end = slice.end;
    else slices.push({ ...slice });
  }
  return slices;
}

/**
 * Gross and net role hours for one day, from the payroll day timeline.
 * Gross is scheduled time on the role. Net subtracts a timed break only where it overlaps that role.
 * An untimed break is subtracted only when the shift has that single role. It is never placed on a clock.
 * Time spent on several roles at once is split across those roles, the same way payroll counts it.
 */
export function roleDayCoverage(entries, role, day) {
  const people = new Set();
  let gross = 0;
  let net = 0;
  let timedBreak = 0;
  let untimed = 0;
  let unallocated = 0;
  let openTime = 0;
  let severalRoles = 0;
  let shared = false;
  for (const timeline of coverageTimelines(entries, day)) {
    const matched = timeline.assignedRoles.find((item) => rolesMatch(item, role));
    if (!matched) continue;
    people.add(timeline.userId);
    const parts = timeline.parts.get(matched);
    if (parts) {
      gross += parts.gross;
      net += parts.net;
      timedBreak += parts.timedBreak;
      untimed += parts.untimedBreak;
      unallocated += parts.unallocatedBreak;
      openTime += parts.openTimeUntimed || 0;
      severalRoles += parts.severalRoleUntimed || 0;
    }
    if (timeline.pieces.some((piece) => piece.roles.length > 1 && piece.roles.some((item) => rolesMatch(item, role)))) shared = true;
  }
  return {
    people: people.size,
    hours: roundHours(gross),
    grossHours: roundHours(gross),
    netHours: roundHours(net),
    timedBreakHours: roundHours(timedBreak),
    untimedHours: roundHours(untimed),
    unallocatedUntimedHours: roundHours(unallocated),
    openTimeUntimedHours: roundHours(openTime),
    severalRoleUntimedHours: roundHours(severalRoles),
    shared,
  };
}

/** Coverage totals beside the existing shift gross, break, and net. This reads those figures and does not change them. */
export function coverageShiftLedger(entries, day) {
  let shiftGross = 0;
  let roleGross = 0;
  let roleNet = 0;
  let noRoleGross = 0;
  let timedBreak = 0;
  let untimedBreak = 0;
  let unallocatedUntimed = 0;
  for (const timeline of coverageTimelines(entries, day)) {
    shiftGross += timeline.shiftHours;
    unallocatedUntimed += timeline.unallocatedUntimedOnce / 60;
    for (const [role, parts] of timeline.parts) {
      timedBreak += parts.timedBreak;
      untimedBreak += parts.untimedBreak;
      if (!role) noRoleGross += parts.gross;
      else {
        roleGross += parts.gross;
        roleNet += parts.net;
      }
    }
  }
  return {
    shiftGross: roundHours(shiftGross),
    roleGross: roundHours(roleGross),
    roleNet: roundHours(roleNet),
    noRoleGross: roundHours(noRoleGross),
    timedBreak: roundHours(timedBreak),
    untimedBreak: roundHours(untimedBreak),
    unallocatedUntimed: roundHours(unallocatedUntimed),
  };
}

function coversRoleInWindow(entry, role, begin, end) {
  const segments = (entry?.role_assignments || []).filter((item) => item?.role && item.start_time && item.end_time);
  const named = segments.filter((item) => rolesMatch(item.role, role));
  if (named.length) return named.some((item) => intervalOverlaps(item.start_time, item.end_time, begin, end));
  if (segments.length) return false;
  const names = String(entry?.role || "").split(",").map((item) => item.trim()).filter(Boolean);
  if (!names.some((item) => rolesMatch(item, role))) return false;
  return intervalOverlaps(entry?.start_time, entry?.end_time, begin, end);
}

/** Required, scheduled, and available counts for one role during one hour. Availability can change inside the hour. */
export function roleCoverage(entries, role, hour, required, day = null) {
  const begin = hour * 60;
  const end = begin + 60;
  const slices = roleAvailability(entries, role, { day, start: begin, end });
  const breaking = new Set(slices.flatMap((slice) => slice.onBreakIds));
  const scheduledIds = new Set(slices.flatMap((slice) => slice.scheduledIds));
  const scheduled = [];
  const onBreak = [];
  for (const entry of entries || []) {
    if (day != null && Number(entry.day_of_week) !== Number(day)) continue;
    if (!scheduledIds.has(Number(entry.user_id)) || !coversRoleInWindow(entry, role, begin, end)) continue;
    scheduled.push(entry);
    if (breaking.has(Number(entry.user_id))) onBreak.push(entry);
  }
  const available = scheduled.filter((entry) => !breaking.has(Number(entry.user_id)));
  const low = slices.length ? Math.min(...slices.map((slice) => slice.available)) : 0;
  const high = slices.length ? Math.max(...slices.map((slice) => slice.available)) : 0;
  const need = required == null || required === "" ? null : Number(required);
  const finite = Number.isFinite(need);
  return {
    hour,
    role,
    scheduled,
    onBreak,
    available,
    slices,
    lowAvailable: low,
    highAvailable: high,
    required: finite ? need : null,
    shortage: finite ? Math.max(0, need - low) : 0,
    surplus: finite ? Math.max(0, low - need) : 0,
  };
}

/** Timed breaks only. Untimed breaks are not placed on a clock. Adjacent slices with the same people are one band. */
export function breakOverlapBands(entries) {
  const pieces = [];
  for (const entry of entries || []) {
    for (const slot of entry.break_slots || []) {
      if (slot?.timed === false || !slot?.start_time || !slot?.end_time) continue;
      const start = clockMinutes(slot.start_time);
      let end = clockMinutes(slot.end_time);
      if (start == null || end == null) continue;
      if (end <= start) end += 24 * 60;
      pieces.push({ user: Number(entry.user_id), start, end });
    }
  }
  const points = [...new Set(pieces.flatMap((piece) => [piece.start, piece.end]))].sort((a, b) => a - b);
  const raw = [];
  for (let index = 0; index < points.length - 1; index += 1) {
    const start = points[index];
    const end = points[index + 1];
    if (end <= start) continue;
    const userIds = [...new Set(
      pieces.filter((piece) => piece.start <= start && piece.end >= end).map((piece) => piece.user),
    )].sort((a, b) => a - b);
    if (!userIds.length) continue;
    raw.push({ start, end, count: userIds.length, userIds });
  }
  const merged = [];
  for (const band of raw) {
    const key = band.userIds.join(",");
    const last = merged[merged.length - 1];
    if (last && last.userIds.join(",") === key && last.end === band.start) last.end = band.end;
    else merged.push({ ...band });
  }
  return merged;
}

export function overlappingBreakCount(entries) {
  return breakOverlapBands(entries).reduce((max, band) => Math.max(max, band.count), 0);
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

/** Scheduled and available employees for a role through the day. A short hour is one where the fewest available people fall below the target. */
export function staffingHours(entries, requirements, role, day) {
  const dayEntries = (entries || []).filter((entry) => Number(entry.day_of_week) === Number(day));
  const rows = [];
  for (let hour = 5; hour <= 22; hour += 1) {
    const required = requirementFor(requirements, role, day, hour);
    const coverage = roleCoverage(dayEntries, role, hour, required, day);
    const scheduledIds = [...new Set(coverage.scheduled.map((entry) => Number(entry.user_id)))];
    const breakIds = new Set(coverage.onBreak.map((entry) => Number(entry.user_id)));
    const working = scheduledIds.filter((id) => !breakIds.has(id));
    const need = coverage.required;
    const low = coverage.lowAvailable;
    let status = "unset";
    if (need != null) {
      if (low < need) status = "short";
      else if (low > need) status = "extra";
      else status = "ok";
    }
    if (!scheduledIds.length && need == null) continue;
    rows.push({
      hour,
      required: need,
      scheduled: scheduledIds.length,
      available: low,
      lowAvailable: low,
      highAvailable: coverage.highAvailable,
      slices: coverage.slices,
      assignments: scheduledIds.length,
      onBreak: scheduledIds.filter((id) => breakIds.has(id)).length,
      status,
      userIds: working,
    });
  }
  return rows;
}

/** People scheduled, on a timed break, and still working, by hour. Untimed breaks are not placed. */
export function breakLoad(entries, day) {
  const dayEntries = (entries || []).filter((entry) => Number(entry.day_of_week) === Number(day));
  const rows = [];
  for (let hour = 5; hour <= 22; hour += 1) {
    const coverage = hourCoverage(dayEntries, hour);
    const scheduled = new Set(coverage.scheduled.map((entry) => Number(entry.user_id)));
    const onBreak = new Set(coverage.onBreak.map((entry) => Number(entry.user_id)));
    if (!scheduled.size && !onBreak.size) continue;
    rows.push({
      hour,
      scheduled: scheduled.size,
      onBreak: onBreak.size,
      working: scheduled.size - onBreak.size,
    });
  }
  return rows;
}

const TASK_MINUTES = 30;

/** A clock position only when the task itself stores a specific time. */
export function taskWindow(task) {
  if (task?.timing_mode !== "specific_time" || !task?.start_time) {
    return { scheduled: false, label: task?.timing_mode && task.timing_mode !== "anytime" ? task.timing_mode : "no clock time" };
  }
  const start = clockMinutes(task.start_time);
  if (start == null) return { scheduled: false, label: "no clock time" };
  const duration = Math.max(15, Number(task.estimated_minutes || task.duration_minutes || TASK_MINUTES));
  return { scheduled: true, start, end: start + duration, label: `${minutesToClock(start)}–${minutesToClock((start + duration) % (24 * 60))}` };
}
