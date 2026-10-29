import { formatTime12 } from "../datetime/scheduleTimeUi";
import { parseTimeToMinutes } from "../../payroll/schedulePlanner";

/** Stored on the task assignment. Relative modes follow the current shift and break. */
export const TASK_TIMING = {
  ANYTIME: "anytime",
  SPECIFIC: "specific_time",
  UPON_ENTRY: "upon_entry",
  BEFORE_BREAK: "before_break",
  AFTER_BREAK: "after_break",
  BEFORE_EXIT: "before_exit",
};

export const TASK_TIMING_OPTIONS = [
  { value: TASK_TIMING.ANYTIME, label: "Anytime" },
  { value: TASK_TIMING.SPECIFIC, label: "Specific Time" },
  { value: TASK_TIMING.UPON_ENTRY, label: "Upon Entry" },
  { value: TASK_TIMING.BEFORE_BREAK, label: "Before Break" },
  { value: TASK_TIMING.AFTER_BREAK, label: "After Break" },
  { value: TASK_TIMING.BEFORE_EXIT, label: "Before Exit" },
];

const BREAK_MODES = new Set([TASK_TIMING.BEFORE_BREAK, TASK_TIMING.AFTER_BREAK]);
const DAY = 24 * 60;

export function assignmentKey(item) {
  const groupId = String(item?.assignment_group_id || "").trim();
  if (groupId) return `g:${item?.week_start || ""}:${item?.day_of_week}:${groupId}`;
  return `solo:${item?.id}`;
}

export function taskMemberIds(item) {
  const raw = Array.isArray(item?.user_ids) && item.user_ids.length ? item.user_ids : [item?.user_id];
  const ids = [];
  for (const value of raw) {
    const id = Number(value);
    if (id > 0 && !ids.includes(id)) ids.push(id);
  }
  return ids;
}

export function scheduleEmployeeName(employeesById, userId) {
  const employee = employeesById?.[userId] || employeesById?.[String(userId)];
  return employee?.display_name || `User #${userId}`;
}

export function taskMemberNames(item, employeesById) {
  return taskMemberIds(item).map((id) => scheduleEmployeeName(employeesById, id));
}

/** "Shared" when this activity group is one collaborative assignment. */
export function taskExecutionLabel(item) {
  const ids = taskMemberIds(item);
  return item?.execution_mode === "shared" && ids.length >= 2 ? "Shared" : "";
}

/** "Maria Perez + Francis", or "" when the assignment is a single employee. */
export function taskGroupLabel(item, employeesById) {
  const names = [...taskMemberNames(item, employeesById)].sort((a, b) =>
    a.localeCompare(b, undefined, { sensitivity: "base" }),
  );
  return names.length > 1 ? names.join(" + ") : "";
}

export function taskTimingLabel(item) {
  const mode = item?.timing_mode || TASK_TIMING.ANYTIME;
  if (mode === TASK_TIMING.ANYTIME) return "";
  if (mode === TASK_TIMING.SPECIFIC) return formatTime12(item?.start_time);
  return TASK_TIMING_OPTIONS.find((option) => option.value === mode)?.label || "";
}

function minutes(value) {
  return parseTimeToMinutes(value);
}

function span(start, end) {
  return end <= start ? [start, end + DAY] : [start, end];
}

function onShift(point, start, end) {
  const [spanStart, spanEnd] = span(start, end);
  const mapped = point >= spanStart ? point : point + DAY;
  return spanStart <= mapped && mapped < spanEnd ? mapped : null;
}

function inWindow(mappedPoint, shiftStart, windowStart, windowEnd) {
  let start = windowStart;
  let end = windowEnd;
  if (end <= start) end += DAY;
  if (start < shiftStart) {
    start += DAY;
    end += DAY;
  }
  return start <= mappedPoint && mappedPoint < end;
}

function shiftBreaks(shift) {
  return (shift?.break_slots || [])
    .map((slot) => [minutes(slot?.start_time), minutes(slot?.end_time)])
    .filter(([start, end]) => start != null && end != null && start !== end);
}

function coveringShift(shifts, point) {
  return (shifts || []).find((shift) => {
    const start = minutes(shift.start_time);
    const end = minutes(shift.end_time);
    return start != null && end != null && onShift(point, start, end) != null;
  });
}

function duringBreak(shift, point) {
  const start = minutes(shift.start_time);
  const end = minutes(shift.end_time);
  if (start == null || end == null) return false;
  const mapped = onShift(point, start, end);
  if (mapped == null) return false;
  return shiftBreaks(shift).some(([b0, b1]) => inWindow(mapped, start, b0, b1));
}

function earliestStart(shifts) {
  const found = (shifts || [])
    .map((shift) => [minutes(shift.start_time), String(shift.start_time || "").slice(0, 5)])
    .filter(([start]) => start != null);
  if (!found.length) return null;
  return found.sort((a, b) => a[0] - b[0])[0][1];
}

