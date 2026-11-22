import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  BREAK_OVERLAP_CAP,
  DAY_NAMES,
  DAY_ORDER,
  breakAccounting,
  clockMinutes,
  minutesToClock,
  overlappingBreakCount,
  pointerToMinutes,
  spanMinutes,
} from "./plannerModel";
import {
  addRoleSegment,
  asList,
  placeBreak,
  relocateShift,
  removeRoleSegment,
  resizeBreak,
  unscheduleBreak,
  resizeEdge,
  resizeSegment,
  roleColor,
  shiftKey,
  storedSegments,
  timelineAxis,
  visibleBreaks,
  visualPieces,
} from "./plannerGeometry";
import { BreakImpact, CoverageBoard, TaskPlanner } from "./PlannerBoards";

const SHORT = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

function personName(employees, userId) {
  return employees.find((employee) => Number(employee.user_id) === Number(userId))?.display_name || `Employee ${userId}`;
}

function initials(name) {
  const parts = String(name || "").trim().split(/\s+/);
  return ((parts[0]?.[0] || "") + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase();
}

function nice(role) {
  return String(role || "No role").replaceAll("_", " ");
}

function hm(value) {
  return String(value || "").slice(0, 5);
}

function shiftRange(entry) {
  const start = clockMinutes(entry.start_time);
  let end = clockMinutes(entry.end_time);
  if (start == null || end == null) return null;
  if (end <= start) end += 24 * 60;
  return { start, end };
}

function overlaps(a, b) {
  if (!a || !b || shiftKey(a) === shiftKey(b)) return false;
  if (Number(a.user_id) !== Number(b.user_id) || Number(a.day_of_week) !== Number(b.day_of_week)) return false;
  const left = shiftRange(a);
  const right = shiftRange(b);
  if (!left || !right) return false;
  return left.start < right.end && right.start < left.end;
}

function pack(items) {
  const sorted = [...items].sort((a, b) => a.start - b.start || a.end - b.end);
  const ends = [];
  const placed = sorted.map((item) => {
    let lane = ends.findIndex((end) => item.start >= end);
    if (lane < 0) {
      lane = ends.length;
      ends.push(item.end);
    } else ends[lane] = item.end;
    return { ...item, lane };
  });
  return { placed, lanes: Math.max(1, ends.length) };
}

function dayStamp(weekStart, dow) {
  if (!weekStart) return "";
  const [year, month, day] = String(weekStart).split("-").map(Number);
  if (!year) return "";
  const offset = Number(dow) === 0 ? 6 : Number(dow) - 1;
  const date = new Date(Date.UTC(year, month - 1, day + offset));
  return date.getUTCDate();
}

function leftOf(minute, axis) {
  return ((minute - axis.startMin) / axis.span) * 100;
}

function widthOf(start, end, axis) {
  return Math.max(((end - start) / axis.span) * 100, 0.6);
}

function guideImage(axis) {
  return [6, 10, 14, 18].map((hour) => {
    const at = ((hour * 60 - axis.startMin) / axis.span) * 100;
    if (at <= 0 || at >= 100) return "";
    return `linear-gradient(to right, transparent calc(${at}% - .5px), #eef0f3 calc(${at}% - .5px), #eef0f3 calc(${at}% + .5px), transparent calc(${at}% + .5px))`;
  }).filter(Boolean).join(",");
}

function ticks(axis) {
  const marks = [];
  for (let minute = axis.startMin; minute <= Math.min(axis.endMin, 18 * 60); minute += 240) marks.push(minute);
  return marks;
}

function untimed(entry) {
  return visibleBreaks(entry).some((slot) => slot.unscheduled);
}

function pieceLabel(role) {
  const full = nice(role);
  return { full, short: full.length <= 4 ? full : "" };
}

function trackPointer(event, axis, apply) {
  event.preventDefault();
  event.stopPropagation();
  const lane = event.currentTarget.closest(".cell")?.getBoundingClientRect();
  if (!lane) return;
  const read = (pointer) => pointerToMinutes(pointer.clientX, lane, axis.startMin / 60, axis.endMin / 60);
  const move = (pointer) => {
    const minutes = read(pointer);
    if (minutes != null) apply(minutes, false);
  };
  const finish = (pointer) => {
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", finish);
    const minutes = read(pointer);
    if (minutes != null) apply(minutes, true);
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", finish);
}

function changeStart(entry, minutes) {
  const segments = storedSegments(entry);
  const clock = minutesToClock(minutes);
  if (!segments.length || hm(segments[0].start_time) === hm(entry.start_time)) return resizeEdge(entry, "start", minutes);
  return { ...entry, start_time: clock };
}

function changeEnd(entry, minutes) {
  const segments = storedSegments(entry);
  const clock = minutesToClock(minutes);
  const last = segments[segments.length - 1];
  if (!segments.length || !last || hm(last.end_time) === hm(entry.end_time)) return resizeEdge(entry, "end", minutes);
  return { ...entry, end_time: clock };
}

function moveSplit(entry, pieces, index, minutes) {
  const clock = minutesToClock(minutes);
  const left = pieces[index];
  const right = pieces[index + 1];
  if (!clock || !left || !right) return entry;
  const segments = storedSegments(entry);
  const next = segments.map((segment) => ({ ...segment }));
  if (left.allocated) {
    const match = next.findIndex((segment) => segment.role === left.role && hm(segment.end_time) === minutesToClock(left.end));
    if (match >= 0) next[match] = { ...next[match], end_time: clock };
  }
  if (right.allocated) {
    const match = next.findIndex((segment) => segment.role === right.role && hm(segment.start_time) === minutesToClock(right.start));
    if (match >= 0) next[match] = { ...next[match], start_time: clock };
  }
  const updated = { ...entry, role_assignments: next };
  if (left.allocated && hm(segments[0]?.start_time) === hm(entry.start_time) && index === 0) return resizeSegment(updated, 0, "end", minutes);
  return updated;
}

function coverageBands(role, dow, placed, requirements, axis) {
  const reqs = (requirements || []).filter((item) => {
    const key = String(item.role || item.role_key || "");
    if (key !== String(role)) return false;
    return item.day_of_week == null || item.day_of_week === "" || Number(item.day_of_week) === Number(dow);
  });
  if (!reqs.length) return [];
  const bands = [];
  for (let minute = axis.startMin; minute < axis.endMin; minute += 30) {
    const matching = reqs.filter((item) => {
      const start = clockMinutes(item.start_time);
      let end = clockMinutes(item.end_time);
      if (start == null || end == null) return false;
      if (end <= start) end += 24 * 60;
      return minute < end && minute + 30 > start;
    });
    if (!matching.length) continue;
    const style = { left: `${leftOf(minute, axis)}%`, width: `${widthOf(minute, minute + 30, axis)}%` };
    if (matching.length > 1) {
      bands.push({ key: minute, kind: "conflict", style, title: "Overlapping requirements are not resolved" });
      continue;
    }
    const required = Number(matching[0].required_headcount);
    if (!Number.isFinite(required)) continue;
    const scheduled = placed.filter((item) => item.start < minute + 30 && item.end > minute).length;
    if (scheduled < required) bands.push({ key: minute, kind: "short", style, title: `${scheduled} scheduled, ${required} required` });
    else if (scheduled > required) bands.push({ key: minute, kind: "extra", style, title: `${scheduled} scheduled, ${required} required` });
  }
  return bands;
}

function breakOutside(entry) {
  const range = shiftRange(entry);
  if (!range) return false;
  return visibleBreaks(entry).some((slot) => {
    if (!slot.start_time) return false;
    const start = clockMinutes(slot.start_time);
    let end = clockMinutes(slot.end_time);
    if (start == null || end == null || end === start) return true;
    if (end <= start) end += 24 * 60;
    return start < range.start || end > range.end;
  });
}

function ShiftFace({ entry, axis, lane, bar, stacked, selected, peer, showGrips, muted, onSelect, onCommit, onHover, onDragShift, onEdit, onMenu }) {
  const range = shiftRange(entry);
  if (!range) return null;
  const pieces = visualPieces(entry);
  const split = pieces.length > 1 || pieces.some((piece) => piece.allocated);
  const labelRole = entry.role || pieces[0]?.role || "No role";
  const breakText = untimed(entry) ? `. ${entry.break_minutes} minute break with no clock time` : "";
  const label = `${nice(labelRole)}. ${hm(entry.start_time)} to ${hm(entry.end_time)}${breakText}`;
  const timed = visibleBreaks(entry).filter((slot) => slot.start_time);
  return (
    <div
      role="button"
      tabIndex={0}
      className={`shift${selected ? " is-on" : ""}${peer ? " is-peer" : ""}${stacked ? " is-stacked" : ""}${untimed(entry) ? " has-break" : ""}${muted ? " is-work" : ""}`}
      data-shift-key={shiftKey(entry)}
      aria-label={label}
      style={{
        left: `${leftOf(range.start, axis)}%`,
        width: `${widthOf(range.start, range.end, axis)}%`,
        top: 4 + lane * (bar + 3),
        height: bar,
      }}
      draggable={!showGrips}
      onDragStart={(event) => {
        event.dataTransfer.setData("text/plain", shiftKey(entry));
        event.dataTransfer.effectAllowed = "move";
        onDragShift?.(entry);
      }}
      onClick={() => onSelect(entry)}
      onDoubleClick={(event) => {
        event.preventDefault();
        onEdit?.(entry);
      }}
      onContextMenu={(event) => {
        event.preventDefault();
        event.stopPropagation();
        onSelect(entry);
        onMenu?.(event, entry);
      }}
      onKeyDown={(event) => {
        if (event.key === "Enter") onEdit?.(entry);
        else if (event.key === " ") onSelect(entry);
      }}
      onMouseEnter={(event) => onHover(entry, event.currentTarget.getBoundingClientRect())}
      onMouseLeave={() => onHover(null)}
    >
      {split ? pieces.map((piece) => {
        const text = pieceLabel(piece.role);
        const span = range.end - range.start;
        const shown = `${text.full} ${minutesToClock(piece.start)}–${minutesToClock(piece.end)}`;
        return (
          <span
            key={`${piece.role}-${piece.start}`}
            className={`piece${String(piece.role).includes(",") ? " is-combined" : ""}`}
            title={shown}
            style={{
              left: `${((piece.start - range.start) / span) * 100}%`,
              width: `${((piece.end - piece.start) / span) * 100}%`,
              background: roleColor(piece.role),
            }}
          >
            {shown}
          </span>
        );
      }) : (
        <span className={`txt${String(entry.role || "").includes(",") ? " is-combined" : ""}`} title={`${nice(labelRole)} ${hm(entry.start_time)}–${hm(entry.end_time)}`} style={{ background: roleColor(entry.role) }}>
          {nice(labelRole)} {hm(entry.start_time)}–{hm(entry.end_time)}
        </span>
      )}
      {timed.map((slot) => {
        const start = clockMinutes(slot.start_time);
        let end = clockMinutes(slot.end_time);
        if (start == null || end == null) return null;
        if (end <= start) end += 24 * 60;
        const span = range.end - range.start;
        return <i key={`${slot.start_time}-${slot.end_time}`} className="timed-break" style={{ left: `${((start - range.start) / span) * 100}%`, width: `${((end - start) / span) * 100}%` }} />;
      })}
      {showGrips ? (
        <>
          <button type="button" className="grip start" aria-label="Drag to change the start" onPointerDown={(event) => trackPointer(event, axis, (minutes, done) => { if (done) onCommit(changeStart(entry, minutes), "Proposed a new shift start. Not saved."); })} />
          {pieces.slice(0, -1).map((piece, index) => (
            <button
              key={`split-${piece.start}`}
              type="button"
              className="grip split"
              aria-label="Drag to move the role split"
              style={{ left: `${((piece.end - range.start) / (range.end - range.start)) * 100}%` }}
              onPointerDown={(event) => trackPointer(event, axis, (minutes, done) => { if (done) onCommit(moveSplit(entry, pieces, index, minutes), "Proposed a role-segment change. Not saved."); })}
            />
          ))}
          <button type="button" className="grip end" aria-label="Drag to change the end" onPointerDown={(event) => trackPointer(event, axis, (minutes, done) => { if (done) onCommit(changeEnd(entry, minutes), "Proposed a new shift end. Not saved."); })} />
        </>
      ) : null}
    </div>
  );
}

function RequirementEditor({ role, day, requirements, axis, onChange }) {
  const mine = (requirements || []).filter((item) => String(item.role || item.role_key || "") === String(role));
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    day: String(day),
    start: minutesToClock(axis.startMin) || "05:00",
    end: minutesToClock(Math.min(axis.endMin, 21 * 60)) || "13:00",
    count: "",
  });
  function add() {
    if (form.count === "") return;
    const next = {
      role,
      day_of_week: form.day === "all" ? null : Number(form.day),
      start_time: form.start,
      end_time: form.end,
      required_headcount: Number(form.count),
    };
    const clash = mine.some((item) => {
      const sameDay = (item.day_of_week == null && next.day_of_week == null) || Number(item.day_of_week) === Number(next.day_of_week) || item.day_of_week == null || next.day_of_week == null;
      if (!sameDay) return false;
      const start = clockMinutes(item.start_time);
      const end = clockMinutes(item.end_time);
      const nextStart = clockMinutes(next.start_time);
      const nextEnd = clockMinutes(next.end_time);
      return start != null && end != null && nextStart < end && start < nextEnd;
    });
    if (clash) return;
    onChange([...(requirements || []), next], `Proposed ${role} staffing. Not saved.`);
    setForm({ ...form, count: "" });
  }
  return (
    <label className="need">
      <span>Need</span>
      <input
        inputMode="numeric"
        placeholder={mine.length ? "" : "—"}
        aria-label={`Required headcount for ${nice(role)}. ${mine.length ? "Requirement saved" : "Not set"}`}
        value={form.count}
        onFocus={() => setOpen(true)}
        onChange={(event) => setForm({ ...form, count: event.target.value.replace(/[^\d]/g, "") })}
      />
      <em>{mine.length ? "" : "Not set"}</em>
      {open ? (
        <span className="intervals">
          {mine.length ? mine.map((item, index) => (
            <span key={`${item.start_time}-${item.end_time}-${index}`}>
              {item.day_of_week == null ? "Every day" : SHORT[item.day_of_week]} {hm(item.start_time)}–{hm(item.end_time)} need {item.required_headcount}
            </span>
          )) : null}
          <select aria-label={`${role} requirement day`} value={form.day} onChange={(event) => setForm({ ...form, day: event.target.value })}>
            <option value="all">Every day</option>
            {DAY_ORDER.map((value) => <option key={value} value={value}>{SHORT[value]}</option>)}
          </select>
          <input aria-label={`${role} requirement start`} type="time" step="900" value={form.start} onChange={(event) => setForm({ ...form, start: event.target.value })} />
          <input aria-label={`${role} requirement end`} type="time" step="900" value={form.end} onChange={(event) => setForm({ ...form, end: event.target.value })} />
          <button type="button" onClick={add}>Set interval</button>
        </span>
      ) : null}
    </label>
  );
}

