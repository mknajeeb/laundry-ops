import { useState } from "react";
import { DAY_NAMES, DAY_ORDER, breakLoad, clockMinutes, staffingHours, taskWindow } from "./plannerModel";
import { roleColor, visibleBreaks } from "./plannerGeometry";
import { DEFAULT_CATEGORY_TABS } from "../components/tasks/taskDashboardLabels";
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

export function CoverageBoard({ entries, requirements, employees, day, onOpenGap }) {
  const roles = [...new Set((entries || []).flatMap((entry) => {
    const segments = (entry.role_assignments || []).map((item) => item.role).filter(Boolean);
    return segments.length ? segments : [entry.role].filter(Boolean);
  }))];
  return (
    <section className="coverage-board" aria-label="Hourly staffing">
      <header>
        <h2>{DAY_NAMES[day]} coverage</h2>
        <p>Each number is employees still working that role after timed breaks. A requirement shows scheduled/required. An hour with no requirement shows how many are scheduled.</p>
      </header>
      {roles.map((role) => {
        const rows = staffingHours(entries, requirements, role, day);
        return (
          <div key={role} className="coverage-role">
            <strong><i style={{ background: roleColor(role) }} />{String(role).replaceAll("_", " ")}</strong>
            <div className="hour-row">
              {rows.map((row) => (
                <button
                  key={row.hour}
                  type="button"
                  className={`hour-chip ${row.status}`}
                  onClick={() => onOpenGap(day, role, row.hour)}
                  title={row.assignments === row.scheduled ? "" : `${row.assignments} role assignments, ${row.scheduled} employees`}
                >
                  <b>{String(row.hour).padStart(2, "0")}</b>
                  <span>{row.required == null ? `${row.scheduled} scheduled` : `${row.scheduled}/${row.required}`}</span>
                </button>
              ))}
              {!rows.length ? <span className="quiet">No scheduled time and no requirement.</span> : null}
            </div>
            {rows.filter((row) => row.status === "short").map((row) => (
              <p key={`gap-${row.hour}`} className="quiet">
                Short {row.required - row.scheduled} at {String(row.hour).padStart(2, "0")}:00.
                Working: {row.userIds.map((id) => personName(employees, id)).join(", ") || "nobody"}.
              </p>
            ))}
          </div>
        );
      })}
      {!roles.length ? <p className="quiet">No roles are scheduled. Set a requirement from a role row after a shift has a role.</p> : null}
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

export function TaskPlanner({ tasks, employees, entries, day, mode, catalog, onChange, onReview }) {
  const [userId, setUserId] = useState(employees[0] ? String(employees[0].user_id) : "");
  const [role, setRole] = useState("");
  const [category, setCategory] = useState("intra_day");
  const [timing, setTiming] = useState(TASK_TIMING.ANYTIME);
  const [start, setStart] = useState("");
  const [shared, setShared] = useState(false);
  const visible = (tasks || []).filter((task) => !task.remove && (mode !== "day" || Number(task.day_of_week) === Number(day)));
  const taskRoles = (catalog || []).filter((item) => item.uses_time_slots === false && item.active !== false);
  const choices = taskRoles.length ? taskRoles : [];
  const workload = new Map();
  visible.forEach((task) => {
    const key = Number(task.user_id);
    workload.set(key, (workload.get(key) || 0) + 1);
  });

  function add(event) {
    event.preventDefault();
    const name = role.trim();
    if (!name || !userId) return;
    if (timing === TASK_TIMING.SPECIFIC && !start) return;
    onChange([...tasks, {
      id: `draft-task-${Date.now()}`,
      draft: true,
      user_id: Number(userId),
      day_of_week: day,
      role: name,
      category_code: category,
      timing_mode: timing,
      start_time: timing === TASK_TIMING.SPECIFIC ? start : null,
      shared,
      assignment_group_id: shared ? `draft-group-${Date.now()}` : null,
      status: "assigned",
    }]);
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
        <select aria-label="Task employee" value={userId} onChange={(event) => setUserId(event.target.value)}>
          {employees.map((employee) => <option key={employee.user_id} value={employee.user_id}>{employee.display_name}</option>)}
        </select>
        {choices.length ? (
          <select aria-label="Task" value={role} onChange={(event) => setRole(event.target.value)}>
            <option value="">Choose a task</option>
            {choices.map((item) => <option key={item.code} value={item.code}>{item.name || item.code}</option>)}
          </select>
        ) : (
          <input aria-label="Task name" value={role} onChange={(event) => setRole(event.target.value)} placeholder="Task name" />
        )}
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
      <div className="task-columns">
        <div>
          <h3>On the timeline</h3>
          <ul className="task-list">
            {visible.filter((task) => taskWindow(task).scheduled).map((task) => {
              const window = taskWindow(task);
              const notes = taskConflicts(task, entries);
              return (
                <li key={task.id || `${task.user_id}-${task.role}-${window.label}`}>
                  <b>{personName(employees, task.user_id)}</b>
                  <span>{task.role} · {window.label}</span>
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
            {visible.filter((task) => !taskWindow(task).scheduled).map((task) => (
              <li key={task.id || `${task.user_id}-${task.role}`}>
                <b>{personName(employees, task.user_id)}</b>
                <span>{task.role} · {taskWindow(task).label.replaceAll("_", " ")}</span>
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
