import { formatTime12 } from "../datetime/scheduleTimeUi";
import {
  computeFilteredDaySummaries,
  employeeScheduleRoles,
  entryRoleAssignments,
  formatRoleHoursLabel,
  HOUR_TRACKED_ROLES,
  NO_ROLE_LABEL,
  parseEntryRoles,
  ROLE_COMPACT_LABELS,
  ROLE_HOURS_EXPLANATION,
  ROLE_ORDER,
  ROLE_STYLES,
  roleLabels,
  scheduleRoleLabel,
  sortRoles,
} from "./weeklyScheduleRoles";
import { DAY_LABELS } from "./weeklyScheduleDates";
import { dayDateLabel, timeBlockLabel } from "./weeklyScheduleTimeBlocks";

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
    .map((r) => scheduleRoleLabel(r))
    .join(" / ");
}

/** Per-role ranges inside a shift and assignment remarks, e.g. "Sort 2:00 AM - 5:00 AM | Lint Cleaning: Dryers". */
export function formatAssignmentDetails(entry, { scheduleEndTimeEnabled = true } = {}) {
  return entryRoleAssignments(entry)
    .filter((a) => a.remarks || (a.full_shift === false && scheduleEndTimeEnabled))
    .map((a) => {
      const range =
        a.full_shift === false && scheduleEndTimeEnabled
          ? ` ${formatTime12(a.start_time)} - ${formatTime12(a.end_time)}`
          : "";
      return `${scheduleRoleLabel(a.role)}${range}${a.remarks ? `: ${a.remarks}` : ""}`;
    })
    .join(" | ");
}

export function formatResponsibilityText(item, { forExport = false } = {}) {
  const text = `${scheduleRoleLabel(item.role)} (task)${item.remarks ? `: ${item.remarks}` : ""}`;
  return forExport ? exportAsciiText(text) : text;
}

export function formatShiftEntryText(entry, { showRoleLabels = true, forExport = false, scheduleEndTimeEnabled = true } = {}) {
  const hours = Number(entry.hours || 0);
  const hoursLabel = Number.isInteger(hours) ? `${hours}h` : `${hours.toFixed(1)}h`;
  const details = showRoleLabels ? formatAssignmentDetails(entry, { scheduleEndTimeEnabled }) : "";
  const roles = parseEntryRoles(entry);
  const roleText = showRoleLabels
    ? ` ${roles.length ? exportRoleLabels(roles) : NO_ROLE_LABEL}${details ? ` [${details}]` : ""}`
    : "";
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

export function formatDayShiftsText(entries, options, responsibilities = []) {
  const forExport = options?.forExport === true;
  return [
    ...(entries || []).map((entry) => formatShiftEntryText(entry, { ...options, forExport })),
    ...(responsibilities || []).map((item) => formatResponsibilityText(item, { forExport })),
  ].join("; ");
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
  for (const role of sortRoles(ROLE_ORDER)) {
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
  responsibilities = [],
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
      const cellResponsibilities = (responsibilities || []).filter(
        (item) => Number(item.user_id) === Number(employee.user_id) && Number(item.day_of_week) === dow,
      );
      row.push(
        csvCell(
          formatDayShiftsText(
            cellEntries,
            { showRoleLabels, forExport: true, scheduleEndTimeEnabled },
            cellResponsibilities,
          ),
        ),
      );
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

function csvFileName({ weekStart, tabLabel, filename }) {
  const safeTab = String(tabLabel || "schedule")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
  return filename || `weekly-schedule-${weekStart}-${safeTab || "schedule"}.csv`;
}

function downloadCsv(lines, downloadName) {
  const body = `\uFEFF${lines.join("\r\n")}`;
  const blob = new Blob([body], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = downloadName;
  anchor.click();
  URL.revokeObjectURL(url);
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
  responsibilities = [],
}) {
  const lines = buildWeeklyScheduleCsvRows({
    employees,
    entries,
    scheduleEndTimeEnabled,
    showRoleLabels,
    dayLabels,
    dayIndices,
    daySummaries,
    responsibilities,
  });
  downloadCsv(lines, csvFileName({ weekStart, tabLabel, filename }));
}

function peopleRemarks(people) {
  return people
    .filter((person) => person.remarks)
    .map((person) => `${person.name}: ${person.remarks}`)
    .join("; ");
}

/** Employee hours and role hours/resources sections appended to the time-and-role export. */
export function buildHoursSummaryCsvRows(summary) {
  if (!summary) return [];
  const hours = (value) => String(Math.round(Number(value || 0) * 100) / 100);
  const lines = ["", csvCell("Employee hours"), ["Employee", "Hours"].map(csvCell).join(",")];
  for (const row of summary.employees) lines.push([csvCell(row.name), hours(row.hours)].join(","));
  lines.push([csvCell(`Total (${summary.employees.length} employees)`), hours(summary.totalHours)].join(","));
  lines.push("", csvCell("Role hours & resources"), ["Role", "Employees", "Hours"].map(csvCell).join(","));
  for (const row of summary.roles) lines.push([csvCell(row.label), String(row.employees), hours(row.hours)].join(","));
  if (summary.unassignedHours > 0) {
    lines.push([csvCell("Shift time without a role"), "", hours(summary.unassignedHours)].join(","));
  }
  lines.push([csvCell("Total role hours"), "", hours(summary.roleTotal)].join(","));
  lines.push("", csvCell(ROLE_HOURS_EXPLANATION));
  return lines;
}

/** By Time & Role export: one row per day / time block / role, then that day's tasks. */
export function buildTimeRoleCsvRows({ days, weekStart, scheduleEndTimeEnabled = true, hoursSummary = null }) {
  const headers = ["Day", "Date", "Time", "Role", "Count", "Employees", "Remarks"];
  const lines = [headers.map(csvCell).join(",")];
  for (const day of days || []) {
    const dayCells = [csvCell(DAY_LABELS[day.dow]), csvCell(dayDateLabel(weekStart, day.dow))];
    for (const block of day.blocks) {
      const time = timeBlockLabel(block, scheduleEndTimeEnabled, " - ");
      for (const group of block.roles) {
        lines.push(
          [
            ...dayCells,
            csvCell(time),
            csvCell(group.label),
            String(group.count),
            csvCell(group.people.map((person) => person.name).join(", ")),
            csvCell(peopleRemarks(group.people)),
          ].join(","),
        );
      }
    }
    for (const group of day.responsibilities) {
      lines.push(
        [
          ...dayCells,
          csvCell("Task"),
          csvCell(group.label),
          String(group.count),
          csvCell(group.people.map((person) => person.name).join(", ")),
          csvCell(peopleRemarks(group.people)),
        ].join(","),
      );
    }
  }
  return [...lines, ...buildHoursSummaryCsvRows(hoursSummary)];
}

export function exportWeeklyScheduleTimeRoleCsv({
  days,
  weekStart,
  tabLabel,
  scheduleEndTimeEnabled = true,
  hoursSummary = null,
}) {
  const lines = buildTimeRoleCsvRows({ days, weekStart, scheduleEndTimeEnabled, hoursSummary });
  downloadCsv(lines, csvFileName({ weekStart, tabLabel: `${tabLabel || "schedule"} by time and role` }));
}
