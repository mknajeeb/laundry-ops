import { clockMinutes, minutesToClock, spanMinutes } from "./plannerModel";

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

/**
 * The schedule the server will still show after a save.
 * One role that fills the envelope is stored on the shift itself, so the
 * segment list comes back empty and the role plus its times are the schedule.
 */
export function persistedRoleSignature(entry) {
  const stored = storedRoleSegments(entry);
  if (stored.length) {
    return stored
      .map((item) => `${item.role}@${String(item.start_time || "").slice(0, 5)}-${String(item.end_time || "").slice(0, 5)}`)
      .sort()
      .join("|");
  }
  const role = String(entry?.role || "").trim();
  const start = String(entry?.start_time || "").slice(0, 5);
  const end = String(entry?.end_time || "").slice(0, 5);
  if (role && !role.includes(",") && start && end) return `${role}@${start}-${end}`;
  return role;
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
  const label = String(entry?.role || "").trim();
  const assigned = storedRoleSegments(entry).map((segment) => {
    const segStart = clockMinutes(segment.start_time);
    let segEnd = clockMinutes(segment.end_time);
    if (segStart == null || segEnd == null) return null;
    if (segEnd <= segStart) segEnd += 24 * 60;
    return { role: segment.role || label, start: segStart, end: segEnd, allocated: true };
  }).filter(Boolean).sort((a, b) => a.start - b.start);
  if (assigned.length) return assigned;
  const start = clockMinutes(entry?.start_time);
  let end = clockMinutes(entry?.end_time);
  if (start == null || end == null) return [];
  if (end <= start) end += 24 * 60;
  return [{ role: label || "Unassigned", start, end, allocated: false }];
}

function mergeRanges(ranges) {
  const merged = [];
  ranges.filter((range) => range && range[1] > range[0]).sort((a, b) => a[0] - b[0]).forEach(([start, end]) => {
    const last = merged[merged.length - 1];
    if (!last || start > last[1]) merged.push([start, end]);
    else if (end > last[1]) last[1] = end;
  });
  return merged;
}

function rangeMinutes(ranges) {
  return mergeRanges(ranges).reduce((sum, [start, end]) => sum + (end - start), 0);
}

/** Role intervals are the schedule. A legacy row with no stored split uses its one span. */
export function roleIntervals(entry) {
  const pieces = [];
  storedRoleSegments(entry).forEach((segment) => {
    const start = clockMinutes(segment.start_time);
    let end = clockMinutes(segment.end_time);
    if (start == null || end == null || start === end) return;
    if (end <= start) end += 24 * 60;
    pieces.push([start, end]);
  });
  if (pieces.length) return pieces;
  const start = clockMinutes(entry?.start_time);
  let end = clockMinutes(entry?.end_time);
  if (start == null || end == null || start === end) return [];
  if (end <= start) end += 24 * 60;
  return [[start, end]];
}

function breakCutMinutes(entries, intervals) {
  const timed = [];
  let untimed = 0;
  let sawTimed = false;
  entries.forEach((entry) => {
    const slots = visibleBreaks(entry).filter((slot) => slot.start_time);
    if (slots.length) {
      sawTimed = true;
      slots.forEach((slot) => {
        const start = clockMinutes(slot.start_time);
        let end = clockMinutes(slot.end_time);
        if (start == null || end == null || start === end) return;
        if (end <= start) end += 24 * 60;
        timed.push([start, end]);
      });
      return;
    }
    untimed = Math.max(untimed, Math.max(0, Number(entry?.break_minutes) || 0));
  });
  const work = mergeRanges(intervals);
  const offs = mergeRanges(timed);
  let cut = 0;
  work.forEach(([start, end]) => {
    offs.forEach(([breakStart, breakEnd]) => {
      const left = Math.max(start, breakStart);
      const right = Math.min(end, breakEnd);
      if (right > left) cut += right - left;
    });
  });
  if (!sawTimed) cut += untimed;
  return Math.min(rangeMinutes(work), cut);
}

/**
 * Gross is the union of role intervals for each employee and day.
 * A timed break is removed only where it overlaps that union, and only once.
 * The stored shift start and end are not added on top.
 */
