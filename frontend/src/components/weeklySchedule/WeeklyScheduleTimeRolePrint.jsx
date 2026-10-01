import { DAY_LABELS } from "./weeklyScheduleDates";
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

/** Plain-HTML print layout (copied into the print window, so no MUI styling). */
export default function WeeklyScheduleTimeRolePrint({ days, weekStart, endTimeEnabled = true }) {
  return (
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
                    Daily responsibilities
                    <div className="weekly-schedule-print-employee-meta">No time slot</div>
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
  );
}
