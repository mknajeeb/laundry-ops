import { parseTimeToMinutes } from "../../payroll/schedulePlanner";
import { formatTime12, normalizeTimeHm } from "../datetime/scheduleTimeUi";
import { entryRoleAssignments, scheduleRoleLabel, sortRoles } from "./weeklyScheduleRoles";

export const ASSIGNMENT_KIND = { SHIFT: "shift", RESPONSIBILITY: "responsibility" };

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

export function timeBlockLabel(block, endTimeEnabled = true, separator = " – ") {
  if (!block?.start_time) return "";
  if (!endTimeEnabled || !block.end_time) return formatTime12(block.start_time);
  return `${formatTime12(block.start_time)}${separator}${formatTime12(block.end_time)}`;
}

const ALL_DAYS = [0, 1, 2, 3, 4, 5, 6];

function blockSortKey(start, end) {
  const s = parseTimeToMinutes(start);
  let e = parseTimeToMinutes(end);
  if (s == null) return [Number.MAX_SAFE_INTEGER, 0];
  if (e == null) return [s, 0];
  if (e <= s) e += 24 * 60;
  return [s, e - s];
}

function employeeName(employeesById, userId) {
  const employee = employeesById?.[userId] || employeesById?.[String(userId)];
  return employee?.display_name || `User #${userId}`;
}

function byName(a, b) {
  return a.name.localeCompare(b.name, undefined, { sensitivity: "base" });
}

/**
 * Week schedule organized by day → time block → role, from the same entries as the employee grid.
 *
 * A time block is every role assignment sharing an exact start + end, so overlapping but different
 * ranges stay separate blocks. Assignments with their own range inside a shift land in the block
 * for that range (not the parent shift's). Roles follow the configured display order.
 * Daily responsibilities (no time slots) are returned per day, grouped by role.
 */
export function buildTimeRoleDays(
  entries,
  {
    dayIndices = ALL_DAYS,
    employeesById = {},
    responsibilities = [],
    selectedRoles = null,
    endTimeEnabled = true,
  } = {},
) {
  const roleFilter = selectedRoles?.length ? new Set(selectedRoles) : null;

  return dayIndices.map((dow) => {
    const blocks = new Map();
    for (const entry of entries || []) {
      if (Number(entry.day_of_week) !== dow) continue;
      for (const assignment of entryRoleAssignments(entry)) {
        if (roleFilter && !roleFilter.has(assignment.role)) continue;
        const start = normalizeTimeHm(assignment.start_time) || "";
        const end = endTimeEnabled ? normalizeTimeHm(assignment.end_time) || "" : "";
        const key = `${start}|${end}`;
        if (!blocks.has(key)) blocks.set(key, { key, start_time: start, end_time: end, roles: new Map() });
        const block = blocks.get(key);
        if (!block.roles.has(assignment.role)) {
          block.roles.set(assignment.role, {
            role: assignment.role,
            label: scheduleRoleLabel(assignment.role),
            people: [],
          });
        }
        block.roles.get(assignment.role).people.push({
          key: `${entry.id}:${assignment.role}:${start}`,
          entry,
          userId: Number(entry.user_id),
          name: employeeName(employeesById, entry.user_id),
          remarks: assignment.remarks || null,
          fullShift: assignment.full_shift !== false,
        });
      }
    }

    const sortedBlocks = [...blocks.values()]
      .map((block) => {
        const roleOrder = sortRoles([...block.roles.keys()]);
        const roles = roleOrder.map((role) => {
          const group = block.roles.get(role);
          const people = [...group.people].sort(byName);
          return { ...group, people, count: new Set(people.map((p) => p.userId)).size };
        });
        return { key: block.key, start_time: block.start_time, end_time: block.end_time, roles };
      })
      .sort((a, b) => {
        const [as, ad] = blockSortKey(a.start_time, a.end_time);
        const [bs, bd] = blockSortKey(b.start_time, b.end_time);
        return as - bs || ad - bd;
      });

    const dayResponsibilities = new Map();
    for (const item of responsibilities || []) {
      if (Number(item.day_of_week) !== dow) continue;
      if (roleFilter && !roleFilter.has(item.role)) continue;
      if (!dayResponsibilities.has(item.role)) {
        dayResponsibilities.set(item.role, { role: item.role, label: scheduleRoleLabel(item.role), people: [] });
      }
      dayResponsibilities.get(item.role).people.push({
        key: `r${item.id}`,
        item,
        userId: Number(item.user_id),
        name: employeeName(employeesById, item.user_id),
        remarks: item.remarks || null,
      });
    }
    const responsibilityGroups = sortRoles([...dayResponsibilities.keys()]).map((role) => {
      const group = dayResponsibilities.get(role);
      const people = [...group.people].sort(byName);
      return { ...group, people, count: people.length };
    });

    return { dow, blocks: sortedBlocks, responsibilities: responsibilityGroups };
  });
}
