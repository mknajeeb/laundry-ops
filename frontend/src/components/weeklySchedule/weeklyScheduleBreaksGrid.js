import { scheduleRoleCatalog, scheduleRoleLabel, sortRoles } from "./weeklyScheduleRoles";

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
 * `days` comes from buildHourlyCoverage (already limited to the selected roles), so break figures are
 * the same ones the hourly views use. `shiftEntries` are the shifts in the selected roles, used to mark
 * employee-days that have a shift but no planned break. `responsibilities` are listed independently of
 * the role selection so tasks never disappear because timed roles are unchecked. `taskTypes` limits the
 * unassigned-task row (null = every task type).
 */
export function buildBreaksTasksGrid({
  days = [],
  dayIndices = [0, 1, 2, 3, 4, 5, 6],
  shiftEntries = [],
  responsibilities = [],
  employeesById = {},
  includeBreaks = true,
  taskTypes = null,
} = {}) {
  const shown = new Set(dayIndices);
  const rows = new Map();
  const rowFor = (userId) => {
    const uid = Number(userId);
    if (!rows.has(uid)) {
      rows.set(uid, { userId: uid, name: employeeName(employeesById, uid), breakHours: 0, taskCount: 0, cells: {} });
    }
    return rows.get(uid);
  };
  const cellFor = (row, dow) => {
    if (!row.cells[dow]) row.cells[dow] = { hasShift: false, timed: [], untimed: [], tasks: [] };
    return row.cells[dow];
  };

  const dayByDow = new Map((days || []).map((day) => [day.dow, day]));
  if (includeBreaks) {
    for (const entry of shiftEntries || []) {
      const dow = Number(entry.day_of_week);
      if (!shown.has(dow)) continue;
      cellFor(rowFor(entry.user_id), dow).hasShift = true;
    }
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
  for (const item of responsibilities || []) {
    const dow = Number(item.day_of_week);
    if (!shown.has(dow)) continue;
    const row = rowFor(item.user_id);
    cellFor(row, dow).tasks.push({
      key: `r${item.id}`,
      item,
      role: item.role,
      label: scheduleRoleLabel(item.role),
      remarks: item.remarks || null,
    });
    row.taskCount += 1;
    if (!assignedByDay.has(dow)) assignedByDay.set(dow, new Set());
    assignedByDay.get(dow).add(item.role);
  }
  const order = new Map(sortRoles([...new Set((responsibilities || []).map((item) => item.role))]).map((role, i) => [role, i]));
  for (const row of rows.values()) {
    for (const cell of Object.values(row.cells)) {
      cell.tasks.sort((a, b) => (order.get(a.role) ?? 0) - (order.get(b.role) ?? 0));
    }
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
      taskCount: (responsibilities || []).filter((item) => Number(item.day_of_week) === dow).length,
      unassignedTasks: sortRoles(catalogTasks.filter((code) => !assigned.has(code))),
    };
  });

  return {
    columns,
    rows: [...rows.values()].sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" })),
  };
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
