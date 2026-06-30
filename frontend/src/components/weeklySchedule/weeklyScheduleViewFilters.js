/** Role / day view tabs for weekly schedule visibility. */

import { DAY_LABELS } from "./weeklyScheduleDates";
import {
  parseEntryRoles,
  ROLE_STYLES,
  WEEKLY_SCHEDULE_ROLES,
} from "./weeklyScheduleRoles";

export const SCHEDULE_VIEW_ALL = "all";

export function entryMatchesRoleView(entry, roleTab) {
  if (!roleTab || roleTab === SCHEDULE_VIEW_ALL) return true;
  return parseEntryRoles(entry).includes(roleTab);
}

export function filterEntriesByRoleView(entries, roleTab) {
  if (!roleTab || roleTab === SCHEDULE_VIEW_ALL) return entries || [];
  return (entries || []).filter((entry) => entryMatchesRoleView(entry, roleTab));
}

export function filterEntriesByDayView(entries, dayTab) {
  if (!dayTab || dayTab === SCHEDULE_VIEW_ALL) return entries || [];
  const dow = Number(dayTab);
  if (!Number.isInteger(dow) || dow < 0 || dow > 6) return entries || [];
  return (entries || []).filter((entry) => Number(entry.day_of_week) === dow);
}

export function filterEntriesByScheduleView(entries, roleTab, dayTab) {
  return filterEntriesByDayView(filterEntriesByRoleView(entries, roleTab), dayTab);
}

export function countRoleAssignments(entries, roleKey) {
  let count = 0;
  for (const entry of entries || []) {
    for (const role of parseEntryRoles(entry)) {
      if (role === roleKey) count += 1;
    }
  }
  return count;
}

export function countDayShifts(entries, dayOfWeek) {
  return (entries || []).filter((entry) => Number(entry.day_of_week) === dayOfWeek).length;
}

export function buildRoleViewTabs(entries) {
  const list = entries || [];
  const tabs = [{ value: SCHEDULE_VIEW_ALL, label: "All Roles", count: list.length }];
  for (const role of WEEKLY_SCHEDULE_ROLES) {
    tabs.push({
      value: role.value,
      label: role.label,
      count: countRoleAssignments(list, role.value),
    });
  }
  return tabs;
}

export function buildDayViewTabs(entries) {
  const list = entries || [];
  const tabs = [{ value: SCHEDULE_VIEW_ALL, label: "All Days", count: list.length }];
  DAY_LABELS.forEach((label, dow) => {
    tabs.push({
      value: String(dow),
      label,
      count: countDayShifts(list, dow),
    });
  });
  return tabs;
}

export function visibleDayIndices(dayTab) {
  if (!dayTab || dayTab === SCHEDULE_VIEW_ALL) return [0, 1, 2, 3, 4, 5, 6];
  const dow = Number(dayTab);
  if (!Number.isInteger(dow) || dow < 0 || dow > 6) return [0, 1, 2, 3, 4, 5, 6];
  return [dow];
}

export function filterEmployeesByScheduleView(employees, entries, roleTab, dayTab) {
  const filteredEntries = filterEntriesByScheduleView(entries, roleTab, dayTab);
  const userIdsWithEntries = new Set(filteredEntries.map((entry) => Number(entry.user_id)));
  return (employees || []).filter((employee) => userIdsWithEntries.has(Number(employee.user_id)));
}

export function scheduleViewSummaryLabel(roleTab, dayTab) {
  const parts = [];
  if (roleTab && roleTab !== SCHEDULE_VIEW_ALL) {
    parts.push(ROLE_STYLES[roleTab]?.label || roleTab);
  }
  if (dayTab && dayTab !== SCHEDULE_VIEW_ALL) {
    parts.push(DAY_LABELS[Number(dayTab)] || dayTab);
  }
  if (!parts.length) return null;
  return parts.join(" · ");
}
