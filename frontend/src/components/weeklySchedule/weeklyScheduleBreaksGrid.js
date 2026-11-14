import { formatTime12 } from "../datetime/scheduleTimeUi";
import { scheduleRoleCatalog, scheduleRoleLabel, sortRoles } from "./weeklyScheduleRoles";
import { assignmentKey, taskExecutionLabel, taskGroupLabel, taskTimingIssues, taskTimingLabel } from "./weeklyScheduleTaskTiming";

function shiftWindowLabel(entry) {
  const start = formatTime12(entry?.start_time);
  const end = formatTime12(entry?.end_time);
  if (!start || !end) return "";
  return `${start}–${end}`;
}

function employeeName(employeesById, userId) {
  const employee = employeesById?.[userId] || employeesById?.[String(userId)];
  return employee?.display_name || `User #${userId}`;
}

/** Active task types (no times, no hours) plus any task type already assigned. */
export function taskRoleOptions(responsibilities = []) {
  const codes = new Set(
    scheduleRoleCatalog()
      .filter((role) => role.uses_time_slots === false && role.active !== false)
      .map((role) => role.code),
  );
  for (const item of responsibilities || []) {
    if (item?.role) codes.add(item.role);
  }
  return sortRoles([...codes]);
}

/** Tasks of the selected task types (null = every type, [] = none). */
export function filterResponsibilitiesByTaskSelection(responsibilities, selection) {
  if (!Array.isArray(selection)) return responsibilities || [];
  const chosen = new Set(selection);
  return (responsibilities || []).filter((item) => chosen.has(item.role));
}

/**
 * Breaks & tasks as a grid: shown days as columns, employees as rows.
 *
 * `days` comes from buildHourlyCoverage for the schedule scope, with no role filter. `shiftEntries`
 * are that scope's shifts, including shifts that have no role. `roster` lists every eligible employee
 * so someone with no shift and no task still appears. `responsibilities` follow the task filter only.
 * `taskTypes` limits the unassigned-task row (null = every task type).
 */
export function buildBreaksTasksGrid({
  days = [],
  dayIndices = [1, 2, 3, 4, 5, 6, 0],
  shiftEntries = [],
  timingEntries = null,
  responsibilities = [],
  employeesById = {},
  roster = [],
  includeBreaks = true,
  taskTypes = null,
} = {}) {
  const shown = new Set(dayIndices);
  const rows = new Map();
  const rowFor = (userId) => {
    const uid = Number(userId);
    if (!rows.has(uid)) {
      rows.set(uid, {
        userId: uid,
        name: employeeName(employeesById, uid),
        breakHours: 0,
        taskCount: 0,
        unscheduledTaskDays: 0,
        cells: {},
      });
    }
    return rows.get(uid);
  };
  const cellFor = (row, dow) => {
    if (!row.cells[dow]) row.cells[dow] = { hasShift: false, shifts: [], timed: [], untimed: [], tasks: [] };
    return row.cells[dow];
  };

  for (const employee of roster || []) {
    const uid = Number(employee?.user_id ?? employee?.userId);
    if (uid) rowFor(uid);
  }

  const dayByDow = new Map((days || []).map((day) => [day.dow, day]));
  for (const entry of shiftEntries || []) {
    const dow = Number(entry.day_of_week);
    if (!shown.has(dow)) continue;
    const cell = cellFor(rowFor(entry.user_id), dow);
    cell.hasShift = true;
    const shiftId = entry.id ?? `${entry.user_id}-${dow}-${entry.start_time || ""}`;
    if (!cell.shifts.some((shift) => shift.id === shiftId)) {
      cell.shifts.push({ id: shiftId, label: shiftWindowLabel(entry) });
    }
  }
  if (includeBreaks) {
    for (const day of days || []) {
      if (!shown.has(day.dow)) continue;
      for (const range of day.breakRanges || []) {
        const row = rowFor(range.userId);
        const cell = cellFor(row, day.dow);
        cell.hasShift = true;
        cell.timed.push(range);
        row.breakHours += range.hours;
      }
      for (const item of day.unscheduledBreaks || []) {
        const row = rowFor(item.userId);
        const cell = cellFor(row, day.dow);
        cell.hasShift = true;
        cell.untimed.push(item);
        row.breakHours += item.hours;
      }
    }
  }

  const assignedByDay = new Map();
  const assignmentsByDay = new Map();
  for (const item of responsibilities || []) {
    const dow = Number(item.day_of_week);
    if (!shown.has(dow)) continue;
    const key = assignmentKey(item);
    const namesLabel = taskGroupLabel(item, employeesById);
    const row = rowFor(item.user_id);
    cellFor(row, dow).tasks.push({
      key: `r${item.id}`,
      assignmentKey: key,
      item,
      role: item.role,
      label: scheduleRoleLabel(item.role),
      remarks: item.remarks || null,
      namesLabel,
      executionLabel: taskExecutionLabel(item),
      timingLabel: taskTimingLabel(item),
      warnings: taskTimingIssues(item, timingEntries || shiftEntries, employeesById).warnings,
    });
    row.taskCount += 1;
    if (!assignedByDay.has(dow)) assignedByDay.set(dow, new Set());
    assignedByDay.get(dow).add(item.role);
    if (!assignmentsByDay.has(dow)) assignmentsByDay.set(dow, new Set());
    assignmentsByDay.get(dow).add(key);
  }
  const order = new Map(sortRoles([...new Set((responsibilities || []).map((item) => item.role))]).map((role, i) => [role, i]));
  for (const row of rows.values()) {
    let unscheduledTaskDays = 0;
    for (const cell of Object.values(row.cells)) {
      cell.tasks.sort((a, b) => (order.get(a.role) ?? 0) - (order.get(b.role) ?? 0));
      if (cell.tasks.length && !cell.hasShift) unscheduledTaskDays += 1;
    }
    row.unscheduledTaskDays = unscheduledTaskDays;
  }

  const catalogTasks = scheduleRoleCatalog()
    .filter((role) => role.uses_time_slots === false && role.active !== false)
    .map((role) => role.code)
    .filter((code) => !Array.isArray(taskTypes) || taskTypes.includes(code));

  const columns = dayIndices.map((dow) => {
    const day = dayByDow.get(dow);
    const assigned = assignedByDay.get(dow) || new Set();
    const timedBreakHours = includeBreaks ? Number(day?.breakTotal?.hours || 0) : 0;
    const untimedBreakHours = includeBreaks ? Number(day?.unscheduledBreakTotal?.hours || 0) : 0;
    return {
      dow,
      timedBreakHours,
      untimedBreakHours,
      breakHours: timedBreakHours + untimedBreakHours,
      breakCount: includeBreaks ? (day?.breakRanges?.length || 0) + (day?.unscheduledBreaks?.length || 0) : 0,
      taskCount: assignmentsByDay.get(dow)?.size || 0,
      unassignedTasks: sortRoles(catalogTasks.filter((code) => !assigned.has(code))),
    };
  });

  return {
    columns,
    rows: [...rows.values()].sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" })),
  };
}