function Drawer({ entry, employees, tasks, dayLabel, dirty, canUndo, canRedo, conflict, missingRole, badBreak, onClose, onCommit, onReview, onUndo, onRedo, onDiscard, onAdd, onCopy, onDuplicate, onSplit, onRemove }) {
  const timed = visibleBreaks(entry || {}).filter((slot) => slot.start_time);
  const unscheduled = visibleBreaks(entry || {}).find((slot) => slot.unscheduled);
  const [breakStart, setBreakStart] = useState(timed[0]?.start_time || "");
  const [breakEnd, setBreakEnd] = useState(timed[0]?.end_time || "");
  useLayoutEffect(() => {
    setBreakStart(timed[0]?.start_time || "");
    setBreakEnd(timed[0]?.end_time || "");
  }, [entry?.id, timed[0]?.start_time, timed[0]?.end_time, unscheduled?.minutes]);
  if (!entry) return null;
  const person = personName(employees, entry.user_id);
  const pieces = visualPieces(entry);
  const range = shiftRange(entry);
  const hours = range ? (range.end - range.start) / 60 : 0;
  const stored = storedSegments(entry);
  const allocated = stored.reduce((sum, segment) => sum + ((spanMinutes(segment.start_time, segment.end_time) || 0) / 60), 0);
  const kept = Math.max(0, hours - (stored.length ? allocated : hours));
  const mine = (tasks || []).filter((task) => Number(task.user_id) === Number(entry.user_id) && Number(task.day_of_week) === Number(entry.day_of_week));
  function patch(next, label) {
    onCommit({ ...entry, ...next, id: entry.id }, label);
  }
  return (
    <aside className="drawer" aria-label="Shift details">
      <header>
        <span className="avatar">{initials(person)}</span>
        <div>
          <h2>{person}</h2>
          <p>{dayLabel} · {entry.role || "No role"}</p>
        </div>
        <button type="button" className="close" aria-label="Close" onClick={onClose}>×</button>
      </header>
        <div className="body">
        {conflict ? <p className="ops-warn">This shift overlaps another shift for the same employee.</p> : null}
        {missingRole ? <p className="ops-warn">This shift has no role.</p> : null}
        {badBreak ? <p className="ops-warn">A break sits outside the shift, or its start and end are the same.</p> : null}
        <div className="facts">
          <div><b>{hours.toFixed(1)}h</b><span>Shift on the timeline</span></div>
          <div><b>{(stored.length ? allocated : hours).toFixed(1)}h</b><span>{stored.length ? "Allocated to roles" : "No role split"}</span></div>
          <div><b>{((unscheduled?.minutes || 0) / 60).toFixed(1)}h</b><span>{unscheduled ? "Break, not on the bar" : "No break"}</span></div>
        </div>
        <div className="sec">
          <h3>Assignment</h3>
          <select aria-label="Employee" value={String(entry.user_id)} onChange={(event) => patch({ user_id: Number(event.target.value) }, "Proposed a different employee. Not saved.")}>
            {employees.map((employee) => <option key={employee.user_id} value={employee.user_id}>{employee.display_name}</option>)}
          </select>
          <select aria-label="Day" value={String(entry.day_of_week)} onChange={(event) => patch(relocateShift(entry, entry.start_time, Number(event.target.value)), "Proposed a different day. Not saved.")}>
            {DAY_ORDER.map((value) => <option key={value} value={value}>{DAY_NAMES[value]}</option>)}
          </select>
        </div>
        <div className="sec">
          <h3>Shift hours</h3>
          <div className="hours">
            <input aria-label="Start" type="time" step="900" value={hm(entry.start_time)} onChange={(event) => patch(relocateShift(entry, event.target.value, entry.day_of_week), "Proposed a new start. Not saved.")} />
            <span className="to">to</span>
            <input aria-label="End" type="time" step="900" value={hm(entry.end_time)} onChange={(event) => patch({ end_time: event.target.value }, "Proposed a new end. Not saved.")} />
            <span className="dur">{hours.toFixed(1)}h</span>
          </div>
          <div className="mini" aria-hidden="true">
            {pieces.map((piece) => (
              <span key={`${piece.role}-${piece.start}`} className={String(piece.role).includes(",") ? "is-combined" : ""} style={{ width: `${range ? ((piece.end - piece.start) / (range.end - range.start)) * 100 : 0}%`, background: roleColor(piece.role) }} />
            ))}
          </div>
          <div className="key"><span><i />Start and end</span><span><i className="split" />Role split</span></div>
        </div>
        <div className="sec">
          <h3>Role time</h3>
          <input className="role-field" aria-label="Shift role" value={entry.role || ""} onChange={(event) => patch({ role: event.target.value }, "Proposed a role label change. Not saved.")} />
          {String(entry.role || "").includes(",") && !stored.length ? <p className="quiet">This combined role has no timed split. It stays combined until you know how the time is divided.</p> : (
            <div className="break-times">
              <input aria-label="New role segment" placeholder="Role" id={`segment-role-${entry.id}`} />
              <button type="button" className="btn" onClick={() => {
                const field = document.getElementById(`segment-role-${entry.id}`);
                const name = field?.value || "";
                const range = shiftRange(entry);
                if (!range || !name.trim()) return;
                const start = minutesToClock(range.start);
                const end = minutesToClock(Math.min(range.end, range.start + 60));
                patch(addRoleSegment(entry, name.trim(), start, end), "Proposed a role segment. Not saved.");
              }}>Add segment</button>
            </div>
          )}
          <ul className="segs">
            {pieces.map((piece) => {
              const span = ((piece.end - piece.start) / 60).toFixed(1);
              const note = String(piece.role).includes(",") && !piece.allocated ? " · combined role" : "";
              return (
                <li key={`${piece.role}-${piece.start}`}>
                  <span className="swatch" style={{ background: roleColor(piece.role) }} />
                  <b>{nice(piece.role)}</b>
                  <em>{minutesToClock(piece.start)}–{minutesToClock(piece.end)} · {span}h{note}</em>
                  {piece.allocated ? <button type="button" className="btn" onClick={() => patch(removeRoleSegment(entry, stored.findIndex((segment) => segment.role === piece.role && clockMinutes(segment.start_time) === piece.start)), "Proposed removing a role segment. Not saved.")}>Remove</button> : null}
                </li>
              );
            })}
          </ul>
          {kept > 0.05 ? <p className="quiet">{kept.toFixed(1)}h stays on the combined role. It is not assigned to {nice(String(entry.role).split(",")[0])}.</p> : null}
        </div>
        <div className="sec">
          <h3>Break</h3>
          {unscheduled ? (
            <div className="note"><div><strong>{unscheduled.minutes} min · no clock time</strong>Marked by the gold line. It does not shorten the {hours.toFixed(1)}h bar.</div></div>
          ) : timed.length ? timed.map((slot) => <p key={`${slot.start_time}-${slot.end_time}`} className="quiet">Timed break {slot.start_time}–{slot.end_time}. It is on the bar.</p>) : <p className="quiet">No break on this shift.</p>}
          <div className="break-times">
            <input aria-label="Break start time" type="time" step="900" value={breakStart} onChange={(event) => { setBreakStart(event.target.value); if (event.target.value && breakEnd) onCommit(placeBreak(entry, event.target.value, breakEnd), "Proposed a break time. Not saved."); }} />
            <input aria-label="Break end time" type="time" step="900" value={breakEnd} onChange={(event) => { setBreakEnd(event.target.value); if (breakStart && event.target.value) onCommit(placeBreak(entry, breakStart, event.target.value), "Proposed a break time. Not saved."); }} />
          </div>
        </div>
        <div className="sec">
          <h3>Tasks</h3>
          {mine.length ? mine.map((task) => (
            <p key={task.id || task.role} className="quiet">{task.role} · {task.draft ? "Draft assignment · not saved" : (task.activity_status || task.status || "pending")}</p>
          )) : <p className="quiet">No task assigned on this shift.</p>}
        </div>
        <div className="actions">
          <button type="button" className="btn" onClick={() => onAdd(Number(entry.user_id), Number(entry.day_of_week))}>Add shift</button>
          <button type="button" className="btn" onClick={() => onCopy(entry)}>Copy</button>
          <button type="button" className="btn" onClick={() => onDuplicate(entry)}>Duplicate</button>
          <button type="button" className="btn" onClick={() => onSplit(entry)}>Split</button>
          <button type="button" className="btn danger" onClick={() => onRemove(entry)}>Remove</button>
        </div>
      </div>
      <footer>
        <p className={`state${dirty ? " dirty" : ""}`}><i />{dirty ? "Unsaved changes" : "No unsaved changes"}</p>
        <p className="hint">Undo and redo stay on unsaved edits. Review save is required before anything is written.</p>
        <div className="footer-row">
          <button type="button" className="btn" onClick={onUndo} disabled={!canUndo}>Undo</button>
          <button type="button" className="btn" onClick={onRedo} disabled={!canRedo}>Redo</button>
          <button type="button" className="btn" onClick={onDiscard} disabled={!dirty}>Discard</button>
          <button type="button" className="btn primary" onClick={() => onReview()}>Review save</button>
        </div>
      </footer>
    </aside>
  );
}

