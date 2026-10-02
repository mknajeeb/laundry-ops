import { parseTimeToMinutes } from "../../payroll/schedulePlanner";
import { normalizeTimeHm } from "../datetime/scheduleTimeUi";
import {
  entryRoleAssignments,
  isScheduleTask,
  placeOnShiftTimeline,
  scheduleRoleLabel,
  sortRoles,
} from "./weeklyScheduleRoles";

export const ASSIGNMENT_KIND = { SHIFT: "shift", RESPONSIBILITY: "responsibility" };

const DAY_MINUTES = 24 * 60;

export const HOURLY_COVERAGE_EXPLANATION =
  "Hourly cells are gross scheduled coverage: each role assignment is intersected with each hour, and "
  + "simultaneous roles split the employee's time evenly. Breaks are stored as a duration without a time, so "
  + "they are not taken out of any specific hour; the employee and role totals above are net of breaks. "
  + "Overnight shifts stay on the day they start (hours after midnight are marked +1).";

/** Calendar date for a schedule day; week_start is a plain ET date, so format without zone shifts. */
export function dayDateLabel(weekStart, dow) {
  const [y, m, d] = String(weekStart || "").split("-").map(Number);
  if (!y || !m || !d) return "";
  return new Date(Date.UTC(y, m - 1, d + dow)).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

function clockParts(minutes) {
  const h = Math.floor(minutes / 60) % 24;
  return { h12: h % 12 || 12, minute: minutes % 60, suffix: h < 12 ? "AM" : "PM" };
}

/** "2", "2:30" — compact clock without AM/PM for times inside an hour row. */
export function compactClock(minutes) {
  const { h12, minute } = clockParts(minutes);
  return minute ? `${h12}:${String(minute).padStart(2, "0")}` : `${h12}`;
}

function clockWithSuffix(minutes) {
  const { suffix } = clockParts(minutes);
  return `${compactClock(minutes)} ${suffix}`;
}

/** "2–3 AM", "11 AM–12 PM"; hours past midnight of an overnight shift get "(+1)". */
export function hourLabel(hour, separator = "–") {
  const start = clockParts(hour * 60);
  const end = clockParts((hour + 1) * 60);
  const text = start.suffix === end.suffix
    ? `${start.h12}${separator}${end.h12} ${end.suffix}`
    : `${start.h12} ${start.suffix}${separator}${end.h12} ${end.suffix}`;
  return hour >= 24 ? `${text} (+1)` : text;
}

/** Clock label for an hour boundary, e.g. "5 AM"; boundaries after midnight of an overnight day get "(+1)". */
export function hourBoundaryLabel(hour) {
  return `${clockWithSuffix(hour * 60)}${hour >= 24 ? " (+1)" : ""}`;
}

/** End-of-interval label for cumulative totals, e.g. "5 AM". */
export function hourEndLabel(hour) {
  return hourBoundaryLabel(hour + 1);
}

export function formatCoverageHours(hours) {
  const value = Math.round(Number(hours || 0) * 100) / 100;
  return `${value}h`;
}

function shiftInterval(entry) {
  const start = parseTimeToMinutes(normalizeTimeHm(entry?.start_time));
  let end = parseTimeToMinutes(normalizeTimeHm(entry?.end_time));
  if (start == null || end == null) return null;
  if (end <= start) end += DAY_MINUTES;
  return { start, end };
}

/** Timed role ranges of one shift on its start day's timeline (minutes, may run past midnight). */
function roleSegments(entry, shift) {
  const out = [];
  for (const assignment of entryRoleAssignments(entry)) {
    if (!assignment?.role || isScheduleTask(assignment.role)) continue;
    let { start, end } = shift;
    const segStart = parseTimeToMinutes(normalizeTimeHm(assignment.start_time));
    const segEnd = parseTimeToMinutes(normalizeTimeHm(assignment.end_time));
    if (assignment.full_shift === false && segStart != null && segEnd != null) {
      const placed = placeOnShiftTimeline(segStart, segEnd, shift.start);
      start = Math.max(placed.start, shift.start);
      end = Math.min(placed.end, shift.end);
    }
    if (end > start) out.push({ role: assignment.role, start, end, entry });
  }
  return out;
}

/**
 * Split one employee's day into pieces with the set of roles active in each. Overlapping shifts merge
 * (a role is never counted twice) and simultaneous roles share the piece evenly.
 */
function employeePieces(segments) {
  const points = [...new Set(segments.flatMap((s) => [s.start, s.end]))].sort((a, b) => a - b);
  const pieces = [];
  for (let i = 0; i < points.length - 1; i += 1) {
    const start = points[i];
    const end = points[i + 1];
    const covering = segments.filter((s) => s.start <= start && s.end >= end);
    const roles = [...new Set(covering.map((s) => s.role))];
    if (!roles.length) continue;
    pieces.push({ start, end, roles, entryByRole: Object.fromEntries(covering.map((s) => [s.role, s.entry])) });
  }
  return pieces;
}

function mergeRanges(ranges) {
  const sorted = [...ranges].sort((a, b) => a[0] - b[0]);
  const out = [];
  for (const [start, end] of sorted) {
    const last = out[out.length - 1];
    if (last && start <= last[1]) last[1] = Math.max(last[1], end);
    else out.push([start, end]);
  }
  return out;
}

function employeeName(employeesById, userId) {
  const employee = employeesById?.[userId] || employeesById?.[String(userId)];
  return employee?.display_name || `User #${userId}`;
}

function byName(a, b) {
  return a.name.localeCompare(b.name, undefined, { sensitivity: "base" });
}

function dayTaskGroups(responsibilities, dow, employeesById) {
  const groups = new Map();
  for (const item of responsibilities || []) {
    if (Number(item.day_of_week) !== dow) continue;
    if (!groups.has(item.role)) groups.set(item.role, { role: item.role, label: scheduleRoleLabel(item.role), people: [] });
    groups.get(item.role).people.push({
      key: `r${item.id}`,
      item,
      userId: Number(item.user_id),
      name: employeeName(employeesById, item.user_id),
      remarks: item.remarks || null,
    });
  }
  return sortRoles([...groups.keys()]).map((role) => {
    const group = groups.get(role);
    const people = [...group.people].sort(byName);
    return { ...group, people, count: people.length };
  });
}

/**
 * Hourly coverage per day: one row per clock hour from the day's first to last scheduled minute.
 *
 * Each role assignment is intersected with each hour. A cell holds the distinct employees on that role
 * in the hour, the employee-hours they contribute, and the role's cumulative employee-hours through the
 * end of the hour (counted from the first hour of the day, so hidden rows still count). Breaks have no
 * stored time, so cells are gross scheduled coverage. ``roles`` limits columns and totals (null = all);
 * the time split between simultaneous roles is always computed over all of the employee's roles.
 */
export function buildHourlyCoverage(
  entries,
  { dayIndices = [0, 1, 2, 3, 4, 5, 6], employeesById = {}, responsibilities = [], roles = null } = {},
) {
  const roleFilter = Array.isArray(roles) ? new Set(roles) : null;
  return dayIndices.map((dow) => {
    let first = null;
    let last = null;
    const segmentsByUser = new Map();
    const shiftsByUser = new Map();
    for (const entry of entries || []) {
      if (Number(entry.day_of_week) !== dow) continue;
      const shift = shiftInterval(entry);
      if (!shift) continue;
      const uid = Number(entry.user_id);
      first = first == null ? shift.start : Math.min(first, shift.start);
      last = last == null ? shift.end : Math.max(last, shift.end);
      if (!shiftsByUser.has(uid)) shiftsByUser.set(uid, []);
      shiftsByUser.get(uid).push(shift);
      if (!segmentsByUser.has(uid)) segmentsByUser.set(uid, []);
      segmentsByUser.get(uid).push(...roleSegments(entry, shift));
    }

    const cells = new Map();
    const cellFor = (hour, role) => {
      const key = `${hour}|${role}`;
      if (!cells.has(key)) cells.set(key, { hours: 0, people: new Map() });
      return cells.get(key);
    };
    const dayRoles = new Set();
    for (const [uid, segments] of segmentsByUser) {
      for (const piece of employeePieces(segments)) {
        const share = 1 / piece.roles.length;
        for (let hour = Math.floor(piece.start / 60); hour * 60 < piece.end; hour += 1) {
          const from = Math.max(piece.start, hour * 60);
          const to = Math.min(piece.end, (hour + 1) * 60);
          if (to <= from) continue;
          for (const role of piece.roles) {
            if (roleFilter && !roleFilter.has(role)) continue;
            dayRoles.add(role);
            const cell = cellFor(hour, role);
            const contributed = ((to - from) / 60) * share;
            cell.hours += contributed;
            if (!cell.people.has(uid)) {
              cell.people.set(uid, {
                userId: uid,
                name: employeeName(employeesById, uid),
                entry: piece.entryByRole[role],
                ranges: [],
                hours: 0,
                shared: false,
              });
            }
            const person = cell.people.get(uid);
            person.ranges.push([from, to]);
            person.hours += contributed;
            if (piece.roles.length > 1) person.shared = true;
          }
        }
      }
    }

    const columns = sortRoles([...dayRoles]);
    const hours = [];
    const cumulative = Object.fromEntries(columns.map((role) => [role, 0]));
    let cumulativeTotal = 0;
    const dayPeople = Object.fromEntries(columns.map((role) => [role, new Set()]));
    const dayAllPeople = new Set();
    if (first != null) {
      for (let hour = Math.floor(first / 60); hour * 60 < last; hour += 1) {
        const rowCells = {};
        const hourPeople = new Set();
        let hourTotal = 0;
        for (const role of columns) {
          const cell = cells.get(`${hour}|${role}`);
          const people = cell
            ? [...cell.people.values()]
                .map((person) => {
                  const ranges = mergeRanges(person.ranges);
                  const minutes = ranges.reduce((sum, [a, b]) => sum + (b - a), 0);
                  return {
                    ...person,
                    ranges,
                    partial: minutes < 60,
                    rangeLabel: ranges.map(([a, b]) => `${compactClock(a)}–${compactClock(b)}`).join(", "),
                  };
                })
                .sort(byName)
            : [];
          const roleHours = cell ? cell.hours : 0;
          cumulative[role] += roleHours;
          hourTotal += roleHours;
          for (const person of people) {
            hourPeople.add(person.userId);
            dayPeople[role].add(person.userId);
            dayAllPeople.add(person.userId);
          }
          rowCells[role] = { people, count: people.length, hours: roleHours, cumulative: cumulative[role] };
        }
        cumulativeTotal += hourTotal;
        let scheduled = 0;
        for (const shifts of shiftsByUser.values()) {
          if (shifts.some((s) => s.start < (hour + 1) * 60 && s.end > hour * 60)) scheduled += 1;
        }
        hours.push({
          hour,
          label: hourLabel(hour),
          endLabel: hourEndLabel(hour),
          cells: rowCells,
          total: { count: hourPeople.size, hours: hourTotal, cumulative: cumulativeTotal },
          scheduled,
          gap: hourTotal <= 0,
        });
      }
    }
    const totals = Object.fromEntries(
      columns.map((role) => [role, { count: dayPeople[role].size, hours: cumulative[role] }]),
    );
    return {
      dow,
      columns,
      hours,
      totals,
      overall: { count: dayAllPeople.size, hours: cumulativeTotal },
      responsibilities: dayTaskGroups(responsibilities, dow, employeesById),
    };
  });
}

/** Columns shared across the shown days, in configured role order. */
export function coverageColumns(days) {
  return sortRoles([...new Set((days || []).flatMap((day) => day.columns))]);
}

/** Keep only hours inside [fromHour, toHour); cumulative values already include hidden rows. */
export function filterCoverageHours(days, { fromHour = null, toHour = null } = {}) {
  if (fromHour == null && toHour == null) return days;
  return (days || []).map((day) => ({
    ...day,
    hours: day.hours.filter((row) => (fromHour == null || row.hour >= fromHour) && (toHour == null || row.hour < toHour)),
  }));
}
