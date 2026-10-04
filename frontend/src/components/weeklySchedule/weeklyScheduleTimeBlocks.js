import {
  scheduleDayTimelines,
  scheduleRoleLabel,
  sortRoles,
} from "./weeklyScheduleRoles";

export const ASSIGNMENT_KIND = { SHIFT: "shift", RESPONSIBILITY: "responsibility" };

export const HOURLY_COVERAGE_EXPLANATION =
  "Hourly cells are role coverage after timed breaks: an employee on a timed break is taken off every role "
  + "for that time, then the remaining time is intersected with each hour and simultaneous roles split it "
  + "evenly. The Break column counts employees on a timed break in each hour and their break hours. Breaks "
  + "without a time (\u201cNot scheduled\u201d) are not placed in any hour; they are listed under the day "
  + "totals as a separate deduction, so role hours \u2212 that deduction match net hours. Overnight shifts stay "
  + "on the day they start (hours after midnight are marked +1).";

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

function finishPeople(peopleMap) {
  return [...peopleMap.values()]
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
    .sort(byName);
}

function clockRangeLabel(start, end) {
  return `${clockWithSuffix(start)}–${clockWithSuffix(end)}${end > 24 * 60 ? " (+1)" : ""}`;
}

/**
 * Hourly coverage per day: one row per clock hour from the day's first to last scheduled minute.
 *
 * Built from the shared day timeline (`scheduleDayTimelines`), so it matches the role and net-hour
 * totals. Timed breaks take the employee off every role; the remaining role time is intersected with
 * each hour. A role cell holds the distinct employees on that role in the hour, the employee-hours they
 * contribute, and the cumulative employee-hours through the end of the hour (counted from the first hour
 * of the day, so hidden rows still count). `breaks` holds the employees on a timed break in the hour.
 * Breaks without a time are listed per day in `unscheduledBreaks` and never placed in an hour.
 * `roles` limits columns and totals (null = all); breaks count when they interrupt a selected role (or the
 * employee holds one that day, for breaks without a time). The split between simultaneous roles is always
 * computed over all of the employee's roles.
 */
