import { useEffect, useMemo, useState } from "react";
import {
  BREAK_OVERLAP_CAP,
  DAY_NAMES,
  DAY_ORDER,
  breakAccounting,
  minutesToClock,
  overlappingBreakCount,
  pointerToMinutes,
  requirementFor,
  roleCoverage,
  shiftHours,
} from "./plannerModel";
import {
  asList,
  barBox,
  displaySegments,
  pieceBox,
  placeBreak,
  relocateShift,
  resizeBreak,
  resizeEdge,
  resizeSegment,
  roleColor,
  shiftKey,
  timelineAxis,
  visibleBreaks,
} from "./plannerGeometry";

function personName(employees, userId) {
  return employees.find((employee) => Number(employee.user_id) === Number(userId))?.display_name || `Employee ${userId}`;
}

function clockOf(value) {
  const [hour, minute] = String(value || "00:00").slice(0, 5).split(":").map(Number);
  return hour * 60 + minute;
}

function HourRuler({ axis }) {
  const hours = [];
  for (let minute = axis.startMin; minute < axis.endMin; minute += 60) hours.push(minute / 60);
  return (
    <div className="ops-ws-ruler" aria-hidden="true">
      {hours.map((hour) => (
        <span key={hour} className={hour % 2 ? "tick" : ""} style={{ left: `${((hour * 60 - axis.startMin) / axis.span) * 100}%` }}>
          {hour % 2 ? "" : String(hour).padStart(2, "0")}
        </span>
      ))}
    </div>
  );
}

function shiftDetail(entry) {
  const timed = visibleBreaks(entry).filter((slot) => slot.start_time);
  const unscheduled = visibleBreaks(entry).find((slot) => slot.unscheduled);
  const segments = displaySegments(entry);
  const roleText = segments.some((segment) => segment.allocated)
    ? segments.map((segment) => `${segment.role} ${segment.start_time}–${segment.end_time}`).join(", ")
    : (entry.role || "No role segments");
  const breakText = unscheduled
    ? `Unscheduled break ${unscheduled.minutes} min`
    : timed.map((slot) => `Break ${slot.start_time}–${slot.end_time}`).join(", ");
  return `${String(entry.start_time).slice(0, 5)}–${String(entry.end_time).slice(0, 5)} · ${roleText}${breakText ? ` · ${breakText}` : ""}`;
}

function shiftCaption(entry, employees) {
  return `${personName(employees, entry.user_id)} · ${shiftDetail(entry)}`;
}