export default function PlannerWorkspace({
  lens,
  mode,
  day,
  weekStart,
  employees,
  entries,
  tasks,
  planner,
  selectedKey,
  dirty,
  canUndo,
  canRedo,
  editorOpen,
  onSelect,
  onEdit,
  onCloseEditor,
  onCommit,
  onUndo,
  onRedo,
  onDiscard,
  onReview,
  requirements,
  onAdd,
  onCopy,
  onPaste,
  canPaste,
  onDuplicate,
  onSplit,
  onRemove,
  onReviewBundle,
  onOpenDay,
  onMove,
  onCopyRequest,
  catalog,
}) {
  const boardRef = useRef(null);
  const scrollMem = useRef({});
  const scrollKey = useRef(`${lens}:${mode}`);
  const [menu, setMenu] = useState(null);
  useEffect(() => {
    if (!menu) return undefined;
    function close(event) {
      if (event.target?.closest?.(".context-menu")) return;
      setMenu(null);
    }
    window.addEventListener("mousedown", close);
    return () => window.removeEventListener("mousedown", close);
  }, [menu]);
  const [roster, setRoster] = useState("all");
  const [query, setQuery] = useState("");
  const [roleFilter, setRoleFilter] = useState("");
  const [sort, setSort] = useState("name");
  const [zoom, setZoom] = useState(1);
  const [tip, setTip] = useState(null);
  const axis = useMemo(() => timelineAxis(entries), [entries]);
  const days = mode === "day" ? [day] : DAY_ORDER;
  const guides = guideImage(axis);
  const selected = entries.find((entry) => shiftKey(entry) === selectedKey) || null;
  const peers = entries.filter((entry) => overlaps(entry, selected));
  const scheduledIds = new Set(entries.map((entry) => Number(entry.user_id)));
  const rosterEmployees = employees.filter((employee) => {
    const scheduled = scheduledIds.has(Number(employee.user_id));
    if (roster === "scheduled" && !scheduled) return false;
    if (roster === "unscheduled" && scheduled) return false;
    if (query && !String(employee.display_name || "").toLowerCase().includes(query.toLowerCase())) return false;
    if (roleFilter) {
      const mine = entries.filter((entry) => Number(entry.user_id) === Number(employee.user_id));
      const holds = mine.some((entry) => String(entry.role || "").split(",").includes(roleFilter) || visualPieces(entry).some((piece) => piece.role === roleFilter));
      if (!holds && scheduled) return false;
    }
    return true;
  }).sort((a, b) => {
    if (sort === "scheduled") {
      const left = scheduledIds.has(Number(a.user_id)) ? 0 : 1;
      const right = scheduledIds.has(Number(b.user_id)) ? 0 : 1;
      if (left !== right) return left - right;
    }
    return String(a.display_name || "").localeCompare(String(b.display_name || ""));
  });
  const roleNames = [...new Set(entries.flatMap((entry) => String(entry.role || "").split(",").map((item) => item.trim()).filter(Boolean)))].sort();
  const addTarget = selected ? Number(selected.user_id) : Number(rosterEmployees[0]?.user_id || employees[0]?.user_id || 0);
  const breaks = breakAccounting(entries);
  const overlap = overlappingBreakCount(entries.filter((entry) => mode !== "day" || Number(entry.day_of_week) === Number(day)));
  const showDrawer = Boolean(editorOpen && selected && lens !== "tasks");

  function rememberScroll() {
    const node = boardRef.current;
    if (!node) return;
    scrollMem.current[scrollKey.current] = { x: node.scrollLeft, y: node.scrollTop };
  }

  useLayoutEffect(() => {
    const node = boardRef.current;
    const nextKey = `${lens}:${mode}`;
    if (!node || scrollKey.current === nextKey) return;
    const mem = scrollMem.current[nextKey] || { x: 0, y: 0 };
    node.scrollLeft = mem.x;
    node.scrollTop = mem.y;
    scrollKey.current = nextKey;
  }, [lens, mode]);

  function openMenu(event, entry, userId, dayOfWeek) {
    setMenu({
      x: Math.min(event.clientX, window.innerWidth - 220),
      y: Math.min(event.clientY, window.innerHeight - 280),
      entry,
      userId,
      day: dayOfWeek,
    });
  }

  function openCoverage(dayValue, role, hour) {
    const minute = Number(hour) * 60;
    const match = entries.find((entry) => {
      if (Number(entry.day_of_week) !== Number(dayValue)) return false;
      return visualPieces(entry).some((piece) => piece.role === role && piece.start < minute + 60 && piece.end > minute);
    });
    if (match) onEdit?.(match);
    else onOpenDay(dayValue);
  }

  function commit(next, label) {
    onCommit(entries.map((entry) => (shiftKey(entry) === shiftKey(next) ? { ...entry, ...next } : entry)), label);
    onSelect(shiftKey(next));
  }

  function hover(entry, rect) {
    if (!entry || !rect) {
      setTip(null);
      return;
    }
    const person = personName(employees, entry.user_id);
    const extra = untimed(entry) ? ` · ${entry.break_minutes} min break, no clock time` : "";
    setTip({
      name: person,
      detail: `${SHORT[entry.day_of_week]} ${hm(entry.start_time)}–${hm(entry.end_time)} · ${nice(entry.role || "No role")}${extra}`,
      left: Math.min(rect.left, window.innerWidth - 250),
      top: Math.max(8, rect.top - 58),
    });
  }

  const head = days.map((value) => (
    <div key={value} className={`dayhead${value === 6 || value === 0 ? " is-end" : ""}${mode === "day" ? " is-on" : ""}`}>
      <strong>{SHORT[value]} {dayStamp(weekStart, value)}</strong>
      <div className="axis">{ticks(axis).map((minute) => <b key={minute} style={{ left: `${leftOf(minute, axis)}%` }}>{String(minute / 60).padStart(2, "0")}</b>)}</div>
    </div>
  ));

  const employeeRows = rosterEmployees.map((employee) => {
    const open = !scheduledIds.has(Number(employee.user_id));
    const picked = entries.some((entry) => Number(entry.user_id) === Number(employee.user_id) && shiftKey(entry) === selectedKey);
    const byDay = days.map((value) => {
      const shifts = entries.filter((entry) => Number(entry.user_id) === Number(employee.user_id) && Number(entry.day_of_week) === Number(value));
      return pack(shifts.map((entry) => ({ ...shiftRange(entry), entry })).filter((item) => item.start != null));
    });
    const lanes = Math.max(1, ...byDay.map((column) => (column.placed.length ? column.lanes : 1)));
    const bar = mode === "day" ? 26 : 18;
    const height = 6 + lanes * bar + (lanes - 1) * 3;
    return (
      <div className={`person${open ? " is-open" : ""}${picked ? " is-pick" : ""}`} key={employee.user_id}>
        <div className="who"><span className="avatar">{initials(employee.display_name)}</span><span className="nm">{String(employee.display_name || "").replace(/\s+/g, " ")}</span></div>
        {byDay.map((column, index) => {
          const value = days[index];
          const stacked = column.lanes > 1 && column.placed.length > 1;
          return (
            <div
              key={value}
              className={`cell${value === 6 || value === 0 ? " is-end" : ""}`}
              style={{ "--guides": guides }}
              onDragOver={(event) => event.preventDefault()}
              onContextMenu={(event) => {
                if (event.target.closest(".shift")) return;
                event.preventDefault();
                openMenu(event, null, Number(employee.user_id), Number(value));
              }}
              onDrop={(event) => {
                const key = event.dataTransfer.getData("text/plain");
                const moving = entries.find((entry) => shiftKey(entry) === key);
                if (moving && onMove) onMove(moving, Number(employee.user_id), Number(value));
              }}
            >
              <div className="guides" />
              <div className="track" style={{ height }}>
                {!column.placed.length && lens === "employees" ? (
                  <button type="button" className="cell-add" onClick={() => onAdd(Number(employee.user_id), Number(value))}>Add shift</button>
                ) : null}
                {column.placed.map((item) => (
                  <ShiftFace
                    key={shiftKey(item.entry)}
                    entry={item.entry}
                    axis={axis}
                    lane={item.lane}
                    bar={bar}
                    stacked={stacked}
                    muted={lens === "breaks"}
                    selected={shiftKey(item.entry) === selectedKey}
                    peer={peers.some((entry) => shiftKey(entry) === shiftKey(item.entry))}
                    showGrips={mode === "day" && lens !== "breaks" && shiftKey(item.entry) === selectedKey}
                    onSelect={(entry) => onSelect(shiftKey(entry))}
                    onCommit={commit}
                    onHover={hover}
                    onDragShift={() => onSelect(shiftKey(item.entry))}
                    onEdit={onEdit}
                    onMenu={(event, entry) => openMenu(event, entry, Number(entry.user_id), Number(entry.day_of_week))}
                  />
                ))}
                {lens === "breaks" ? column.placed.flatMap((item) => visibleBreaks(item.entry).filter((slot) => slot.start_time).map((slot) => {
                  const start = clockMinutes(slot.start_time);
                  let end = clockMinutes(slot.end_time);
                  if (start == null || end == null) return null;
                  if (end <= start) end += 24 * 60;
                  return (
                    <span
                      key={`${shiftKey(item.entry)}-${slot.start_time}`}
                      className="break-block"
                      style={{ left: `${leftOf(start, axis)}%`, width: `${widthOf(start, end, axis)}%`, top: 4 + item.lane * (bar + 3), height: bar }}
                      title={`Break ${hm(slot.start_time)}–${hm(slot.end_time)}`}
                    >
                      <button
                        type="button"
                        className="break-grip"
                        aria-label={`Change break start ${hm(slot.start_time)}`}
                        onPointerDown={(event) => trackPointer(event, axis, (minutes, done) => {
                          if (!done) return;
                          const index = visibleBreaks(item.entry).filter((itemSlot) => itemSlot.start_time).indexOf(slot);
                          commit(resizeBreak(item.entry, index, "start", minutes), "Proposed a new break start. Not saved.");
                        })}
                      />
                      Break {hm(slot.start_time)}–{hm(slot.end_time)}
                      <button
                        type="button"
                        className="break-grip"
                        aria-label={`Change break end ${hm(slot.end_time)}`}
                        onPointerDown={(event) => trackPointer(event, axis, (minutes, done) => {
                          if (!done) return;
                          const index = visibleBreaks(item.entry).filter((itemSlot) => itemSlot.start_time).indexOf(slot);
                          commit(resizeBreak(item.entry, index, "end", minutes), "Proposed a new break end. Not saved.");
                        })}
                      />
                      <button
                        type="button"
                        aria-label="Remove the clock time and keep the break length"
                        onClick={() => commit(unscheduleBreak(item.entry), "Removed the break clock time. The break length stays. Not saved.")}
                      >
                        Unschedule
                      </button>
                    </span>
                  );
                })) : null}
              </div>
            </div>
          );
        })}
      </div>
    );
  });

  const roleBuckets = new Map();
  entries.forEach((entry) => {
    visualPieces(entry).forEach((piece) => {
      if (!piece.role) return;
      if (!roleBuckets.has(piece.role)) roleBuckets.set(piece.role, []);
      roleBuckets.get(piece.role).push({ ...piece, entry });
    });
  });
  const roles = [...roleBuckets.entries()].sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0]));

  return (
    <div className="stage">
      {dirty && !showDrawer ? (
        <div className="draft-bar">
          <p className="state dirty"><i />Unsaved changes</p>
          <button type="button" className="btn" onClick={onUndo} disabled={!canUndo}>Undo</button>
          <button type="button" className="btn" onClick={onRedo} disabled={!canRedo}>Redo</button>
          <button type="button" className="btn" onClick={onDiscard}>Discard</button>
          <button type="button" className="btn primary" onClick={() => onReview()}>Review save</button>
        </div>
      ) : null}
      {selected && lens !== "tasks" ? (
        <div className="shift-actions">
          <strong>{personName(employees, selected.user_id)}</strong>
          <span className="when">{SHORT[selected.day_of_week]} {hm(selected.start_time)}–{hm(selected.end_time)} · {nice(selected.role || "No role")}</span>
          {peers.length ? <span className="ops-warn">Overlaps another shift</span> : null}
          {peers.map((entry) => (
            <button key={shiftKey(entry)} type="button" onClick={() => onSelect(shiftKey(entry))}>{nice(entry.role || "shift")} {hm(entry.start_time)}–{hm(entry.end_time)}</button>
          ))}
          {!selected.role ? <span className="ops-warn">Missing role</span> : null}
          <button type="button" className="btn" onClick={() => onEdit?.(selected)}>Edit</button>
          <button type="button" className="btn" onClick={() => onOpenDay(selected.day_of_week)}>Open day</button>
          <button type="button" className="btn" onClick={() => onCopy(selected)}>Copy</button>
          {canPaste ? <button type="button" className="btn" onClick={() => onPaste(Number(selected.user_id), Number(selected.day_of_week))}>Paste</button> : null}
          <button type="button" className="btn" onClick={() => onDuplicate(selected)}>Duplicate</button>
          <button type="button" className="btn" onClick={() => onSplit(selected)}>Split</button>
          <button type="button" className="btn danger" onClick={() => onRemove(selected)}>Delete</button>
        </div>
      ) : null}
      {lens === "breaks" ? (
        <div className="break-queue">
          <p>Timed breaks stay on the timeline. Open a shift to place or move a break. Break rules and payroll deductions are unchanged.</p>
          {entries.some((entry) => untimed(entry) && (mode !== "day" || Number(entry.day_of_week) === Number(day))) ? (
            <div className="picks">
              {entries.filter((entry) => untimed(entry) && (mode !== "day" || Number(entry.day_of_week) === Number(day))).map((entry) => (
                <button key={shiftKey(entry)} type="button" onClick={() => onEdit?.(entry)}>
                  {personName(employees, entry.user_id)} · {SHORT[entry.day_of_week]} · {entry.break_minutes} min, no clock time
                </button>
              ))}
            </div>
          ) : <span className="when">Every stored break on this view has a clock time.</span>}
        </div>
      ) : null}
          {lens === "breaks" ? (
        <>
        <BreakImpact entries={entries} day={day} unscheduledCount={entries.filter((entry) => untimed(entry) && (mode !== "day" || Number(entry.day_of_week) === Number(day))).length} />
        <div className="inspect">
          <span className="when">
            {overlap > BREAK_OVERLAP_CAP
              ? `${overlap} people have a timed break at the same time. The limit is ${BREAK_OVERLAP_CAP}.`
              : breaks.overlapKnown
                ? `Timed break overlap is ${overlap}. Every stored break has a clock time.`
                : `Timed break overlap is ${overlap}. ${breaks.unscheduledCount} breaks have no clock time, so overlap cannot be fully determined.`}
          </span>
        </div>
        </>
      ) : null}
      <div className="workspace">
        <div className="board" ref={boardRef} onScroll={rememberScroll}>
          {lens === "employees" || lens === "breaks" ? (
            <div className={`sheet${mode === "day" ? " day-layout" : ""}`} style={{ "--cols": String(days.length), "--colmin": `${Math.round(96 * zoom)}px` }}>
              <div className="filters">
                <select aria-label="Employee roster" value={roster} onChange={(event) => setRoster(event.target.value)}>
                  <option value="all">All</option>
                  <option value="scheduled">Scheduled</option>
                  <option value="unscheduled">Unscheduled</option>
                </select>
                <input aria-label="Find employee" value={query} placeholder="Find employee" onChange={(event) => setQuery(event.target.value)} />
                <select aria-label="Role filter" value={roleFilter} onChange={(event) => setRoleFilter(event.target.value)}>
                  <option value="">All roles</option>
                  {roleNames.map((role) => <option key={role} value={role}>{role}</option>)}
                </select>
                <select aria-label="Sort employees" value={sort} onChange={(event) => setSort(event.target.value)}>
                  <option value="name">Name</option>
                  <option value="scheduled">Scheduled first</option>
                </select>
                <select aria-label="Timeline zoom" value={String(zoom)} onChange={(event) => setZoom(Number(event.target.value))}>
                  <option value="1">Fit</option>
                  <option value="1.4">Wider</option>
                  <option value="1.8">Widest</option>
                </select>
                <span className="legend">{roleNames.slice(0, 8).map((role) => <span key={role}><i style={{ background: roleColor(role) }} />{nice(role)}</span>)}</span>
              </div>
              <div className="head">
                <div className="who">
                  <span>Employee</span>
                  <button type="button" onClick={() => onAdd(addTarget)}>Add</button>
                </div>
                {head}
              </div>
              {employeeRows}
              {!rosterEmployees.length ? <div className="empty"><div><h2>{roster === "unscheduled" ? "Every eligible employee has a shift" : "No employees"}</h2><p>The roster is the same eligible list Weekly Schedule uses.</p></div></div> : null}
            </div>
          ) : null}
          {lens === "roles" ? (
            <div className="sheet roles-sheet">
              <div className="filters">
                <span className="legend">{roleNames.map((role) => <span key={role}><i style={{ background: roleColor(role) }} />{nice(role)}</span>)}</span>
                {requirements?.length ? <button type="button" className="staff-review" onClick={() => onReviewBundle("requirements")}>Review staffing</button> : null}
              </div>
              <CoverageBoard
                entries={mode === "day" ? entries.filter((entry) => Number(entry.day_of_week) === Number(day)) : entries}
                requirements={requirements}
                employees={employees}
                day={day}
                onOpenGap={openCoverage}
              />
              <details className="role-blocks">
                <summary>Shift blocks for {SHORT[day]}</summary>
                <div className="roles-body">
                  {roles.map(([role, items]) => {
                    const column = pack(items.filter((item) => Number(item.entry.day_of_week) === Number(day)));
                    return (
                      <section key={role} className="role role-day">
                        <div className="role-id">
                          <span className="swatch" style={{ background: roleColor(role) }} />
                          <strong>{nice(role)}</strong>
                          <div className="meta">{column.placed.length} on {SHORT[day]}</div>
                          <RequirementEditor role={role} day={day} requirements={requirements} axis={axis} onChange={(next, label) => onCommit({ requirements: next }, label)} />
                        </div>
                        <div className="cell">
                          <div className="track" style={{ height: Math.max(28, 8 + column.lanes * 24) }}>
                            {column.placed.map((item) => (
                              <button
                                key={`${shiftKey(item.entry)}-${item.start}`}
                                type="button"
                                className="shift"
                                title={`${personName(employees, item.entry.user_id)} · ${hm(item.entry.start_time)}–${hm(item.entry.end_time)}`}
                                style={{ left: `${leftOf(item.start, axis)}%`, width: `${widthOf(item.start, item.end, axis)}%`, top: 2 + item.lane * 24, height: 22, background: roleColor(role) }}
                                onClick={() => onSelect(shiftKey(item.entry))}
                                onDoubleClick={() => onEdit?.(item.entry)}
                              >
                                <span className="txt">{personName(employees, item.entry.user_id)}</span>
                              </button>
                            ))}
                          </div>
                        </div>
                      </section>
                    );
                  })}
                  {!roles.length ? <div className="empty"><div><h2>No roles on this day</h2><p>Add a shift and a role. Coverage stays “Not set” until a staffing interval is saved.</p></div></div> : null}
                </div>
              </details>
            </div>
          ) : null}
          {lens === "tasks" ? (
            <TaskPlanner
              tasks={tasks}
              employees={employees}
              entries={entries}
              day={day}
              mode={mode}
              catalog={catalog}
              onChange={(next) => onCommit({ tasks: next }, "Updated the task draft. Not saved.")}
              onReview={() => onReviewBundle("tasks")}
            />
          ) : null}
        </div>
        {showDrawer ? (
          <Drawer
            entry={selected}
            employees={employees}
            tasks={tasks}
            dayLabel={`${SHORT[selected.day_of_week]} ${dayStamp(weekStart, selected.day_of_week)}`}
            dirty={dirty}
            canUndo={canUndo}
            canRedo={canRedo}
            conflict={peers.length > 0}
            missingRole={!selected.role && !storedSegments(selected).length}
            badBreak={breakOutside(selected)}
            onClose={onCloseEditor}
            onCommit={commit}
            onReview={onReview}
            onUndo={onUndo}
            onRedo={onRedo}
            onDiscard={onDiscard}
            onAdd={onAdd}
            onCopy={onCopy}
            onDuplicate={onDuplicate}
            onSplit={onSplit}
            onRemove={onRemove}
          />
        ) : null}
      </div>
      {menu ? (
        <div className="context-menu" role="menu" style={{ left: menu.x, top: menu.y }} onMouseDown={(event) => event.stopPropagation()}>
          {menu.entry ? <button type="button" role="menuitem" onClick={() => { onEdit?.(menu.entry); setMenu(null); }}>Edit</button> : null}
          {menu.entry ? <button type="button" role="menuitem" onClick={() => { onCopy(menu.entry); setMenu(null); }}>Copy</button> : null}
          {canPaste ? <button type="button" role="menuitem" onClick={() => { onPaste(menu.userId, menu.day); setMenu(null); }}>Paste</button> : null}
          {menu.entry ? <button type="button" role="menuitem" onClick={() => { onDuplicate(menu.entry); setMenu(null); }}>Duplicate</button> : null}
          {menu.entry ? <button type="button" role="menuitem" onClick={() => { onSplit(menu.entry); setMenu(null); }}>Split</button> : null}
          <button type="button" role="menuitem" onClick={() => { onAdd(menu.userId, menu.day); setMenu(null); }}>Add shift</button>
          {menu.entry ? <button type="button" role="menuitem" onClick={() => { onCopyRequest?.("employee-day", menu); setMenu(null); }}>Copy employee day</button> : null}
          {menu.entry ? <button type="button" role="menuitem" onClick={() => { onCopyRequest?.("employee-week", menu); setMenu(null); }}>Copy employee week</button> : null}
          <button type="button" role="menuitem" onClick={() => { onCopyRequest?.("day", menu); setMenu(null); }}>Copy day</button>
          <button type="button" role="menuitem" onClick={() => { onCopyRequest?.("week", menu); setMenu(null); }}>Copy week</button>
          {menu.entry ? <button type="button" role="menuitem" className="danger" onClick={() => { onRemove(menu.entry); setMenu(null); }}>Delete</button> : null}
        </div>
      ) : null}
      {tip ? <div className="tip" style={{ left: tip.left, top: tip.top }}><b>{tip.name}</b><span>{tip.detail}</span></div> : null}
      {planner?.legacy_template ? null : null}
    </div>
  );
}
