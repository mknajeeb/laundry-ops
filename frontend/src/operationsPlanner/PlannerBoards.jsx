import { useState } from "react";
import { DAY_NAMES, DAY_ORDER, breakLoad, clockMinutes, roleDayCoverage, staffingHours, taskWindow } from "./plannerModel";
import { roleColor, staffingFigures, visibleBreaks } from "./plannerGeometry";
import { DEFAULT_CATEGORY_TABS } from "../components/tasks/taskDashboardLabels";
import { scheduleRoleCatalog, scheduleRoleLabel } from "../components/weeklySchedule/weeklyScheduleRoles";
import { TASK_TIMING, TASK_TIMING_OPTIONS } from "../components/weeklySchedule/weeklyScheduleTaskTiming";

function personName(employees, userId) {
  return employees.find((employee) => Number(employee.user_id) === Number(userId))?.display_name || `Employee ${userId}`;
}

function lockedTask(task) {
  return ["in_progress", "pending_approval", "approved", "rejected", "completed"].includes(String(task.activity_status || task.status || ""));
}

function overlapsWindow(start, end, otherStart, otherEnd) {
  return start < otherEnd && otherStart < end;
}

export function taskConflicts(task, entries) {
  const window = taskWindow(task);
  if (!window.scheduled) return [];
  const shifts = (entries || []).filter((entry) => Number(entry.user_id) === Number(task.user_id) && Number(entry.day_of_week) === Number(task.day_of_week));
  const notes = [];
  const inside = shifts.some((entry) => {
    const start = clockMinutes(entry.start_time);
    let end = clockMinutes(entry.end_time);
    if (start == null || end == null) return false;
    if (end <= start) end += 24 * 60;
    return window.start >= start && window.end <= end;
  });
  if (!shifts.length || !inside) notes.push("Outside a scheduled shift");
  const onBreak = shifts.some((entry) => visibleBreaks(entry).some((slot) => {
    if (!slot.start_time) return false;
    const start = clockMinutes(slot.start_time);
    let end = clockMinutes(slot.end_time);
    if (start == null || end == null) return false;
    if (end <= start) end += 24 * 60;
    return overlapsWindow(window.start, window.end, start, end);
  }));
  if (onBreak) notes.push("Overlaps a timed break");
  return notes;
}

function roleTitle(role) {
  const text = String(role || "");
  if (!text) return "No role";
  if (text.includes(",")) return text.split(",").map((part) => scheduleRoleLabel(part.trim())).join(" · ");
  return scheduleRoleLabel(text);
}

function dayRoleFigures(entries, role, day) {
  return roleDayCoverage(entries, role, day);
}

function hoursLabel(value) {
  return `${Number(value || 0).toFixed(1)}h`;
}

function roleStaff(entries, role, day) {
  return (entries || []).flatMap((entry) => {
    if (Number(entry.day_of_week) !== Number(day)) return [];
    const segments = (entry.role_assignments || []).filter((item) => item.role === role && item.start_time && item.end_time);
    if (segments.length) {
      return segments.map((item) => ({
        entry,
        start: String(item.start_time).slice(0, 5),
        end: String(item.end_time).slice(0, 5),
      }));
    }
    const named = String(entry.role || "").split(",").map((item) => item.trim()).includes(role);
    if (!named) return [];
    return [{
      entry,
      start: String(entry.start_time || "").slice(0, 5),
      end: String(entry.end_time || "").slice(0, 5),
      unsplit: true,
    }];
  });
}

