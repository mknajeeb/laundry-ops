import { formatTime12 } from "../datetime/scheduleTimeUi";
import {
  computeFilteredDaySummaries,
  employeeScheduleRoles,
  entryBreakBreakdown,
  entryBreakLines,
  entryRoleAssignments,
  entryRoleScopeView,
  formatHoursBreakdown,
  formatRoleResourcesLabel,
  NO_ROLE_LABEL,
  parseEntryRoles,
  ROLE_HOURS_EXPLANATION,
  roleLabels,
  scheduleEntryKey,
  scheduleRoleLabel,
  sortRoles,
} from "./weeklyScheduleRoles";
import { DAY_LABELS } from "./weeklyScheduleDates";
import { compactClock, dayDateLabel, hourLabel, HOURLY_COVERAGE_EXPLANATION } from "./weeklyScheduleTimeBlocks";

/** Excel-safe text — no smart quotes, en-dashes, or middle dots. */
export function exportAsciiText(value) {
  return String(value ?? "")
    .replace(/\u2013|\u2014/g, " - ")
    .replace(/ *\u00b7 */g, " / ")
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

/**
 * With a role selection (`roleFilter` + the shift's `roleScope`), only the selected roles' segments,
 * net hours, and breaks are written, e.g. "9:00 AM - 1:00 PM (3.5h net, Break 11:00 AM - 11:30 AM) Fold".
 */
function formatScopedShiftEntryText(entry, { showRoleLabels, forExport, scheduleEndTimeEnabled, showBreaks, roleFilter, roleScope }) {
  const view = entryRoleScopeView(entry, roleFilter, roleScope, { separator: forExport ? " - " : " \u2013 " });
  const roleText = showRoleLabels ? ` ${exportRoleLabels(view.roles)}` : "";
  if (!scheduleEndTimeEnabled) {
    const text = `${formatTime12(entry.start_time)}${roleText}`;
    return forExport ? exportAsciiText(text) : text;
  }
  const breakLines = showBreaks ? view.breaks : [];
  const net = showBreaks && entryBreakBreakdown(entry).breakMinutes > 0 ? " net" : "";
  const hours = Math.round(view.hours * 100) / 100;
  const range = view.segments.length
    ? view.segments.map((segment) => segment.label).join(", ")
    : `${formatTime12(entry.start_time)}${forExport ? " - " : " \u2013 "}${formatTime12(entry.end_time)}`;
  const text = `${range} (${hours}h${net}${breakLines.length ? `, ${breakLines.join(", ")}` : ""})${roleText}`;
  return forExport ? exportAsciiText(text) : text;
}

export function formatShiftEntryText(
  entry,
  {
    showRoleLabels = true,
    forExport = false,
    scheduleEndTimeEnabled = true,
    showBreaks = false,
    roleFilter = null,
    roleScope = null,
  } = {},
) {
  if (Array.isArray(roleFilter)) {
    return formatScopedShiftEntryText(entry, {
      showRoleLabels,
      forExport,
      scheduleEndTimeEnabled,
      showBreaks,
      roleFilter,
      roleScope,
    });
  }
  const hours = Number(entry.hours || 0);
  const breakLines = showBreaks && scheduleEndTimeEnabled ? entryBreakLines(entry) : [];
  const hoursLabel = `${Number.isInteger(hours) ? hours : hours.toFixed(1)}h${breakLines.length ? " net" : ""}${
    breakLines.length ? `, ${breakLines.join(", ")}` : ""
  }`;
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

/** `options.entryScopes` (from `summarizeRoleSelection`) supplies each shift's selected-role hours. */
export function formatDayShiftsText(entries, options, responsibilities = []) {
  const forExport = options?.forExport === true;
  const scopes = options?.entryScopes;
  return [
    ...(entries || []).map((entry) =>
      formatShiftEntryText(entry, { ...options, forExport, roleScope: scopes?.get(scheduleEntryKey(entry)) || null }),
    ),
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

/** "Fold: 3 people · 21.5 hours; Wash: 1 person · 4 hours" — distinct employees and net hours per role. */
export function formatDayRoleTotalsText(summary, { daysOnly = false, forExport = false } = {}) {
  const text = (summary?.roles || [])
    .filter((row) => Number(row.employees || 0) > 0)
    .map((row) => formatRoleResourcesLabel(row, { daysOnly, short: true }))
    .join("; ");
  return forExport ? exportAsciiText(text) : text;
}

/** Roles for an employee row: the role totals on the row (selection-aware), else every assigned role. */
export function employeeRowRoles(employee, entries) {
  if (Array.isArray(employee?.role_hours)) return employee.role_hours.map((row) => row.role);
  return employeeScheduleRoles(employee?.user_id, entries);
}

export function buildWeeklyScheduleCsvRows({
  employees,
  entries,
  scheduleEndTimeEnabled = true,
  showRoleLabels = true,
  showBreaks = false,
  dayLabels = null,
  dayIndices = null,
  daySummaries = null,
  responsibilities = [],
  roleFilter = null,
  entryScopes = null,
}) {
  const columnDays = dayIndices || [0, 1, 2, 3, 4, 5, 6];
  const columnLabels = dayLabels || columnDays.map((dow) => DAY_LABELS[dow]);
  const breakColumns = scheduleEndTimeEnabled && showBreaks;
  const headers = [
    "Employee",
    "Roles",
    ...columnLabels,
    ...(breakColumns ? ["Gross Hours", "Break Hours", "Net Hours"] : [scheduleEndTimeEnabled ? "Total Hours" : "Total Days"]),
  ];
  const lines = [headers.map(csvCell).join(",")];

  for (const employee of employees || []) {
    const roles = employeeRowRoles(employee, entries);
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
            { showRoleLabels, forExport: true, scheduleEndTimeEnabled, showBreaks, roleFilter, entryScopes },
            cellResponsibilities,
          ),
        ),
      );
    }

    if (breakColumns) {
      for (const key of ["gross_hours", "break_hours", "total_hours"]) {
        row.push(String(Math.round(Number(employee[key] || 0) * 100) / 100));
      }
    } else if (scheduleEndTimeEnabled) {
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
      { entries, includeExcluded: true, roles: roleFilter },
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
    ...(breakColumns ? [csvCell(""), csvCell(""), csvCell("")] : [csvCell("")]),
  ];
  lines.push(totalsRow.join(","));
  if (breakColumns) {
    lines.push(
      [
        csvCell("Day Hours"),
        csvCell(""),
        ...columnDays.map((dow) =>
          csvCell(
            formatHoursBreakdown({
              gross: summaries[dow]?.gross_hours,
              breakHours: summaries[dow]?.break_hours,
              net: summaries[dow]?.hours,
            }),
          ),
        ),
        csvCell(""),
        csvCell(""),
        csvCell(""),
      ].join(","),
    );
  }

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
  showBreaks = false,
  dayLabels = null,
  dayIndices = null,
  daySummaries = null,
  responsibilities = [],
  roleFilter = null,
  entryScopes = null,
}) {
  const lines = buildWeeklyScheduleCsvRows({
    employees,
    entries,
    scheduleEndTimeEnabled,
    showRoleLabels,
    showBreaks,
    dayLabels,
    dayIndices,
    daySummaries,
    responsibilities,
    roleFilter,
    entryScopes,
  });
  downloadCsv(lines, csvFileName({ weekStart, tabLabel, filename }));
}

