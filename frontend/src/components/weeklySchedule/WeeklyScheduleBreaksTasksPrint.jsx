import { DAY_LABELS } from "./weeklyScheduleDates";
import { scheduleRoleLabel } from "./weeklyScheduleRoles";
import { dayDateLabel, formatCoverageHours } from "./weeklyScheduleTimeBlocks";
import { gridDayBreakText, gridDayTaskText } from "./weeklyScheduleBreaksGrid";

function minutesText(hours) {
  return `${Math.round(Number(hours || 0) * 60)} min`;
}

/** Plain-HTML print of the breaks & tasks grid (copied into the print window, so no MUI styling). */
export default function WeeklyScheduleBreaksTasksPrint({ grid, weekStart, showBreaks = true, noRolesText = "" }) {
  const columns = grid?.columns || [];
  const rows = grid?.rows || [];
  const hasUnassigned = columns.some((column) => column.unassignedTasks.length);
  return (
    <>
      {noRolesText ? (
        <div className="weekly-schedule-print-employee-meta">{noRolesText}: breaks are not shown. Tasks are listed.</div>
      ) : null}
      <table className="weekly-schedule-print-table weekly-schedule-print-breaks-grid">
        <thead>
          <tr>
            <th className="weekly-schedule-print-th-employee">Employee</th>
            {columns.map((column) => (
              <th key={column.dow} className="weekly-schedule-print-th-day">
                {DAY_LABELS[column.dow]} · {dayDateLabel(weekStart, column.dow)}
                {showBreaks ? (
                  <div className="weekly-schedule-print-day-totals">{gridDayBreakText(column, formatCoverageHours) || "No breaks"}</div>
                ) : null}
                <div className="weekly-schedule-print-day-totals">{gridDayTaskText(column)}</div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.userId}>
              <td className="weekly-schedule-print-employee-name">
                {row.name}
                <div className="weekly-schedule-print-employee-meta">
                  {[
                    showBreaks && row.breakHours ? `${formatCoverageHours(row.breakHours)} breaks` : "",
                    row.taskCount ? `${row.taskCount} ${row.taskCount === 1 ? "task" : "tasks"}` : "",
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </div>
              </td>
              {columns.map((column) => {
                const cell = row.cells[column.dow];
                const empty = !cell || (!cell.timed.length && !cell.untimed.length && !cell.tasks.length);
                return (
                  <td key={column.dow}>
                    {empty ? (cell?.hasShift && showBreaks ? "No break planned" : "—") : null}
                    {cell?.timed.map((range) => (
                      <div key={`t${range.start}`} className="weekly-schedule-print-shift-line">
                        <strong>Break {range.label}</strong>
                      </div>
                    ))}
                    {cell?.untimed.map((item, index) => (
                      <div key={`u${index}`} className="weekly-schedule-print-shift-line">
                        <strong>Not scheduled</strong> · {minutesText(item.hours)}
                        {item.unallocated ? " · not allocated to a role" : ""}
                      </div>
                    ))}
                    {cell?.tasks.map((task) => (
                      <div key={task.key} className="weekly-schedule-print-shift-line">
                        <strong>{task.label}</strong>
                        {task.remarks ? `: ${task.remarks}` : " — no instructions"}
                      </div>
                    ))}
                  </td>
                );
              })}
            </tr>
          ))}
          {hasUnassigned ? (
            <tr className="weekly-schedule-print-tr-daily">
              <td className="weekly-schedule-print-employee-name">Unassigned tasks</td>
              {columns.map((column) => (
                <td key={column.dow}>{column.unassignedTasks.map(scheduleRoleLabel).join(", ") || "—"}</td>
              ))}
            </tr>
          ) : null}
        </tbody>
      </table>
      <div className="weekly-schedule-print-employee-meta">
        Tasks are whole-day assignments with instructions; they have no times and add no hours.
      </div>
    </>
  );
}
