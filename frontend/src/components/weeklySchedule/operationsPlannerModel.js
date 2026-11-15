import {
  BREAK_OVERLAP_CAP,
  buildTaskGroups,
  dayBreaks,
  maxSimultaneous,
  simultaneousBreaks,
} from "./breaksTasksPlannerModel";
import { DAY_LABELS } from "./weeklyScheduleDates";
import {
  entryRoleAssignments,
  formatRoleHoursLabel,
  scheduleDayTimelines,
  scheduleEntryKey,
  scheduleRoleLabel,
  timelineRoleBreakdown,
} from "./weeklyScheduleRoles";

/** Existing activity statuses. Awaiting verification is not approved. */
export function classifyActivityStatus(status) {
  const value = String(status || "");
  if (value === "pending_approval") return "awaiting";
  if (value === "approved") return "verified";
  if (value === "completed") return "completed";
  if (value === "in_progress") return "inProgress";
  if (value === "rejected") return "rejected";
  return "notStarted";
}

const EMPTY_COUNTS = () => ({
  notStarted: 0,
  inProgress: 0,
  awaiting: 0,
  verified: 0,
  completed: 0,
  rejected: 0,
  total: 0,
});

function groupBucket(states) {
  if (states.includes("rejected")) return "rejected";
  if (states.includes("inProgress")) return "inProgress";
  if (states.includes("awaiting")) return "awaiting";
  if (states.length && states.every((state) => state === "verified")) return "verified";
  if (states.length && states.every((state) => state === "verified" || state === "completed")) return "completed";
  if (states.length && states.every((state) => state === "notStarted")) return "notStarted";
  return states.length ? "inProgress" : "notStarted";
}

/**
 * Group totals count a shared Activity Group once.
 * People totals count each participant and are labeled separately.
 */
export function taskStatusRollup(responsibilities, employeesById = {}) {
  const groups = buildTaskGroups(responsibilities, employeesById).map((group) => {
    const members = group.members.map((member) => ({
      ...member,
      bucket: classifyActivityStatus(member.status),
    }));
    return {
      ...group,
      members,
      shared: Boolean(group.shared || group.groupId || members.length > 1),
      bucket: groupBucket(members.map((member) => member.bucket)),
    };
  });
  const people = EMPTY_COUNTS();
  const byGroup = EMPTY_COUNTS();
  byGroup.shared = 0;
  for (const group of groups) {
    byGroup.total += 1;
    byGroup[group.bucket] += 1;
    if (group.shared) byGroup.shared += 1;
    for (const member of group.members) {
      people.total += 1;
      people[member.bucket] += 1;
    }
  }
  return { groups, byGroup, people };
}

/**
 * Display rounding for planned hours.
 * Each figure is rounded on its own, half away from zero, to one decimal hour.
 * Role nets are not adjusted so the rounded cards add up to the rounded week net.
 * Those source nets already sum to the week net; a gap between the two one-decimal
 * figures is only the accumulated rounding.
 */
export function roundHoursForDisplay(value) {
  const number = Number(value || 0);
  if (!Number.isFinite(number)) return 0;
  return Math.round(number * 10) / 10;
}

export function describeRoleHourDisplay(rows, weekNet) {
  const exact = (rows || []).map((row) => {
    const hours = Number(row?.hours || 0);
    return Number.isFinite(hours) ? hours : 0;
  });
  const exactSum = exact.reduce((sum, value) => sum + value, 0);
  const shown = exact.map((value) => roundHoursForDisplay(value));
  const shownSum = shown.reduce((sum, value) => sum + value, 0);
  const week = Number(weekNet || 0);
  const weekExact = Number.isFinite(week) ? week : 0;
  const weekShown = roundHoursForDisplay(weekExact);
  return {
    shown,
    exactSum,
    shownSum,
    weekExact,
    weekShown,
    sourceAgrees: Math.abs(exactSum - weekExact) < 0.001,
    displayGap: Math.round((shownSum - weekShown) * 10) / 10,
  };
}