/** Keep the rows whose names match the employee search, and recount that day's visible breaks and tasks. */
export function filterBreaksGridByEmployee(grid, query) {
  if (!grid) return grid;
  const q = String(query || "").trim().toLowerCase();
  if (!q) return grid;
  const rows = (grid.rows || []).filter((row) => String(row.name || "").toLowerCase().includes(q));
  const columns = (grid.columns || []).map((column) => {
    let breakCount = 0;
    let timedBreakHours = 0;
    let untimedBreakHours = 0;
    const assignments = new Set();
    for (const row of rows) {
      const cell = row.cells?.[column.dow];
      if (!cell) continue;
      breakCount += (cell.timed?.length || 0) + (cell.untimed?.length || 0);
      timedBreakHours += (cell.timed || []).reduce((sum, range) => sum + Number(range.hours || 0), 0);
      untimedBreakHours += (cell.untimed || []).reduce((sum, item) => sum + Number(item.hours || 0), 0);
      for (const task of cell.tasks || []) assignments.add(task.assignmentKey || task.key);
    }
    return {
      ...column,
      breakCount,
      timedBreakHours,
      untimedBreakHours,
      breakHours: timedBreakHours + untimedBreakHours,
      taskCount: assignments.size,
    };
  });
  return { ...grid, rows, columns };
}

/** Tasks of each shown day with the employee's name, from the same grid rows (by task type, then name). */
export function gridTasksByDay(grid) {
  const roles = new Set();
  for (const row of grid?.rows || []) {
    for (const cell of Object.values(row.cells)) cell.tasks.forEach((task) => roles.add(task.role));
  }
  const order = new Map(sortRoles([...roles]).map((role, i) => [role, i]));
  return Object.fromEntries(
    (grid?.columns || []).map((column) => {
      const tasks = [];
      const seen = new Set();
      for (const row of grid?.rows || []) {
        for (const task of row.cells[column.dow]?.tasks || []) {
          const key = task.assignmentKey || task.key;
          if (seen.has(key)) continue;
          seen.add(key);
          tasks.push({ ...task, key, userId: row.userId, name: task.namesLabel || row.name });
        }
      }
      tasks.sort(
        (a, b) =>
          (order.get(a.role) ?? 0) - (order.get(b.role) ?? 0) || a.name.localeCompare(b.name, undefined, { sensitivity: "base" }),
      );
      return [column.dow, tasks];
    }),
  );
}

/** "Breaks 1.5h · 0.5h not scheduled" for a day header ("" without breaks). */
export function gridDayBreakText(column, formatHours) {
  if (!column.breakHours) return "";
  const notScheduled = column.untimedBreakHours > 0.0001 ? ` · ${formatHours(column.untimedBreakHours)} not scheduled` : "";
  return `Breaks ${formatHours(column.breakHours)}${notScheduled}`;
}

export function gridDayTaskText(column) {
  return `${column.taskCount} ${column.taskCount === 1 ? "task" : "tasks"}`;
}