export function scheduledRoleHours(entries) {
  const list = Array.isArray(entries) ? entries : [entries];
  const groups = new Map();
  list.forEach((entry) => {
    const key = `${entry?.user_id}:${Number(entry?.day_of_week)}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(entry);
  });
  let grossMin = 0;
  let breakMin = 0;
  groups.forEach((group) => {
    const intervals = group.flatMap((entry) => roleIntervals(entry));
    const gross = rangeMinutes(intervals);
    grossMin += gross;
    breakMin += breakCutMinutes(group, intervals);
  });
  const round = (minutes) => Math.round((minutes / 60) * 10000) / 10000;
  return {
    gross: round(grossMin),
    net: round(Math.max(0, grossMin - breakMin)),
    timedBreak: round(breakMin),
  };
}

function clockRange(start, end) {
  const open = clockMinutes(start);
  let close = clockMinutes(end);
  if (open == null || close == null || open === close) return null;
  if (close <= open) close += 24 * 60;
  return [open, close];
}

function allocatedRanges(entry) {
  const pieces = [];
  storedRoleSegments(entry).forEach((segment) => {
    const span = clockRange(segment.start_time, segment.end_time);
    if (span) pieces.push(span);
  });
  if (pieces.length) return pieces;
  const role = String(entry?.role || "").trim();
  const span = clockRange(entry?.start_time, entry?.end_time);
  if (role && span) return [span];
  return [];
}

function subtractRanges(spans, covered) {
  let free = mergeRanges(spans).map((span) => [...span]);
  mergeRanges(covered).forEach(([cutStart, cutEnd]) => {
    const next = [];
    free.forEach(([start, end]) => {
      if (cutEnd <= start || cutStart >= end) next.push([start, end]);
      else {
        if (cutStart > start) next.push([start, cutStart]);
        if (cutEnd < end) next.push([cutEnd, end]);
      }
    });
    free = next;
  });
  return free;
}

function rangesOverlap(left, right) {
  if (!left || !right) return true;
  return left[0] < right[1] && right[0] < left[1];
}

function untimedDeduction(records) {
  const pending = records.map((record) => ({ ...record }));
  let minutes = 0;
  let review = false;
  while (pending.length) {
    const cluster = [pending.shift()];
    for (let index = 0; index < pending.length;) {
      if (cluster.some((item) => rangesOverlap(item.span, pending[index].span))) cluster.push(pending.splice(index, 1)[0]);
      else index += 1;
    }
    const amounts = cluster.map((item) => item.minutes).filter((value) => value > 0);
    if (!amounts.length) continue;
    if (cluster.length > 1) review = true;
    if (amounts.every((value) => value === amounts[0])) minutes += amounts[0];
    else minutes += amounts.reduce((sum, value) => sum + value, 0);
  }
  return { minutes, review };
}

/**
 * Role-hours are the union of allocated role intervals.
 * Unallocated staffing is the stored span minus that union.
 * Total is the union of stored spans. Net subtracts break overlap once.
 * Identical untimed breaks on overlapping shifts stay separate and deduct once.
 */
export function staffingFigures(entries) {
  const list = Array.isArray(entries) ? entries : [entries];
  const groups = new Map();
  list.filter(Boolean).forEach((entry) => {
    const key = `${entry?.user_id}:${Number(entry?.day_of_week)}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(entry);
  });
  const round = (minutes) => Math.round((minutes / 60) * 10000) / 10000;
  let roleMin = 0;
  let totalMin = 0;
  let breakMin = 0;
  let review = false;
  groups.forEach((group) => {
    const spans = group.map((entry) => clockRange(entry?.start_time, entry?.end_time)).filter(Boolean);
    const roles = group.flatMap((entry) => allocatedRanges(entry));
    const total = rangeMinutes(spans);
    const role = rangeMinutes(roles);
    totalMin += total;
    roleMin += role;
    const timed = [];
    const untimed = [];
    group.forEach((entry) => {
      const span = clockRange(entry?.start_time, entry?.end_time);
      visibleBreaks(entry).forEach((slot) => {
        if (slot.start_time) {
          const range = clockRange(slot.start_time, slot.end_time);
          if (range) timed.push(range);
        } else if (slot.minutes) untimed.push({ minutes: Number(slot.minutes), span });
      });
    });
    let cut = 0;
    mergeRanges(spans).forEach(([start, end]) => {
      mergeRanges(timed).forEach(([breakStart, breakEnd]) => {
        const left = Math.max(start, breakStart);
        const right = Math.min(end, breakEnd);
        if (right > left) cut += right - left;
      });
    });
    const duration = untimedDeduction(untimed);
    if (duration.review) review = true;
    breakMin += Math.min(total, cut + duration.minutes);
  });
  const unallocated = Math.max(0, totalMin - roleMin);
  return {
    role: round(roleMin),
    unallocated: round(unallocated),
    total: round(totalMin),
    net: round(Math.max(0, totalMin - breakMin)),
    review,
  };
}