export function CoverageBoard({ entries, requirements, employees, day, days, onOpenShift }) {
  const shown = (days && days.length ? days : [day]);
  const [picked, setPicked] = useState(null);
  const roles = [...new Set((entries || []).flatMap((entry) => {
    const segments = (entry.role_assignments || []).map((item) => item.role).filter(Boolean);
    const codes = segments.length ? segments : String(entry.role || "").split(",").map((item) => item.trim()).filter(Boolean);
    return codes.filter((code) => !String(code).includes(","));
  }))];
  const storedTargets = (requirements || []).filter((item) => item && (item.required_headcount || item.hourly_headcount));
  const pickedHours = picked ? staffingHours(entries, storedTargets, picked.role, picked.day) : [];
  const breakWindows = pickedHours.flatMap((row) => (row.slices || []).filter((slice) => slice.onBreak > 0).map((slice) => ({ ...slice, hour: row.hour })));
  return (
    <section className="coverage-board" aria-label="Role coverage">
      <header>
        <h2>Staffing coverage</h2>
        <p>Each cell is scheduled employees, gross role hours, and net role hours. Gross is scheduled time on that role. Net subtracts a timed break only where it overlaps that role. An untimed break is subtracted only when the shift has that single role. Time on several roles at once is split across those roles. Open a cell to see scheduled and available employees through the day. A shortage appears only where a target is stored.</p>
        <p className="quiet">Hourly availability excludes only known timed breaks. Untimed breaks cannot be placed on the timeline.</p>
      </header>
      <div className="coverage-grid week-board" role="table" aria-label="Coverage for the week">
        <div className="week-head"><span>Role</span>{shown.map((value) => <span key={value}>{DAY_NAMES[value].slice(0, 3)}</span>)}</div>
        {roles.map((role) => (
          <div className="week-row" key={role}>
            <strong>{roleTitle(role)}</strong>
            {shown.map((value) => {
              const cell = dayRoleFigures(entries, role, value);
              const target = storedTargets.find((item) => item.role === role);
              const short = target && target.required_headcount && cell.people < Number(target.required_headcount);
              return (
                <div key={value}>
                  <button
                    type="button"
                    className={`week-chip${short ? " is-open" : ""}${picked?.day === value && picked?.role === role ? " is-on" : ""}`}
                    aria-label={cell.people ? `${roleTitle(role)} ${DAY_NAMES[value]}: ${cell.people} scheduled, ${hoursLabel(cell.grossHours)} gross, ${hoursLabel(cell.netHours)} net${Number(cell.unallocatedUntimedHours) > 0 ? `, ${hoursLabel(cell.unallocatedUntimedHours)} untimed off the clock` : ""}` : `${roleTitle(role)} ${DAY_NAMES[value]}: nobody scheduled`}
                    onClick={() => setPicked({ day: value, role, ...cell })}
                  >
                    {cell.people ? (
                      <>
                        <span>{cell.people} scheduled</span>
                        <small>{hoursLabel(cell.grossHours)} gross</small>
                        <small>{hoursLabel(cell.netHours)} net</small>
                        {Number(cell.unallocatedUntimedHours) > 0 ? <small>{hoursLabel(cell.unallocatedUntimedHours)} unassigned</small> : null}
                      </>
                    ) : "—"}
                  </button>
                </div>
              );
            })}
          </div>
        ))}
        <div className="week-row">
          <strong>Unallocated staffing</strong>
          {shown.map((value) => {
            const shifts = (entries || []).filter((entry) => Number(entry.day_of_week) === Number(value));
            const byPerson = new Map();
            shifts.forEach((entry) => {
              const key = Number(entry.user_id);
              byPerson.set(key, [...(byPerson.get(key) || []), entry]);
            });
            let people = 0;
            let hours = 0;
            byPerson.forEach((group) => {
              const figures = staffingFigures(group);
              if (figures.unallocated > 0) {
                people += 1;
                hours += figures.unallocated;
              }
            });
            return <div key={value}><span className="week-chip">{people ? <><span>{people} scheduled</span><small>{hours.toFixed(1)}h gross</small></> : "—"}</span></div>;
          })}
        </div>
      </div>
      {!storedTargets.length ? <p className="quiet">No target is stored. Open a cell for available staffing. The counts above are scheduled employees and role hours, not shortages.</p> : null}
      {picked ? (
        <div className="cov-day">
          <h3>{DAY_NAMES[picked.day]} · {roleTitle(picked.role)} · {picked.people} scheduled · {hoursLabel(picked.grossHours)} gross · {hoursLabel(picked.netHours)} net</h3>
          {picked.shared ? <p>Hours on this role are its share of time that is also assigned to another role.</p> : null}
          {Number(picked.untimedHours) > 0 ? <p>Net includes {hoursLabel(picked.untimedHours)} of untimed break. That break is not placed on the clock.</p> : null}
          {Number(picked.severalRoleUntimedHours) > 0 ? <p>{hoursLabel(picked.severalRoleUntimedHours)} of untimed break is not assigned to {roleTitle(picked.role)} because the shift has more than one role. It is not placed on the clock.</p> : null}
          {Number(picked.openTimeUntimedHours) > 0 ? <p>{hoursLabel(picked.openTimeUntimedHours)} of untimed break is not placed on the clock. It stays off {roleTitle(picked.role)} because part of the shift has no role.</p> : null}
          <p className="quiet">The first figure in each hour is scheduled headcount. The second is available headcount. A range means the number changes during that hour.</p>
          <div className="cov-hours">
            {pickedHours.map((row) => {
              const span = row.lowAvailable === row.highAvailable ? `${row.lowAvailable} av` : `${row.lowAvailable}–${row.highAvailable} av`;
              const detail = (row.slices || []).map((slice) => `${slice.start}–${slice.end}: ${slice.scheduled} scheduled, ${slice.available} available`).join(". ");
              return (
                <div
                  key={row.hour}
                  className={`cov-cell ${row.required == null ? "ok" : row.status}`}
                  title={detail || `${row.scheduled} scheduled`}
                  aria-label={`${String(row.hour).padStart(2, "0")}:00, ${row.scheduled} scheduled, ${span}${row.required == null ? "" : `, target ${row.required}`}`}
                >
                  <b>{String(row.hour).padStart(2, "0")}</b>
                  <span>{row.scheduled} sch</span>
                  <span>{row.required == null ? span : `${span} / ${row.required}`}</span>
                </div>
              );
            })}
          </div>
          <ul className="cov-slices">
            {breakWindows.map((slice) => (
              <li key={`${slice.hour}-${slice.start}-${slice.end}`}>{slice.start}–{slice.end}: {slice.scheduled} scheduled, {slice.available} available, {slice.onBreak} on a timed break</li>
            ))}
          </ul>
          {!breakWindows.length && picked.people ? <p className="quiet">No timed break overlaps this role, so scheduled employees stay available through each hour.</p> : null}
          <ul className="cov-staff">
            {roleStaff(entries, picked.role, picked.day).map((row, index) => (
              <li key={`${row.entry.id || row.entry.user_id}-${row.start}-${index}`}>
                <b>{personName(employees, row.entry.user_id)}</b>
                <span>{row.start && row.end ? `${row.start}–${row.end}` : "Not split"}{row.unsplit ? " · not split by role" : ""}</span>
                <button type="button" className="btn" onClick={() => onOpenShift?.(row.entry)}>Open in schedule</button>
              </li>
            ))}
          </ul>
          {!roleStaff(entries, picked.role, picked.day).length ? <p className="quiet">Nobody is scheduled in this role.</p> : null}
        </div>
      ) : null}
      {!roles.length ? <p className="quiet">No roles are scheduled.</p> : null}
    </section>
  );
}