function latestEnd(shifts) {
  const found = [];
  for (const shift of shifts || []) {
    const start = minutes(shift.start_time);
    const end = minutes(shift.end_time);
    if (start == null || end == null) continue;
    found.push([span(start, end)[1], String(shift.end_time || "").slice(0, 5)]);
  }
  if (!found.length) return null;
  return found.sort((a, b) => b[0] - a[0])[0][1];
}

function breakAnchor(shifts, { after = false } = {}) {
  const found = [];
  for (const shift of shifts || []) {
    const start = minutes(shift.start_time);
    if (start == null) continue;
    for (const [b0, b1] of shiftBreaks(shift)) {
      const anchor = after ? b1 : b0;
      found.push([anchor >= start ? anchor : anchor + DAY, formatTime12(`${String(Math.floor(anchor / 60) % 24).padStart(2, "0")}:${String(anchor % 60).padStart(2, "0")}`)]);
    }
  }
  if (!found.length) return null;
  return found.sort((a, b) => a[0] - b[0])[0][1];
}

function hasTimedBreak(shifts) {
  return (shifts || []).some((shift) => shiftBreaks(shift).length);
}

function hasUnscheduledBreak(shifts) {
  return (shifts || []).some((shift) => Number(shift.unscheduled_break_minutes || 0) > 0 && !shiftBreaks(shift).length);
}

function clock(value) {
  return formatTime12(value);
}

/** Same rules as the server: errors block Specific Time; warnings stay with the assignment. */
export function evaluateTaskTiming({ timingMode, startTime, members }) {
  const mode = timingMode || TASK_TIMING.ANYTIME;
  if (mode === TASK_TIMING.ANYTIME || !members?.length) return { errors: [], warnings: [] };
  const label = TASK_TIMING_OPTIONS.find((option) => option.value === mode)?.label || mode;
  if (mode === TASK_TIMING.SPECIFIC) {
    const point = minutes(startTime);
    const when = clock(startTime);
    if (point == null) return { errors: ["start time is required for Specific Time"], warnings: [] };
    const errors = [];
    for (const member of members) {
      const shift = coveringShift(member.shifts, point);
      if (!shift) errors.push(`${member.name} is not scheduled at ${when}`);
      else if (duringBreak(shift, point)) errors.push(`${member.name} is on a scheduled break at ${when}`);
    }
    return { errors, warnings: [] };
  }
  const warnings = [];
  const anchors = [];
  for (const member of members) {
    const shifts = member.shifts || [];
    if (mode === TASK_TIMING.UPON_ENTRY) {
      const anchor = earliestStart(shifts);
      if (!anchor) warnings.push(`${member.name} has no shift on this day, so Upon Entry has no start to follow`);
      else anchors.push([member.name, clock(anchor)]);
    } else if (mode === TASK_TIMING.BEFORE_EXIT) {
      const anchor = latestEnd(shifts);
      if (!anchor) warnings.push(`${member.name} has no shift on this day, so Before Exit has no end to follow`);
      else anchors.push([member.name, clock(anchor)]);
    } else if (BREAK_MODES.has(mode)) {
      if (!hasTimedBreak(shifts)) {
        warnings.push(
          hasUnscheduledBreak(shifts)
            ? `${member.name}'s break has no time, so ${label} cannot be placed`
            : `${member.name} has no scheduled break, so ${label} cannot be placed`,
        );
      } else {
        const anchor = breakAnchor(shifts, { after: mode === TASK_TIMING.AFTER_BREAK });
        if (anchor) anchors.push([member.name, anchor]);
      }
    }
  }
  const distinct = new Set(anchors.map(([, when]) => when));
  if (members.length > 1 && distinct.size > 1) {
    warnings.push(`${label} differs across the group: ${anchors.map(([name, when]) => `${name} ${when}`).join(", ")}`);
  }
  return { errors: [], warnings };
}

function shiftsFor(entries, userId, dayOfWeek) {
  return (entries || [])
    .filter((entry) => Number(entry.user_id) === Number(userId) && Number(entry.day_of_week) === Number(dayOfWeek))
    .map((entry) => ({
      start_time: entry.start_time,
      end_time: entry.end_time,
      break_slots: entry.break_slots || [],
      unscheduled_break_minutes:
        entry.unscheduled_break_minutes != null
          ? Number(entry.unscheduled_break_minutes)
          : Math.max(0, Number(entry.break_minutes || 0)),
    }));
}

export function taskTimingIssues(item, entries, employeesById) {
  const ids = taskMemberIds(item);
  return evaluateTaskTiming({
    timingMode: item?.timing_mode || TASK_TIMING.ANYTIME,
    startTime: item?.start_time,
    members: ids.map((id) => ({
      name: scheduleEmployeeName(employeesById, id),
      shifts: shiftsFor(entries, id, item?.day_of_week),
    })),
  });
}
