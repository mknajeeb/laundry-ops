import {
  formatEmployeeWeeklySummary,
  formatHoursBreakdown,
  formatRoleResourcesLabel,
  formatUnallocatedBreak,
  roleLabels,
  UNALLOCATED_BREAK_NOTE,
} from "./weeklyScheduleRoles";
import { employeeRowRoles, formatDayShiftsText } from "./weeklyScheduleExport";

function unresolvedText(hours, showBreaks) {
  return `${showBreaks ? `${formatUnallocatedBreak(hours)} · ` : ""}${UNALLOCATED_BREAK_NOTE}`;
}

function DayHeaderTotals({ summary, daysOnly = false, showBreaks = false }) {
  if (!summary) return null;
  const people = Number(summary.people || 0);
  const hours = Number(summary.hours || 0);
  const hoursLabel = Number.isInteger(hours) ? `${hours}` : hours.toFixed(1);
  const pending = !daysOnly && Number(summary.unallocated_break_hours || 0) > 0.0001;
  const roleUnallocated = daysOnly ? 0 : Number(summary.role_unallocated_break_hours || 0);
  const roleParts = (summary.roles || [])
    .filter((row) => Number(row.employees || 0) > 0)
    .map((row) => formatRoleResourcesLabel(row, { daysOnly, short: true }));

  return (
    <div className="weekly-schedule-print-day-totals">
      <div>
        {people} emp{daysOnly ? "" : ` · ${hoursLabel}${pending ? " gross" : ""} hrs`}
      </div>
      {!daysOnly && showBreaks && Number(summary.break_hours || 0) > 0 ? (
        <div className="weekly-schedule-print-day-roles">
          {formatHoursBreakdown({ gross: summary.gross_hours, breakHours: summary.break_hours, net: hours })}
        </div>
      ) : null}
      {roleParts.map((part) => (
        <div key={part} className="weekly-schedule-print-day-roles">
          {part}
        </div>
      ))}
      {roleUnallocated > 0.0001 ? (
        <div className="weekly-schedule-print-day-roles">{unresolvedText(roleUnallocated, showBreaks)}</div>
      ) : null}
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
  showBreaks = false,
  responsibilities = [],
  roleFilter = null,
  entryScopes = null,
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
                <DayHeaderTotals summary={daySummaries?.[dow]} daysOnly={daysOnly} showBreaks={showBreaks} />
              </th>
            );
          })}
        </tr>
      </thead>
      <tbody>
        {(employees || []).map((employee) => {
          const roles = employeeRowRoles(employee, entries);
          return (
            <tr key={employee.user_id}>
              <td className="weekly-schedule-print-td-employee">
                <div className="weekly-schedule-print-employee-name">{employee.display_name}</div>
                {roles.length ? (
                  <div className="weekly-schedule-print-employee-meta">{roleLabels(roles)}</div>
                ) : null}
                <div className="weekly-schedule-print-employee-meta">
                  {formatEmployeeWeeklySummary(employee, { daysOnly, showBreaks })}
                </div>
                {!daysOnly && showBreaks && Number(employee.break_hours || 0) > 0 ? (
                  <div className="weekly-schedule-print-employee-meta">
                    {formatHoursBreakdown({
                      gross: employee.gross_hours,
                      breakHours: employee.break_hours,
                      net: employee.total_hours,
                    })}
                  </div>
                ) : null}
                {!daysOnly && Number(employee.role_unallocated_break_hours || 0) > 0.0001 ? (
                  <div className="weekly-schedule-print-employee-meta">
                    {unresolvedText(employee.role_unallocated_break_hours, showBreaks)}
                  </div>
                ) : null}
              </td>
              {labels.map((label, index) => {
                const dow = indices[index] ?? index;
                const cellEntries = (entries || []).filter(
                  (entry) =>
                    Number(entry.user_id) === Number(employee.user_id) &&
                    Number(entry.day_of_week) === dow,
                );
                const cellResponsibilities = (responsibilities || []).filter(
                  (item) =>
                    Number(item.user_id) === Number(employee.user_id) && Number(item.day_of_week) === dow,
                );
                const text = formatDayShiftsText(
                  cellEntries,
                  {
                    showRoleLabels,
                    forExport: true,
                    scheduleEndTimeEnabled: !daysOnly,
                    showBreaks,
                    roleFilter,
                    entryScopes,
                  },
                  cellResponsibilities,
                );
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
