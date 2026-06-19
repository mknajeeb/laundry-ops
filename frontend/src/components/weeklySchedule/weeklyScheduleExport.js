import { formatTime12 } from "../datetime/scheduleTimeUi";
import { employeeScheduleRoles, parseEntryRoles, roleLabels } from "./weeklyScheduleRoles";
import { DAY_LABELS } from "./weeklyScheduleDates";

export function formatShiftEntryText(entry, { showRoleLabels = true } = {}) {
  const hours = Number(entry.hours || 0);
  const hoursLabel = Number.isInteger(hours) ? `${hours}h` : `${hours.toFixed(1)}h`;
  const roleText = showRoleLabels ? ` ${roleLabels(parseEntryRoles(entry))}` : "";
  return `${formatTime12(entry.start_time)} – ${formatTime12(entry.end_time)} (${hoursLabel})${roleText}`;
}

export function formatDayShiftsText(entries, options) {
  return (entries || []).map((entry) => formatShiftEntryText(entry, options)).join("; ");
}

function csvCell(value) {
  return JSON.stringify(value ?? "");
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
  const lines = [headers.join(",")];

  for (const employee of employees || []) {
    const roles = employeeScheduleRoles(employee.user_id, entries);
    const row = [
      csvCell(employee.display_name),
      csvCell(roles.length ? roleLabels(roles) : ""),
    ];

    for (let dow = 0; dow < 7; dow += 1) {
      const cellEntries = (entries || []).filter(
        (entry) =>
          Number(entry.user_id) === Number(employee.user_id) &&
          Number(entry.day_of_week) === dow,
      );
      row.push(csvCell(formatDayShiftsText(cellEntries, { showRoleLabels })));
    }

    const totalHours = Number(employee.total_hours || 0);
    row.push(Number.isInteger(totalHours) ? totalHours : totalHours.toFixed(1));
    lines.push(row.join(","));
  }

  const safeTab = String(tabLabel || "schedule")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
  const downloadName =
    filename || `weekly-schedule-${weekStart}-${safeTab || "schedule"}.csv`;

  const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = downloadName;
  anchor.click();
  URL.revokeObjectURL(url);
}
