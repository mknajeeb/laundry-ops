import { useState } from "react";
import { DAY_NAMES, DAY_ORDER, breakLoad, clockMinutes, staffingHours, taskWindow } from "./plannerModel";
import { roleColor, visibleBreaks } from "./plannerGeometry";
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

export function CoverageBoard({ entries, requirements, employees, day, days, onOpenGap }) {
  const shown = (days && days.length ? days : [day]);
  const [picked, setPicked] = useState(null);
  const roles = [...new Set((entries || []).flatMap((entry) => {
    const segments = (entry.role_assignments || []).map((item) => item.role).filter(Boolean);
    const codes = segments.length ? segments : String(entry.role || "").split(",").map((item) => item.trim()).filter(Boolean);
    return codes.filter((code) => !String(code).includes(","));
  }))];
  return (
    <section className="coverage-board" aria-label="Hourly staffing">
      <header>
        <h2>Staffing coverage</h2>
        <p>A colored hour is people still working after timed breaks. A requirement shows scheduled/required. An hour with no requirement is not a shortage.</p>
      </header>
      {shown.map((value) => (
        <div key={value} className="cov-day">
          <h3>{DAY_NAMES[value]}</h3>
          {roles.map((role) => {
            const rows = staffingHours(entries, requirements, role, value);
            if (!rows.length) return null;
            return (
              <div key={`${value}-${role}`} className="cov-row">
                <div className="cov-name"><i style={{ background: roleColor(role) }} />{roleTitle(role)}</div>
                <div className="cov-hours">
                  {rows.map((row) => (
                    <button
                      key={row.hour}
                      type="button"
                      className={`cov-cell ${row.status}${picked && picked.day === value && picked.role === role && picked.hour === row.hour ? " is-on" : ""}`}
                      onClick={() => {
                        setPicked({ day: value, role, hour: row.hour, row });
                        onOpenGap?.(value, role, row.hour);
                      }}
                    >
                      <b>{String(row.hour).padStart(2, "0")}</b>
                      <span>{row.required == null ? row.scheduled : `${row.scheduled}/${row.required}`}</span>
                    </button>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      ))}
      {picked ? (
        <p className="cov-detail">
          {DAY_NAMES[picked.day]} {String(picked.hour).padStart(2, "0")}:00 · {roleTitle(picked.role)} · {picked.row.required == null ? `${picked.row.scheduled} scheduled, no requirement` : `${picked.row.scheduled} scheduled, ${picked.row.required} required`}.
          {" "}{picked.row.userIds.map((id) => personName(employees, id)).join(", ") || "Nobody scheduled."}
        </p>
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
      <input aria-label={`Clock time for ${task.role}`} type="time" step="900" value={String(task.start_time || "").slice(0, 5)} onChange={(event) => onChange(patchTask(tasks, task, { timing_mode: event.target.value ? TASK_TIMING.SPECIFIC : "anytime", start_time: event.target.value || null }))} />
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

export function TaskPlanner({ tasks, employees, entries, day, mode, catalog, onChange, onReview }) {
  const [people, setPeople] = useState(employees[0] ? [String(employees[0].user_id)] : []);
  const [days, setDays] = useState([String(day)]);
  const [role, setRole] = useState("");
  const [category, setCategory] = useState("intra_day");
  const [timing, setTiming] = useState(TASK_TIMING.ANYTIME);
  const [start, setStart] = useState("");
  const [shared, setShared] = useState(false);
  const [query, setQuery] = useState("");
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
    if (timing === TASK_TIMING.SPECIFIC && !start) return;
    const group = shared ? `draft-group-${Date.now()}` : null;
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
          shared,
          assignment_group_id: group,
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
        <select multiple aria-label="Employees" value={people} onChange={(event) => setPeople([...event.target.selectedOptions].map((option) => option.value))}>
          {employees.map((employee) => <option key={employee.user_id} value={employee.user_id}>{employee.display_name}</option>)}
        </select>
        <p className="quiet">Hold Command or Ctrl to choose more than one employee. A task can store a start time. The assignment record has no scheduled end time.</p>
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
        {timing === TASK_TIMING.SPECIFIC ? <input aria-label="Task time" type="time" step="900" value={start} onChange={(event) => setStart(event.target.value)} /> : null}
        <label><input type="checkbox" checked={shared} onChange={(event) => setShared(event.target.checked)} /> Shared group</label>
        <button type="submit" className="btn">Assign</button>
        <button type="button" className="btn primary" disabled={!(tasks || []).some((task) => task.draft || task.remove)} onClick={onReview}>Review task save</button>
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
        <div>
          <h3>On the timeline</h3>
          <ul className="task-list">
            {visible.filter((task) => (mode !== "day" || Number(task.day_of_week) === Number(day)) && taskWindow(task).scheduled).map((task) => {
              const window = taskWindow(task);
              const notes = taskConflicts(task, entries);
              return (
                <li key={task.id || `${task.user_id}-${task.role}-${window.label}`}>
                  <b>{personName(employees, task.user_id)}</b>
                  <span>{roleTitle(task.role)} · {window.label}</span>
                  <em>{task.draft ? "Draft" : (task.activity_status || task.status || "assigned")}{task.verification_status ? ` · verification ${task.verification_status}` : ""}</em>
                  {notes.length ? <em className="warn">{notes.join(". ")}</em> : null}
                  <TaskEdit task={task} tasks={tasks} employees={employees} onChange={onChange} />
                </li>
              );
            })}
          </ul>
        </div>
        <div>
          <h3>No clock time</h3>
          <ul className="task-list">
            {visible.filter((task) => (mode !== "day" || Number(task.day_of_week) === Number(day)) && !taskWindow(task).scheduled).map((task) => (
              <li key={task.id || `${task.user_id}-${task.role}`}>
                <b>{personName(employees, task.user_id)}</b>
                <span>{roleTitle(task.role)} · {taskWindow(task).label.replaceAll("_", " ")}</span>
                <em>{task.draft ? "Draft" : (task.activity_status || task.status || "assigned")}{task.assignment_group_id ? " · shared" : ""}</em>
                <TaskEdit task={task} tasks={tasks} employees={employees} onChange={onChange} />
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}