export function BreakImpact({ entries, day, unscheduledCount }) {
  const rows = breakLoad(entries, day);
  const peak = rows.reduce((max, row) => Math.max(max, row.onBreak), 0);
  return (
    <section className="coverage-board" aria-label="Break staffing">
      <header>
        <h2>{DAY_NAMES[day]} breaks and coverage</h2>
        <p>
          {unscheduledCount
            ? `${unscheduledCount} breaks have no clock time. Timed overlap below does not include them, so a zero is confirmed timed overlap only.`
            : "Every stored break on this day has a clock time, so the overlap count is complete."}
          {peak ? ` Peak timed overlap is ${peak}.` : ""}
        </p>
      </header>
      <div className="hour-row">
        {rows.map((row) => (
          <div key={row.hour} className={`hour-chip ${row.onBreak > 2 ? "short" : "ok"}`}>
            <b>{String(row.hour).padStart(2, "0")}</b>
            <span>{row.onBreak} on break</span>
            <span>{row.working} working</span>
          </div>
        ))}
      </div>
    </section>
  );
}

function patchTask(tasks, task, patch) {
  return tasks.map((item) => (item === task || (task.id && item.id === task.id) ? { ...item, ...patch, changed: !item.draft } : item));
}

function TaskEdit({ task, tasks, employees, onChange }) {
  if (lockedTask(task)) return <em>History kept</em>;
  return (
    <span className="task-edit">
      <select aria-label={`Reassign ${task.role}`} value={task.user_id} onChange={(event) => onChange(patchTask(tasks, task, { user_id: Number(event.target.value) }))}>
        {employees.map((employee) => <option key={employee.user_id} value={employee.user_id}>{employee.display_name}</option>)}
      </select>
      <select aria-label={`Reschedule ${task.role}`} value={task.day_of_week} onChange={(event) => onChange(patchTask(tasks, task, { day_of_week: Number(event.target.value) }))}>
        {DAY_ORDER.map((value) => <option key={value} value={value}>{DAY_NAMES[value]}</option>)}
      </select>
      <label><input type="checkbox" checked={task.timing_mode !== "specific_time"} onChange={(event) => onChange(patchTask(tasks, task, event.target.checked ? { timing_mode: "anytime", start_time: null, end_time: null } : { timing_mode: TASK_TIMING.SPECIFIC }))} /> Anytime</label>
      {task.timing_mode === "specific_time" ? (
        <>
          <input aria-label={`Planned start for ${task.role}`} type="time" step="900" value={String(task.start_time || "").slice(0, 5)} onChange={(event) => onChange(patchTask(tasks, task, { timing_mode: TASK_TIMING.SPECIFIC, start_time: event.target.value || null }))} />
          <input aria-label={`Planned end for ${task.role}`} type="time" step="900" value={String(task.end_time || "").slice(0, 5)} onChange={(event) => onChange(patchTask(tasks, task, { timing_mode: TASK_TIMING.SPECIFIC, end_time: event.target.value || null }))} />
        </>
      ) : null}
      <button type="button" className="btn" onClick={() => onChange(tasks.map((item) => (item === task || item.id === task.id ? { ...item, remove: true } : item)).filter((item) => !(item.draft && item.remove)))}>
        Remove
      </button>
    </span>
  );
}

