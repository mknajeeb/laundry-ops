/** Role / day view tabs for weekly schedule visibility. */

import { DAY_LABELS } from "./weeklyScheduleDates";
import {
  parseEntryRoles,
  ROLE_STYLES,
  WEEKLY_SCHEDULE_ROLES,
} from "./weeklyScheduleRoles";

export const SCHEDULE_VIEW_ALL = "all";
export const ROLE_GROUP_PREFIX = "group:";

/** Management role groups — filter shifts that include any role in the group. */
export const SCHEDULE_ROLE_GROUPS = [
  {
    value: `${ROLE_GROUP_PREFIX}production`,
    label: "Production",
    roles: ["wash", "sort", "weigher", "fold"],
  },
  {
    value: `${ROLE_GROUP_PREFIX}hd`,
    label: "HD",
    roles: ["hd_operator", "hd_folder"],
  },
  {
    value: `${ROLE_GROUP_PREFIX}support`,
    label: "Support",
    roles: ["non_rinse_folder", "attendant"],
  },
];

export function isRoleGroupTab(roleTab) {
  return String(roleTab || "").startsWith(ROLE_GROUP_PREFIX);
}

export function resolveRoleViewRoles(roleTab) {
  if (!roleTab || roleTab === SCHEDULE_VIEW_ALL) return null;
  if (isRoleGroupTab(roleTab)) {
    const group = SCHEDULE_ROLE_GROUPS.find((item) => item.value === roleTab);
    return group?.roles?.length ? group.roles : null;
  }
  return [roleTab];
}

export function roleViewLabel(roleTab) {
  if (!roleTab || roleTab === SCHEDULE_VIEW_ALL) return null;
  if (isRoleGroupTab(roleTab)) {
    return SCHEDULE_ROLE_GROUPS.find((item) => item.value === roleTab)?.label || roleTab;
  }
  return ROLE_STYLES[roleTab]?.label || roleTab;
}

export function entryMatchesRoleView(entry, roleTab) {
  const roles = resolveRoleViewRoles(roleTab);
  if (!roles) return true;
  const entryRoles = parseEntryRoles(entry);
  return roles.some((role) => entryRoles.includes(role));
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
  const tabs = [{ value: SCHEDULE_VIEW_ALL, label: "All", count: list.length, isGroup: false }];
  for (const group of SCHEDULE_ROLE_GROUPS) {
    tabs.push({
      value: group.value,
      label: group.label,
      count: countShiftsMatchingRoles(list, group.roles),
      isGroup: true,
    });
  }
  for (const role of WEEKLY_SCHEDULE_ROLES) {
    tabs.push({
      value: role.value,
      label: role.label,
      count: countRoleAssignments(list, role.value),
      isGroup: false,
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

export function filterEmployeesByScheduleView(employees, entries, roleTab, dayTab) {
  const filteredEntries = filterEntriesByScheduleView(entries, roleTab, dayTab);
  const userIdsWithEntries = new Set(filteredEntries.map((entry) => Number(entry.user_id)));
  return (employees || []).filter((employee) => userIdsWithEntries.has(Number(employee.user_id)));
}

export function scheduleViewSummaryLabel(roleTab, dayTab) {
  const parts = [];
  const roleLabel = roleViewLabel(roleTab);
  if (roleLabel) parts.push(roleLabel);
  if (dayTab && dayTab !== SCHEDULE_VIEW_ALL) {
    parts.push(DAY_LABELS[Number(dayTab)] || dayTab);
  }
  if (!parts.length) return null;
  return parts.join(" · ");
}
