import { DAY_LABELS } from "./weeklyScheduleDates";
import { formatRoleHoursLabel, ROLE_HOURS_EXPLANATION, scheduleRoleLabel } from "./weeklyScheduleRoles";
import { dayDateLabel, formatCoverageHours, HOURLY_COVERAGE_EXPLANATION } from "./weeklyScheduleTimeBlocks";

function peopleCount(count) {
  return `${count} ${count === 1 ? "person" : "people"}`;
}

function HoursSummaryPrint({ summary }) {
  if (!summary) return null;
  return (
    <div className="weekly-schedule-print-hours-summary">
      <table className="weekly-schedule-print-table">
        <thead>
          <tr>
            <th>Employee</th>
            <th className="weekly-schedule-print-tr-count">Hours</th>
          </tr>
        </thead>
        <tbody>
          {summary.employees.map((row) => (
            <tr key={row.user_id}>
              <td>{row.name}</td>
              <td>{formatRoleHoursLabel(row.hours)}</td>
            </tr>
          ))}
          <tr className="weekly-schedule-print-tr-day">
            <td>Total · {summary.employees.length} employees</td>
            <td>{formatRoleHoursLabel(summary.totalHours)}</td>
          </tr>
        </tbody>
      </table>
      <table className="weekly-schedule-print-table">
        <thead>
          <tr>
            <th>Role</th>
            <th className="weekly-schedule-print-tr-count">Employees</th>
            <th className="weekly-schedule-print-tr-count">Hours</th>
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
            <td>Total role hours</td>
            <td />
            <td>{formatRoleHoursLabel(summary.roleTotal)}</td>
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
export default function WeeklyScheduleTimeRolePrint({ days, weekStart, columns, showNames = false, hoursSummary = null }) {
  return (
    <>
      <HoursSummaryPrint summary={hoursSummary} />
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
                  </tr>
                ))}
                <tr className="weekly-schedule-print-tr-day">
                  <td>Day total</td>
                  {columns.map((role) => {
                    const total = day.totals[role];
                    return <td key={role}>{total ? `${peopleCount(total.count)} · ${formatCoverageHours(total.hours)}` : "—"}</td>;
                  })}
                  <td>
                    {peopleCount(day.overall.count)} · {formatCoverageHours(day.overall.hours)}
                  </td>
                </tr>
              </tbody>
            </table>
          ) : !day.responsibilities.length ? (
            <div className="weekly-schedule-print-employee-meta">No assignments</div>
          ) : null}
          <DayTasksPrint day={day} />
        </div>
      ))}
      <div className="weekly-schedule-print-employee-meta">{HOURLY_COVERAGE_EXPLANATION}</div>
    </>
  );
}