function coveragePeople(list) {
  return (list || []).map((person) => ({
    name: person?.name || "Employee",
    range: person?.rangeLabel || "",
    hours: Number(person?.hours || 0),
  }));
}

/**
 * One bar row per role for the focused day.
 * Cell hours stay the existing worked amounts. A timed break does not remove the
 * scheduled assignment: scheduled staff include anyone on that role in the hour,
 * and available staff are the scheduled people with no timed break in that hour.
 */
export function roleTimelineFromCoverage(coverageDay) {
  const hours = coverageDay?.hours || [];
  const columns = coverageDay?.columns || [];
  return {
    hours: hours.map((row) => ({ hour: row.hour, label: row.label })),
    roles: columns.map((role) => {
      const total = coverageDay?.totals?.[role] || {};
      const slices = hours.map((row) => {
        const cell = row.cells?.[role] || {};
        const working = coveragePeople(cell.people);
        const breaks = coveragePeople((row.breaks?.people || []).filter((person) => (person.roles || []).includes(role)));
        const byName = new Map();
        for (const person of working) {
          byName.set(person.name, { ...person, onBreak: false, breakRange: "", breakHours: 0 });
        }
        for (const person of breaks) {
          const current = byName.get(person.name) || { name: person.name, range: "", hours: 0, onBreak: false, breakRange: "", breakHours: 0 };
          current.onBreak = true;
          current.breakRange = person.range;
          current.breakHours = person.hours;
          byName.set(person.name, current);
        }
        const scheduled = [...byName.values()];
        const onBreak = scheduled.filter((person) => person.onBreak);
        const available = scheduled.filter((person) => !person.onBreak);
        const workedHours = Number(cell.hours || 0);
        const breakHours = onBreak.reduce((sum, person) => sum + Number(person.breakHours || 0), 0);
        return {
          hours: workedHours,
          grossHours: workedHours + breakHours,
          netHours: workedHours,
          count: scheduled.length,
          scheduledCount: scheduled.length,
          scheduledPeople: scheduled,
          people: working,
          availableCount: available.length,
          availablePeople: available,
          breakHours,
          breakCount: onBreak.length,
          breakPeople: onBreak,
        };
      });
      const peak = slices.reduce((max, slice) => Math.max(max, slice.scheduledCount), 0);
      return {
        role,
        label: scheduleRoleLabel(role),
        people: Number(total.count || 0),
        hours: Number(total.hours || 0),
        gross: Number(total.hours || 0),
        net: Number(total.net ?? total.hours ?? 0),
        slices,
        peak: peak || 1,
      };
    }).filter((row) => row.people > 0 || row.hours > 0.001),
  };
}

export function dayBreakDetail(entries, employeesById, day) {
  const breaks = dayBreaks(entries, employeesById, day);
  const windows = simultaneousBreaks(breaks.timed);
  return {
    timed: breaks.timed,
    untimed: breaks.untimed,
    maxOverlap: maxSimultaneous(breaks.timed),
    hot: windows.filter((window) => window.count > BREAK_OVERLAP_CAP),
  };
}

export function weekBreakOverview(entries, employeesById, days) {
  return (days || []).map((day) => dayBreakDetail(entries, employeesById, day));
}

/**
 * Role portions of one shift. Clock ranges come from the assignment.
 * Gross and net come from the existing day timeline for that shift alone.
 */