export function buildHourlyCoverage(
  entries,
  { dayIndices = [0, 1, 2, 3, 4, 5, 6], employeesById = {}, responsibilities = [], roles = null } = {},
) {
  const roleFilter = Array.isArray(roles) ? new Set(roles) : null;
  const timelines = [...scheduleDayTimelines(entries).values()];
  return dayIndices.map((dow) => {
    const dayTimelines = timelines.filter((t) => t.dow === dow && t.shifts.length);
    let first = null;
    let last = null;
    for (const t of dayTimelines) {
      for (const shift of t.shifts) {
        first = first == null ? shift.start : Math.min(first, shift.start);
        last = last == null ? shift.end : Math.max(last, shift.end);
      }
    }

    const cells = new Map();
    const cellFor = (hour, role) => {
      const key = `${hour}|${role}`;
      if (!cells.has(key)) cells.set(key, { hours: 0, people: new Map() });
      return cells.get(key);
    };
    const breakCells = new Map();
    const breakRanges = [];
    const unscheduledBreaks = [];
    const dayRoles = new Set();
    for (const t of dayTimelines) {
      const uid = t.userId;
      const name = employeeName(employeesById, uid);
      for (const piece of t.pieces) {
        if (piece.onBreak || !piece.roles.length) continue;
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
              cell.people.set(uid, { userId: uid, name, entry: piece.entryByRole[role], ranges: [], hours: 0, shared: false });
            }
            const person = cell.people.get(uid);
            person.ranges.push([from, to]);
            person.hours += contributed;
            if (piece.roles.length > 1) person.shared = true;
          }
        }
      }
      for (const range of t.breakRanges) {
        if (roleFilter && !range.roles.some((role) => roleFilter.has(role))) continue;
        breakRanges.push({
          userId: uid,
          name,
          entry: range.entry,
          start: range.start,
          end: range.end,
          hours: (range.end - range.start) / 60,
          roles: range.roles,
          label: clockRangeLabel(range.start, range.end),
        });
        for (let hour = Math.floor(range.start / 60); hour * 60 < range.end; hour += 1) {
          const from = Math.max(range.start, hour * 60);
          const to = Math.min(range.end, (hour + 1) * 60);
          if (to <= from) continue;
          if (!breakCells.has(hour)) breakCells.set(hour, { hours: 0, people: new Map() });
          const cell = breakCells.get(hour);
          cell.hours += (to - from) / 60;
          if (!cell.people.has(uid)) {
            cell.people.set(uid, { userId: uid, name, entry: range.entry, roles: [], ranges: [], hours: 0 });
          }
          const person = cell.people.get(uid);
          person.ranges.push([from, to]);
          person.hours += (to - from) / 60;
          person.roles = sortRoles([...new Set([...person.roles, ...range.roles])]);
        }
      }
      if (t.unscheduledBreakHours > 0) {
        const dayRolesForUser = new Set(t.pieces.flatMap((piece) => piece.roles));
        if (!roleFilter || [...dayRolesForUser].some((role) => roleFilter.has(role))) {
          for (const item of t.unscheduledEntries) {
            unscheduledBreaks.push({ userId: uid, name, entry: item.entry, hours: item.minutes / 60 });
          }
        }
      }
    }
    breakRanges.sort((a, b) => a.start - b.start || byName(a, b));
    for (const range of breakRanges) {
      range.overlapsWith = breakRanges
        .filter((other) => other !== range && other.start < range.end && range.start < other.end)
        .map((other) => other.name);
    }
    unscheduledBreaks.sort(byName);

    const columns = sortRoles([...dayRoles]);
    const hours = [];
    const cumulative = Object.fromEntries(columns.map((role) => [role, 0]));
    let cumulativeTotal = 0;
    let cumulativeBreak = 0;
    const dayPeople = Object.fromEntries(columns.map((role) => [role, new Set()]));
    const dayAllPeople = new Set();
    const dayBreakPeople = new Set();
    if (first != null) {
      for (let hour = Math.floor(first / 60); hour * 60 < last; hour += 1) {
        const rowCells = {};
        const hourPeople = new Set();
        let hourTotal = 0;
        for (const role of columns) {
          const cell = cells.get(`${hour}|${role}`);
          const people = cell ? finishPeople(cell.people) : [];
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
        const breakCell = breakCells.get(hour);
        const breakPeople = breakCell ? finishPeople(breakCell.people) : [];
        const breakHours = breakCell ? breakCell.hours : 0;
        cumulativeBreak += breakHours;
        for (const person of breakPeople) dayBreakPeople.add(person.userId);
        let scheduled = 0;
        for (const t of dayTimelines) {
          if (t.shifts.some((s) => s.start < (hour + 1) * 60 && s.end > hour * 60)) scheduled += 1;
        }
        hours.push({
          hour,
          label: hourLabel(hour),
          endLabel: hourEndLabel(hour),
          cells: rowCells,
          breaks: { people: breakPeople, count: breakPeople.length, hours: breakHours, cumulative: cumulativeBreak },
          total: { count: hourPeople.size, hours: hourTotal, cumulative: cumulativeTotal },
          scheduled,
          gap: hourTotal <= 0,
        });
      }
    }
    const totals = Object.fromEntries(
      columns.map((role) => [role, { count: dayPeople[role].size, hours: cumulative[role] }]),
    );
    const unscheduledHours = unscheduledBreaks.reduce((sum, item) => sum + item.hours, 0);
    return {
      dow,
      columns,
      hours,
      totals,
      overall: { count: dayAllPeople.size, hours: cumulativeTotal },
      breakTotal: { count: dayBreakPeople.size, hours: cumulativeBreak },
      breakRanges,
      unscheduledBreaks,
      unscheduledBreakTotal: { count: new Set(unscheduledBreaks.map((b) => b.userId)).size, hours: unscheduledHours },
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