/** Keep the stored envelope unless the manager confirms a trim or an extension. */
export function applyRoleEdits(entry, segments, mode) {
  const clean = (segments || []).filter((segment) => segment?.role && spanMinutes(segment.start_time, segment.end_time));
  const names = [];
  clean.forEach((segment) => {
    if (segment.role && !names.includes(segment.role)) names.push(segment.role);
  });
  const stored = clockRange(entry?.start_time, entry?.end_time);
  let needStart = null;
  let needEnd = null;
  clean.forEach((segment) => {
    const span = clockRange(segment.start_time, segment.end_time);
    if (!span) return;
    if (needStart == null || span[0] < needStart) needStart = span[0];
    if (needEnd == null || span[1] > needEnd) needEnd = span[1];
  });
  const draft = {
    ...entry,
    role: names.join(","),
    role_assignments: clean.map((segment) => ({
      role: segment.role,
      start_time: String(segment.start_time).slice(0, 5),
      end_time: String(segment.end_time).slice(0, 5),
    })),
  };
  if (!stored && needStart != null) {
    return { entry: { ...draft, start_time: minutesToClock(needStart), end_time: minutesToClock(needEnd) } };
  }
  if (mode === "trim" && needStart != null) {
    return { entry: { ...draft, start_time: minutesToClock(needStart), end_time: minutesToClock(needEnd) } };
  }
  if (mode === "extend" && needStart != null && stored) {
    return {
      entry: {
        ...draft,
        start_time: minutesToClock(Math.min(stored[0], needStart)),
        end_time: minutesToClock(Math.max(stored[1], needEnd)),
      },
    };
  }
  const outside = stored && needStart != null && (needStart < stored[0] || needEnd > stored[1]);
  if (outside) {
    const extended = {
      ...draft,
      start_time: minutesToClock(Math.min(stored[0], needStart)),
      end_time: minutesToClock(Math.max(stored[1], needEnd)),
    };
    return {
      entry,
      confirm: {
        kind: "extend",
        segments: draft.role_assignments,
        before: staffingFigures(entry).total,
        after: staffingFigures(extended).total,
        end: extended.end_time,
      },
    };
  }
  return { entry: { ...draft, start_time: entry?.start_time, end_time: entry?.end_time } };
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

/** Timed slots stay on the clock. A minutes-only slot is its own untimed record, not a guessed time. */
export function visibleBreaks(entry) {
  const raw = asList(entry?.break_slots);
  const timed = raw.filter((slot) => slot?.start_time && slot?.end_time).map((slot) => ({
    start_time: String(slot.start_time).slice(0, 5),
    end_time: String(slot.end_time).slice(0, 5),
    timed: true,
    unscheduled: false,
  }));
  const untimed = raw.filter((slot) => !slot?.start_time && Number(slot?.minutes) > 0).map((slot) => ({
    unscheduled: true,
    minutes: Number(slot.minutes),
    timed: false,
  }));
  if (timed.length || untimed.length) return [...timed, ...untimed];
  const minutes = Number(entry?.break_minutes) || 0;
  if (!minutes) return [];
  return [{ unscheduled: true, minutes, timed: false }];
}

/** Persist timed slots and minutes-only records. Identical untimed lengths deduct once. */
export function breakAssignment(entry, slots) {
  const timed = (slots || []).filter((slot) => slot?.start_time && slot?.end_time);
  const untimed = (slots || []).filter((slot) => !slot?.start_time && Number(slot?.minutes) > 0);
  const timedMinutes = timed.reduce((sum, slot) => sum + (spanMinutes(slot.start_time, slot.end_time) || 0), 0);
  const sameUntimed = untimed.length > 1 && untimed.every((slot) => Number(slot.minutes) === Number(untimed[0].minutes));
  const untimedMinutes = sameUntimed ? Number(untimed[0].minutes) : untimed.reduce((sum, slot) => sum + Number(slot.minutes), 0);
  return {
    ...entry,
    break_slots: [
      ...timed.map((slot) => ({ start_time: String(slot.start_time).slice(0, 5), end_time: String(slot.end_time).slice(0, 5), timed: true })),
      ...untimed.map((slot) => ({ minutes: Number(slot.minutes) })),
    ],
    break_minutes: timedMinutes + untimedMinutes,
  };
}

/**
 * Propose one break for a shift.
 * A shift that already has a break is left unchanged unless the manager chooses replace.
 * Replace is explicit. It does not merge records on its own and it does not touch tasks.
 */
export function proposeBreak(entry, { mode = "timed", minutes = 30, start = "12:00", replace = false } = {}) {
  const existing = visibleBreaks(entry);
  if ((existing.length || Number(entry?.break_minutes) > 0) && !replace) return { entry, skipped: true };
  const length = Number(minutes);
  if (!length) return { entry, skipped: true };
  if (mode === "untimed") return { entry: breakAssignment(entry, [{ minutes: length }]), skipped: false };
  const begin = clockMinutes(start);
  if (begin == null) return { entry, skipped: true };
  return {
    entry: breakAssignment(entry, [{ start_time: String(start).slice(0, 5), end_time: minutesToClock(begin + length) }]),
    skipped: false,
  };
}

/**
 * One row per stored role segment, with its own start and end.
 * A gap that is not a timed break stays "not split" instead of borrowing the combined role name.
 * A combined role with no stored split lists each name and does not invent a time for each name.
 */
export function scheduleCardRows(entry) {
  const stored = storedRoleSegments(entry).filter((segment) => segment.start_time && segment.end_time);
  if (stored.length) {
    return stored.map((segment) => ({
      role: segment.role,
      start_time: String(segment.start_time).slice(0, 5),
      end_time: String(segment.end_time).slice(0, 5),
      allocated: true,
      unsplit: false,
    })).sort((a, b) => String(a.start_time).localeCompare(String(b.start_time)));
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

/** Day totals from role intervals. Overlapping roles for one person count once. */
export function dayScheduleSummary(entries, day) {
  const shifts = (entries || []).filter((entry) => Number(entry.day_of_week) === Number(day));
  const roles = {};
  const rolePeople = {};
  const rolePieces = {};
  const booked = scheduledRoleHours(shifts);
  const gross = booked.gross;
  const net = booked.net;
  function countPerson(role, userId) {
    if (!role) return;
    rolePeople[role] = rolePeople[role] || new Set();
    rolePeople[role].add(Number(userId));
  }
  for (const entry of shifts) {
    const hours = scheduledRoleHours(entry);
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
    scheduled: staffingFigures(shifts),
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

/** Remove one break record. The shift envelope and tasks stay as they are. */
export function removeBreak(entry, index) {
  const slots = visibleBreaks(entry).filter((_, itemIndex) => itemIndex !== index);
  return breakAssignment(entry, slots);
}

function breakIdentity(slot) {
  if (slot?.start_time && slot?.end_time) return `t:${String(slot.start_time).slice(0, 5)}-${String(slot.end_time).slice(0, 5)}`;
  if (Number(slot?.minutes) > 0) return `u:${Number(slot.minutes)}`;
  return "";
}

function breakInsideShift(entry, slot) {
  if (!slot?.start_time) return true;
  const span = clockRange(entry?.start_time, entry?.end_time);
  const piece = clockRange(slot.start_time, slot.end_time);
  if (!span || !piece) return false;
  return piece[0] >= span[0] && piece[1] <= span[1];
}

/**
 * Copy break records onto existing shifts for the chosen employees and days.
 * An identical break is not added again. A timed break outside the target shift is skipped.
 * Tasks are not copied.
 */
export function copyBreaksOnto(entries, source, userIds, days) {
  const breaks = visibleBreaks(source).filter((slot) => slot?.start_time || Number(slot?.minutes) > 0);
  const people = new Set((userIds || []).map(Number));
  const chosen = new Set((days || []).map(Number));
  if (!breaks.length) return entries || [];
  return (entries || []).map((entry) => {
    if (!people.has(Number(entry.user_id)) || !chosen.has(Number(entry.day_of_week))) return entry;
    const existing = visibleBreaks(entry);
    const seen = new Set(existing.map(breakIdentity));
    const additions = breaks.filter((slot) => breakInsideShift(entry, slot) && !seen.has(breakIdentity(slot)));
    if (!additions.length) return entry;
    return breakAssignment(entry, [...existing, ...additions]);
  });
}

/**
 * Copy one assignment onto other employees and days as a new individual draft.
 * The source record, its group, and any completed or verified history stay unchanged.
 * An Anytime assignment stays Anytime.
 */
export function copyTaskAssignments(tasks, source, userIds, days) {
  if (!source?.role) return tasks || [];
  const timed = source.timing_mode === "specific_time" && source.start_time;
  const stamp = Date.now();
  const additions = [];
  (userIds || []).forEach((userId) => {
    (days || []).forEach((day) => {
      if (Number(userId) === Number(source.user_id) && Number(day) === Number(source.day_of_week)) return;
      additions.push({
        id: `draft-task-${stamp}-${userId}-${day}`,
        draft: true,
        user_id: Number(userId),
        day_of_week: Number(day),
        role: source.role,
        timing_mode: timed ? "specific_time" : "anytime",
        start_time: timed ? String(source.start_time).slice(0, 5) : null,
        end_time: timed && source.end_time ? String(source.end_time).slice(0, 5) : null,
        execution_mode: "individual",
        assignment_group_id: null,
        status: "assigned",
      });
    });
  });
  return [...(tasks || []), ...additions];
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
