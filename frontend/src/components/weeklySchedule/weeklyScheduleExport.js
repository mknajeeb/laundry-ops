import { formatTime12 } from "../datetime/scheduleTimeUi";
import {
  computeFilteredDaySummaries,
  employeeScheduleRoles,
  formatRoleHoursLabel,
  HOUR_TRACKED_ROLES,
  parseEntryRoles,
  ROLE_COMPACT_LABELS,
  ROLE_ORDER,
  ROLE_STYLES,
  roleLabels,
  sortRoles,
} from "./weeklyScheduleRoles";
import { DAY_LABELS } from "./weeklyScheduleDates";

/** Excel-safe text — no smart quotes, en-dashes, or middle dots. */
export function exportAsciiText(value) {
  return String(value ?? "")
    .replace(/\u2013|\u2014/g, " - ")
    .replace(/\u00b7/g, " / ")
    .replace(/\u2212/g, "-")
    .replace(/[\u2018\u2019]/g, "'")
    .replace(/[\u201c\u201d]/g, '"')
    .trim();
}

function exportRoleLabels(roles) {
  return sortRoles(roles)
    .map((r) => ROLE_STYLES[r]?.label || r)
    .join(" / ");
}

export function formatShiftEntryText(entry, { showRoleLabels = true, forExport = false, scheduleEndTimeEnabled = true } = {}) {
  const hours = Number(entry.hours || 0);
  const hoursLabel = Number.isInteger(hours) ? `${hours}h` : `${hours.toFixed(1)}h`;
  const roleText = showRoleLabels ? ` ${exportRoleLabels(parseEntryRoles(entry))}` : "";
  const start = formatTime12(entry.start_time);
  const end = formatTime12(entry.end_time);
  const range = scheduleEndTimeEnabled
    ? forExport
      ? `${start} - ${end}`
      : `${start} – ${end}`
    : start;
  const text = scheduleEndTimeEnabled ? `${range} (${hoursLabel})${roleText}` : `${range}${roleText}`;
  return forExport ? exportAsciiText(text) : text;
}

export function formatDayShiftsText(entries, options) {
  const forExport = options?.forExport === true;
  return (entries || [])
    .map((entry) => formatShiftEntryText(entry, { ...options, forExport }))
    .join(forExport ? "; " : "; ");
}

function csvCell(value) {
  const text = exportAsciiText(value);
  if (/[",\n\r]/.test(text)) {
    return `"${text.replace(/"/g, '""')}"`;
  }
  return text;
}

export function formatDayRoleTotalsText(summary, { daysOnly = false, forExport = false } = {}) {
  const parts = [];
  for (const role of ROLE_ORDER) {
    const count = Number(summary?.[role] || 0);
    if (count <= 0) continue;
    const label = ROLE_COMPACT_LABELS[role] || ROLE_STYLES[role]?.label || role;
    if (!daysOnly && HOUR_TRACKED_ROLES.includes(role)) {
      const hours = Number(summary?.[`${role}_hours`] || 0);
      if (hours > 0) {
        parts.push(`${label} ${count} / ${formatRoleHoursLabel(hours)}`);
        continue;
      }
    }
    parts.push(`${label} ${count}`);
  }
  const text = parts.join("; ");
  return forExport ? exportAsciiText(text) : text;
}

export function buildWeeklyScheduleCsvRows({
  employees,
  entries,
  scheduleEndTimeEnabled = true,
  showRoleLabels = true,
  dayLabels = null,
  dayIndices = null,
  daySummaries = null,
}) {
  const columnDays = dayIndices || [0, 1, 2, 3, 4, 5, 6];
  const columnLabels = dayLabels || columnDays.map((dow) => DAY_LABELS[dow]);
  const headers = [
    "Employee",
    "Roles",
    ...columnLabels,
    scheduleEndTimeEnabled ? "Total Hours" : "Total Days",
  ];
  const lines = [headers.map(csvCell).join(",")];

  for (const employee of employees || []) {
    const roles = employeeScheduleRoles(employee.user_id, entries);
    const row = [
      csvCell(employee.display_name),
      csvCell(roles.length ? exportAsciiText(roleLabels(roles).replace(/\u00b7/g, " / ")) : ""),
    ];

    for (const dow of columnDays) {
      const cellEntries = (entries || []).filter(
        (entry) =>
          Number(entry.user_id) === Number(employee.user_id) &&
          Number(entry.day_of_week) === dow,
      );
      row.push(csvCell(formatDayShiftsText(cellEntries, { showRoleLabels, forExport: true, scheduleEndTimeEnabled })));
    }

    if (scheduleEndTimeEnabled) {
      const totalHours = Number(employee.total_hours || 0);
      row.push(Number.isInteger(totalHours) ? String(totalHours) : totalHours.toFixed(1));
    } else {
      row.push(String(Number(employee.scheduled_days || 0)));
    }
    lines.push(row.join(","));
  }

  const summaries =
    daySummaries ||
    computeFilteredDaySummaries(
      { entries, employees },
      { entries, includeExcluded: true },
    );
  const totalsRow = [
    csvCell("Day Role Totals"),
    csvCell(""),
    ...columnDays.map((dow) =>
      csvCell(
        formatDayRoleTotalsText(summaries[dow] || {}, {
          daysOnly: !scheduleEndTimeEnabled,
          forExport: true,
        }),
      ),
    ),
    csvCell(""),
  ];
  lines.push(totalsRow.join(","));

  return lines;
}

export function exportWeeklyScheduleCsv({
  employees,
  entries,
  weekStart,
  tabLabel,
  filename,
  showRoleLabels = true,
  scheduleEndTimeEnabled = true,
  dayLabels = null,
  dayIndices = null,
  daySummaries = null,
}) {
  const lines = buildWeeklyScheduleCsvRows({
    employees,
    entries,
    scheduleEndTimeEnabled,
    showRoleLabels,
    dayLabels,
    dayIndices,
    daySummaries,
  });

  const safeTab = String(tabLabel || "schedule")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
  const downloadName =
    filename || `weekly-schedule-${weekStart}-${safeTab || "schedule"}.csv`;

  const body = `\uFEFF${lines.join("\r\n")}`;
  const blob = new Blob([body], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = downloadName;
  anchor.click();
  URL.revokeObjectURL(url);
}