export function shiftRoleSegments(entry) {
  const assignments = entryRoleAssignments(entry).filter((assignment) => assignment?.role);
  const timelines = scheduleDayTimelines(entry ? [entry] : []);
  const timeline = timelines.values().next().value;
  const breakdown = timeline ? timelineRoleBreakdown(timeline) : null;
  const entryHours = breakdown?.entries?.get?.(scheduleEntryKey(entry));
  return assignments.map((assignment) => {
    const parts = breakdown?.roles?.get?.(assignment.role);
    const net = entryHours?.get?.(assignment.role);
    return {
      role: assignment.role,
      label: scheduleRoleLabel(assignment.role),
      start: assignment.full_shift === false && assignment.start_time ? assignment.start_time : entry.start_time,
      end: assignment.full_shift === false && assignment.end_time ? assignment.end_time : entry.end_time,
      gross: parts ? parts.gross : null,
      net: net == null ? parts?.net ?? null : net,
      unallocated: Number(parts?.unallocatedBreak || 0),
    };
  });
}

export function entryHasRole(entry, role) {
  if (!role) return true;
  return entryRoleAssignments(entry).some((assignment) => assignment.role === role);
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[ch]));
}

/** Plain print of the current planner scope. Hours and states come from the same records as the board. */
export function buildOperationsPrintHtml({
  weekLabel = "",
  lens = "employees",
  mode = "week",
  dayLabel = "",
  employees = [],
  dayColumns = [],
  entriesByCell = {},
  responsibilitiesByCell = {},
  employeesById = {},
  weekSummary = {},
}) {
  const roles = (weekSummary.roles || [])
    .map((row) => `<li>${escapeHtml(row.label)}: ${row.employees} people, weekly hours ${escapeHtml(formatRoleHoursLabel(row.hours))}</li>`)
    .join("");
  const columns = mode === "day" ? [dayColumns.find((day) => DAY_LABELS[day] === dayLabel) ?? dayColumns[0]].filter((day) => day != null) : dayColumns;
  const head = columns.map((day) => `<th>${escapeHtml(DAY_LABELS[day] || day)}</th>`).join("");
  const body = employees.map((employee) => {
    const cells = columns.map((day) => {
      const shifts = entriesByCell[`${employee.user_id}:${day}`] || [];
      const tasks = taskStatusRollup(responsibilitiesByCell[`${employee.user_id}:${day}`] || [], employeesById).groups;
      const shiftText = shifts.map((entry) => {
        const segments = shiftRoleSegments(entry).map((segment) => `${segment.label} ${segment.start}–${segment.end}`).join("; ");
        const breaks = (entry.break_slots || []).map((slot) => `break ${slot.start_time}–${slot.end_time}`).join(", ");
        const untimed = Number(entry.unscheduled_break_minutes || 0) > 0 ? `${entry.unscheduled_break_minutes}m untimed` : "";
        return [segments || `${entry.start_time}–${entry.end_time}`, breaks, untimed].filter(Boolean).join(" · ");
      }).join("<br>");
      const taskText = tasks.map((group) => `${group.shared ? "Shared " : ""}${group.label}: ${group.members.map((member) => `${member.name} ${member.bucket}`).join(", ")}`).join("<br>");
      const text = lens === "tasks" ? taskText : lens === "breaks" ? [shiftText].join("") : [shiftText, taskText].filter(Boolean).join("<br>");
      return `<td>${text || ""}</td>`;
    }).join("");
    return `<tr><td>${escapeHtml(employee.display_name || employee.user_id)}</td>${cells}</tr>`;
  }).join("");
  return `<h1>Operations Planner</h1>
<p>${escapeHtml(weekLabel)} · ${escapeHtml(mode)} · ${escapeHtml(lens)} · ${escapeHtml(dayLabel)}</p>
<p>Entire week: headcount ${escapeHtml(weekSummary.employeesScheduled ?? 0)}, gross ${escapeHtml(formatRoleHoursLabel(weekSummary.grossHours))}, net ${escapeHtml(formatRoleHoursLabel(weekSummary.totalHours))}.</p>
<ul>${roles}</ul>
<table border="1" cellpadding="4" cellspacing="0"><thead><tr><th>Employee</th>${head}</tr></thead><tbody>${body}</tbody></table>
<p>Drag does not change start or end times. Untimed breaks are not placed on the clock.</p>`;
}
