import { parseTimeToMinutes } from "../../payroll/schedulePlanner";
import { formatTime12, normalizeTimeHm } from "../datetime/scheduleTimeUi";
import { DAY_LABELS, dayOffset, DISPLAY_DAY_ORDER } from "./weeklyScheduleDates";
import { scheduleRoleLabel } from "./weeklyScheduleRoles";
import { assignmentKey } from "./weeklyScheduleTaskTiming";

export const BREAK_OVERLAP_CAP = 3;
export const PLANNER_SECTION = { TIMELINE: "timeline", TASKS: "tasks", EMPLOYEES: "employees" };

function minutes(value) {
  return parseTimeToMinutes(normalizeTimeHm(value));
}

function clock(value) {
  const hm = normalizeTimeHm(value);
  return hm ? formatTime12(hm) : "";
}

function durationLabel(start, end) {
  if (start == null || end == null || end <= start) return "";
  const total = end - start;
  const hours = Math.floor(total / 60);
  const mins = total % 60;
  if (hours && mins) return `${hours}h ${mins}m`;
  if (hours) return `${hours}h`;
  return `${mins}m`;
}

export function calendarDateForDay(weekStart, dayOfWeek) {
  const date = new Date(`${String(weekStart || "").slice(0, 10)}T12:00:00`);
  if (Number.isNaN(date.getTime())) return "";
  date.setDate(date.getDate() + dayOffset(dayOfWeek));
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

function employeeName(employee, userId) {
  return employee?.display_name || employee?.name || `User #${userId}`;
}

function dayEntries(entries, day) {
  return (entries || []).filter((entry) => Number(entry.day_of_week) === Number(day));
}

/** Timed breaks participate in overlap. A break without a clock time does not. */
export function dayBreaks(entries, employeesById, day) {
  const timed = [];
  const untimed = [];
  for (const entry of dayEntries(entries, day)) {
    const userId = Number(entry.user_id);
    const name = employeeName(employeesById?.[userId] || employeesById?.[String(userId)], userId);
    const slots = Array.isArray(entry.break_slots) ? entry.break_slots : [];
    slots.forEach((slot, index) => {
      const start = minutes(slot?.start_time);
      const end = minutes(slot?.end_time);
      if (start == null || end == null || end <= start) return;
      timed.push({
        key: `${entry.id}:${index}`,
        entryId: entry.id,
        userId,
        name,
        start,
        end,
        startLabel: clock(slot.start_time),
        endLabel: clock(slot.end_time),
        duration: durationLabel(start, end),
        entry,
      });
    });
    const unscheduled = Math.max(0, Number(entry.unscheduled_break_minutes || 0));
    if (unscheduled > 0) {
      untimed.push({
        key: `untimed:${entry.id}`,
        entryId: entry.id,
        userId,
        name,
        minutes: unscheduled,
        entry,
      });
    }
  }
  timed.sort((a, b) => a.start - b.start || a.name.localeCompare(b.name));
  untimed.sort((a, b) => a.name.localeCompare(b.name));
  return { timed, untimed };
}

/**
 * Distinct employees on a timed break. Touching endpoints do not overlap.
 * Untimed breaks are ignored by the caller.
 */
export function simultaneousBreaks(intervals) {
  const events = [];
  for (const item of intervals || []) {
    events.push({ t: item.start, delta: 1, userId: item.userId });
    events.push({ t: item.end, delta: -1, userId: item.userId });
  }
  events.sort((a, b) => a.t - b.t || a.delta - b.delta);
  const active = new Map();
  const segments = [];
  let cursor = null;
  const size = () => active.size;
  const snapshot = () => [...active.keys()];
  for (const event of events) {
    if (cursor != null && event.t > cursor && size() > 0) {
      segments.push({ start: cursor, end: event.t, count: size(), userIds: snapshot() });
    }
    const next = (active.get(event.userId) || 0) + event.delta;
    if (next <= 0) active.delete(event.userId);
    else active.set(event.userId, next);
    cursor = event.t;
  }
  return segments;
}

export function maxSimultaneous(intervals) {
  return simultaneousBreaks(intervals).reduce((max, segment) => Math.max(max, segment.count), 0);
}

export function overlapExceedsCap(intervals, cap = BREAK_OVERLAP_CAP) {
  return maxSimultaneous(intervals) > cap;
}

/** Replace one shift's timed breaks and measure the day. Untimed breaks stay out of the count. */
export function breaksAfterEdit(entries, employeesById, day, entryId, nextSlots) {
  const nextEntries = (entries || []).map((entry) =>
    entry.id === entryId ? { ...entry, break_slots: nextSlots } : entry,
  );
  return dayBreaks(nextEntries, employeesById, day).timed;
}

function shiftLabel(entry) {
  const start = clock(entry?.start_time);
  const end = clock(entry?.end_time);
  if (!start || !end) return "";
  return `${start}–${end}`;
}

const STARTED = new Set(["in_progress", "rejected", "pending_approval", "completed", "approved"]);
const COMPLETED = new Set(["completed", "approved"]);

function memberState(status) {
  const value = String(status || "");
  if (value === "pending_approval") return "awaiting";
  if (COMPLETED.has(value)) return "completed";
  if (value === "in_progress" || value === "rejected") return "started";
  return "assigned";
}

export function buildTaskGroups(responsibilities, employeesById = {}) {
  const groups = new Map();
  for (const item of responsibilities || []) {
    const key = assignmentKey(item);
    if (!groups.has(key)) {
      groups.set(key, {
        key,
        id: item.id,
        groupId: item.assignment_group_id || null,
        role: item.role,
        label: scheduleRoleLabel(item.role),
        day: Number(item.day_of_week),
        timingLabel: item.timing_label || "",
        executionMode: item.execution_mode || "individual",
        shared: String(item.execution_mode || "") === "shared",
        members: [],
      });
    }
    const group = groups.get(key);
    const userId = Number(item.user_id);
    if (group.members.some((member) => member.userId === userId)) continue;
    const status = item.activity_status || null;
    group.members.push({
      userId,
      responsibilityId: item.id,
      name: employeeName(employeesById[userId] || employeesById[String(userId)], userId),
      status,
      state: memberState(status),
    });
    if (item.timing_label) group.timingLabel = item.timing_label;
    if (String(item.execution_mode || "") === "shared") group.shared = true;
  }
  return [...groups.values()].sort(
    (a, b) => a.day - b.day || a.label.localeCompare(b.label) || a.key.localeCompare(b.key),
  );
}

export function taskGroupCounts(group, employees = []) {
  const members = group?.members || [];
  const assignedIds = new Set(members.map((member) => member.userId));
  return {
    assigned: members.length,
    started: members.filter((member) => STARTED.has(String(member.status || ""))).length,
    completed: members.filter((member) => member.state === "completed").length,
    awaiting: members.filter((member) => member.state === "awaiting").length,
    unassigned: (employees || []).filter((employee) => !assignedIds.has(Number(employee.user_id))).length,
  };
}

export function filterTaskGroups(groups, { day = null, role = "", userId = null, status = "", scope = "day" } = {}) {
  return (groups || []).filter((group) => {
    if (scope !== "week" && day != null && group.day !== Number(day)) return false;
    if (role && group.role !== role) return false;
    if (userId != null && !group.members.some((member) => member.userId === Number(userId))) return false;
    if (status === "not_started") return group.members.every((member) => member.state === "assigned");
    if (status === "started") return group.members.some((member) => member.state === "started" || member.state === "awaiting" || member.state === "completed");
    if (status === "completed") return group.members.some((member) => member.state === "completed");
    if (status === "awaiting") return group.members.some((member) => member.state === "awaiting");
    return true;
  });
}

export function peopleByState(group, state) {
  return (group?.members || []).filter((member) => member.state === state);
}

export function applyDashboardRow(group, row) {
  if (!group || !row) return group;
  const byEmployee = new Map(
    (row.contributions || []).map((item) => [Number(item.employee_id), item]),
  );
  const checklist = (row.contributions || []).find((item) => item.shared_checklist_items)?.shared_checklist_items || null;
  return {
    ...group,
    checklist,
    checklistStatus: row.checklist_status || null,
    members: group.members.map((member) => {
      const item = byEmployee.get(member.userId);
      if (!item) return member;
      const status = item.status || member.status;
      return {
        ...member,
        status,
        state: memberState(status),
        statusLabel: item.status_label || "",
        duration: item.activity?.duration_seconds ?? item.group_duration_seconds ?? null,
        activityId: item.activity?.id || null,
      };
    }),
  };
}

export function matchDashboardAssignment(group, sharedAssignments = []) {
  const memberIds = new Set((group?.members || []).map((member) => Number(member.responsibilityId)));
  return (
    (sharedAssignments || []).find((row) => {
      if (group?.groupId && String(row.assignment_group_id || "") === String(group.groupId)) return true;
      return (row.contributions || []).some((item) => memberIds.has(Number(item.responsibility_id || item.id)));
    }) || null
  );
}

export function recentCompletions(activityLog = [], role = "", limit = 8) {
  return (activityLog || [])
    .filter((item) => !role || String(item.role || "") === String(role))
    .filter((item) => ["completed", "approved", "pending_approval"].includes(String(item.status || "")))
    .slice(0, limit)
    .map((item) => ({
      id: item.id,
      name: item.employee_name || `User #${item.user_id}`,
      status: item.status,
      duration: item.duration_seconds,
      role: item.role,
    }));
}

export function buildEmployeeRows({ employees, entries, responsibilities, day, employeesById = {} }) {
  const tasks = buildTaskGroups(
    (responsibilities || []).filter((item) => Number(item.day_of_week) === Number(day)),
    employeesById,
  );
  return (employees || [])
    .map((employee) => {
      const userId = Number(employee.user_id);
      const shifts = dayEntries(entries, day).filter((entry) => Number(entry.user_id) === userId);
      const assigned = tasks.filter((group) => group.members.some((member) => member.userId === userId));
      const breaks = dayBreaks(shifts, { [userId]: employee }, day);
      return {
        userId,
        name: employeeName(employee, userId),
        shifts,
        shiftLabel: shifts.map(shiftLabel).filter(Boolean).join(", ") || "",
        hasShift: shifts.length > 0,
        breakCount: breaks.timed.length + breaks.untimed.length,
        breakLabel: [
          ...breaks.timed.map((item) => `${item.startLabel}–${item.endLabel}`),
          ...breaks.untimed.map((item) => `${item.minutes} min untimed`),
        ].join(", "),
        tasks: assigned,
        roles: [...new Set(shifts.flatMap((entry) => {
          const assignedRoles = Array.isArray(entry.role_assignments)
            ? entry.role_assignments.map((item) => item?.role).filter(Boolean)
            : [];
          return assignedRoles.length ? assignedRoles : [entry.role].filter(Boolean);
        }))],
      };
    })
    .sort((a, b) => Number(b.hasShift) - Number(a.hasShift) || a.name.localeCompare(b.name));
}

export function weekBreakSummary(entries, employeesById) {
  return DISPLAY_DAY_ORDER.map((day) => {
    const breaks = dayBreaks(entries, employeesById, day);
    return {
      day,
      label: DAY_LABELS[day],
      maxOverlap: maxSimultaneous(breaks.timed),
      overCap: overlapExceedsCap(breaks.timed),
      untimed: breaks.untimed.length,
    };
  });
}

export function timelineScale(intervals, shifts) {
  const points = [];
  for (const item of intervals || []) points.push(item.start, item.end);
  for (const shift of shifts || []) {
    const start = minutes(shift.start_time);
    const end = minutes(shift.end_time);
    if (start != null) points.push(start);
    if (end != null) points.push(end);
  }
  if (!points.length) return { start: 6 * 60, end: 20 * 60 };
  const start = Math.max(0, Math.floor(Math.min(...points) / 60) * 60);
  const end = Math.min(24 * 60, Math.ceil(Math.max(...points) / 60) * 60);
  return { start, end: Math.max(end, start + 60) };
}

export function plannerCsv({ section, day, weekStart, timeline, tasks, employees, week }) {
  const lines = [[`Breaks & tasks`, weekStart || "", DAY_LABELS[day] || ""].join(",")];
  if (section === PLANNER_SECTION.TASKS) {
    lines.push(["Task", "Day", "Assigned", "Started", "Completed", "Awaiting verification", "Unassigned"].join(","));
    for (const group of tasks || []) {
      const counts = taskGroupCounts(group, employees);
      lines.push(
        [group.label, DAY_LABELS[group.day], counts.assigned, counts.started, counts.completed, counts.awaiting, counts.unassigned]
          .map((value) => `"${String(value).replaceAll('"', '""')}"`)
          .join(","),
      );
    }
    return lines;
  }
  if (section === PLANNER_SECTION.EMPLOYEES) {
    lines.push(["Employee", "Shift", "Breaks", "Tasks"].join(","));
    for (const row of employees || []) {
      lines.push(
        [row.name, row.shiftLabel || "No shift", row.breakLabel || "", row.tasks.map((task) => task.label).join("; ")]
          .map((value) => `"${String(value).replaceAll('"', '""')}"`)
          .join(","),
      );
    }
    return lines;
  }
  lines.push(["Employee", "Break start", "Break end", "Duration"].join(","));
  for (const item of timeline?.timed || []) {
    lines.push([item.name, item.startLabel, item.endLabel, item.duration].map((value) => `"${value}"`).join(","));
  }
  lines.push(["Employee", "Untimed break minutes"].join(","));
  for (const item of timeline?.untimed || []) {
    lines.push([item.name, item.minutes].map((value) => `"${value}"`).join(","));
  }
  lines.push(["Day", "Maximum overlap", "Untimed breaks"].join(","));
  for (const item of week || []) lines.push([item.label, item.maxOverlap, item.untimed].join(","));
  return lines;
}
