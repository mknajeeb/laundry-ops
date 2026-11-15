import { useCallback, useEffect, useMemo, useState } from "react";
import axios from "axios";
import { getWashproApiBase } from "../api";
import "./operationsPlanner.css";
import {
  BREAK_OVERLAP_CAP,
  DAY_NAMES,
  DAY_ORDER,
  autoScrollDelta,
  entriesForPeriod,
  hourCoverage,
  movedShift,
  overlappingBreakCount,
  periodLabel,
  shiftHours,
  taskRollup,
} from "./plannerModel";
import { printDocumentHtml, scheduleCardSvg, scheduleCsv } from "./scheduleExport";

const LENSES = [
  ["employees", "Employees"],
  ["roles", "Roles"],
  ["breaks", "Breaks"],
  ["tasks", "Tasks"],
];

function api(path, config = {}) {
  return axios({ baseURL: getWashproApiBase(), url: path, ...config });
}

function shiftIso(iso, days) {
  const [year, month, day] = String(iso || "").split("-").map(Number);
  if (!year) return "";
  const date = new Date(Date.UTC(year, month - 1, day + days));
  return date.toISOString().slice(0, 10);
}

function download(filename, contents, type) {
  const blob = new Blob([contents], { type });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

async function copyCard(svg) {
  try {
    const blob = new Blob([svg], { type: "image/svg+xml" });
    const url = URL.createObjectURL(blob);
    const image = new Image();
    await new Promise((resolve, reject) => {
      image.onload = resolve;
      image.onerror = reject;
      image.src = url;
    });
    const canvas = document.createElement("canvas");
    canvas.width = image.width;
    canvas.height = image.height;
    canvas.getContext("2d").drawImage(image, 0, 0);
    URL.revokeObjectURL(url);
    const png = await new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
    await navigator.clipboard.write([new ClipboardItem({ "image/png": png })]);
    return "copied";
  } catch {
    download("schedule.svg", svg, "image/svg+xml");
    return "downloaded";
  }
}

function entryShift(entry) {
  return {
    user_id: Number(entry.user_id),
    day_of_week: Number(entry.day_of_week),
    start_time: String(entry.start_time || "").slice(0, 5),
    end_time: String(entry.end_time || "").slice(0, 5),
    role: entry.role || "fold",
    break_minutes: Number(entry.break_minutes || 0),
    break_slots: entry.break_slots || [],
    role_assignments: entry.role_assignments || entry.assignments || [],
    tasks: entry.tasks || [],
  };
}

export default function OperationsPlannerV2Page() {
  const [flags, setFlags] = useState(null);
  const [week, setWeek] = useState("");
  const [mode, setMode] = useState("week");
  const [lens, setLens] = useState("employees");
  const [day, setDay] = useState(1);
  const [payload, setPayload] = useState(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [full, setFull] = useState(false);
  const [pending, setPending] = useState(null);
  const [scope, setScope] = useState("this_week");
  const [publishedChoice, setPublishedChoice] = useState(null);
  const [exceptionChoice, setExceptionChoice] = useState(null);
  const [stopTemplate, setStopTemplate] = useState(false);
  const [selectedWeeks, setSelectedWeeks] = useState("");
  const [drag, setDrag] = useState(null);

  const load = useCallback(async (weekStart) => {
    const status = await api("/operations-planner/v2/status");
    setFlags(status.data.flags);
    if (!status.data.flags?.manager_pilot) {
      setPayload(null);
      return;
    }
    const response = await api("/operations-planner/v2/week", { params: weekStart ? { week_start: weekStart } : {} });
    setPayload(response.data);
    if (!weekStart && response.data?.planner?.week_monday) setWeek(response.data.planner.week_monday);
  }, []);

  useEffect(() => {
    load(week).catch((err) => setError(err.response?.data?.error || err.message));
  }, [load, week]);

  const employees = payload?.employees || [];
  const entries = useMemo(() => (payload?.entries || []).map(entryShift), [payload]);
  const responsibilities = payload?.daily_responsibilities || [];
  const visibleEntries = entriesForPeriod(entries, { mode, day });
  const visibleTasks = responsibilities.filter((row) => mode !== "day" || Number(row.day_of_week) === Number(day));
  const planner = payload?.planner || {};
  const period = periodLabel(mode, payload?.week_label || week, DAY_NAMES[day]);
  const hours = visibleEntries.reduce((sum, entry) => sum + shiftHours(entry).net, 0);
  const breakHot = overlappingBreakCount(visibleEntries) > BREAK_OVERLAP_CAP;
  const tasks = taskRollup(visibleTasks);

  function rowsFor(list) {
    return list.map((entry) => {
      const person = employees.find((employee) => Number(employee.user_id) === Number(entry.user_id));
      const slot = (entry.break_slots || []).map((item) => `${item.start_time}–${item.end_time}${item.timed === false ? " untimed" : ""}`).join("; ");
      return {
        employee: person?.display_name || `Employee ${entry.user_id}`,
        day: DAY_NAMES[entry.day_of_week],
        start: entry.start_time,
        end: entry.end_time,
        role: entry.role,
        breaks: slot,
        tasks: "",
        when: `${DAY_NAMES[entry.day_of_week]} ${entry.start_time}–${entry.end_time}`,
        detail: `${entry.role} ${slot}`.trim(),
        name: person?.display_name || `Employee ${entry.user_id}`,
      };
    });
  }

  async function saveFlags(next) {
    const response = await api("/operations-planner/v2/settings", { method: "PUT", data: next });
    setFlags(response.data.flags);
    await load(week);
  }

  function queueChange(command) {
    setScope("this_week");
    setPublishedChoice(null);
    setExceptionChoice(null);
    setStopTemplate(false);
    setPending({ command });
    setError("");
  }

  async function send(path) {
    const body = {
      ...pending.command,
      scope,
      week_start: week,
      anchor: week,
      selected_weeks: selectedWeeks.split(",").map((item) => item.trim()).filter(Boolean),
      include_published: publishedChoice,
      replace_exceptions: exceptionChoice,
      stop_legacy_template: stopTemplate,
    };
    const response = await api(path, { method: "POST", data: body, validateStatus: () => true });
    if (path.endsWith("/preview")) {
      setPending({ command: pending.command, preview: response.data });
      setError(response.status >= 400 && response.data?.code !== "confirmation_required" ? (response.data?.error || "Could not review the change") : "");
      return;
    }
    if (response.status === 409 && response.data?.code === "confirmation_required") {
      setPending({ command: pending.command, preview: response.data });
      setError("");
      return;
    }
    if (response.status === 409) {
      setPending({ command: pending.command, preview: response.data });
      setError(response.data.error || "Choose how far this change applies.");
      return;
    }
    if (response.status >= 400) {
      setError(response.data?.error || "Could not save the schedule");
      return;
    }
    setPending(null);
    setNotice(response.data.republish_required?.length ? "Saved. Published weeks went back to draft and need approval." : "Saved.");
    await load(week);
  }

  function onDrop(event, userId, dayOfWeek) {
    event.preventDefault();
    if (!drag) return;
    const copy = event.altKey;
    const next = movedShift(drag.shift, { dayOfWeek });
    queueChange({
      action: copy ? "copy" : "move",
      user_id: userId,
      user_ids: [userId],
      from_user_id: drag.shift.user_id,
      from_day_of_week: drag.shift.day_of_week,
      day_of_week: dayOfWeek,
      previous_shift: drag.shift,
      shift: { ...next, user_id: userId },
    });
    setDrag(null);
  }

  function onDragOver(event) {
    event.preventDefault();
    const board = event.currentTarget.closest(".ops-board");
    if (!board) return;
    const delta = autoScrollDelta(event.clientY, board.getBoundingClientRect());
    if (delta) board.scrollTop += delta;
  }

  const exportRows = rowsFor(visibleEntries);
  const preview = pending?.preview?.preview || pending?.preview;

  return (
    <div className={`ops-planner ${full ? "fullscreen" : ""}`}>
      <header>
        <div>
          <h1>Operations Planner</h1>
          <p>{period} · {planner.status || "draft"} · revision {planner.revision || 1}</p>
        </div>
        <button type="button" onClick={() => setFull((value) => !value)}>{full ? "Exit full screen" : "Expand"}</button>
      </header>
      {!flags?.manager_pilot ? (
        <div className="ops-toolbar">
          <span>The manager pilot is off.</span>
          <button type="button" className="primary" onClick={() => saveFlags({ manager_pilot: true }).catch((err) => setError(err.response?.data?.error || err.message))}>
            Enable manager pilot
          </button>
        </div>
      ) : (
        <div className="ops-toolbar no-print">
          {LENSES.map(([id, label]) => (
            <button key={id} type="button" className={lens === id ? "active" : ""} onClick={() => setLens(id)}>{label}</button>
          ))}
          <button type="button" className={mode === "week" ? "active" : ""} onClick={() => setMode("week")}>Week</button>
          <button type="button" className={mode === "day" ? "active" : ""} onClick={() => setMode("day")}>Day</button>
          <button type="button" onClick={() => setWeek(shiftIso(week, -7))}>Previous</button>
          <button type="button" onClick={() => setWeek(shiftIso(week, 7))}>Next</button>
          {mode === "day" ? (
            <select value={day} onChange={(event) => setDay(Number(event.target.value))}>
              {DAY_ORDER.map((value) => <option key={value} value={value}>{DAY_NAMES[value]}</option>)}
            </select>
          ) : null}
          <button type="button" onClick={() => api("/operations-planner/v2/weeks/approve", { method: "POST", data: { weeks: [week] } }).then(() => load(week))}>Approve week</button>
          <button type="button" onClick={() => api("/operations-planner/v2/weeks/publish", { method: "POST", data: { weeks: [week] } }).then(() => load(week))}>Publish week</button>
          <button type="button" onClick={() => copyCard(scheduleCardSvg({ title: `Schedule · ${period}`, subtitle: planner.status || "draft", rows: exportRows }))}>Copy image</button>
          <button type="button" onClick={() => download(`schedule-${week}.csv`, scheduleCsv(exportRows), "text/csv")}>CSV</button>
          <button type="button" onClick={() => {
            const html = printDocumentHtml({ title: `${lens} · ${period}`, subtitle: week, sections: [{ heading: lens, rows: exportRows }] });
            const popup = window.open("", "_blank");
            if (!popup) return;
            popup.document.write(html);
            popup.document.close();
            popup.focus();
            popup.print();
          }}>Print</button>
        </div>
      )}
      {error ? <p className="ops-note ops-warn">{error}</p> : null}
      {notice ? <p className="ops-note">{notice}</p> : null}
      {payload ? (
        <div className="ops-main">
          <section className="ops-board" onDragOver={onDragOver}>
            {lens === "employees" ? (
              <table className="ops-grid">
                <thead>
                  <tr>
                    <th>Employee</th>
                    {(mode === "day" ? [day] : DAY_ORDER).map((value) => <th key={value}>{DAY_NAMES[value]}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {employees.map((employee) => (
                    <tr key={employee.user_id}>
                      <th>{employee.display_name}</th>
                      {(mode === "day" ? [day] : DAY_ORDER).map((value) => (
                        <td key={value} onDragOver={(event) => event.preventDefault()} onDrop={(event) => onDrop(event, Number(employee.user_id), value)}>
                          {entries.filter((entry) => Number(entry.user_id) === Number(employee.user_id) && Number(entry.day_of_week) === value).map((entry) => {
                            const figures = shiftHours(entry);
                            return (
                              <button
                                key={entry.id || `${entry.user_id}-${entry.start_time}`}
                                type="button"
                                className="ops-shift"
                                draggable
                                onDragStart={() => setDrag({ shift: entry })}
                                title={`${entry.role}, ${figures.net} net hours. Drag to move. Hold Alt to copy.`}
                              >
                                {entry.start_time}–{entry.end_time}
                                <small>{entry.role} · {figures.gross.toFixed(1)} gross / {figures.net.toFixed(1)} net</small>
                              </button>
                            );
                          })}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : null}
            {lens === "roles" ? (
              <RoleBoard entries={visibleEntries} employees={employees} />
            ) : null}
            {lens === "breaks" ? (
              <BreakBoard entries={visibleEntries} employees={employees} />
            ) : null}
            {lens === "tasks" ? (
              <TaskBoard tasks={visibleTasks} employees={employees} />
            ) : null}
          </section>
          <aside className="ops-side">
            <h2>{period}</h2>
            <p>{employees.length} employees · {visibleEntries.length} shifts · {hours.toFixed(1)} net hours</p>
            <p>Tasks: {tasks.counts.total} groups ({tasks.counts.completed} completed, {tasks.counts.awaiting} awaiting verification). People rows: {tasks.people.total}.</p>
            {breakHot ? <p className="ops-warn">More than three timed breaks overlap in this {mode}.</p> : <p>Break overlap is within the limit of three.</p>}
            <p>Status: {planner.status || "draft"}. Employees see the last published revision{planner.published_revision ? ` ${planner.published_revision}` : ""}.</p>
            <AccessEditor employees={employees} onSaved={() => load(week)} onError={setError} />
            {(planner.role_settings || []).map((role) => (
              <label key={role.role} style={{ display: "block", fontSize: 13 }}>
                <input
                  type="checkbox"
                  checked={Boolean(role.show_on_rinse_dashboard)}
                  onChange={(event) => {
                    api(`/operations-planner/v2/roles/${encodeURIComponent(role.role)}`, {
                      method: "PUT",
                      data: { show_on_rinse_dashboard: event.target.checked },
                    }).then(() => load(week)).catch((err) => setError(err.response?.data?.error || err.message));
                  }}
                />
                {" "}{role.role} on the Rinse dashboard
                {role.visible_to_rinse ? "" : " (still hidden by labor policy)"}
              </label>
            ))}
            {planner.legacy_template ? <p className="ops-warn">The old repeating template is still on. A recurring save will ask to stop it.</p> : null}
          </aside>
        </div>
      ) : null}
      {pending ? (
        <div className="ops-dialog-back">
          <form className="ops-dialog" onSubmit={(event) => { event.preventDefault(); send("/operations-planner/v2/apply"); }}>
            <h2>How should this change apply?</h2>
            <p>{pending.command.action} · employee {pending.command.user_id} · {DAY_NAMES[pending.command.day_of_week] || ""}</p>
            {["this_week", "this_and_future", "future_only", "selected_weeks"].map((value) => (
              <label key={value} style={{ display: "block", marginBottom: 6 }}>
                <input type="radio" name="scope" checked={scope === value} onChange={() => setScope(value)} /> {value.replaceAll("_", " ")}
              </label>
            ))}
            {scope === "selected_weeks" ? (
              <input value={selectedWeeks} onChange={(event) => setSelectedWeeks(event.target.value)} placeholder="Mondays, comma separated" />
            ) : null}
            <p>Affected: {(preview?.dates || [week]).join(", ")}</p>
            {preview?.shift ? <p>{preview.shift.start_time}–{preview.shift.end_time} · {(preview.shift.roles || []).join(", ")} · {preview.shift.net_hours} net hours</p> : null}
            {preview?.approved_or_published_weeks?.length ? (
              <fieldset>
                <legend>Approved or published weeks: {preview.approved_or_published_weeks.join(", ")}</legend>
                <button type="button" className={publishedChoice === true ? "active" : ""} onClick={() => setPublishedChoice(true)}>Update them and require a new approval</button>
                <button type="button" className={publishedChoice === false ? "active" : ""} onClick={() => setPublishedChoice(false)}>Leave them unchanged</button>
              </fieldset>
            ) : null}
            {preview?.exception_weeks?.length ? (
              <fieldset>
                <legend>Weeks with a one-time exception: {preview.exception_weeks.join(", ")}</legend>
                <button type="button" className={exceptionChoice === true ? "active" : ""} onClick={() => setExceptionChoice(true)}>Replace those exceptions</button>
                <button type="button" className={exceptionChoice === false ? "active" : ""} onClick={() => setExceptionChoice(false)}>Keep those exceptions</button>
              </fieldset>
            ) : null}
            {planner.legacy_template ? (
              <label>
                <input type="checkbox" checked={stopTemplate} onChange={(event) => setStopTemplate(event.target.checked)} /> Stop the old template
              </label>
            ) : null}
            <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
              <button type="button" onClick={() => send("/operations-planner/v2/preview")}>Review</button>
              <button type="submit" className="primary">Confirm</button>
              <button type="button" onClick={() => setPending(null)}>Cancel</button>
            </div>
          </form>
        </div>
      ) : null}
    </div>
  );
}

function AccessEditor({ employees, onSaved, onError }) {
  const [userId, setUserId] = useState(employees[0] ? String(employees[0].user_id) : "");
  const [access, setAccess] = useState(null);
  useEffect(() => {
    if (!userId) return undefined;
    let cancel = false;
    api(`/operations-planner/v2/employees/${userId}/access`)
      .then((response) => {
        if (!cancel) setAccess(response.data.access);
      })
      .catch(() => {
        if (!cancel) setAccess(null);
      });
    return () => {
      cancel = true;
    };
  }, [userId]);

  async function update(key, value) {
    try {
      const response = await api(`/operations-planner/v2/employees/${userId}/access`, {
        method: "PUT",
        data: { [key]: value },
      });
      setAccess(response.data.access);
      onSaved();
    } catch (err) {
      onError(err.response?.data?.error || err.message);
    }
  }

  return (
    <div>
      <p>Employee PIN access</p>
      <select value={userId} onChange={(event) => setUserId(event.target.value)}>
        {employees.map((employee) => (
          <option key={employee.user_id} value={employee.user_id}>{employee.display_name}</option>
        ))}
      </select>
      {access ? ["schedule_enabled", "hours_enabled", "paystub_enabled"].map((key) => (
        <label key={key} style={{ display: "block", fontSize: 13 }}>
          <input type="checkbox" checked={Boolean(access[key])} onChange={(event) => update(key, event.target.checked)} />
          {" "}{key.replace("_enabled", "")}
        </label>
      )) : null}
    </div>
  );
}

function names(employees, userId) {
  return employees.find((employee) => Number(employee.user_id) === Number(userId))?.display_name || `Employee ${userId}`;
}

function RoleBoard({ entries, employees }) {
  const roles = [...new Set(entries.flatMap((entry) => (entry.role_assignments || []).map((item) => item.role).concat(entry.role)))];
  return (
    <div>
      {roles.map((role) => (
        <div key={role} className="lane">
          <strong>{role}</strong>
          <div>
            {entries.filter((entry) => entry.role === role || (entry.role_assignments || []).some((item) => item.role === role)).map((entry) => (
              <div key={`${role}-${entry.user_id}-${entry.start_time}`}>{names(employees, entry.user_id)} {entry.start_time}–{entry.end_time}</div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function BreakBoard({ entries, employees }) {
  const hours = [];
  for (let hour = 6; hour <= 21; hour += 1) hours.push(hour);
  return (
    <div style={{ display: "grid", gridTemplateColumns: `repeat(${hours.length}, minmax(72px, 1fr))` }}>
      {hours.map((hour) => {
        const cell = hourCoverage(entries, hour);
        return (
          <div key={hour} className="hour-cell">
            <strong>{hour}:00</strong>
            <div>{cell.available.length} available / {cell.scheduled.length} scheduled</div>
            {cell.onBreak.map((entry) => <div key={entry.user_id}>{names(employees, entry.user_id)} on break</div>)}
          </div>
        );
      })}
    </div>
  );
}

function TaskBoard({ tasks, employees }) {
  const byPerson = new Map();
  for (const task of tasks) {
    const key = Number(task.user_id);
    if (!byPerson.has(key)) byPerson.set(key, []);
    byPerson.get(key).push(task);
  }
  return (
    <div>
      {[...byPerson.entries()].map(([userId, rows]) => {
        const rollup = taskRollup(rows);
        return (
          <div key={userId} className="lane">
            <strong>{names(employees, userId)}</strong>
            <div>
              <div>{rollup.people.completed} completed · {rollup.people.inProgress} in progress · {rollup.people.pending} pending · {rollup.people.awaiting} awaiting verification · {rollup.people.verified} verified</div>
              {rows.map((row) => (
                <div key={row.id || `${row.role}-${row.user_id}`}>{row.role || row.name} · {row.assignment_group_id ? "shared" : "individual"} · {row.status || "pending"}</div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