function ShiftBar({ entry, axis, employees, onSelect, onCommit, onlyRole, compact }) {
  const [live, setLive] = useState(null);
  const shown = live || entry;
  const segments = displaySegments(shown)
    .map((segment, index) => ({ ...segment, index }))
    .filter((segment) => !onlyRole || segment.role === onlyRole);
  const breaks = visibleBreaks(shown).filter((slot) => slot.start_time);
  const unscheduled = visibleBreaks(shown).find((slot) => slot.unscheduled);
  if (onlyRole && !segments.length) return null;
  const box = barBox(segments[0].start_time, segments[segments.length - 1].end_time, axis);
  const label = shiftCaption(shown, employees);

  function track(event, applyMove, applyEnd) {
    event.preventDefault();
    event.stopPropagation();
    const lane = event.currentTarget.closest(".ops-ws-track")?.getBoundingClientRect();
    if (!lane) return;
    const move = (pointer) => {
      const minutes = pointerToMinutes(pointer.clientX, lane, axis.startMin / 60, axis.endMin / 60);
      if (minutes != null) applyMove(minutes);
    };
    const finish = (pointer) => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", finish);
      const minutes = pointerToMinutes(pointer.clientX, lane, axis.startMin / 60, axis.endMin / 60);
      setLive(null);
      if (minutes != null) applyEnd(minutes);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", finish);
  }

  function beginMove(event) {
    if (event.button !== 0) return;
    const origin = event.clientX;
    const lane = event.currentTarget.closest(".ops-ws-track")?.getBoundingClientRect();
    if (!lane) return;
    let moved = false;
    let latest = entry.start_time;
    const move = (pointer) => {
      if (Math.abs(pointer.clientX - origin) > 4) moved = true;
      const delta = ((pointer.clientX - origin) / lane.width) * axis.span;
      latest = minutesToClock(clockOf(entry.start_time) + delta);
      if (!latest) return;
      setLive(relocateShift(entry, latest, entry.day_of_week));
    };
    const finish = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", finish);
      setLive(null);
      if (!moved) onSelect(entry);
      else onCommit(relocateShift(entry, latest, entry.day_of_week), `Proposed ${personName(employees, entry.user_id)} at ${latest}. Not saved.`);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", finish);
  }

  return (
    <div className="ops-ws-bar" style={box} data-shift-key={shiftKey(entry)}>
      <button type="button" className="ops-ws-body" aria-label={`Edit shift ${label}`} onPointerDown={beginMove}>
        {segments.map((segment) => (
          <span key={`${segment.role}-${segment.start_time}`} className={`ops-ws-segment${segment.allocated ? "" : " unallocated"}`} style={{ ...pieceBox(shown, segment), background: roleColor(segment.role) }}>
            <em>{segment.allocated ? segment.role : `${String(segment.start_time).slice(0, 5)}–${String(segment.end_time).slice(0, 5)}`}</em>
          </span>
        ))}
        {unscheduled && !compact ? <span className="ops-ws-unscheduled">Unscheduled break {unscheduled.minutes} min</span> : null}
        {breaks.map((slot, index) => (
          <span
            key={`${slot.start_time}-${index}`}
            className="ops-ws-break placed"
            style={pieceBox(shown, slot)}
            title={`Break ${slot.start_time}–${slot.end_time}`}
          />
        ))}
      </button>
      <button
        type="button"
        className="ops-ws-handle start"
        aria-label={`Change shift start for ${shown.start_time}`}
        onPointerDown={(event) => track(
          event,
          (minutes) => setLive(resizeEdge(entry, "start", minutes)),
          (minutes) => onCommit(resizeEdge(entry, "start", minutes), "Proposed a new shift start. Not saved."),
        )}
      />
      <button
        type="button"
        className="ops-ws-handle end"
        aria-label={`Change shift end for ${shown.end_time}`}
        onPointerDown={(event) => track(
          event,
          (minutes) => setLive(resizeEdge(entry, "end", minutes)),
          (minutes) => onCommit(resizeEdge(entry, "end", minutes), "Proposed a new shift end. Not saved."),
        )}
      />
      {segments.map((segment, index) => (
        segment.allocated ? (
          <span key={`seg-${segment.role}-${index}`} className="ops-ws-seg-handles" style={pieceBox(shown, segment)}>
            <button type="button" aria-label={`Change ${segment.role} start`} onPointerDown={(event) => track(event, (minutes) => setLive(resizeSegment(entry, segment.index, "start", minutes)), (minutes) => onCommit(resizeSegment(entry, segment.index, "start", minutes), "Proposed a role-segment change. Not saved."))} />
            <button type="button" aria-label={`Change ${segment.role} end`} onPointerDown={(event) => track(event, (minutes) => setLive(resizeSegment(entry, segment.index, "end", minutes)), (minutes) => onCommit(resizeSegment(entry, segment.index, "end", minutes), "Proposed a role-segment change. Not saved."))} />
          </span>
        ) : null
      ))}
      {breaks.map((slot, index) => (
        <span key={`brk-${slot.start_time}-${index}`} className="ops-ws-break-handles" style={pieceBox(shown, slot)}>
          <button type="button" aria-label={`Change break start ${slot.start_time}`} onPointerDown={(event) => track(event, (minutes) => setLive(resizeBreak(entry, index, "start", minutes)), (minutes) => onCommit(resizeBreak(entry, index, "start", minutes), "Proposed a break change. Not saved."))} />
          <button type="button" aria-label={`Change break end ${slot.end_time}`} onPointerDown={(event) => track(event, (minutes) => setLive(resizeBreak(entry, index, "end", minutes)), (minutes) => onCommit(resizeBreak(entry, index, "end", minutes), "Proposed a break change. Not saved."))} />
        </span>
      ))}
    </div>
  );
}

