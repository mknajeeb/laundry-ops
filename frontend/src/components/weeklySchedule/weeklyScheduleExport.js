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
import { compactClock, dayDateLabel, hourLabel, HOURLY_COVERAGE_EXPLANATION } from "./weeklyScheduleTimeBlocks";

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

/** Employee hours and role hours/resources sections appended to the hourly coverage export. */
export function buildHoursSummaryCsvRows(summary) {
  if (!summary) return [];
  const hours = (value) => String(Math.round(Number(value || 0) * 100) / 100);
  const lines = ["", csvCell("Employee hours"), ["Employee", "Hours"].map(csvCell).join(",")];
  for (const row of summary.employees) lines.push([csvCell(row.name), hours(row.hours)].join(","));
  lines.push([csvCell(`Total (${summary.employees.length} employees)`), hours(summary.totalHours)].join(","));
  lines.push("", csvCell("Role hours & resources"), ["Role", "Employees", "Hours"].map(csvCell).join(","));
  for (const row of summary.roles) lines.push([csvCell(row.label), String(row.employees), hours(row.hours)].join(","));
  if (summary.unassignedHours > 0) {
    lines.push([csvCell(summary.unassignedLabel || "Shift time without a role"), "", hours(summary.unassignedHours)].join(","));
  }
  lines.push([csvCell("Total role hours"), "", hours(summary.roleTotal)].join(","));
  lines.push("", csvCell(ROLE_HOURS_EXPLANATION));
  return lines;
}

function coverageHours(value) {
  return String(Math.round(Number(value || 0) * 100) / 100);
}

/** "A: 2-3; B: 2:30-3 (split, 0.25h)" — names with partial-hour times. */
export function coveragePeopleText(people) {
  return people
    .map((person) => {
      const range = person.partial
        ? ` ${person.ranges.map(([a, b]) => `${compactClock(a)}-${compactClock(b)}`).join(", ")}`
        : "";
      const split = person.shared ? ` (split, ${coverageHours(person.hours)}h)` : "";
      return `${person.name}${range ? `:${range}` : ""}${split}`;
    })
    .join("; ");
}

/**
 * Hourly coverage export: per day, one row per hour and selected role (people, employee-hours,
 * cumulative hours, names with partial coverage), an all-roles row per hour, daily role totals, then tasks.
 */
export function buildHourlyCoverageCsvRows({ days, weekStart, columns, hoursSummary = null }) {
  const headers = ["Day", "Date", "Hour", "Role", "People", "Role hours", "Cumulative role hours", "Employees and coverage"];
  const lines = [headers.map(csvCell).join(",")];
  for (const day of days || []) {
    const dayCells = [csvCell(DAY_LABELS[day.dow]), csvCell(dayDateLabel(weekStart, day.dow))];
    for (const row of day.hours) {
      const hour = csvCell(hourLabel(row.hour, "-"));
      for (const role of columns) {
        const cell = row.cells[role];
        if (!cell?.count) continue;
        lines.push(
          [
            ...dayCells,
            hour,
            csvCell(scheduleRoleLabel(role)),
            String(cell.count),
            coverageHours(cell.hours),
            coverageHours(cell.cumulative),
            csvCell(coveragePeopleText(cell.people)),
          ].join(","),
        );
      }
      lines.push(
        [
          ...dayCells,
          hour,
          csvCell(row.gap ? (row.scheduled ? `No role coverage (${row.scheduled} scheduled)` : "No one scheduled") : "All shown roles"),
          String(row.total.count),
          coverageHours(row.total.hours),
          coverageHours(row.total.cumulative),
          "",
        ].join(","),
      );
    }
    for (const role of columns) {
      const total = day.totals[role];
      if (!total) continue;
      lines.push(
        [...dayCells, csvCell("Day total"), csvCell(scheduleRoleLabel(role)), String(total.count), coverageHours(total.hours), "", ""].join(","),
      );
    }
    if (day.hours.length) {
      lines.push(
        [...dayCells, csvCell("Day total"), csvCell("All shown roles"), String(day.overall.count), coverageHours(day.overall.hours), "", ""].join(","),
      );
    }
    for (const group of day.responsibilities) {
      lines.push(
        [
          ...dayCells,
          csvCell("Task"),
          csvCell(group.label),
          String(group.count),
          "",
          "",
          csvCell(group.people.map((person) => (person.remarks ? `${person.name}: ${person.remarks}` : person.name)).join("; ")),
        ].join(","),
      );
    }
  }
  lines.push("", csvCell(HOURLY_COVERAGE_EXPLANATION));
  return [...lines, ...buildHoursSummaryCsvRows(hoursSummary)];
}

export function exportWeeklyScheduleHourlyCsv({ days, weekStart, columns, tabLabel, hoursSummary = null }) {
  const lines = buildHourlyCoverageCsvRows({ days, weekStart, columns, hoursSummary });
  downloadCsv(lines, csvFileName({ weekStart, tabLabel: `${tabLabel || "schedule"} hourly coverage` }));
}
