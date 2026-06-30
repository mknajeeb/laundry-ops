/** Role / day view filters for weekly schedule visibility. */

import { DAY_LABELS } from "./weeklyScheduleDates";
import {
  parseEntryRoles,
  ROLE_STYLES,
  WEEKLY_SCHEDULE_ROLES,
} from "./weeklyScheduleRoles";

export const SCHEDULE_VIEW_ALL = "all";

export function normalizeRoleViewSelection(selectedRoles) {
  if (!Array.isArray(selectedRoles)) return [];
  const valid = new Set(WEEKLY_SCHEDULE_ROLES.map((role) => role.value));
  return [...new Set(selectedRoles.filter((role) => valid.has(role)))];
}

export function hasRoleViewFilter(selectedRoles) {
  return normalizeRoleViewSelection(selectedRoles).length > 0;
}

export function resolveRoleViewRoles(selectedRoles) {
  const roles = normalizeRoleViewSelection(selectedRoles);
  return roles.length ? roles : null;
}

export function roleViewLabel(selectedRoles) {
  const roles = normalizeRoleViewSelection(selectedRoles);
  if (!roles.length) return null;
  return roles.map((role) => ROLE_STYLES[role]?.label || role).join(" · ");
}

export function toggleRoleViewSelection(selectedRoles, roleKey) {
  const roles = normalizeRoleViewSelection(selectedRoles);
  if (roles.includes(roleKey)) {
    return roles.filter((role) => role !== roleKey);
  }
  return [...roles, roleKey];
}

export function entryMatchesRoleView(entry, selectedRoles) {
  const roles = resolveRoleViewRoles(selectedRoles);
  if (!roles) return true;
  const entryRoles = parseEntryRoles(entry);
  return roles.some((role) => entryRoles.includes(role));
}

export function filterEntriesByRoleView(entries, selectedRoles) {
  if (!hasRoleViewFilter(selectedRoles)) return entries || [];
  return (entries || []).filter((entry) => entryMatchesRoleView(entry, selectedRoles));
}

export function filterEntriesByDayView(entries, dayTab) {
  if (!dayTab || dayTab === SCHEDULE_VIEW_ALL) return entries || [];
  const dow = Number(dayTab);
  if (!Number.isInteger(dow) || dow < 0 || dow > 6) return entries || [];
  return (entries || []).filter((entry) => Number(entry.day_of_week) === dow);
}

export function filterEntriesByScheduleView(entries, selectedRoles, dayTab) {
  return filterEntriesByDayView(filterEntriesByRoleView(entries, selectedRoles), dayTab);
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

export function countShiftsMatchingRoles(entries, roleKeys) {
  const keys = roleKeys || [];
  if (!keys.length) return 0;
  let count = 0;
  for (const entry of entries || []) {
    const entryRoles = parseEntryRoles(entry);
    if (keys.some((role) => entryRoles.includes(role))) count += 1;
  }
  return count;
}

export function countDayShifts(entries, dayOfWeek) {
  return (entries || []).filter((entry) => Number(entry.day_of_week) === dayOfWeek).length;
}

export function buildRoleViewTabs(entries) {
  const list = entries || [];
  const tabs = [{ value: SCHEDULE_VIEW_ALL, label: "All", count: list.length }];
  for (const role of WEEKLY_SCHEDULE_ROLES) {
    tabs.push({
      value: role.value,
      label: role.label,
      count: countRoleAssignments(list, role.value),
    });
  }
  return tabs;
}

export const COMPACT_DAY_LABELS = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"];

export function buildDayViewTabs(entries, { compact = false } = {}) {
  const list = entries || [];
  const tabs = [{ value: SCHEDULE_VIEW_ALL, label: compact ? "All" : "All Days", count: list.length }];
  DAY_LABELS.forEach((label, dow) => {
    tabs.push({
      value: String(dow),
      label: compact ? COMPACT_DAY_LABELS[dow] : label,
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

export function filterEmployeesByScheduleView(employees, entries, selectedRoles, dayTab) {
  const filteredEntries = filterEntriesByScheduleView(entries, selectedRoles, dayTab);
  const userIdsWithEntries = new Set(filteredEntries.map((entry) => Number(entry.user_id)));
  return (employees || []).filter((employee) => userIdsWithEntries.has(Number(employee.user_id)));
}

export function scheduleViewSummaryLabel(selectedRoles, dayTab) {
  const parts = [];
  const roleLabel = roleViewLabel(selectedRoles);
  if (roleLabel) parts.push(roleLabel);
  if (dayTab && dayTab !== SCHEDULE_VIEW_ALL) {
    parts.push(DAY_LABELS[Number(dayTab)] || dayTab);
  }
  if (!parts.length) return null;
  return parts.join(" · ");
}