function Lane({ entries, axis, employees, onSelect, onCommit, onlyRole, compact }) {
  return (
    <div className="ops-ws-lane" style={{ "--hours": String((axis.span || 60) / 60) }}>
      {entries.map((entry) => {
        const unscheduled = visibleBreaks(entry).some((slot) => slot.unscheduled);
        return (
          <div className="ops-ws-shift" key={shiftKey(entry)}>
            <div className="ops-ws-track">
              <ShiftBar entry={entry} axis={axis} employees={employees} onlyRole={onlyRole} compact={compact} onSelect={onSelect} onCommit={onCommit} />
            </div>
            <button type="button" className={`ops-ws-caption${unscheduled ? " unscheduled" : ""}`} title={shiftCaption(entry, employees)} onClick={() => onSelect(entry)}>
              {shiftDetail(entry)}
            </button>
          </div>
        );
      })}
      {!entries.length ? <span className="ops-ws-empty">No shift</span> : null}
    </div>
  );
}

function CoverageRail({ entries, role, requirements, day, setting, axis }) {
  const hours = [];
  for (let minute = axis.startMin; minute < axis.endMin; minute += 60) hours.push(minute / 60);
  return (
    <div className="ops-ws-rail" aria-label={`${role} coverage`}>
      {hours.map((hour) => {
        const required = requirementFor(requirements, role, day, hour, setting);
        const cell = roleCoverage(entries, role, hour, required);
        const tone = required == null ? "idle" : cell.shortage ? "short" : cell.surplus ? "extra" : "ok";
        const title = required == null
          ? `${hour}:00 not configured`
          : `${hour}:00 need ${required}, active ${cell.available.length}`;
        return <span key={hour} className={tone} title={title} />;
      })}
    </div>
  );
}

function ShiftDrawer({ entry, employees, onClose, onCommit, onReview, onRemove, onDuplicate, onSplit }) {
  const timed = visibleBreaks(entry || {}).find((slot) => slot.start_time);
  const unscheduled = visibleBreaks(entry || {}).find((slot) => slot.unscheduled);
  const [breakStart, setBreakStart] = useState(timed?.start_time || "");
  const [breakEnd, setBreakEnd] = useState(timed?.end_time || "");
  useEffect(() => {
    setBreakStart(timed?.start_time || "");
    setBreakEnd(timed?.end_time || "");
  }, [entry?.id, timed?.start_time, timed?.end_time, unscheduled?.minutes]);
  if (!entry) return null;
  function patch(next, label) {
    onCommit(next, label);
  }
  function updateBreak(start, end) {
    setBreakStart(start);
    setBreakEnd(end);
    if (start && end) patch(placeBreak(entry, start, end), "Proposed a break time. Not saved.");
  }
  function updateRole(value) {
    patch({ ...entry, role: value }, "Proposed a role label change. Not saved.");
  }
  return (
    <aside className="ops-ws-drawer" aria-label="Shift details">
      <header>
        <strong>{personName(employees, entry.user_id)}</strong>
        <button type="button" onClick={onClose}>Close</button>
      </header>
      <p>{DAY_NAMES[entry.day_of_week]} · stays on this screen until you review a save</p>
      <label>Start
        <input aria-label="Shift start time" type="time" step="900" value={String(entry.start_time).slice(0, 5)} onChange={(event) => patch(relocateShift(entry, event.target.value, entry.day_of_week), "Proposed a new start. Not saved.")} />
      </label>
      <label>End
        <input aria-label="Shift end time" type="time" step="900" value={String(entry.end_time).slice(0, 5)} onChange={(event) => patch({ ...entry, end_time: event.target.value }, "Proposed a new end. Not saved.")} />
      </label>
      <label>Role
        <input aria-label="Shift role" value={entry.role || ""} onChange={(event) => updateRole(event.target.value)} />
      </label>
      <p>{asList(entry.role_assignments).length ? "Timed segments keep their own roles. This label changes only when you edit it." : "No timed role segments are stored. The role above is the saved label."}</p>
      <label>Break start
        <input aria-label="Break start time" type="time" step="900" value={breakStart} onChange={(event) => updateBreak(event.target.value, breakEnd)} />
      </label>
      <label>Break end
        <input aria-label="Break end time" type="time" step="900" value={breakEnd} onChange={(event) => updateBreak(breakStart, event.target.value)} />
      </label>
      {unscheduled ? <p>Unscheduled break · {unscheduled.minutes} min. It counts in break hours. It is not on the timeline and does not change coverage until both times are set.</p> : null}
      <div className="ops-ws-drawer-actions">
        <button type="button" onClick={() => onDuplicate(entry)}>Duplicate</button>
        <button type="button" onClick={() => onSplit(entry)}>Split</button>
        <button type="button" onClick={() => onRemove(entry)}>Remove</button>
        <button type="button" className="primary" onClick={() => onReview(entry)}>Review save</button>
      </div>
      <p>Review save asks which weeks to update. It does not publish.</p>
    </aside>
  );
}

