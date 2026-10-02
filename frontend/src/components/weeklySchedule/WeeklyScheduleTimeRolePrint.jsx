import { DAY_LABELS } from "./weeklyScheduleDates";
import { formatRoleHoursLabel, ROLE_HOURS_EXPLANATION } from "./weeklyScheduleRoles";
import { dayDateLabel, timeBlockLabel } from "./weeklyScheduleTimeBlocks";

function PeopleCell({ people }) {
  return people.map((person) => (
    <div key={person.key} className="weekly-schedule-print-shift-line">
      {person.name}
    </div>
  ));
}

function RemarksCell({ people }) {
  return people
    .filter((person) => person.remarks)
    .map((person) => (
      <div key={person.key} className="weekly-schedule-print-shift-line">
        <strong>{person.name}:</strong> {person.remarks}
      </div>
    ));
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
              <td>Shift time without a role</td>
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

/** Plain-HTML print layout (copied into the print window, so no MUI styling). */
export default function WeeklyScheduleTimeRolePrint({ days, weekStart, endTimeEnabled = true, hoursSummary = null }) {
  return (
    <>
    <HoursSummaryPrint summary={hoursSummary} />
    <table className="weekly-schedule-print-table weekly-schedule-print-time-role">
      <thead>
        <tr>
          <th className="weekly-schedule-print-tr-time">Time</th>
          <th className="weekly-schedule-print-tr-role">Role</th>
          <th className="weekly-schedule-print-tr-count">#</th>
          <th className="weekly-schedule-print-tr-people">Employees</th>
          <th>Remarks</th>
        </tr>
      </thead>
      {(days || []).map((day) => {
        const empty = !day.blocks.length && !day.responsibilities.length;
        return (
          <tbody key={day.dow}>
            <tr className="weekly-schedule-print-tr-day">
              <td colSpan={5}>
                {DAY_LABELS[day.dow]} · {dayDateLabel(weekStart, day.dow)}
              </td>
            </tr>
            {empty ? (
              <tr>
                <td colSpan={5} className="weekly-schedule-print-employee-meta">
                  No assignments
                </td>
              </tr>
            ) : null}
            {day.blocks.map((block) =>
              block.roles.map((group, index) => (
                <tr key={`${block.key}-${group.role}`}>
                  {index === 0 ? (
                    <td rowSpan={block.roles.length} className="weekly-schedule-print-employee-name">
                      {timeBlockLabel(block, endTimeEnabled, " - ")}
                    </td>
                  ) : null}
                  <td>{group.label}</td>
                  <td>{group.count}</td>
                  <td>
                    <PeopleCell people={group.people} />
                  </td>
                  <td>
                    <RemarksCell people={group.people} />
                  </td>
                </tr>
              )),
            )}
            {day.responsibilities.map((group, index) => (
              <tr key={`daily-${group.role}`} className="weekly-schedule-print-tr-daily">
                {index === 0 ? (
                  <td rowSpan={day.responsibilities.length} className="weekly-schedule-print-employee-name">
                    Tasks
                    <div className="weekly-schedule-print-employee-meta">Whole day · no times · no hours</div>
                  </td>
                ) : null}
                <td>{group.label}</td>
                <td>{group.count}</td>
                <td>
                  <PeopleCell people={group.people} />
                </td>
                <td>
                  <RemarksCell people={group.people} />
                </td>
              </tr>
            ))}
          </tbody>
        );
      })}
    </table>
    </>
  );
}
