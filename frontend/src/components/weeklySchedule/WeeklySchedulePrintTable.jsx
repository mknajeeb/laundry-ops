import { employeeScheduleRoles, formatEmployeeWeeklySummary, roleLabels } from "./weeklyScheduleRoles";
import { formatDayShiftsText } from "./weeklyScheduleExport";

export default function WeeklySchedulePrintTable({
  employees,
  entries,
  dayLabels,
  dayIndices = null,
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
          {labels.map((label) => (
            <th key={label} className="weekly-schedule-print-th-day">
              {label}
            </th>
          ))}
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
