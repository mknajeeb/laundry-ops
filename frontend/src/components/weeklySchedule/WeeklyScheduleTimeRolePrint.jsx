import { DAY_LABELS } from "./weeklyScheduleDates";
import { formatHours, ROLE_HOURS_EXPLANATION, scheduleRoleLabel } from "./weeklyScheduleRoles";
import { dayDateLabel, formatCoverageHours, HOURLY_COVERAGE_EXPLANATION } from "./weeklyScheduleTimeBlocks";

function peopleCount(count) {
  return `${count} ${count === 1 ? "person" : "people"}`;
}

function formatRoleHoursLabel(hours) {
  return `${formatHours(hours)}h`;
}

function netNote(total) {
  if (!total || !(Number(total.untimedBreak) > 0.0001)) return "";
  return ` (net ${formatCoverageHours(total.net)} after ${formatCoverageHours(total.untimedBreak)} break without a time)`;
}

function HoursSummaryPrint({ summary, showBreaks }) {
  if (!summary) return null;
  return (
    <div className="weekly-schedule-print-hours-summary">
      <table className="weekly-schedule-print-table">
        <thead>
          <tr>
            <th>Employee</th>
            {showBreaks ? <th className="weekly-schedule-print-tr-count">Gross</th> : null}
            {showBreaks ? <th className="weekly-schedule-print-tr-count">Break</th> : null}
            <th className="weekly-schedule-print-tr-count">{showBreaks ? "Net" : "Hours"}</th>
          </tr>
        </thead>
        <tbody>
          {summary.employees.map((row) => (
            <tr key={row.user_id}>
              <td>{row.name}</td>
              {showBreaks ? <td>{formatRoleHoursLabel(row.grossHours)}</td> : null}
              {showBreaks ? <td>{formatRoleHoursLabel(row.breakHours)}</td> : null}
              <td>{formatRoleHoursLabel(row.hours)}</td>
            </tr>
          ))}
          <tr className="weekly-schedule-print-tr-day">
            <td>Total · {summary.employees.length} employees</td>
            {showBreaks ? <td>{formatRoleHoursLabel(summary.grossHours)}</td> : null}
            {showBreaks ? (
              <td>
                {formatRoleHoursLabel(summary.breakHours)}
                {summary.unscheduledBreakHours > 0
                  ? ` (${formatRoleHoursLabel(summary.unscheduledBreakHours)} not scheduled)`
                  : ""}
              </td>
            ) : null}
            <td>{formatRoleHoursLabel(summary.totalHours)}</td>
          </tr>
        </tbody>
      </table>
      <table className="weekly-schedule-print-table">
        <thead>
          <tr>
            <th>Role</th>
            <th className="weekly-schedule-print-tr-count">People</th>
            <th className="weekly-schedule-print-tr-count">Net hours</th>
          </tr>
        </thead>
        <tbody>
          {summary.roles.map((row) => (
            <tr key={row.role}>
              <td>{row.label}</td>
              <td>{row.employees}</td>
              <td>{formatRoleHoursLabel(row.hours)}</td>
            </tr>
          ))}
          {summary.unassignedHours > 0 ? (
            <tr>
              <td>{summary.unassignedLabel || "Shift time without a role"}</td>
              <td />
              <td>{formatRoleHoursLabel(summary.unassignedHours)}</td>
            </tr>
          ) : null}
          <tr className="weekly-schedule-print-tr-day">
            <td>{summary.roleFilter ? "Total (selected roles)" : "Total net hours"}</td>
            <td>{summary.distinctEmployees ?? summary.employees.length}</td>
            <td>{formatRoleHoursLabel(summary.roleTotal + (summary.unassignedHours || 0))}</td>
          </tr>
        </tbody>
      </table>
      <div className="weekly-schedule-print-employee-meta">{ROLE_HOURS_EXPLANATION}</div>
    </div>
  );
}

function PrintCell({ cell, endLabel, showNames }) {
  if (!cell?.count) {
    return (
      <>
        <div>—</div>
        {cell?.cumulative ? (
          <div className="weekly-schedule-print-employee-meta">
            Total through {endLabel}: {formatCoverageHours(cell.cumulative)}
          </div>
        ) : null}
      </>
    );
  }
  return (
    <>
      <div className="weekly-schedule-print-hourly-count">
        {peopleCount(cell.count)} · {formatCoverageHours(cell.hours)}
      </div>
      <div className="weekly-schedule-print-employee-meta">
        Total through {endLabel}: {formatCoverageHours(cell.cumulative)}
      </div>
      {showNames
        ? cell.people.map((person) => (
            <div key={person.userId} className="weekly-schedule-print-shift-line">
              {person.name}
              {person.partial ? ` ${person.rangeLabel}` : ""}
              {person.shared ? ` (split ${formatCoverageHours(person.hours)})` : ""}
            </div>
          ))
        : null}
    </>
  );
}