/** Employee hours and role hours/resources sections appended to the hourly coverage export. */
export function buildHoursSummaryCsvRows(summary) {
  if (!summary) return [];
  const hours = (value) => String(Math.round(Number(value || 0) * 100) / 100);
  const lines = ["", csvCell("Employee hours"), ["Employee", "Net hours", "Gross hours", "Break hours"].map(csvCell).join(",")];
  for (const row of summary.employees) {
    lines.push([csvCell(row.name), hours(row.hours), hours(row.grossHours), hours(row.breakHours)].join(","));
  }
  lines.push(
    [
      csvCell(`Total (${summary.employees.length} employees)`),
      hours(summary.totalHours),
      hours(summary.grossHours),
      hours(summary.breakHours),
    ].join(","),
  );
  if (summary.unscheduledBreakHours > 0) {
    lines.push([csvCell("Breaks without a time (included in break hours)"), "", "", hours(summary.unscheduledBreakHours)].join(","));
  }
  lines.push("", csvCell("Role hours & resources"), ["Role", "People", "Net hours"].map(csvCell).join(","));
  for (const row of summary.roles) lines.push([csvCell(row.label), String(row.employees), hours(row.hours)].join(","));
  if (summary.unassignedHours > 0) {
    lines.push([csvCell(summary.unassignedLabel || "Shift time without a role"), "", hours(summary.unassignedHours)].join(","));
  }
  lines.push(
    [
      csvCell(summary.roleFilter ? "Total (selected roles)" : "Total net hours"),
      String(summary.distinctEmployees ?? summary.employees.length),
      hours(summary.roleTotal + (summary.unassignedHours || 0)),
    ].join(","),
  );
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
      if (row.breaks?.count) {
        lines.push(
          [
            ...dayCells,
            hour,
            csvCell("On break"),
            String(row.breaks.count),
            coverageHours(row.breaks.hours),
            coverageHours(row.breaks.cumulative),
            csvCell(coveragePeopleText(row.breaks.people)),
          ].join(","),
        );
      }
    }
    const netNote = (total) =>
      total.untimedBreak > 0.0001 ? csvCell(`Net ${coverageHours(total.net)}h after ${coverageHours(total.untimedBreak)}h break without a time`) : "";
    for (const role of columns) {
      const total = day.totals[role];
      if (!total) continue;
      lines.push(
        [...dayCells, csvCell("Day total"), csvCell(scheduleRoleLabel(role)), String(total.count), coverageHours(total.hours), "", netNote(total)].join(","),
      );
    }
    if (day.hours.length) {
      lines.push(
        [
          ...dayCells,
          csvCell("Day total"),
          csvCell("All shown roles"),
          String(day.overall.count),
          coverageHours(day.overall.hours),
          "",
          netNote(day.overall),
        ].join(","),
      );
    }
    if (day.breakTotal?.count) {
      lines.push(
        [...dayCells, csvCell("Day total"), csvCell("On break"), String(day.breakTotal.count), coverageHours(day.breakTotal.hours), "", ""].join(","),
      );
    }
    for (const item of day.unscheduledBreaks || []) {
      lines.push(
        [
          ...dayCells,
          csvCell("Break without a time"),
          csvCell("Not scheduled"),
          "1",
          coverageHours(item.hours),
          "",
          csvCell(`${item.name}: not placed in any hour`),
        ].join(","),
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
