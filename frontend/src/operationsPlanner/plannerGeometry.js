import { clockMinutes, minutesToClock, shiftHours, spanMinutes } from "./plannerModel";

export function asList(value) {
  if (Array.isArray(value)) return value;
  if (typeof value === "string" && value.trim().startsWith("[")) {
    try {
      const parsed = JSON.parse(value);
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  }
  return [];
}

/** Segments a manager actually stored. A full-shift placeholder is not a split. */
export function storedRoleSegments(entry) {
  const explicit = entry?.role_assignments;
  const source = Array.isArray(explicit) || (typeof explicit === "string" && explicit.trim().startsWith("["))
    ? explicit
    : entry?.assignments;
  return asList(source).filter((item) => item && item.full_shift !== true && item.role);
}

export function shiftKey(entry) {
  return String(entry?.id ?? `${entry?.user_id}-${entry?.day_of_week}-${entry?.start_time}`);
}

function persistentId(entry) {
  const id = Number(entry?.id);
  return Number.isInteger(id) && id > 0 ? id : null;
}

function stamp(entry) {
  return JSON.stringify({
    user_id: Number(entry?.user_id),
    day_of_week: Number(entry?.day_of_week),
    start_time: String(entry?.start_time || "").slice(0, 5),
    end_time: String(entry?.end_time || "").slice(0, 5),
    role: entry?.role || "",
    break_minutes: Number(entry?.break_minutes || 0),
    break_slots: asList(entry?.break_slots),
    role_assignments: storedRoleSegments(entry),
  });
}

/** Additions, changes, and removals between the saved week and the draft. */
export function draftOperations(before, after) {
  const prior = new Map((before || []).map((entry) => [shiftKey(entry), entry]));
  const next = new Map((after || []).map((entry) => [shiftKey(entry), entry]));
  const operations = [];
  for (const [key, entry] of next) {
    const id = persistentId(entry);
    const saved = prior.get(key);
    if (!saved || !id) {
      operations.push({ op: "create", user_id: Number(entry.user_id), day_of_week: Number(entry.day_of_week), shift: entry });
    } else if (stamp(saved) !== stamp(entry)) {
      operations.push({ op: "update", id, user_id: Number(entry.user_id), day_of_week: Number(entry.day_of_week), shift: entry });
    }
  }
  for (const [key, entry] of prior) {
    if (next.has(key)) continue;
    const id = persistentId(entry);
    if (id) operations.push({ op: "delete", id, user_id: Number(entry.user_id), day_of_week: Number(entry.day_of_week) });
  }
  return operations;
}

function clipSegments(entry, from, to) {
  return storedRoleSegments(entry).flatMap((segment) => {
    let start = clockMinutes(segment.start_time);
    let end = clockMinutes(segment.end_time);
    if (start == null || end == null) return [];
    if (end <= start) end += 24 * 60;
    const left = Math.max(start, from);
    const right = Math.min(end, to);
    if (right - left < 1) return [];
    return [{
      role: segment.role,
      start_time: minutesToClock(left % (24 * 60)),
      end_time: minutesToClock(right % (24 * 60)),
    }];
  });
}

function slotsInside(entry, from, to) {
  return asList(entry?.break_slots).filter((slot) => {
    const start = clockMinutes(slot?.start_time);
    let end = clockMinutes(slot?.end_time);
    if (start == null || end == null) return false;
    if (end <= start) end += 24 * 60;
    return start >= from && end <= to;
  });
}

/** Two independent halves. The caller gives the second half its own draft id. */
export function splitHalves(entry) {
  const start = clockMinutes(entry?.start_time);
  let end = clockMinutes(entry?.end_time);
  if (start == null || end == null) return null;
  if (end <= start) end += 24 * 60;
  if (end - start < 30) return null;
  const midTotal = Math.round((start + (end - start) / 2) / 15) * 15;
  if (midTotal <= start || midTotal >= end) return null;
  const mid = minutesToClock(midTotal % (24 * 60));
  const timed = asList(entry?.break_slots).some((slot) => slot?.start_time && slot?.end_time && slot?.timed !== false);
  const firstSegments = clipSegments(entry, start, midTotal);
  const secondSegments = clipSegments(entry, midTotal, end);
  const roleFor = (segments) => {
    const roles = [];
    for (const segment of segments) {
      if (segment.role && !roles.includes(segment.role)) roles.push(segment.role);
    }
    return roles.length ? roles.join(",") : (entry.role || "");
  };
  const first = {
    ...entry,
    end_time: mid,
    role: roleFor(firstSegments),
    role_assignments: firstSegments,
    break_slots: slotsInside(entry, start, midTotal),
    break_minutes: timed ? 0 : Number(entry?.break_minutes || 0),
  };
  const second = {
    ...entry,
    start_time: mid,
    role: roleFor(secondSegments),
    role_assignments: secondSegments,
    break_slots: slotsInside(entry, midTotal, end),
    break_minutes: 0,
  };
  delete second.id;
  return { first, second };
}

/** Axis includes early-morning shifts. The old lane started at 06:00 and clipped them. */
export function timelineAxis(entries) {
  let min = 6 * 60;
  let max = 22 * 60;
  for (const entry of entries || []) {
    const start = clockMinutes(entry.start_time);
    let end = clockMinutes(entry.end_time);
    if (start == null || end == null) continue;
    if (end <= start) end += 24 * 60;
    min = Math.min(min, start);
    max = Math.max(max, end);
  }
  const startMin = Math.floor(min / 60) * 60;
  const endMin = Math.max(startMin + 60, Math.ceil(max / 60) * 60);
  return { startMin, endMin, span: endMin - startMin };
}

export function barBox(start, end, axis) {
  const begin = clockMinutes(start);
  let finish = clockMinutes(end);
  if (begin == null || finish == null || !axis?.span) return { left: "0%", width: "0%" };
  if (finish <= begin) finish += 24 * 60;
  const left = ((begin - axis.startMin) / axis.span) * 100;
  const width = ((finish - begin) / axis.span) * 100;
  return { left: `${Math.max(0, left)}%`, width: `${Math.max(1.5, Math.min(100, width))}%` };
}

export function pieceBox(shift, piece) {
  const open = clockMinutes(shift.start_time);
  let close = clockMinutes(shift.end_time);
  const begin = clockMinutes(piece.start_time);
  let finish = clockMinutes(piece.end_time);
  if (open == null || close == null || begin == null || finish == null || close === open) return { left: "0%", width: "0%" };
  if (close <= open) close += 24 * 60;
  if (finish <= begin) finish += 24 * 60;
  return {
    left: `${Math.max(0, ((begin - open) / (close - open)) * 100)}%`,
    width: `${Math.max(6, ((finish - begin) / (close - open)) * 100)}%`,
  };
}

/**
 * Display pieces only. A gap between stored segments keeps the shift's own role
 * string, including a combined label. It is not assigned to the first role.
 */
export function visualPieces(entry) {
  const start = clockMinutes(entry?.start_time);
  let end = clockMinutes(entry?.end_time);
  if (start == null || end == null) return [];
  if (end <= start) end += 24 * 60;
  const label = String(entry?.role || "").trim();
  const assigned = asList(entry?.role_assignments).map((segment) => {
    const segStart = clockMinutes(segment.start_time);
    let segEnd = clockMinutes(segment.end_time);
    if (segStart == null || segEnd == null) return null;
    if (segEnd <= segStart) segEnd += 24 * 60;
    return { role: segment.role || label, start: segStart, end: segEnd, allocated: true };
  }).filter(Boolean).sort((a, b) => a.start - b.start);
  if (!assigned.length) return [{ role: label, start, end, allocated: false }];
  const pieces = [];
  let cursor = start;
  for (const segment of assigned) {
    if (segment.start > cursor + 1) pieces.push({ role: label, start: cursor, end: segment.start, allocated: false });
    pieces.push(segment);
    cursor = Math.max(cursor, segment.end);
  }
  if (end > cursor + 1) pieces.push({ role: label, start: cursor, end, allocated: false });
  return pieces;
}

/** Stored segments only. A missing list stays missing; the display label is not written back. */
export function storedSegments(entry) {
  return asList(entry?.role_assignments).map((segment) => ({
    role: segment.role,
    start_time: String(segment.start_time || "").slice(0, 5),
    end_time: String(segment.end_time || "").slice(0, 5),
  }));
}

export function displaySegments(entry) {
  const assigned = asList(entry?.role_assignments);
  if (assigned.length) {
    return assigned.map((segment) => ({
      role: segment.role || "Unassigned",
      start_time: String(segment.start_time || entry.start_time).slice(0, 5),
      end_time: String(segment.end_time || entry.end_time).slice(0, 5),
      allocated: true,
    }));
  }
  const label = String(entry?.role || "").trim();
  return [{
    role: label || "No role segments",
    start_time: String(entry?.start_time || "").slice(0, 5),
    end_time: String(entry?.end_time || "").slice(0, 5),
    allocated: false,
  }];
}

/** Timed slots stay on the clock. break_minutes alone is an unscheduled duration, not a guessed time. */
export function visibleBreaks(entry) {
  const slots = asList(entry?.break_slots).filter((slot) => slot?.start_time && slot?.end_time);
  if (slots.length) {
    return slots.map((slot) => ({
      start_time: String(slot.start_time).slice(0, 5),
      end_time: String(slot.end_time).slice(0, 5),
      timed: slot.timed !== false,
      unscheduled: false,
    }));
  }
  const minutes = Number(entry?.break_minutes) || 0;
  if (!minutes) return [];
  return [{ unscheduled: true, minutes, timed: false }];
}

function clockOf(total) {
  return minutesToClock(total);
}

/**
 * One row per stored role segment, with its own start and end.
 * A gap that is not a timed break stays "not split" instead of borrowing the combined role name.
 * A combined role with no stored split lists each name and does not invent a time for each name.
 */
export function scheduleCardRows(entry) {
  const breaks = new Set(visibleBreaks(entry).filter((slot) => slot.start_time).map((slot) => `${slot.start_time}-${slot.end_time}`));
  const stored = asList(entry?.role_assignments).length ? displaySegments(entry).filter((segment) => segment.allocated) : [];
  if (stored.length) {
    const gaps = visualPieces(entry).filter((piece) => !piece.allocated).map((piece) => {
      const start = clockOf(piece.start);
      const end = clockOf(piece.end);
      return { role: "", start_time: start, end_time: end, allocated: false, unsplit: true };
    }).filter((row) => row.start_time && row.end_time && !breaks.has(`${row.start_time}-${row.end_time}`));
    return [...stored.map((segment) => ({
      role: segment.role,
      start_time: segment.start_time,
      end_time: segment.end_time,
      allocated: true,
      unsplit: false,
    })), ...gaps].sort((a, b) => String(a.start_time).localeCompare(String(b.start_time)));
  }
  const codes = String(entry?.role || "").split(",").map((part) => part.trim()).filter(Boolean);
  if (codes.length <= 1) {
    return [{
      role: codes[0] || "",
      start_time: String(entry?.start_time || "").slice(0, 5),
      end_time: String(entry?.end_time || "").slice(0, 5),
      allocated: false,
      unsplit: !codes.length,
    }];
  }
  return codes.map((role) => ({ role, start_time: "", end_time: "", allocated: false, unsplit: true }));
}

function mergedRoleHours(pieces) {
  const byUser = new Map();
  pieces.forEach(([userId, start, end]) => {
    const list = byUser.get(userId) || [];
    list.push([start, end]);
    byUser.set(userId, list);
  });
  let minutes = 0;
  byUser.forEach((list) => {
    list.sort((a, b) => a[0] - b[0]);
    let cursor = null;
    list.forEach(([start, end]) => {
      if (!cursor || start > cursor[1]) {
        if (cursor) minutes += cursor[1] - cursor[0];
        cursor = [start, end];
      } else if (end > cursor[1]) cursor[1] = end;
    });
    if (cursor) minutes += cursor[1] - cursor[0];
  });
  return minutes / 60;
}

/** Day totals from the shifts on that day. Role hours follow stored segments. Gross and net stay on shiftHours. */
export function dayScheduleSummary(entries, day) {
  const shifts = (entries || []).filter((entry) => Number(entry.day_of_week) === Number(day));
  const roles = {};
  const rolePeople = {};
  const rolePieces = {};
  let gross = 0;
  let net = 0;
  function countPerson(role, userId) {
    if (!role) return;
    rolePeople[role] = rolePeople[role] || new Set();
    rolePeople[role].add(Number(userId));
  }
  for (const entry of shifts) {
    const hours = shiftHours(entry);
    gross += hours.gross;
    net += hours.net;
    const rows = scheduleCardRows(entry);
    let namedUnsplit = false;
    for (const row of rows) {
      if (row.allocated && row.role && row.start_time) {
        const start = clockMinutes(row.start_time);
        let end = clockMinutes(row.end_time);
        if (start == null || end == null) continue;
        if (end <= start) end += 24 * 60;
        countPerson(row.role, entry.user_id);
        rolePieces[row.role] = rolePieces[row.role] || [];
        rolePieces[row.role].push([Number(entry.user_id), start, end]);
      } else if (row.unsplit && row.start_time) {
        roles.unsplit = (roles.unsplit || 0) + ((spanMinutes(row.start_time, row.end_time) || 0) / 60);
        countPerson("unsplit", entry.user_id);
      } else if (!row.unsplit && row.role) {
        roles[row.role] = (roles[row.role] || 0) + hours.gross;
        countPerson(row.role, entry.user_id);
      } else if (row.unsplit && row.role) {
        countPerson(row.role, entry.user_id);
        if (!namedUnsplit) {
          roles.unsplit = (roles.unsplit || 0) + hours.gross;
          countPerson("unsplit", entry.user_id);
          namedUnsplit = true;
        }
      } else if (row.unsplit && !namedUnsplit) {
        roles.unsplit = (roles.unsplit || 0) + hours.gross;
        countPerson("unsplit", entry.user_id);
        namedUnsplit = true;
      }
    }
  }
  Object.entries(rolePieces).forEach(([role, pieces]) => {
    roles[role] = (roles[role] || 0) + mergedRoleHours(pieces);
  });
  const roleCounts = {};
  Object.entries(rolePeople).forEach(([role, people]) => {
    roleCounts[role] = people.size;
  });
  return {
    people: new Set(shifts.map((entry) => Number(entry.user_id))).size,
    shifts: shifts.length,
    gross,
    net,
    roles,
    roleCounts,
  };
}

function shiftClock(start, delta) {
  const begin = clockMinutes(start);
  if (begin == null) return start;
  const total = ((begin + delta) % (24 * 60) + 24 * 60) % (24 * 60);
  return minutesToClock(total);
}

export function relocateShift(entry, startTime, dayOfWeek = entry.day_of_week) {
  const nextStart = minutesToClock(clockMinutes(startTime));
  const delta = (clockMinutes(nextStart) ?? 0) - (clockMinutes(entry.start_time) ?? 0);
  const duration = spanMinutes(entry.start_time, entry.end_time);
  const next = {
    ...entry,
    day_of_week: dayOfWeek,
    start_time: nextStart || entry.start_time,
    end_time: duration == null ? entry.end_time : shiftClock(entry.start_time, duration + delta),
  };
  if (asList(entry.role_assignments).length) {
    next.role_assignments = storedSegments(entry).map((segment) => ({
      role: segment.role,
      start_time: shiftClock(segment.start_time, delta),
      end_time: shiftClock(segment.end_time, delta),
    }));
  }
  const slots = asList(entry.break_slots).filter((slot) => slot?.start_time && slot?.end_time);
  if (slots.length) {
    next.break_slots = slots.map((slot) => ({
      start_time: shiftClock(slot.start_time, delta),
      end_time: shiftClock(slot.end_time, delta),
      timed: slot.timed !== false,
    }));
  }
  return next;
}

export function resizeEdge(entry, edge, minutes) {
  const clock = minutesToClock(minutes);
  if (!clock) return entry;
  const next = { ...entry, [edge === "end" ? "end_time" : "start_time"]: clock };
  const segments = storedSegments(entry);
  if (segments.length) {
    if (edge === "start") segments[0] = { ...segments[0], start_time: clock };
    else segments[segments.length - 1] = { ...segments[segments.length - 1], end_time: clock };
    next.role_assignments = segments;
  }
  return next;
}

export function resizeSegment(entry, index, edge, minutes) {
  const clock = minutesToClock(minutes);
  const segments = storedSegments(entry);
  if (!clock || !segments[index]) return entry;
  const key = edge === "end" ? "end_time" : "start_time";
  segments[index] = { ...segments[index], [key]: clock };
  const next = { ...entry, role_assignments: segments };
  if (index === 0 && key === "start_time") next.start_time = clock;
  if (index === segments.length - 1 && key === "end_time") next.end_time = clock;
  return next;
}

export function resizeBreak(entry, index, edge, minutes) {
  const clock = minutesToClock(minutes);
  const slots = asList(entry?.break_slots)
    .filter((slot) => slot?.start_time && slot?.end_time)
    .map((slot) => ({
      start_time: String(slot.start_time).slice(0, 5),
      end_time: String(slot.end_time).slice(0, 5),
      timed: slot.timed !== false,
    }));
  if (!clock || !slots[index]) return entry;
  slots[index] = { ...slots[index], [edge === "end" ? "end_time" : "start_time"]: clock, timed: true };
  const breakMinutes = slots.reduce((sum, slot) => sum + (spanMinutes(slot.start_time, slot.end_time) || 0), 0);
  return { ...entry, break_slots: slots, break_minutes: breakMinutes };
}

/** Take the clock off a break and keep its duration. The break is not given a guessed time. */
export function unscheduleBreak(entry) {
  const slots = asList(entry?.break_slots).filter((slot) => slot?.start_time && slot?.end_time);
  const timed = slots.reduce((sum, slot) => sum + (spanMinutes(slot.start_time, slot.end_time) || 0), 0);
  const minutes = Math.max(Number(entry?.break_minutes) || 0, timed);
  return { ...entry, break_slots: [], break_minutes: minutes };
}

/**
 * Add a timed role segment the manager named.
 * A combined role with no stored split is left unchanged so hours are not assigned to the first role.
 */
export function addRoleSegment(entry, role, start, end) {
  const name = String(role || "").trim();
  const startTime = String(start || "").slice(0, 5);
  const endTime = String(end || "").slice(0, 5);
  if (!name || !spanMinutes(startTime, endTime)) return entry;
  if (String(entry?.role || "").includes(",") && !storedRoleSegments(entry).length) return entry;
  return {
    ...entry,
    role_assignments: [...storedRoleSegments(entry), { role: name, start_time: startTime, end_time: endTime }],
  };
}

export function removeRoleSegment(entry, index) {
  const segments = storedRoleSegments(entry).filter((_, itemIndex) => itemIndex !== index);
  return { ...entry, role_assignments: segments };
}

/** A manager placing both ends creates a timed break. An empty field does not invent one. */
export function placeBreak(entry, start, end) {
  const startTime = String(start || "").slice(0, 5);
  const endTime = String(end || "").slice(0, 5);
  if (!/^\d{2}:\d{2}$/.test(startTime) || !/^\d{2}:\d{2}$/.test(endTime)) return entry;
  const minutes = spanMinutes(startTime, endTime);
  if (!minutes) return entry;
  return {
    ...entry,
    break_slots: [{ start_time: startTime, end_time: endTime, timed: true }],
    break_minutes: minutes,
  };
}

export const ROLE_COLOR = {
  wash: "#1d4e89",
  fold: "#0e7c66",
  sort: "#8a5a12",
  weigher: "#5b4b8a",
  attendant: "#9a3412",
  hd_operator: "#3730a3",
  hd_folder: "#3f6212",
  dry: "#0e7490",
  "wash,attendant": "#0f4c5c",
  "fold,attendant": "#3e4c59",
};

export function roleColor(role) {
  const key = String(role || "").trim();
  if (ROLE_COLOR[key]) return ROLE_COLOR[key];
  if (key.includes(",")) return "#3e4c59";
  return "#334155";
}
