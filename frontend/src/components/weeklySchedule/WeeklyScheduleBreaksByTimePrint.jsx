import { DAY_LABELS } from "./weeklyScheduleDates";
import { scheduleRoleLabel } from "./weeklyScheduleRoles";
import { dayDateLabel, formatCoverageHours } from "./weeklyScheduleTimeBlocks";
import { gridDayTaskText } from "./weeklyScheduleBreaksGrid";
import { byTimeDayHeaderText, peakIntensity, slotHeadline, slotPersonDetail, untimedPersonText } from "./weeklyScheduleBreaksByTime";

function DayHeaders({ columns, weekStart, line }) {
  return columns.map((column) => (
    <th key={column.dow} className="weekly-schedule-print-th-day">
      {DAY_LABELS[column.dow]} · {dayDateLabel(weekStart, column.dow)}
      <div className="weekly-schedule-print-day-totals">{line(column)}</div>
    </th>
  ));
}

/** Plain-HTML print of breaks by time plus the tasks section (copied into the print window, so no MUI). */
export default function WeeklyScheduleBreaksByTimePrint({ byTime, grid, tasksByDay = {}, weekStart, showBreaks = true, noRolesText = "" }) {
  const columns = byTime?.columns || [];
  const gridColumns = new Map((grid?.columns || []).map((column) => [column.dow, column]));
  const hasUntimed = columns.some((column) => column.untimed.length);
  const hasUnassigned = (grid?.columns || []).some((column) => column.unassignedTasks.length);
  return (
    <>
      {noRolesText ? (
        <div className="weekly-schedule-print-employee-meta">{noRolesText}: breaks are not shown. Tasks are listed.</div>
      ) : null}
      {showBreaks ? (
        <table className="weekly-schedule-print-table weekly-schedule-print-breaks-grid">
          <thead>
            <tr>
              <th className="weekly-schedule-print-th-employee">Time ({byTime.interval} min)</th>
              <DayHeaders columns={columns} weekStart={weekStart} line={(c) => byTimeDayHeaderText(c, formatCoverageHours)} />
            </tr>
          </thead>
          <tbody>
            {!byTime.hasTimed ? (
              <tr>
                <td colSpan={columns.length + 1}>No timed breaks planned for these days.</td>
              </tr>
            ) : null}
            {byTime.rows.map((row) =>
              row.gap ? (
                <tr key={`g${row.start}`}>
                  <td className="weekly-schedule-print-employee-name">{row.label}</td>
                  <td colSpan={columns.length}>No timed breaks</td>
                </tr>
              ) : (
                <tr key={row.start}>
                  <td className="weekly-schedule-print-employee-name">{row.label}</td>
                  {columns.map((column) => {
                    const cell = row.cells[column.dow];
                    if (!cell?.count) return <td key={column.dow}>—</td>;
                    const shade = (0.04 + 0.2 * peakIntensity(cell.peak, byTime.week.peak)).toFixed(3);
                    return (
                      <td key={column.dow} style={{ backgroundColor: `rgba(234, 88, 12, ${shade})` }}>
                        <strong>{slotHeadline(cell)}</strong>
                        {cell.people.map((person) => (
                          <div key={person.userId} className="weekly-schedule-print-shift-line">
                            {person.name} {slotPersonDetail(person)}
                          </div>
                        ))}
                      </td>
                    );
                  })}
                </tr>
              ),
            )}
            {byTime.hasTimed ? (
              <tr className="weekly-schedule-print-tr-daily">
                <td className="weekly-schedule-print-employee-name">
                  Scheduled total
                  <div className="weekly-schedule-print-employee-meta">Week {formatCoverageHours(byTime.week.intervalHours)}</div>
                </td>
                {columns.map((column) => (
                  <td key={column.dow}>{formatCoverageHours(column.intervalHours)}</td>
                ))}
              </tr>
            ) : null}
            {hasUntimed ? (
              <tr>
                <td className="weekly-schedule-print-employee-name">
                  Not scheduled
                  <div className="weekly-schedule-print-employee-meta">Week {formatCoverageHours(byTime.week.untimedBreakHours)} · no time yet</div>
                </td>
                {columns.map((column) => (
                  <td key={column.dow}>
                    {column.untimed.length
                      ? column.untimed.map((item, index) => (
                          <div key={`${item.userId}-${index}`} className="weekly-schedule-print-shift-line">
                            {untimedPersonText(item)}
                          </div>
                        ))
                      : "—"}
                  </td>
                ))}
              </tr>
            ) : null}
          </tbody>
        </table>
      ) : null}
      <table className="weekly-schedule-print-table weekly-schedule-print-breaks-grid">
        <thead>
          <tr>
            <th className="weekly-schedule-print-th-employee">Tasks</th>
            <DayHeaders
              columns={columns}
              weekStart={weekStart}
              line={(c) => (gridColumns.get(c.dow) ? gridDayTaskText(gridColumns.get(c.dow)) : "")}
            />
          </tr>
        </thead>
        <tbody>
          <tr>
            <td className="weekly-schedule-print-employee-name">Assigned</td>
            {columns.map((column) => {
              const tasks = tasksByDay[column.dow] || [];
              return (
                <td key={column.dow}>
                  {tasks.length
                    ? tasks.map((task) => (
                        <div key={task.key} className="weekly-schedule-print-shift-line">
                          <strong>{task.label}</strong> · {task.name}
                          {task.remarks ? `: ${task.remarks}` : " — no instructions"}
                        </div>
                      ))
                    : "—"}
                </td>
              );
            })}
          </tr>
          {hasUnassigned ? (
            <tr className="weekly-schedule-print-tr-daily">
              <td className="weekly-schedule-print-employee-name">Unassigned tasks</td>
              {columns.map((column) => (
                <td key={column.dow}>{(gridColumns.get(column.dow)?.unassignedTasks || []).map(scheduleRoleLabel).join(", ") || "—"}</td>
              ))}
            </tr>
          ) : null}
        </tbody>
      </table>
      <div className="weekly-schedule-print-employee-meta">
        Break-hours in a row count only the part of each break inside that interval. Max at once is shown when not
        everyone listed is on break together. Tasks are whole-day assignments; they have no times and add no hours.
      </div>
    </>
  );
}