function DayTasksPrint({ day }) {
  if (!day.responsibilities.length) return null;
  return (
    <table className="weekly-schedule-print-table weekly-schedule-print-hourly-tasks">
      <tbody>
        {day.responsibilities.map((group, index) => (
          <tr key={group.role} className="weekly-schedule-print-tr-daily">
            {index === 0 ? (
              <td rowSpan={day.responsibilities.length} className="weekly-schedule-print-employee-name">
                Tasks
                <div className="weekly-schedule-print-employee-meta">Whole day · no times · no hours</div>
              </td>
            ) : null}
            <td>{group.label}</td>
            <td>
              {group.people.map((person) => (
                <div key={person.key} className="weekly-schedule-print-shift-line">
                  <strong>{person.name}</strong>
                  {person.remarks ? `: ${person.remarks}` : ""}
                </div>
              ))}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** Plain-HTML print layout (copied into the print window, so no MUI styling). */
export default function WeeklyScheduleTimeRolePrint({
  days,
  weekStart,
  columns,
  showNames = false,
  hoursSummary = null,
  showBreaks = true,
}) {
  return (
    <>
      <HoursSummaryPrint summary={hoursSummary} showBreaks={showBreaks} />
      {(days || []).map((day) => (
        <div key={day.dow} className="weekly-schedule-print-hourly-day">
          <div className="weekly-schedule-print-hourly-day-title">
            {DAY_LABELS[day.dow]} · {dayDateLabel(weekStart, day.dow)}
          </div>
          {day.hours.length && columns.length ? (
            <table className="weekly-schedule-print-table weekly-schedule-print-hourly">
              <thead>
                <tr>
                  <th className="weekly-schedule-print-tr-time">Hour</th>
                  {columns.map((role) => (
                    <th key={role}>{scheduleRoleLabel(role)}</th>
                  ))}
                  <th>All shown roles</th>
                  {showBreaks ? <th>On break</th> : null}
                </tr>
              </thead>
              <tbody>
                {day.hours.map((row) => (
                  <tr key={row.hour} className={row.gap ? "weekly-schedule-print-hourly-gap" : undefined}>
                    <td className="weekly-schedule-print-employee-name">{row.label}</td>
                    {columns.map((role) => (
                      <td key={role}>
                        <PrintCell cell={row.cells[role]} endLabel={row.endLabel} showNames={showNames} />
                      </td>
                    ))}
                    <td>
                      <div className="weekly-schedule-print-hourly-count">
                        {row.gap
                          ? row.scheduled
                            ? `No coverage · ${peopleCount(row.scheduled)} scheduled`
                            : "No one scheduled"
                          : `${peopleCount(row.total.count)} · ${formatCoverageHours(row.total.hours)}`}
                      </div>
                      <div className="weekly-schedule-print-employee-meta">
                        Total through {row.endLabel}: {formatCoverageHours(row.total.cumulative)}
                      </div>
                    </td>
                    {showBreaks ? (
                      <td>
                        <PrintCell cell={row.breaks} endLabel={row.endLabel} showNames={showNames} />
                      </td>
                    ) : null}
                  </tr>
                ))}
                <tr className="weekly-schedule-print-tr-day">
                  <td>Day total</td>
                  {columns.map((role) => {
                    const total = day.totals[role];
                    return (
                      <td key={role}>
                        {total ? `${peopleCount(total.count)} · ${formatCoverageHours(total.hours)}${netNote(total)}` : "—"}
                      </td>
                    );
                  })}
                  <td>
                    {peopleCount(day.overall.count)} · {formatCoverageHours(day.overall.hours)}
                    {netNote(day.overall)}
                  </td>
                  {showBreaks ? (
                    <td>
                      {day.breakTotal?.count
                        ? `${peopleCount(day.breakTotal.count)} · ${formatCoverageHours(day.breakTotal.hours)}`
                        : "—"}
                    </td>
                  ) : null}
                </tr>
              </tbody>
            </table>
          ) : !day.responsibilities.length ? (
            <div className="weekly-schedule-print-employee-meta">No assignments</div>
          ) : null}
          {showBreaks && day.unscheduledBreaks?.length ? (
            <div className="weekly-schedule-print-employee-meta">
              Breaks without a time ({formatCoverageHours(day.unscheduledBreakTotal.hours)}, not placed in any hour):{" "}
              {day.unscheduledBreaks.map((item) => `${item.name} ${Math.round(item.hours * 60)} min`).join("; ")}
            </div>
          ) : null}
          <DayTasksPrint day={day} />
        </div>
      ))}
      <div className="weekly-schedule-print-employee-meta">{HOURLY_COVERAGE_EXPLANATION}</div>
    </>
  );
}