function RequirementEditor({ role, day, requirements, onChange }) {
  const mine = requirements.filter((item) => item.role === role);
  const [form, setForm] = useState({ day: String(day), start: "05:00", end: "13:00", count: "" });
  function add() {
    if (form.count === "") return;
    onChange([...requirements, {
      role,
      day_of_week: form.day === "all" ? null : Number(form.day),
      start_time: form.start,
      end_time: form.end,
      required_headcount: Number(form.count),
    }], `Proposed ${role} staffing. Not saved.`);
  }
  function remove(index) {
    let seen = -1;
    onChange(requirements.filter((item) => {
      if (item.role !== role) return true;
      seen += 1;
      return seen !== index;
    }), `Removed a ${role} staffing interval from the draft. Not saved.`);
  }
  return (
    <div className="ops-ws-req">
      {mine.length ? mine.map((item, index) => (
        <span key={`${item.day_of_week}-${item.start_time}-${item.end_time}-${index}`}>
          {item.day_of_week == null ? "Every day" : DAY_NAMES[item.day_of_week]} {String(item.start_time).slice(0, 5)}–{String(item.end_time).slice(0, 5)} need {item.required_headcount}
          <button type="button" onClick={() => remove(index)}>Remove</button>
        </span>
      )) : <span className="missing">Not configured</span>}
      <label>Day
        <select aria-label={`${role} requirement day`} value={form.day} onChange={(event) => setForm({ ...form, day: event.target.value })}>
          <option value="all">Every day</option>
          {DAY_ORDER.map((value) => <option key={value} value={value}>{DAY_NAMES[value]}</option>)}
        </select>
      </label>
      <label>From <input aria-label={`${role} requirement start`} type="time" step="900" value={form.start} onChange={(event) => setForm({ ...form, start: event.target.value })} /></label>
      <label>To <input aria-label={`${role} requirement end`} type="time" step="900" value={form.end} onChange={(event) => setForm({ ...form, end: event.target.value })} /></label>
      <label>Need <input aria-label={`${role} required headcount`} type="number" min="0" value={form.count} onChange={(event) => setForm({ ...form, count: event.target.value })} /></label>
      <button type="button" onClick={add}>Set requirement</button>
    </div>
  );
}

