import {
  employeeScheduleRoles,
  formatEmployeeWeeklySummary,
  formatRoleHoursLabel,
  HOUR_TRACKED_ROLES,
  ROLE_COMPACT_LABELS,
  ROLE_ORDER,
  ROLE_STYLES,
  roleLabels,
} from "./weeklyScheduleRoles";
import { formatDayShiftsText } from "./weeklyScheduleExport";

function DayHeaderTotals({ summary, daysOnly = false }) {
  if (!summary) return null;
  const people = Number(summary.people || 0);
  const hours = Number(summary.hours || 0);
  const hoursLabel = Number.isInteger(hours) ? `${hours}` : hours.toFixed(1);
  const roleParts = [];
  for (const role of ROLE_ORDER) {
    const count = Number(summary[role] || 0);
    if (count <= 0) continue;
    const label = ROLE_COMPACT_LABELS[role] || ROLE_STYLES[role]?.label || role;
    if (!daysOnly && HOUR_TRACKED_ROLES.includes(role)) {
      const roleHours = Number(summary[`${role}_hours`] || 0);
      if (roleHours > 0) {
        roleParts.push(`${label} ${count} · ${formatRoleHoursLabel(roleHours)}`);
        continue;
      }
    }
    roleParts.push(`${label} ${count}`);
  }

  return (
    <div className="weekly-schedule-print-day-totals">
      <div>
        {people} emp{daysOnly ? "" : ` · ${hoursLabel} hrs`}
      </div>
      {roleParts.length ? <div className="weekly-schedule-print-day-roles">{roleParts.join(" · ")}</div> : null}
    </div>
  );
}

export default function WeeklySchedulePrintTable({
  employees,
  entries,
  dayLabels,
  dayIndices = null,
  daySummaries = null,
  showRoleLabels = true,
  daysOnly = false,
}) {
  const labels = dayLabels || [];
  const indices = dayIndices || labels.map((_, index) => index);

  return (
    <table className="weekly-schedule-print-table">
      <thead>
        <tr>
          <th className="weekly-schedule-print-th-employee">Employee</th>
          {labels.map((label, index) => {
            const dow = indices[index] ?? index;
            return (
              <th key={label} className="weekly-schedule-print-th-day">
                <div>{label}</div>
                <DayHeaderTotals summary={daySummaries?.[dow]} daysOnly={daysOnly} />
              </th>
            );
          })}
        </tr>
      </thead>
      <tbody>
        {(employees || []).map((employee) => {
          const roles = employeeScheduleRoles(employee.user_id, entries);
          return (
            <tr key={employee.user_id}>
              <td className="weekly-schedule-print-td-employee">
                <div className="weekly-schedule-print-employee-name">{employee.display_name}</div>
                {roles.length ? (
                  <div className="weekly-schedule-print-employee-meta">{roleLabels(roles)}</div>
                ) : null}
                <div className="weekly-schedule-print-employee-meta">
                  {formatEmployeeWeeklySummary(employee, { daysOnly })}
                </div>
              </td>
              {labels.map((label, index) => {
                const dow = indices[index] ?? index;
                const cellEntries = (entries || []).filter(
                  (entry) =>
                    Number(entry.user_id) === Number(employee.user_id) &&
                    Number(entry.day_of_week) === dow,
                );
                const text = formatDayShiftsText(cellEntries, {
                  showRoleLabels,
                  forExport: true,
                  scheduleEndTimeEnabled: !daysOnly,
                });
                return (
                  <td key={`${employee.user_id}-${label}`} className="weekly-schedule-print-td-day">
                    {text
                      ? text.split("; ").map((line) => (
                          <div key={line} className="weekly-schedule-print-shift-line">
                            {line}
                          </div>
                        ))
                      : null}
                  </td>
                );
              })}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
