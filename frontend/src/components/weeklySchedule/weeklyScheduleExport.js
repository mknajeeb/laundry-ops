import { formatTime12 } from "../datetime/scheduleTimeUi";
import { employeeScheduleRoles, parseEntryRoles, roleLabels, sortRoles, ROLE_STYLES } from "./weeklyScheduleRoles";
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

export function formatShiftEntryText(entry, { showRoleLabels = true, forExport = false } = {}) {
  const hours = Number(entry.hours || 0);
  const hoursLabel = Number.isInteger(hours) ? `${hours}h` : `${hours.toFixed(1)}h`;
  const roleText = showRoleLabels ? ` ${exportRoleLabels(parseEntryRoles(entry))}` : "";
  const start = formatTime12(entry.start_time);
  const end = formatTime12(entry.end_time);
  const range = forExport ? `${start} - ${end}` : `${start} – ${end}`;
  const text = `${range} (${hoursLabel})${roleText}`;
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

export function exportWeeklyScheduleCsv({
  employees,
  entries,
  weekStart,
  tabLabel,
  filename,
  showRoleLabels = true,
}) {
  const headers = ["Employee", "Roles", ...DAY_LABELS, "Total Hours"];
  const lines = [headers.map(csvCell).join(",")];

  for (const employee of employees || []) {
    const roles = employeeScheduleRoles(employee.user_id, entries);
    const row = [
      csvCell(employee.display_name),
      csvCell(roles.length ? exportAsciiText(roleLabels(roles).replace(/\u00b7/g, " / ")) : ""),
    ];

    for (let dow = 0; dow < 7; dow += 1) {
      const cellEntries = (entries || []).filter(
        (entry) =>
          Number(entry.user_id) === Number(employee.user_id) &&
          Number(entry.day_of_week) === dow,
      );
      row.push(csvCell(formatDayShiftsText(cellEntries, { showRoleLabels, forExport: true })));
    }

    const totalHours = Number(employee.total_hours || 0);
    row.push(Number.isInteger(totalHours) ? String(totalHours) : totalHours.toFixed(1));
    lines.push(row.join(","));
  }

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