export default function PlannerWorkspace({
  lens,
  mode,
  day,
  employees,
  entries,
  tasks,
  planner,
  selectedKey,
  dirty,
  canUndo,
  onSelect,
  onCommit,
  onUndo,
  onDiscard,
  onReview,
  requirements,
  onAdd,
  onDuplicate,
  onSplit,
  onRemove,
  onReviewBundle,
}) {
  const [roster, setRoster] = useState("scheduled");
  const [addFor, setAddFor] = useState("");
  const [taskUser, setTaskUser] = useState(employees[0] ? String(employees[0].user_id) : "");
  const [taskRole, setTaskRole] = useState("floor_reset");
  const [taskShared, setTaskShared] = useState(false);
  const visible = entries.filter((entry) => mode !== "day" || Number(entry.day_of_week) === Number(day));
  const axis = useMemo(() => timelineAxis(visible), [visible]);
  const days = mode === "day" ? [day] : DAY_ORDER;
  const totals = visible.reduce((sum, entry) => {
    const hours = shiftHours(entry);
    return { gross: sum.gross + hours.gross, net: sum.net + hours.net };
  }, { gross: 0, net: 0 });
  const breaks = breakAccounting(visible);
  const overlap = overlappingBreakCount(visible);
  const settings = planner.role_settings || [];
  const staffing = requirements || [];
  const gaps = [];
  const extras = [];
  const roleNames = [...new Set([
    ...staffing.map((item) => item.role),
    ...settings.map((setting) => setting.role),
    ...visible.flatMap((entry) => displaySegments(entry).map((segment) => segment.role)),
  ])].filter((role) => role && role !== "No role segments");
  for (const role of roleNames) {
    const setting = settings.find((item) => item.role === role) || {};
    for (const value of days) {
      const dayEntries = entries.filter((entry) => Number(entry.day_of_week) === Number(value));
      for (let hour = 0; hour < 24; hour += 1) {
        const required = requirementFor(staffing, role, value, hour, setting);
        if (required == null) continue;
        const cell = roleCoverage(dayEntries, role, hour, required);
        const when = `${mode === "day" ? "" : `${DAY_NAMES[value].slice(0, 3)} `}${String(hour).padStart(2, "0")}:00`;
        if (cell.shortage) gaps.push(`${role} ${when} short ${cell.shortage}`);
        if (cell.surplus) extras.push(`${role} ${when} extra ${cell.surplus}`);
      }
    }
  }
  const scheduledIds = new Set(entries.map((entry) => Number(entry.user_id)));
  const rosterEmployees = employees.filter((employee) => {
    const scheduled = scheduledIds.has(Number(employee.user_id));
    if (roster === "scheduled") return scheduled;
    if (roster === "unscheduled") return !scheduled;
    return true;
  });
  const addTarget = rosterEmployees.some((employee) => String(employee.user_id) === addFor)
    ? addFor
    : String(rosterEmployees[0]?.user_id || "");
  const people = new Set(visible.map((entry) => entry.user_id)).size;
  const selected = entries.find((entry) => shiftKey(entry) === selectedKey) || null;

  function commit(next, label) {
    onCommit(entries.map((entry) => (shiftKey(entry) === shiftKey(next) ? { ...entry, ...next } : entry)), label);
    onSelect(shiftKey(next));
  }

  return (
    <div className="ops-ws">
      <div className="ops-summary" aria-label="Schedule summary">
        <span>{people} scheduled employees</span>
        <span>{visible.length} shifts</span>
        <span>Gross {totals.gross.toFixed(1)}</span>
        <span>Timed break {breaks.timedHours.toFixed(1)}</span>
        <span>Unscheduled break {breaks.unscheduledHours.toFixed(1)}</span>
        <span>Net {totals.net.toFixed(1)}</span>
        <span>{staffing.length ? `${gaps.length} understaffed hours` : "No staffing requirements configured"}</span>
        <span>{staffing.length ? `${extras.length} overstaffed hours` : "Unconfigured hours are not treated as zero"}</span>
        <span className={overlap > BREAK_OVERLAP_CAP ? "ops-warn" : ""}>
          {breaks.overlapKnown
            ? `Timed overlap ${overlap}`
            : `Timed overlap ${overlap} · incomplete, ${breaks.unscheduledCount} breaks have no clock time`}
        </span>
        <span>{planner.snapshot ? "snapshot · not saved" : `${planner.status || "draft"} · rev ${planner.revision || 1}${planner.published_revision ? ` · published ${planner.published_revision}` : " · not published"}`}</span>
        <span role="group" aria-label="Employee roster">
          {[["scheduled", "Scheduled"], ["unscheduled", "Unscheduled"], ["all", "All"]].map(([id, label]) => (
            <button key={id} type="button" className={roster === id ? "active" : ""} onClick={() => setRoster(id)}>{label}</button>
          ))}
        </span>
        <label>Add for
          <select aria-label="Add shift for" value={addTarget} onChange={(event) => setAddFor(event.target.value)}>
            {rosterEmployees.map((employee) => <option key={employee.user_id} value={employee.user_id}>{employee.display_name}</option>)}
          </select>
        </label>
        <button type="button" onClick={() => onAdd(Number(addTarget))}>Add shift</button>
        <button type="button" onClick={onUndo} disabled={!canUndo}>Undo</button>
        <button type="button" onClick={onDiscard} disabled={!dirty}>Discard</button>
      </div>
      {gaps.length ? <p className="ops-ws-gap">{gaps.slice(0, 4).join(" · ")}</p> : null}
      <div className="ops-ws-stage">
        {lens === "employees" || lens === "breaks" ? (
          <div className={`ops-ws-board ${mode} ${lens}`} style={{ "--days": String(days.length) }}>
            {lens === "breaks" ? (
              <p className="ops-ws-note">
                {overlap > BREAK_OVERLAP_CAP
                  ? `${overlap} people have a timed break at the same time. The limit is ${BREAK_OVERLAP_CAP}.`
                  : breaks.overlapKnown
                    ? `Timed break overlap is ${overlap}. Every stored break has a clock time.`
                    : `Timed break overlap is ${overlap}. ${breaks.unscheduledCount} breaks have no clock time, so overlap cannot be fully determined. Those minutes stay in the labor total and are not placed on the timeline.`}
              </p>
            ) : null}
            <div className="ops-ws-scroll">
              <div className="ops-ws-head">
                <div className="ops-ws-name">Employee</div>
                {days.map((value) => (
                  <div key={value} className="ops-ws-dayhead">
                    <strong>{DAY_NAMES[value]}</strong>
                    <HourRuler axis={axis} />
                  </div>
                ))}
              </div>
              {rosterEmployees.map((employee) => (
                <div className="ops-ws-row" key={employee.user_id}>
                  <div className="ops-ws-name">{employee.display_name}</div>
                  {days.map((value) => (
                    <Lane
                      key={value}
                      axis={axis}
                      employees={employees}
                      entries={entries.filter((entry) => Number(entry.user_id) === Number(employee.user_id) && Number(entry.day_of_week) === Number(value))}
                      compact={mode === "week"}
                      onSelect={(entry) => onSelect(shiftKey(entry))}
                      onCommit={commit}
                    />
                  ))}
                </div>
              ))}
              {!rosterEmployees.length ? <p className="ops-ws-blank">{roster === "unscheduled" ? "Every eligible employee has a shift." : "No employees are on this schedule."}</p> : null}
            </div>
          </div>
        ) : null}
        {lens === "roles" ? (
          <div className={`ops-ws-board roles ${mode}`} style={{ "--days": String(days.length) }}>
            <p className="ops-ws-note">A stored role such as wash,attendant stays in its own lane until timed segments exist. An hour with no requirement is not short. A saved 0 means nobody is required.</p>
            {staffing.length ? <button type="button" onClick={() => onReviewBundle("requirements")}>Review staffing save</button> : null}
            <div className="ops-ws-scroll">
              {roleNames.map((role) => {
                const setting = settings.find((item) => item.role === role) || {};
                const roleEntries = visible.filter((entry) => displaySegments(entry).some((segment) => segment.role === role));
                const timedLane = roleEntries.some((entry) => displaySegments(entry).some((segment) => segment.role === role && segment.allocated));
                return (
                  <section
                    key={role}
                    className="ops-ws-role"
                    onDragOver={(event) => event.preventDefault()}
                    onDrop={(event) => {
                      const key = event.dataTransfer.getData("text/plain");
                      const source = entries.find((entry) => shiftKey(entry) === key);
                      if (!source) return;
                      commit({ ...source, role }, `Proposed ${personName(employees, source.user_id)} label ${role}. Not saved.`);
                    }}
                  >
                    <header>
                      <strong style={{ color: roleColor(role) }}>{role}</strong>
                      <span>{timedLane ? "Timed segments" : "No timed role segments"}</span>
                      <span>{roleEntries.length} shifts</span>
                      <RequirementEditor
                        role={role}
                        day={day}
                        requirements={staffing}
                        onChange={(next, label) => onCommit({ requirements: next }, label)}
                      />
                    </header>
                    <div className="ops-ws-head">
                      <div className="ops-ws-name">Role</div>
                      {days.map((value) => (
                        <div key={value} className="ops-ws-dayhead">
                          <strong>{DAY_NAMES[value]}</strong>
                          <HourRuler axis={axis} />
                        </div>
                      ))}
                    </div>
                    <div className="ops-ws-row">
                      <div className="ops-ws-name">{role}</div>
                      {days.map((value) => {
                        const dayEntries = entries.filter((entry) => Number(entry.day_of_week) === Number(value) && displaySegments(entry).some((segment) => segment.role === role));
                        return (
                          <div key={value}>
                            <Lane
                              axis={axis}
                              employees={employees}
                              entries={dayEntries}
                              onlyRole={role}
                              compact={mode === "week"}
                              onSelect={(entry) => onSelect(shiftKey(entry))}
                              onCommit={commit}
                            />
                            <CoverageRail entries={dayEntries} role={role} requirements={staffing} day={value} setting={setting} axis={axis} />
                          </div>
                        );
                      })}
                    </div>
                  </section>
                );
              })}
            </div>
          </div>
        ) : null}
        {lens === "tasks" ? (
          <div className="ops-ws-tasks">
            <form
              onSubmit={(event) => {
                event.preventDefault();
                if (!taskRole.trim() || !taskUser) return;
                onCommit({
                  tasks: [...tasks, {
                    id: `draft-task-${Date.now()}`,
                    draft: true,
                    user_id: Number(taskUser),
                    day_of_week: day,
                    role: taskRole.trim(),
                    shared: taskShared,
                    assignment_group_id: taskShared ? `draft-group-${Date.now()}` : null,
                    status: "draft",
                  }],
                }, "Proposed a task assignment. Not saved.");
              }}
            >
              <p>{tasks.some((task) => !task.draft) ? "Completed and verified records stay stored." : "No task responsibilities are stored for this week."} A new assignment stays in this draft until you review a save. Saving adds a row. It does not rewrite a completed record.</p>
              <button type="button" onClick={() => onReviewBundle("tasks")} disabled={!tasks.some((task) => task.draft)}>Review task save</button>
              <select aria-label="Task employee" value={taskUser} onChange={(event) => setTaskUser(event.target.value)}>
                {employees.map((employee) => <option key={employee.user_id} value={employee.user_id}>{employee.display_name}</option>)}
              </select>
              <input aria-label="Task role" value={taskRole} onChange={(event) => setTaskRole(event.target.value)} />
              <label><input type="checkbox" checked={taskShared} onChange={(event) => setTaskShared(event.target.checked)} /> Shared activity group</label>
              <button type="submit">Assign task</button>
            </form>
            <table>
              <thead>
                <tr><th>Employee</th><th>Day</th><th>Shift</th><th>Assignment</th><th>Record</th></tr>
              </thead>
              <tbody>
                {tasks.filter((task) => mode !== "day" || Number(task.day_of_week) === Number(day)).map((task) => {
                  const shift = entries.find((entry) => Number(entry.user_id) === Number(task.user_id) && Number(entry.day_of_week) === Number(task.day_of_week));
                  const status = task.draft ? "Draft assignment · not saved" : (task.activity_status || task.status || "pending");
                  return (
                    <tr key={task.id || `${task.user_id}-${task.role}`}>
                      <td>{personName(employees, task.user_id)}</td>
                      <td>{DAY_NAMES[task.day_of_week]}</td>
                      <td>{shift ? `${String(shift.start_time).slice(0, 5)}–${String(shift.end_time).slice(0, 5)}` : "No shift"}</td>
                      <td>{task.role}{task.assignment_group_id ? " · shared group" : ""}</td>
                      <td>{status}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : null}
        <ShiftDrawer
          entry={selected}
          employees={employees}
          onClose={() => onSelect("")}
          onCommit={commit}
          onReview={onReview}
          onRemove={onRemove}
          onDuplicate={onDuplicate}
          onSplit={onSplit}
        />
      </div>
    </div>
  );
}