const SHORT = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

function toggleId(list, value) {
  const text = String(value);
  return list.includes(text) ? list.filter((item) => item !== text) : [...list, text];
}

function TaskGroups({ title, tasks, employees, entries, allTasks, onChange, timed = false }) {
  const groups = new Map();
  tasks.forEach((task) => {
    const key = task.assignment_group_id ? `shared:${task.assignment_group_id}` : `task:${task.role}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(task);
  });
  return (
    <div>
      <h3>{title}</h3>
      {[...groups.entries()].map(([key, items]) => (
        <section key={key} className="task-group">
          <h4>
            {roleTitle(items[0].role)} · {items.length}
            {items[0].assignment_group_id ? " · shared activity" : ""}
          </h4>
          <ul className="task-list">
            {items.map((task) => {
              const window = taskWindow(task);
              const notes = timed ? taskConflicts(task, entries) : [];
              return (
                <li key={task.id || `${task.user_id}-${task.role}-${window.label}`}>
                  <b>{personName(employees, task.user_id)}</b>
                  <span>{SHORT[Number(task.day_of_week)] || ""} · {window.label.replaceAll("_", " ")}</span>
                  <em>{task.draft ? "Draft" : (task.activity_status || task.status || "assigned")}{task.verification_status ? ` · verification ${task.verification_status}` : ""}</em>
                  {notes.length ? <em className="warn">{notes.join(". ")}</em> : null}
                  <TaskEdit task={task} tasks={allTasks} employees={employees} onChange={onChange} />
                </li>
              );
            })}
          </ul>
        </section>
      ))}
    </div>
  );
}

export function TaskPlanner({ tasks, employees, entries, day, mode, catalog, onChange, onReview }) {
  const [people, setPeople] = useState(employees[0] ? [String(employees[0].user_id)] : []);
  const [days, setDays] = useState([String(day)]);
  const [role, setRole] = useState("");
  const [category, setCategory] = useState("intra_day");
  const [timing, setTiming] = useState(TASK_TIMING.ANYTIME);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [query, setQuery] = useState("");
  const [joinGroup, setJoinGroup] = useState("");
  const [employeeQuery, setEmployeeQuery] = useState("");
  const visible = (tasks || []).filter((task) => !task.remove);
  const source = catalog && catalog.length ? catalog : scheduleRoleCatalog();
  const taskRoles = source.filter((item) => item.uses_time_slots === false && item.active !== false);
  const choices = taskRoles.filter((item) => {
    const label = `${item.name || ""} ${item.code || ""}`.toLowerCase();
    return !query || label.includes(query.toLowerCase());
  });
  const workload = new Map();
  visible.forEach((task) => {
    const key = Number(task.user_id);
    workload.set(key, (workload.get(key) || 0) + 1);
  });

  function add(event) {
    event.preventDefault();
    const name = role.trim();
    if (!name || !people.length || !days.length) return;
    if (timing === TASK_TIMING.SPECIFIC && (!start || !end)) return;
    const stamp = Date.now();
    const additions = [];
    people.forEach((userId) => {
      days.forEach((value) => {
        additions.push({
          id: `draft-task-${stamp}-${userId}-${value}`,
          draft: true,
          user_id: Number(userId),
          day_of_week: Number(value),
          role: name,
          category_code: category,
          timing_mode: timing,
          start_time: timing === TASK_TIMING.SPECIFIC ? start : null,
          end_time: timing === TASK_TIMING.SPECIFIC ? end : null,
          execution_mode: joinGroup ? "shared" : "individual",
          assignment_group_id: joinGroup || null,
          status: "assigned",
        });
      });
    });
    onChange([...tasks, ...additions]);
  }

  return (
    <section className="task-planner">
      <header>
        <h2>Task planner</h2>
        <p>Assignments use the existing task records. A task without a specific clock time stays off the timeline. Completed history is not rewritten.</p>
      </header>
      <form className="task-form" onSubmit={add}>
        <select aria-label="Task category" value={category} onChange={(event) => setCategory(event.target.value)}>
          {DEFAULT_CATEGORY_TABS.map((item) => <option key={item.code} value={item.code}>{item.name}</option>)}
        </select>
        <input aria-label="Find a task" value={query} placeholder="Find a task" onChange={(event) => setQuery(event.target.value)} />
        <select aria-label="Task" value={role} onChange={(event) => setRole(event.target.value)} required>
          <option value="">Choose a task or activity group</option>
          {choices.map((item) => {
            const frequency = item.recurrence?.weekly_frequency || item.weekly_frequency;
            const recurring = item.recurrence?.mode === "recurring";
            return (
              <option key={item.code} value={item.code}>
                {String(item.code || "").startsWith("agroup_") ? "Activity · " : ""}{item.name || scheduleRoleLabel(item.code)}
                {recurring && frequency ? ` · ${frequency}/week` : ""}
              </option>
            );
          })}
        </select>
        <input aria-label="Find an employee" value={employeeQuery} placeholder="Find an employee" onChange={(event) => setEmployeeQuery(event.target.value)} />
        <div className="pick-row" role="group" aria-label="Employees">
          {employees.filter((employee) => String(employee.display_name || "").toLowerCase().includes(employeeQuery.toLowerCase())).map((employee) => (
            <label key={employee.user_id}>
              <input type="checkbox" checked={people.includes(String(employee.user_id))} onChange={() => setPeople((current) => toggleId(current, employee.user_id))} />
              {employee.display_name}
            </label>
          ))}
        </div>
        <label>
          Occurrence
          <select aria-label="Shared occurrence" value={joinGroup} onChange={(event) => setJoinGroup(event.target.value)}>
            <option value="">Keep this assignment individual</option>
            {[...new Map(visible.filter((task) => task.role === role && task.assignment_group_id).map((task) => [task.assignment_group_id, task])).values()].map((task) => (
              <option key={task.assignment_group_id} value={task.assignment_group_id}>Join {roleTitle(task.role)} · {String(task.assignment_group_id).slice(0, 8)}</option>
            ))}
          </select>
        </label>
        <p className="quiet">{people.length} employees · {days.length} days. Nothing is saved until Save task changes.</p>
        <div className="pick-row" role="group" aria-label="Days">
          {DAY_ORDER.map((value) => (
            <label key={value}>
              <input type="checkbox" checked={days.includes(String(value))} onChange={() => setDays((current) => toggleId(current, value))} />
              {SHORT[value]}
            </label>
          ))}
        </div>
        <select aria-label="Task timing" value={timing} onChange={(event) => setTiming(event.target.value)}>
          {TASK_TIMING_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
        </select>
        {timing === TASK_TIMING.SPECIFIC ? (
          <>
            <input aria-label="Planned start" type="time" step="900" value={start} onChange={(event) => setStart(event.target.value)} required />
            <input aria-label="Planned end" type="time" step="900" value={end} onChange={(event) => setEnd(event.target.value)} required />
          </>
        ) : null}
        <button type="submit" className="btn">Assign</button>
        <button type="button" className="btn primary" disabled={!(tasks || []).some((task) => task.draft || task.remove || task.changed)} onClick={onReview}>Save task changes</button>
      </form>
      <div className="workload">
        {[...workload.entries()].map(([id, count]) => <span key={id}>{personName(employees, id)} · {count}</span>)}
      </div>
      {mode !== "day" ? (
        <div className="week-board" role="table" aria-label="Tasks for the week">
          <div className="week-head"><span>Employee</span>{DAY_ORDER.map((value) => <span key={value}>{SHORT[value]}</span>)}</div>
          {employees.map((employee) => (
            <div className="week-row" key={employee.user_id}>
              <strong>{employee.display_name}</strong>
              {DAY_ORDER.map((value) => {
                const mine = visible.filter((task) => Number(task.user_id) === Number(employee.user_id) && Number(task.day_of_week) === Number(value));
                return (
                  <div key={value}>
                    {mine.map((task) => (
                      <em key={task.id || task.role} className={lockedTask(task) ? "is-locked" : ""}>
                        {roleTitle(task.role)} · {task.draft ? "Draft" : (task.activity_status || task.status || "assigned")}
                      </em>
                    ))}
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      ) : null}
      <div className="task-columns">
        <TaskGroups
          title="On the timeline"
          tasks={visible.filter((task) => (mode !== "day" || Number(task.day_of_week) === Number(day)) && taskWindow(task).scheduled)}
          employees={employees}
          entries={entries}
          allTasks={tasks}
          onChange={onChange}
          timed
        />
        <TaskGroups
          title="No clock time"
          tasks={visible.filter((task) => (mode !== "day" || Number(task.day_of_week) === Number(day)) && !taskWindow(task).scheduled)}
          employees={employees}
          entries={entries}
          allTasks={tasks}
          onChange={onChange}
        />
      </div>
    </section>
  );
}
