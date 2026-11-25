import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  BREAK_OVERLAP_CAP,
  DAY_NAMES,
  DAY_ORDER,
  breakAccounting,
  clockMinutes,
  minutesToClock,
  breakOverlapBands,
  overlappingBreakCount,
  pointerToMinutes,
  spanMinutes,
  staffingHours,
} from "./plannerModel";
import { copiedShift } from "./plannerCopy";
import {
  asList,
  relocateShift,
  removeRoleSegment,
  resizeBreak,
  unscheduleBreak,
  resizeEdge,
  resizeSegment,
  roleColor,
  applyRoleEdits,
  roleIntervals,
  dayScheduleSummary,
  scheduleCardRows,
  scheduledRoleHours,
  staffingFigures,
  breakAssignment,
  copyBreaksOnto,
  copyTaskAssignments,
  moveBreakTo,
  moveTaskTo,
  proposeBreak,
  removeBreak,
  sharedActivity,
  slideBreak,
  shiftKey,
  storedSegments,
  timelineAxis,
  visibleBreaks,
  visualPieces,
} from "./plannerGeometry";
import { scheduleRoleCatalog, scheduleRoleLabel, scheduleRoleMark } from "../components/weeklySchedule/weeklyScheduleRoles";
import { CoverageBoard, TaskPlanner } from "./PlannerBoards";

const SHORT = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const DAY_ROLES = ["fold", "sort", "wash", "hd_folder", "hd_operator", "attendant"];

function personName(employees, userId) {
  return employees.find((employee) => Number(employee.user_id) === Number(userId))?.display_name || `Employee ${userId}`;
}

function initials(name) {
  const parts = String(name || "").trim().split(/\s+/);
  return ((parts[0]?.[0] || "") + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase();
}

function nice(role) {
  const text = String(role || "");
  if (!text) return "No role";
  if (text.includes(",")) return text.split(",").map((part) => nice(part.trim())).join(" · ");
  const label = scheduleRoleLabel(text);
  return label === text ? text.replaceAll("_", " ") : label;
}

function staffingRoles() {
  return scheduleRoleCatalog().filter((role) => role.active !== false && role.uses_time_slots !== false);
}

function taskRoles() {
  return scheduleRoleCatalog().filter((role) => role.active !== false && role.uses_time_slots === false);
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

function intervalsOverlap(left, right) {
  return left.some(([start, end]) => right.some(([otherStart, otherEnd]) => start < otherEnd && otherStart < end));
}

function overlaps(a, b) {
  if (!a || !b || shiftKey(a) === shiftKey(b)) return false;
  if (Number(a.user_id) !== Number(b.user_id) || Number(a.day_of_week) !== Number(b.day_of_week)) return false;
  return intervalsOverlap(roleIntervals(a), roleIntervals(b));
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

function hourLabel(minute, compact) {
  const hour = Math.floor(minute / 60) % 24;
  const shown = hour % 12 || 12;
  if (compact) return `${shown}${hour < 12 ? "a" : "p"}`;
  return `${shown} ${hour < 12 ? "AM" : "PM"}`;
}

function ticks(axis, step) {
  const marks = [];
  const first = Math.ceil(axis.startMin / 60) * 60;
  for (let minute = first; minute <= axis.endMin; minute += step) marks.push(minute);
  return marks;
}

function guideImage(axis, marks) {
  return marks.map((minute) => {
    const at = ((minute - axis.startMin) / axis.span) * 100;
    if (at <= 0 || at >= 100) return "";
    return `linear-gradient(to right, transparent calc(${at}% - .5px), #e7eaee calc(${at}% - .5px), #e7eaee calc(${at}% + .5px), transparent calc(${at}% + .5px))`;
  }).filter(Boolean).join(",");
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
          />
        );
      }) : (
        <span className={`txt${String(entry.role || "").includes(",") ? " is-combined" : ""}`} title={`${nice(labelRole)} ${hm(entry.start_time)}–${hm(entry.end_time)}`} style={{ background: roleColor(entry.role) }} />
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

function writeBreaks(entry, slots) {
  return breakAssignment(entry, slots);
}

function appendSegment(entry, role, start, end) {
  const name = String(role || "").trim();
  if (!name || !spanMinutes(start, end)) return entry;
  return {
    ...entry,
    role: entry.role || name,
    role_assignments: [...storedSegments(entry), { role: name, start_time: start, end_time: end }],
  };
}

function editorRows(entry) {
  const stored = storedSegments(entry).filter((segment) => segment.role && spanMinutes(segment.start_time, segment.end_time));
  if (stored.length) return stored;
  const role = String(entry?.role || "").trim();
  if (!role || role.includes(",") || !spanMinutes(entry?.start_time, entry?.end_time)) return [];
  return [{ role, start_time: hm(entry.start_time), end_time: hm(entry.end_time) }];
}

/** Role edits keep the stored envelope. Trim and extend are explicit. */
function scheduleFromRoles(entry, segments, mode) {
  const decision = applyRoleEdits(entry, segments, mode);
  if (!mode && decision.confirm) return { ...entry, envelopeConfirm: decision.confirm };
  return decision.entry;
}

function segmentsOverlap(segments) {
  const pieces = segments.map((segment) => {
    const start = clockMinutes(segment.start_time);
    let end = clockMinutes(segment.end_time);
    if (start == null || end == null) return null;
    if (end <= start) end += 24 * 60;
    return [start, end];
  }).filter(Boolean).sort((a, b) => a[0] - b[0]);
  return pieces.some((piece, index) => pieces.slice(index + 1).some((other) => piece[0] < other[1] && other[0] < piece[1]));
}

function Drawer({ entry, employees, tasks, dayLabel, dirty, saving, canUndo, canRedo, conflict, missingRole, badBreak, saveError, saveConflict, onReload, onClose, onCommit, onTasks, onReview, onUndo, onRedo, onDiscard, onCopyBreaks, onCopyTask, onDelete }) {
  const range = entry ? shiftRange(entry) : null;
  const [roleCode, setRoleCode] = useState("");
  const [segStart, setSegStart] = useState(range ? minutesToClock(range.start) : "");
  const [segEnd, setSegEnd] = useState(range ? minutesToClock(Math.min(range.end, range.start + 60)) : "");
  const [breakStart, setBreakStart] = useState("");
  const [breakEnd, setBreakEnd] = useState("");
  const [breakMinutes, setBreakMinutes] = useState("30");
  const [editorBreakMode, setEditorBreakMode] = useState("timed");
  const [taskCode, setTaskCode] = useState("");
  const [taskQuery, setTaskQuery] = useState("");
  const [roleQuery, setRoleQuery] = useState("");
  const [envelopeAsk, setEnvelopeAsk] = useState(null);
  useLayoutEffect(() => {
    if (!entry) return;
    const next = shiftRange(entry);
    const stored = storedSegments(entry);
    const last = stored[stored.length - 1];
    const start = last ? clockMinutes(last.end_time) : next?.start;
    setSegStart(start == null ? "" : minutesToClock(start));
    setSegEnd(next && start != null ? minutesToClock(Math.min(next.end, start + 60)) : "");
    const slots = visibleBreaks(entry).filter((slot) => slot.start_time);
    setEditorBreakMode(slots.length ? "timed" : "untimed");
    setBreakStart(slots[0]?.start_time ? String(slots[0].start_time).slice(0, 5) : "");
    setBreakEnd(slots[0]?.end_time ? String(slots[0].end_time).slice(0, 5) : "");
    setBreakMinutes(String(visibleBreaks(entry).find((slot) => slot.unscheduled)?.minutes ?? entry?.break_minutes ?? 0));
    setRoleCode("");
    setTaskCode("");
  }, [entry?.id]);
  if (!entry) return null;
  const person = personName(employees, entry.user_id);
  const stored = editorRows(entry);
  const booked = staffingFigures(entry);
  const mine = (tasks || []).filter((task) => !task.remove && Number(task.user_id) === Number(entry.user_id) && Number(task.day_of_week) === Number(entry.day_of_week));
  const roles = staffingRoles();
  const tasksAvailable = taskRoles().filter((item) => `${item.name || ""} ${item.code}`.toLowerCase().includes(taskQuery.toLowerCase()));
  function patch(next, label) {
    if (next?.envelopeConfirm) {
      setEnvelopeAsk(next.envelopeConfirm);
      return;
    }
    const { envelopeConfirm, ...rest } = next || {};
    onCommit({ ...entry, ...rest, id: entry.id }, label);
  }
  return (
    <aside className="drawer" aria-label="Shift details">
      <header>
        <span className="avatar">{initials(person)}</span>
        <div>
          <h2>{person}</h2>
          <p>{dayLabel} · {nice(entry.role)}</p>
        </div>
        <button type="button" className="close" aria-label="Close" onClick={onClose}>×</button>
      </header>
        <div className="body">
        {saveError ? (
          <p className="ops-warn" role="alert">
            {saveError}
            {saveConflict === "schedule_changed" ? <button type="button" className="btn" onClick={onReload}>Reload week</button> : null}
          </p>
        ) : null}
        {!saveError && conflict ? <p className="ops-warn">This shift overlaps another shift for the same employee.</p> : null}
        {!saveError && missingRole ? <p className="ops-warn">Add a role. The shift hours stay until you save or discard.</p> : null}
        {!saveError && badBreak ? <p className="ops-warn">A break sits outside the shift, or its start and end are the same.</p> : null}
        <div className="sec">
          <h3>Assignment</h3>
          <select aria-label="Employee" value={String(entry.user_id)} onChange={(event) => patch({ user_id: Number(event.target.value) }, "Proposed a different employee. Not saved.")}>
            {employees.map((employee) => <option key={employee.user_id} value={employee.user_id}>{employee.display_name}</option>)}
          </select>
          <select aria-label="Day" value={String(entry.day_of_week)} onChange={(event) => patch(relocateShift(entry, entry.start_time, Number(event.target.value)), "Proposed a different day. Not saved.")}>
            {DAY_ORDER.map((value) => <option key={value} value={value}>{DAY_NAMES[value]}</option>)}
          </select>
          <p className="shift-summary">Role {booked.role.toFixed(1)}h · Unallocated {booked.unallocated.toFixed(1)}h · Total {booked.total.toFixed(1)}h · Net {booked.net.toFixed(1)}h</p>
        </div>
        <div className="sec">
          <h3>Roles</h3>
          <input aria-label="Find a role" value={roleQuery} placeholder="Find a role" onChange={(event) => setRoleQuery(event.target.value)} />
          {!stored.length ? <p className="quiet">Add each role with its own start and end.</p> : null}
          {segmentsOverlap(stored) ? <p className="ops-warn">These role times overlap.</p> : null}
          <div className="role-head" aria-hidden="true"><span>Role</span><span>Start</span><span>End</span><span /></div>
          <ul className="segs">
            {stored.map((segment, index) => (
              <li key={`${segment.role}-${segment.start_time}-${index}`} className="role-row">
                <select aria-label={`Role ${index + 1}`} value={segment.role} onChange={(event) => {
                  const next = stored.map((item, itemIndex) => (itemIndex === index ? { ...item, role: event.target.value } : item));
                  patch(scheduleFromRoles(entry, next), "Proposed a role. Not saved.");
                }}>
                  {segment.role && !roles.some((role) => role.code === segment.role) ? <option value={segment.role}>{nice(segment.role)}</option> : null}
                  {roles.filter((role) => `${role.name || ""} ${scheduleRoleLabel(role.code)}`.toLowerCase().includes(roleQuery.toLowerCase()) || role.code === segment.role).map((role) => <option key={role.code} value={role.code}>{scheduleRoleLabel(role.code)}</option>)}
                </select>
                <input aria-label={`${scheduleRoleLabel(segment.role)} start`} type="time" step="900" value={hm(segment.start_time)} onChange={(event) => {
                  const next = stored.map((item, itemIndex) => (itemIndex === index ? { ...item, start_time: event.target.value } : item));
                  patch(scheduleFromRoles(entry, next), "Proposed a role time. Not saved.");
                }} />
                <input aria-label={`${scheduleRoleLabel(segment.role)} end`} type="time" step="900" value={hm(segment.end_time)} onChange={(event) => {
                  const next = stored.map((item, itemIndex) => (itemIndex === index ? { ...item, end_time: event.target.value } : item));
                  patch(scheduleFromRoles(entry, next), "Proposed a role time. Not saved.");
                }} />
                <button type="button" className="btn danger" onClick={() => patch(scheduleFromRoles(entry, stored.filter((_, itemIndex) => itemIndex !== index)), "Proposed removing a role. Not saved.")}>Remove</button>
              </li>
            ))}
          </ul>
          <div className="role-row">
            <select aria-label="Role to add" value={roleCode} onChange={(event) => setRoleCode(event.target.value)}>
              <option value="">Add a role</option>
              {roles.filter((role) => `${role.name || ""} ${scheduleRoleLabel(role.code)}`.toLowerCase().includes(roleQuery.toLowerCase())).map((role) => <option key={role.code} value={role.code}>{scheduleRoleLabel(role.code)}</option>)}
            </select>
            <input aria-label="Segment start" type="time" step="900" value={segStart} onChange={(event) => setSegStart(event.target.value)} />
            <input aria-label="Segment end" type="time" step="900" value={segEnd} onChange={(event) => setSegEnd(event.target.value)} />
            <button type="button" className="btn" onClick={() => patch(scheduleFromRoles(entry, [...stored, { role: roleCode, start_time: segStart, end_time: segEnd }].filter((item) => item.role && spanMinutes(item.start_time, item.end_time))), "Proposed a role segment. Not saved.")}>Add</button>
          </div>
          {booked.unallocated > 0.05 ? <p className="ops-warn">Unallocated {booked.unallocated.toFixed(1)}h stays on this shift. Change the shift hours if that time should not be scheduled.</p> : null}
          {envelopeAsk ? (
            <div className="ops-warn" role="dialog" aria-label="Confirm scheduled hours">
              <p>Total scheduled hours {Number(envelopeAsk.before).toFixed(1)}h to {Number(envelopeAsk.after).toFixed(1)}h. The stored envelope stays unchanged until this is confirmed.</p>
              <button type="button" className="btn" onClick={() => setEnvelopeAsk(null)}>Cancel</button>
              <button type="button" className="btn primary" onClick={() => {
                const next = envelopeAsk.kind === "trim"
                  ? envelopeAsk.apply
                  : scheduleFromRoles(entry, envelopeAsk.segments, "extend");
                setEnvelopeAsk(null);
                patch(next, envelopeAsk.kind === "trim" ? "Trimmed the unallocated time. Not saved." : "Extended the shift to include the role. Not saved.");
              }}>Confirm</button>
            </div>
          ) : null}
        </div>
        <div className="sec">
          <h3>Break</h3>
          <div className="pick-row">
            <label><input type="radio" name="editor-break" checked={editorBreakMode === "timed"} onChange={() => setEditorBreakMode("timed")} /> Timed</label>
            <label><input type="radio" name="editor-break" checked={editorBreakMode === "untimed"} onChange={() => setEditorBreakMode("untimed")} /> Untimed</label>
          </div>
          {visibleBreaks(entry).map((slot, index) => (
            <div key={`${slot.start_time || "untimed"}-${index}`} className="role-row">
              {slot.start_time ? (
                <>
                  <b>Break</b>
                  <input aria-label={`Break ${index + 1} start`} type="time" step="900" value={hm(slot.start_time)} onChange={(event) => {
                    const next = writeBreaks(entry, visibleBreaks(entry).map((item, itemIndex) => (itemIndex === index ? { ...item, start_time: event.target.value } : item)));
                    patch(scheduleFromRoles(next, editorRows(next)), "Changed a break. Not saved.");
                  }} />
                  <input aria-label={`Break ${index + 1} end`} type="time" step="900" value={hm(slot.end_time)} onChange={(event) => {
                    const next = writeBreaks(entry, visibleBreaks(entry).map((item, itemIndex) => (itemIndex === index ? { ...item, end_time: event.target.value } : item)));
                    patch(scheduleFromRoles(next, editorRows(next)), "Changed a break. Not saved.");
                  }} />
                </>
              ) : <b>Untimed {slot.minutes}m{staffingFigures(entry).review ? " · review" : ""}</b>}
              <button type="button" className="btn danger" onClick={() => {
                const next = removeBreak(entry, index);
                patch(scheduleFromRoles(next, editorRows(next)), "Removed a break. Not saved.");
              }}>Remove</button>
            </div>
          ))}
          {editorBreakMode === "timed" ? (
            <div className="role-row">
              <b>Break</b>
              <input aria-label="Break start" type="time" step="900" value={breakStart} onChange={(event) => setBreakStart(event.target.value)} />
              <input aria-label="Break end" type="time" step="900" value={breakEnd} onChange={(event) => setBreakEnd(event.target.value)} />
              <button type="button" className="btn" onClick={() => {
                if (!breakStart || !breakEnd) return;
                const next = writeBreaks(entry, [...visibleBreaks(entry), { start_time: breakStart, end_time: breakEnd }]);
                patch(scheduleFromRoles(next, editorRows(next)), "Added a timed break. Not saved.");
              }}>Add</button>
            </div>
          ) : (
            <div className="role-row">
              <b>Duration</b>
              <input aria-label="Untimed break minutes" type="number" min="0" step="5" value={breakMinutes} onChange={(event) => setBreakMinutes(event.target.value)} />
              <button type="button" className="btn" onClick={() => {
                const minutes = Number(breakMinutes) || 0;
                if (!minutes) return;
                const next = writeBreaks(entry, [...visibleBreaks(entry), { minutes }]);
                patch(scheduleFromRoles(next, editorRows(next)), "Added an untimed break. Not saved.");
              }}>Add</button>
            </div>
          )}
          {visibleBreaks(entry).length ? <button type="button" className="btn" onClick={() => onCopyBreaks?.(entry)}>Copy breaks</button> : null}
        </div>
        <div className="sec">
          <h3>Tasks</h3>
          <ul className="segs">
            {mine.map((task) => {
              const locked = ["in_progress", "pending_approval", "approved", "rejected", "completed"].includes(String(task.activity_status || task.status || ""));
              const anytime = task.timing_mode !== "specific_time";
              const edit = (patch) => onTasks?.((tasks || []).map((item) => (item === task || (task.id && item.id === task.id) ? { ...item, ...patch, changed: !item.draft } : item)));
              return (
                <li key={task.id || task.role} className="role-row task-row">
                  <b className="task-name" title={nice(task.role)}>{nice(task.role)}</b>
                  <label><input type="checkbox" checked={anytime} disabled={locked} onChange={(event) => edit(event.target.checked ? { timing_mode: "anytime", start_time: null, end_time: null } : { timing_mode: "specific_time" })} /> Anytime</label>
                  {anytime ? null : (
                    <>
                      <input aria-label={`${nice(task.role)} planned start`} type="time" step="900" disabled={locked} value={hm(task.start_time)} onChange={(event) => edit({ timing_mode: "specific_time", start_time: event.target.value })} />
                      <input aria-label={`${nice(task.role)} planned end`} type="time" step="900" disabled={locked} value={hm(task.end_time)} onChange={(event) => edit({ timing_mode: "specific_time", end_time: event.target.value })} />
                    </>
                  )}
                  {locked || sharedActivity(task) ? null : <button type="button" className="btn" onClick={() => onCopyTask?.(task)}>Copy</button>}
                  {sharedActivity(task) ? <span className="quiet">Shared activity. Copy is off so the checklist stays with this group.</span> : null}
                  {locked ? null : <button type="button" className="btn danger" onClick={() => onTasks?.((tasks || []).map((item) => (item === task || item.id === task.id ? { ...item, remove: true } : item)).filter((item) => !(item.draft && item.remove)))}>Remove</button>}
                </li>
              );
            })}
          </ul>
          {!mine.length ? <p className="quiet">No task on this employee and day.</p> : null}
          <div className="segment-add">
            <input aria-label="Find a task" value={taskQuery} placeholder="Find a task" onChange={(event) => setTaskQuery(event.target.value)} />
            <select aria-label="Task to assign" value={taskCode} onChange={(event) => setTaskCode(event.target.value)}>
              <option value="">Add a task</option>
              {tasksAvailable.map((item) => <option key={item.code} value={item.code}>{String(item.code).startsWith("agroup_") ? "Activity · " : ""}{item.name || scheduleRoleLabel(item.code)}</option>)}
            </select>
            <button type="button" className="btn" onClick={() => {
              if (!taskCode) return;
              onTasks?.([...(tasks || []), {
                id: `draft-task-${Date.now()}`,
                draft: true,
                user_id: Number(entry.user_id),
                day_of_week: Number(entry.day_of_week),
                role: taskCode,
                timing_mode: "anytime",
                execution_mode: "individual",
                status: "assigned",
              }]);
              setTaskCode("");
            }}>Add task</button>
          </div>
        </div>
      </div>
      <footer>
        <p className={`state${dirty ? " dirty" : ""}`}><i />{dirty ? "Unsaved changes" : "No unsaved changes"}</p>
        <button type="button" className="btn danger" onClick={() => onDelete?.(entry)}>Delete shift</button>
        <button type="button" className="btn" onClick={() => onReview({ repeat: true })} disabled={!dirty || saving}>Future weeks</button>
        <button type="button" className="btn" onClick={() => onReview()} disabled={!dirty || saving}>{saving ? "Saving…" : "Save"}</button>
        <button type="button" className="btn primary" onClick={() => onReview({ closeAfter: true })} disabled={!dirty || saving}>{saving ? "Saving…" : "Save & Close"}</button>
      </footer>
    </aside>
  );
}

function BreakLoad({ entries, employees, day, mode }) {
  const days = mode === "day" ? [Number(day)] : DAY_ORDER;
  const bands = days.flatMap((value) => breakOverlapBands(
    (entries || []).filter((entry) => Number(entry.day_of_week) === Number(value)),
  ).map((band) => ({ ...band, day: value })));
  const peak = bands.reduce((max, band) => Math.max(max, band.count), 0);
  const overlaps = bands.filter((band) => band.count > 1);
  if (!bands.length) return <p className="break-load">No timed breaks {mode === "day" ? "on this day" : "this week"}.</p>;
  return (
    <div className="break-load" aria-label="Employees on break at the same time">
      <strong>Peak {peak} on break</strong>
      <ul>
        {(overlaps.length ? overlaps : bands).slice(0, 8).map((band) => (
          <li key={`${band.day}-${band.start}-${band.end}`} className={band.count > 1 ? "is-hot" : ""}>
            {mode === "day" ? "" : `${SHORT[band.day]} `}{minutesToClock(band.start)}–{minutesToClock(band.end)} · {band.count}
            <span>{band.userIds.map((id) => personName(employees, id)).join(", ")}</span>
          </li>
        ))}
      </ul>
    </div>
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
  saving,
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
  saveError,
  saveConflict,
  onReload,
}) {
  const boardRef = useRef(null);
  const scrollMem = useRef({});
  const scrollKey = useRef(`${lens}:${mode}`);
  const [menu, setMenu] = useState(null);
  const [dropChoice, setDropChoice] = useState(null);
  const [breakOpen, setBreakOpen] = useState(false);
  const [deleteAsk, setDeleteAsk] = useState(null);
  const [breakCopy, setBreakCopy] = useState(null);
  const [copyPeople, setCopyPeople] = useState([]);
  const [copyDays, setCopyDays] = useState([]);
  const [taskCopy, setTaskCopy] = useState(null);
  const [assignTask, setAssignTask] = useState("");
  const [boardNote, setBoardNote] = useState("");
  const [breakPeople, setBreakPeople] = useState([]);
  const [breakDays, setBreakDays] = useState([String(day)]);
  const [breakMode, setBreakMode] = useState("timed");
  const [breakAt, setBreakAt] = useState("12:00");
  const [breakLen, setBreakLen] = useState("30");
  const [replaceBreaks, setReplaceBreaks] = useState(false);
  const [openDays, setOpenDays] = useState(() => new Set());
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
  useEffect(() => { setTip(null); }, [lens]);
  const axis = useMemo(() => timelineAxis(entries), [entries]);
  const days = mode === "day" ? [day] : DAY_ORDER;
  const hourMarks = ticks(axis, mode === "day" ? 60 : 240);
  const guides = guideImage(axis, ticks(axis, mode === "day" ? 60 : 120));
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
    const week = node.querySelector(".week-board");
    scrollMem.current[scrollKey.current] = {
      x: node.scrollLeft,
      y: node.scrollTop,
      weekX: week?.scrollLeft || 0,
      weekY: week?.scrollTop || 0,
    };
  }

  useLayoutEffect(() => {
    const node = boardRef.current;
    const nextKey = `${lens}:${mode}`;
    if (!node || scrollKey.current === nextKey) return;
    const mem = scrollMem.current[nextKey] || { x: 0, y: 0, weekX: 0, weekY: 0 };
    node.scrollLeft = mem.x;
    node.scrollTop = mem.y;
    const week = node.querySelector(".week-board");
    if (week) {
      week.scrollLeft = mem.weekX || 0;
      week.scrollTop = mem.weekY || 0;
    }
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

  function commit(next, label) {
    onCommit(entries.map((entry) => (shiftKey(entry) === shiftKey(next) ? { ...entry, ...next } : entry)), label);
    onSelect(shiftKey(next));
  }

  function placeDetail(event, entry, dayTasks, key) {
    const rect = event.currentTarget.getBoundingClientRect();
    const panel = 248;
    const top = rect.bottom + 8 + panel > window.innerHeight ? Math.max(8, rect.top - panel) : rect.bottom + 8;
    setTip({
      key: key || shiftKey(entry),
      left: Math.max(8, Math.min(rect.left, window.innerWidth - 308)),
      top,
      entry,
      tasks: dayTasks,
    });
  }

  function hover(entry, rect) {
    if (!entry || !rect) {
      setTip(null);
      return;
    }
    setTip({
      key: shiftKey(entry),
      left: Math.max(8, Math.min(rect.left, window.innerWidth - 308)),
      top: Math.min(rect.bottom + 8, window.innerHeight - 16),
      entry,
      tasks: (tasks || []).filter((task) => !task.remove && Number(task.user_id) === Number(entry.user_id) && Number(task.day_of_week) === Number(entry.day_of_week)),
    });
  }

  const head = days.map((value) => (
    <div key={value} className={`dayhead${value === 6 || value === 0 ? " is-end" : ""}${mode === "day" ? " is-on" : ""}`}>
      <strong>{SHORT[value]} {dayStamp(weekStart, value)}</strong>
      <div className="axis">{hourMarks.map((minute, index) => {
        const at = leftOf(minute, axis);
        const shift = index === hourMarks.length - 1 || at > 88 ? "translateX(-100%)" : index === 0 || at < 8 ? "none" : "translateX(-50%)";
        return <b key={minute} style={{ left: `${at}%`, transform: shift }}>{hourLabel(minute, mode !== "day")}</b>;
      })}</div>
    </div>
  ));

  const employeeRows = lens === "timeline" ? rosterEmployees.map((employee) => {
    const open = !scheduledIds.has(Number(employee.user_id));
    const picked = entries.some((entry) => Number(entry.user_id) === Number(employee.user_id) && shiftKey(entry) === selectedKey);
    const byDay = days.map((value) => {
      const shifts = entries.filter((entry) => Number(entry.user_id) === Number(employee.user_id) && Number(entry.day_of_week) === Number(value));
      return pack(shifts.map((entry) => ({ ...shiftRange(entry), entry })).filter((item) => item.start != null));
    });
    const lanes = Math.max(1, ...byDay.map((column) => (column.placed.length ? column.lanes : 1)));
    const bar = mode === "day" ? 32 : 28;
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
                const payload = event.dataTransfer.getData("text/plain");
                if (payload.startsWith("break|")) {
                  const [, key, start, end] = payload.split("|");
                  const source = entries.find((entry) => shiftKey(entry) === key);
                  if (!source) return;
                  const placed = moveBreakTo(entries, source, { start_time: start, end_time: end, timed: true }, Number(employee.user_id), Number(value));
                  if (placed.note) setBoardNote(placed.note);
                  else if (placed.entries !== entries) onCommit(placed.entries, "Moved the break onto the selected shift. Not saved.");
                  return;
                }
                if (payload.startsWith("task|")) {
                  const source = (tasks || []).find((task) => String(task.id) === payload.slice(5));
                  if (!source) return;
                  const placed = moveTaskTo(tasks, source, Number(employee.user_id), Number(value));
                  if (placed.note) setBoardNote(placed.note);
                  else onCommit({ tasks: placed.tasks }, "Moved the timed task. Not saved.");
                  return;
                }
                const moving = entries.find((entry) => shiftKey(entry) === payload);
                if (moving && onMove) onMove(moving, Number(employee.user_id), Number(value));
              }}
            >
              <div className="guides" />
              <div className="track" style={{ height }}>
                {!column.placed.length ? (
                  <button type="button" className="cell-add is-visible" onClick={() => onAdd(Number(employee.user_id), Number(value))}>+ Add</button>
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
                    showGrips={mode === "day" && shiftKey(item.entry) === selectedKey}
                    onSelect={(entry) => onSelect(shiftKey(entry))}
                    onCommit={commit}
                    onHover={hover}
                    onDragShift={() => onSelect(shiftKey(item.entry))}
                    onEdit={onEdit}
                    onMenu={(event, entry) => openMenu(event, entry, Number(entry.user_id), Number(entry.day_of_week))}
                  />
                ))}
                {column.placed.flatMap((item) => visibleBreaks(item.entry).filter((slot) => slot.start_time).map((slot) => {
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
                          const next = resizeBreak(item.entry, index, "start", minutes);
                          if (next === item.entry || !visibleBreaks(next).some((itemSlot) => itemSlot.start_time)) return;
                          commit(next, "Proposed a new break start. Not saved.");
                        })}
                      />
                      <span
                        className="break-label"
                        tabIndex={0}
                        role="button"
                        draggable
                        aria-label={`Move break ${hm(slot.start_time)} to ${hm(slot.end_time)}. Arrow keys move it by 15 minutes. Shift plus an arrow changes the end.`}
                        onDragStart={(event) => {
                          event.stopPropagation();
                          event.dataTransfer.setData("text/plain", `break|${shiftKey(item.entry)}|${hm(slot.start_time)}|${hm(slot.end_time)}`);
                          event.dataTransfer.effectAllowed = "move";
                        }}
                        onPointerDown={(event) => {
                          const index = visibleBreaks(item.entry).findIndex((itemSlot) => itemSlot.start_time === slot.start_time && itemSlot.end_time === slot.end_time);
                          trackPointer(event, axis, (minutes, done) => {
                            if (!done || index < 0) return;
                            const next = slideBreak(item.entry, index, minutes);
                            if (next === item.entry) setBoardNote("The break stays inside the shift.");
                            else commit(next, "Moved a break. Not saved.");
                          });
                        }}
                        onKeyDown={(event) => {
                          if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
                          event.preventDefault();
                          const index = visibleBreaks(item.entry).findIndex((itemSlot) => itemSlot.start_time === slot.start_time && itemSlot.end_time === slot.end_time);
                          if (index < 0) return;
                          const delta = event.key === "ArrowLeft" ? -15 : 15;
                          const next = event.shiftKey
                            ? resizeBreak(item.entry, index, "end", end + delta)
                            : slideBreak(item.entry, index, start + delta);
                          const placed = visibleBreaks(next)[index];
                          const kept = placed?.start_time && slideBreak(next, index, clockMinutes(placed.start_time)) !== next;
                          if (next === item.entry || !kept) setBoardNote("The break stays inside the shift.");
                          else commit(next, event.shiftKey ? "Changed a break end. Not saved." : "Moved a break. Not saved.");
                        }}
                      />
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
                        Untimed
                      </button>
                      <button
                        type="button"
                        aria-label="Remove this break"
                        onClick={() => {
                          const index = visibleBreaks(item.entry).findIndex((itemSlot) => itemSlot.start_time === slot.start_time && itemSlot.end_time === slot.end_time);
                          if (index < 0) return;
                          commit(removeBreak(item.entry, index), "Removed a break. Not saved.");
                        }}
                      >
                        Remove
                      </button>
                    </span>
                  );
                }))}
                {(tasks || []).filter((task) => !task.remove && Number(task.user_id) === Number(employee.user_id) && Number(task.day_of_week) === Number(value) && task.timing_mode === "specific_time" && task.start_time).map((task) => {
                  const start = clockMinutes(task.start_time);
                  let end = clockMinutes(task.end_time || task.start_time);
                  if (start == null || end == null) return null;
                  if (end <= start) end = start + 30;
                  return (
                    <span
                      key={task.id || `${task.role}-${task.start_time}`}
                      className="task-block"
                      draggable
                      tabIndex={0}
                      role="button"
                      aria-label={`${nice(task.role)} at ${hm(task.start_time)}. Arrow keys move the start by 15 minutes.`}
                      style={{ left: `${leftOf(start, axis)}%`, width: `${widthOf(start, end, axis)}%`, top: 4, height: 16 }}
                      title={`${nice(task.role)} ${hm(task.start_time)}`}
                      onDragStart={(event) => {
                        event.stopPropagation();
                        event.dataTransfer.setData("text/plain", `task|${task.id}`);
                        event.dataTransfer.effectAllowed = "move";
                      }}
                      onKeyDown={(event) => {
                        if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
                        event.preventDefault();
                        const locked = ["in_progress", "pending_approval", "approved", "rejected", "completed"].includes(String(task.activity_status || task.status || ""));
                        if (locked || sharedActivity(task)) {
                          setBoardNote(sharedActivity(task) ? "A shared activity stays with its group." : "Completed work stays on the original assignment.");
                          return;
                        }
                        const delta = event.key === "ArrowLeft" ? -15 : 15;
                        const duration = Math.max(15, end - start);
                        onCommit({
                          tasks: (tasks || []).map((item) => (
                            item === task || (task.id && item.id === task.id)
                              ? { ...item, timing_mode: "specific_time", start_time: minutesToClock(start + delta), end_time: minutesToClock(start + delta + duration), changed: !item.draft }
                              : item
                          )),
                        }, "Moved a timed task. Not saved.");
                      }}
                      onPointerDown={(event) => {
                        const locked = ["in_progress", "pending_approval", "approved", "rejected", "completed"].includes(String(task.activity_status || task.status || ""));
                        if (locked) return;
                        const duration = Math.max(15, end - start);
                        trackPointer(event, axis, (minutes, done) => {
                          if (!done) return;
                          onCommit({
                            tasks: (tasks || []).map((item) => (
                              item === task || (task.id && item.id === task.id)
                                ? { ...item, timing_mode: "specific_time", start_time: minutesToClock(minutes), end_time: minutesToClock(minutes + duration), changed: !item.draft }
                                : item
                            )),
                          }, "Moved a timed task. The shared checklist was not changed. Not saved.");
                        });
                      }}
                    >
                    </span>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    );
  }) : null;

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
      {lens === "schedule" || lens === "timeline" ? (
        <div className="shift-actions">
          <button type="button" className="btn" onClick={() => setBreakOpen(true)}>Assign Breaks & Tasks</button>
          <button type="button" className="btn" onClick={() => onAdd(addTarget, day)}>Add shift</button>
          {boardNote ? <p className="ops-warn" role="status">{boardNote}</p> : null}
        </div>
      ) : null}
      {dirty && !showDrawer ? (
        <div className="draft-bar">
          <p className="state dirty"><i />Unsaved changes</p>
          <button type="button" className="btn" onClick={onUndo} disabled={!canUndo}>Undo</button>
          <button type="button" className="btn" onClick={onRedo} disabled={!canRedo}>Redo</button>
          <button type="button" className="btn" onClick={onDiscard}>Discard</button>
          <button type="button" className="btn" onClick={() => onReview({ repeat: true })}>Future weeks</button>
          <button type="button" className="btn primary" onClick={() => onReview()}>Save changes</button>
        </div>
      ) : null}
      {lens === "breaks" || lens === "timeline" ? (
        <BreakLoad entries={entries} employees={employees} day={day} mode={mode} />
      ) : null}
      {lens === "breaks" ? (
        <div className="board-tools">
          <button type="button" className="btn" onClick={() => setBreakOpen(true)}>Assign Breaks & Tasks</button>
          <span className="when">{breaks.unscheduledCount ? `${breaks.unscheduledCount} untimed, not placed on the clock.` : "Timed breaks are on the board."} Peak overlap {overlap}.</span>
        </div>
      ) : null}
      {lens === "breaks" ? (
        <div className="week-board" role="table" aria-label="Breaks for the week">
          <div className="week-head"><span>Employee</span>{days.map((value) => <span key={value}>{SHORT[value]}</span>)}</div>
          {employees.map((employee) => (
            <div className="week-row" key={employee.user_id}>
              <strong>{employee.display_name}</strong>
              {days.map((value) => {
                const shifts = entries.filter((entry) => Number(entry.user_id) === Number(employee.user_id) && Number(entry.day_of_week) === Number(value));
                return (
                  <div key={value}>
                    {shifts.map((entry) => {
                      const slots = visibleBreaks(entry);
                      const label = slots.length
                        ? slots.map((slot) => (slot.start_time ? `${hm(slot.start_time)}–${hm(slot.end_time)}` : `${slot.minutes} min untimed`)).join(", ")
                        : "No break";
                      return (
                        <button key={shiftKey(entry)} type="button" className={`week-chip${slots.some((slot) => !slot.start_time) ? " is-open" : ""}`} onClick={() => onEdit?.(entry)}>
                          {label}
                        </button>
                      );
                    })}
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      ) : null}
      <div className="workspace">
        <div className="board" ref={boardRef} onScroll={rememberScroll}>
          {lens === "timeline" ? (
            <div className="sheet" style={{ "--cols": days.length, "--name": "168px" }}>
              <p className="when">Colored bars are shifts. Amber bars are timed breaks. Blue bars are tasks. Peak overlap {overlap}.</p>
              <div className="head"><div className="who">Employee</div>{head}</div>
              {employeeRows}
            </div>
          ) : null}
          {lens === "schedule" ? (
            <div className="sheet roles-sheet">
              <div className="week-board" role="table" aria-label="Week schedule" onScroll={rememberScroll}>
                <div className="week-head">
                  <span>
                    Employee
                    <button type="button" className="day-toggle" onClick={() => setOpenDays(openDays.size ? new Set() : new Set(DAY_ORDER))}>{openDays.size ? "Collapse days" : "Expand days"}</button>
                  </span>
                  {days.map((value) => {
                    const summary = dayScheduleSummary(entries, value);
                    const open = openDays.has(value);
                    const counted = [...new Set([...DAY_ROLES, ...Object.keys(summary.roleCounts || {})])].filter((role) => role !== "unsplit" && (summary.roleCounts?.[role] || summary.roles[role]));
                    const roleHours = counted.map((role) => {
                      const count = summary.roleCounts?.[role] || 0;
                      const hours = summary.roles[role];
                      const people = `${count} ${count === 1 ? "employee" : "employees"}`;
                      return hours ? `${nice(role)} — ${people} | ${hours.toFixed(1)} hours` : `${nice(role)} — ${people} | not split`;
                    });
                    const shorts = (requirements || []).length
                      ? DAY_ROLES.flatMap((role) => {
                        const missing = staffingHours(entries, requirements, role, value).filter((row) => row.status === "short").length;
                        return missing ? [`${nice(role)} short ${missing}h`] : [];
                      })
                      : [];
                    return (
                      <span key={value}>
                        <button type="button" className="day-toggle" aria-expanded={open} onClick={() => setOpenDays((current) => {
                          const next = new Set(current);
                          if (next.has(value)) next.delete(value);
                          else next.add(value);
                          return next;
                        })}>{SHORT[value]} {dayStamp(weekStart, value)}</button>
                        {open ? (
                          <small className="day-stats">
                            {summary.people ? `${summary.people} scheduled` : "No one scheduled"}
                            {summary.people ? <span>{Number(summary.scheduled?.total || 0).toFixed(1)}h total</span> : null}
                            {summary.people ? <span>{Number(summary.scheduled?.net || 0).toFixed(1)}h net</span> : null}
                            {roleHours.map((line) => <span key={line}>{line}</span>)}
                            {summary.roles.unsplit ? <span>Not split {summary.roles.unsplit.toFixed(1)}h</span> : null}
                            {shorts.map((line) => <span key={line}>{line}</span>)}
                          </small>
                        ) : null}
                      </span>
                    );
                  })}
                </div>
                {employees.map((employee) => {
                  const weekShifts = entries.filter((entry) => Number(entry.user_id) === Number(employee.user_id));
                  const weekBooked = staffingFigures(weekShifts);
                  const weekNet = weekBooked.net;
                  const weekGross = weekBooked.total;
                  return (
                  <div className="week-row" key={employee.user_id}>
                    <strong>{employee.display_name}<small>{weekShifts.length ? `${weekNet.toFixed(1)}h net · ${weekGross.toFixed(1)}h total` : "Not scheduled"}</small></strong>
                    {days.map((value) => {
                      const shifts = weekShifts.filter((entry) => Number(entry.day_of_week) === Number(value));
                      const dayTasks = (tasks || []).filter((task) => !task.remove && Number(task.user_id) === Number(employee.user_id) && Number(task.day_of_week) === Number(value));
                      return (
                        <div
                          key={value}
                          onDragOver={(event) => event.preventDefault()}
                          onDrop={(event) => {
                            const key = event.dataTransfer.getData("text/plain");
                            const moving = entries.find((entry) => shiftKey(entry) === key);
                            if (!moving) return;
                            if (Number(moving.user_id) === Number(employee.user_id) && Number(moving.day_of_week) === Number(value)) return;
                            setDropChoice({ entry: moving, userId: Number(employee.user_id), day: Number(value) });
                          }}
                        >
                          {shifts.map((entry) => {
                            const hours = staffingFigures(entry);
                            const slots = visibleBreaks(entry);
                            const earliest = [...shifts].sort((a, b) => String(a.start_time).localeCompare(String(b.start_time)))[0];
                            const showTasks = shiftKey(earliest) === shiftKey(entry);
                            const rows = scheduleCardRows(entry);
                            return (
                              <div className="card-stack" key={shiftKey(entry)}>
                              <button
                                type="button"
                                draggable
                                className={`shift-card${peers.some((item) => shiftKey(item) === shiftKey(entry)) ? " is-open" : ""}`}
                                aria-describedby={tip?.key === shiftKey(entry) ? "schedule-card-detail" : undefined}
                                onMouseEnter={(event) => placeDetail(event, entry, showTasks ? dayTasks : [])}
                                onMouseLeave={() => setTip(null)}
                                onFocus={(event) => placeDetail(event, entry, showTasks ? dayTasks : [])}
                                onBlur={() => setTip(null)}
                                onKeyDown={(event) => { if (event.key === "Escape") setTip(null); }}
                                onDragStart={(event) => {
                                  event.dataTransfer.setData("text/plain", shiftKey(entry));
                                  event.dataTransfer.effectAllowed = "copyMove";
                                }}
                                onClick={() => onEdit?.(entry)}
                                onDoubleClick={() => onEdit?.(entry)}
                                onContextMenu={(event) => openMenu(event, entry, Number(entry.user_id), Number(entry.day_of_week))}
                              >
                                {rows.map((row, index) => (
                                  <span key={`${row.role}-${row.start_time}-${index}`} className={`card-line${row.unsplit ? " is-unsplit" : ""}`}>
                                    <i style={{ background: row.role ? roleColor(row.role) : "#cbd5e1" }} />
                                    <span className="card-name">{row.role ? scheduleRoleMark(row.role) : "—"}</span>
                                    <span className="card-time">{row.start_time ? `${hm(row.start_time)}–${hm(row.end_time)}` : "Not split"}</span>
                                  </span>
                                ))}
                                {slots.map((slot, index) => (
                                  <span key={`break-${index}`} className={`card-line is-break${slot.start_time ? "" : " is-unsplit"}`}>
                                    <i />
                                    <span className="card-name" title={slot.start_time ? "Timed break" : "Untimed break"}>Break</span>
                                    <span className="card-time">{slot.start_time ? `${hm(slot.start_time)}–${hm(slot.end_time)}` : `${slot.minutes}m${hours.review ? " · review" : ""}`}</span>
                                  </span>
                                ))}
                                {hours.unallocated > 0 ? (
                                  <span className="card-line is-unsplit">
                                    <i />
                                    <span className="card-name">Unallocated</span>
                                    <span className="card-time">{hours.unallocated.toFixed(1)}h</span>
                                  </span>
                                ) : null}
                                {showTasks ? dayTasks.map((task) => {
                                  const scheduled = task.timing_mode === "specific_time" && task.start_time;
                                  const taskName = nice(task.role);
                                  return (
                                    <span key={task.id || task.role} className={`card-line is-task${scheduled ? "" : " is-unsplit"}`}>
                                      <i />
                                      <span className="card-name">{taskName}</span>
                                      <span className="card-time">{scheduled ? `${hm(task.start_time)}${task.end_time ? `–${hm(task.end_time)}` : ""}` : "Anytime"}</span>
                                    </span>
                                  );
                                }) : null}
                              </button>
                              <button type="button" className="card-menu" aria-label={`Actions for ${employee.display_name} on ${SHORT[value]}`} onClick={(event) => openMenu(event, entry, Number(entry.user_id), Number(entry.day_of_week))}>Actions</button>
                              </div>
                            );
                          })}
                          {!shifts.length ? (
                            <button type="button" className="week-add" onClick={() => onAdd(Number(employee.user_id), Number(value))}>+ Add</button>
                          ) : null}
                          {!shifts.length && dayTasks.length ? (
                            <button
                              type="button"
                              className="shift-card"
                              aria-describedby={tip?.key === `task-${employee.user_id}-${value}` ? "schedule-card-detail" : undefined}
                              onMouseEnter={(event) => placeDetail(event, { user_id: employee.user_id, day_of_week: value }, dayTasks, `task-${employee.user_id}-${value}`)}
                              onMouseLeave={() => setTip(null)}
                              onFocus={(event) => placeDetail(event, { user_id: employee.user_id, day_of_week: value }, dayTasks, `task-${employee.user_id}-${value}`)}
                              onBlur={() => setTip(null)}
                              onClick={() => onAdd(Number(employee.user_id), Number(value))}
                            >
                              {dayTasks.map((task) => (
                                <span key={task.id || task.role} className="card-line is-task">
                                  <i />
                                  <span className="card-name">{nice(task.role)}</span>
                                  <span className="card-time">{task.timing_mode === "specific_time" && task.start_time ? hm(task.start_time) : "Anytime"}</span>
                                </span>
                              ))}
                            </button>
                          ) : null}
                        </div>
                      );
                    })}
                  </div>
                  );
                })}
              </div>
            </div>
          ) : null}
          {lens === "coverage" ? (
            <div className="sheet roles-sheet">
              <CoverageBoard
                entries={entries}
                requirements={requirements}
                employees={employees}
                day={day}
                days={mode === "day" ? [day] : DAY_ORDER}
                onOpenShift={(entry) => onEdit?.(entry)}
              />
              {requirements?.length ? <button type="button" className="staff-review" onClick={() => onReviewBundle("requirements")}>Review staffing</button> : null}
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
            saving={saving}
            canUndo={canUndo}
            canRedo={canRedo}
            conflict={peers.length > 0}
            missingRole={!selected.role && !storedSegments(selected).length}
            badBreak={breakOutside(selected)}
            saveError={saveError}
            saveConflict={saveConflict}
            onReload={onReload}
            onCopyBreaks={(entry) => {
              setBreakCopy(entry);
              setCopyPeople([String(entry.user_id)]);
              setCopyDays([String(entry.day_of_week)]);
            }}
            onCopyTask={(task) => {
              setTaskCopy(task);
              setCopyPeople([String(task.user_id)]);
              setCopyDays([String(task.day_of_week)]);
            }}
            onDelete={(entry) => setDeleteAsk(entry)}
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
            onTasks={(next) => onCommit({ tasks: next }, "Updated the task draft. Not saved.")}
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
          {menu.entry ? <button type="button" role="menuitem" className="danger" onClick={() => { setDeleteAsk(menu.entry); setMenu(null); }}>Delete shift</button> : null}
        </div>
      ) : null}
      {deleteAsk ? (
        <div className="ops-dialog-back">
          <div className="ops-dialog" role="dialog" aria-label="Delete shift">
            <h2>Delete this shift?</h2>
            <p>{personName(employees, deleteAsk.user_id)} · {SHORT[deleteAsk.day_of_week]} · {hm(deleteAsk.start_time)}–{hm(deleteAsk.end_time)}. This removes the shift from the draft. Tasks on this day stay, including completed work.</p>
            <div className="footer-row">
              <button type="button" className="btn" onClick={() => setDeleteAsk(null)}>Cancel</button>
              <button type="button" className="btn danger" onClick={() => { onRemove(deleteAsk); setDeleteAsk(null); }}>Delete shift</button>
            </div>
          </div>
        </div>
      ) : null}
      {taskCopy ? (
        <div className="ops-dialog-back">
          <form className="ops-dialog" onSubmit={(event) => {
            event.preventDefault();
            const result = copyTaskAssignments(tasks, taskCopy, copyPeople.map(Number), copyDays.map(Number));
            if (result.refused) {
              setBoardNote(result.refused);
              return;
            }
            onCommit({ tasks: result.tasks }, "Copied the individual task. Anytime stays Anytime. Completed work was not copied. Not saved.");
            setTaskCopy(null);
          }}>
            <h2>Copy task</h2>
            <p>{nice(taskCopy.role)} stays {taskCopy.timing_mode === "specific_time" && taskCopy.start_time ? "at its planned time" : "Anytime"}. This copies an individual assignment only.</p>
            <div className="pick-row" role="group" aria-label="Employees for the task copy">
              {employees.map((employee) => (
                <label key={employee.user_id}>
                  <input type="checkbox" checked={copyPeople.includes(String(employee.user_id))} onChange={() => setCopyPeople((current) => current.includes(String(employee.user_id)) ? current.filter((item) => item !== String(employee.user_id)) : [...current, String(employee.user_id)])} />
                  {employee.display_name}
                </label>
              ))}
            </div>
            <div className="pick-row">
              {DAY_ORDER.map((value) => (
                <label key={value}><input type="checkbox" checked={copyDays.includes(String(value))} onChange={() => setCopyDays((current) => current.includes(String(value)) ? current.filter((item) => item !== String(value)) : [...current, String(value)])} />{SHORT[value]}</label>
              ))}
            </div>
            <div className="footer-row">
              <button type="button" className="btn" onClick={() => setTaskCopy(null)}>Cancel</button>
              <button type="submit" className="btn primary">Copy task</button>
            </div>
          </form>
        </div>
      ) : null}
      {breakCopy ? (
        <div className="ops-dialog-back">
          <form className="ops-dialog" onSubmit={(event) => {
            event.preventDefault();
            const result = copyBreaksOnto(entries, breakCopy, copyPeople.map(Number), copyDays.map(Number));
            const copied = result.notes.filter((note) => note.reason === "Copied.").length;
            const skipped = result.notes.filter((note) => note.reason !== "Copied.");
            if (copied) onCommit(result.entries, copied === 1 ? "Copied a break onto 1 shift. Not saved." : `Copied a break onto ${copied} shifts. Not saved.`);
            if (skipped.length) {
              setBoardNote(skipped.map((note) => `${personName(employees, note.userId)} ${SHORT[note.day] || ""}: ${note.reason}`).join(" "));
              if (!copied) return;
            }
            setBreakCopy(null);
          }}>
            <h2>Copy breaks</h2>
            <p>Choose employees and days. A day without a shift, or a break that does not fit, is left unchanged.</p>
            <div className="pick-row" role="group" aria-label="Employees">
              {employees.map((employee) => (
                <label key={employee.user_id}>
                  <input type="checkbox" checked={copyPeople.includes(String(employee.user_id))} onChange={() => setCopyPeople((current) => current.includes(String(employee.user_id)) ? current.filter((item) => item !== String(employee.user_id)) : [...current, String(employee.user_id)])} />
                  {employee.display_name}
                </label>
              ))}
            </div>
            <div className="pick-row">
              {DAY_ORDER.map((value) => (
                <label key={value}><input type="checkbox" checked={copyDays.includes(String(value))} onChange={() => setCopyDays((current) => current.includes(String(value)) ? current.filter((item) => item !== String(value)) : [...current, String(value)])} />{SHORT[value]}</label>
              ))}
            </div>
            <ul className="break-preview">
              {copyBreaksOnto(entries, breakCopy, copyPeople.map(Number), copyDays.map(Number)).notes.map((note, index) => (
                <li key={`${note.userId}-${note.day}-${index}`}>{personName(employees, note.userId)} · {SHORT[note.day] || "Day"} · {note.reason}</li>
              ))}
            </ul>
            <div className="footer-row">
              <button type="button" className="btn" onClick={() => setBreakCopy(null)}>Cancel</button>
              <button type="submit" className="btn primary">Copy breaks</button>
            </div>
          </form>
        </div>
      ) : null}
      {dropChoice ? (
        <div className="ops-dialog-back">
          <div className="ops-dialog" role="dialog" aria-label="Move or copy shift">
            <h2>{nice(dropChoice.entry.role)} · {hm(dropChoice.entry.start_time)}–{hm(dropChoice.entry.end_time)}</h2>
            <p>Place this shift on {personName(employees, dropChoice.userId)} · {SHORT[dropChoice.day]}. Copy does not bring completed task history.</p>
            <div className="footer-row">
              <button type="button" className="btn" onClick={() => setDropChoice(null)}>Cancel</button>
              <button type="button" className="btn" onClick={() => {
                onCommit([...entries, copiedShift(dropChoice.entry, { userId: dropChoice.userId, dayOfWeek: dropChoice.day })], "Copied the shift. Not saved.");
                setDropChoice(null);
              }}>Copy</button>
              <button type="button" className="btn primary" onClick={() => { onMove?.(dropChoice.entry, dropChoice.userId, dropChoice.day); setDropChoice(null); }}>Move</button>
            </div>
          </div>
        </div>
      ) : null}
      {breakOpen ? (
        <div className="ops-dialog-back">
          <form className="ops-dialog" onSubmit={(event) => {
            event.preventDefault();
            const minutes = Number(breakLen);
            if (!breakPeople.length || !breakDays.length) return;
            if (!minutes && !assignTask) return;
            const next = minutes ? entries.map((entry) => {
              if (!breakPeople.includes(String(entry.user_id)) || !breakDays.includes(String(entry.day_of_week))) return entry;
              return proposeBreak(entry, { mode: breakMode, minutes, start: breakAt, replace: replaceBreaks }).entry;
            }) : entries;
            const stamp = Date.now();
            const additions = assignTask ? breakPeople.flatMap((userId) => breakDays.map((value) => ({
              id: `draft-task-${stamp}-${userId}-${value}`,
              draft: true,
              user_id: Number(userId),
              day_of_week: Number(value),
              role: assignTask,
              timing_mode: "anytime",
              start_time: null,
              end_time: null,
              execution_mode: "individual",
              assignment_group_id: null,
              status: "assigned",
            }))) : [];
            onCommit(
              { entries: next, ...(additions.length ? { tasks: [...(tasks || []), ...additions] } : {}) },
              "Updated the draft. A new task stays Anytime until you set a time. Nothing is saved.",
            );
            setBreakOpen(false);
            setAssignTask("");
          }}>
            <h2>Assign Breaks & Tasks</h2>
            <p>Breaks are added to existing shifts. A task added here stays Anytime until you set a time on the shift. Nothing is saved until you save the schedule.</p>
            <div className="pick-row" role="group" aria-label="Employees for breaks">
              {employees.map((employee) => (
                <label key={employee.user_id}>
                  <input type="checkbox" checked={breakPeople.includes(String(employee.user_id))} onChange={() => setBreakPeople((current) => current.includes(String(employee.user_id)) ? current.filter((item) => item !== String(employee.user_id)) : [...current, String(employee.user_id)])} />
                  {employee.display_name}
                </label>
              ))}
            </div>
            <div className="pick-row">
              {DAY_ORDER.map((value) => (
                <label key={value}><input type="checkbox" checked={breakDays.includes(String(value))} onChange={() => setBreakDays((current) => current.includes(String(value)) ? current.filter((item) => item !== String(value)) : [...current, String(value)])} />{SHORT[value]}</label>
              ))}
            </div>
            <div className="pick-row">
              <label><input type="radio" name="break-mode" checked={breakMode === "timed"} onChange={() => setBreakMode("timed")} /> Timed</label>
              <label><input type="radio" name="break-mode" checked={breakMode === "untimed"} onChange={() => setBreakMode("untimed")} /> Untimed</label>
            </div>
            {breakMode === "timed" ? <label>Starts <input aria-label="Break start" type="time" step="900" value={breakAt} onChange={(event) => setBreakAt(event.target.value)} /></label> : null}
            <label>Minutes <input aria-label="Break length" type="number" min="5" step="5" value={breakLen} onChange={(event) => setBreakLen(event.target.value)} /></label>
            <label><input type="checkbox" checked={replaceBreaks} onChange={(event) => setReplaceBreaks(event.target.checked)} /> Replace a break that is already on the shift</label>
            <label>Task
              <select aria-label="Task to assign" value={assignTask} onChange={(event) => setAssignTask(event.target.value)}>
                <option value="">No task</option>
                {(catalog && catalog.length ? catalog : scheduleRoleCatalog()).filter((item) => item.uses_time_slots === false && item.active !== false).map((item) => (
                  <option key={item.code} value={item.code}>{String(item.code).startsWith("agroup_") ? "Activity · " : ""}{item.name || scheduleRoleLabel(item.code)}</option>
                ))}
              </select>
            </label>
            {assignTask ? <p className="quiet">{String(assignTask).startsWith("agroup_") ? "This adds a new individual assignment. It does not join or copy a shared checklist." : "A task added here stays Anytime until you set a time on the shift."}</p> : null}
            <ul className="break-preview">
              {entries.filter((entry) => breakPeople.includes(String(entry.user_id)) && breakDays.includes(String(entry.day_of_week))).map((entry) => {
                const proposal = proposeBreak(entry, { mode: breakMode, minutes: Number(breakLen), start: breakAt, replace: replaceBreaks });
                const before = staffingFigures(entry);
                const after = staffingFigures(proposal.entry);
                return (
                  <li key={shiftKey(entry)}>
                    {personName(employees, entry.user_id)} · {SHORT[entry.day_of_week]}
                    {proposal.skipped
                      ? " · existing break left in place"
                      : ` · net ${before.net.toFixed(1)}h to ${after.net.toFixed(1)}h`}
                  </li>
                );
              })}
            </ul>
            {!entries.some((entry) => breakPeople.includes(String(entry.user_id)) && breakDays.includes(String(entry.day_of_week))) ? <p className="quiet">No shift matches the employees and days.</p> : null}
            <div className="footer-row">
              <button type="button" className="btn" onClick={() => setBreakOpen(false)}>Cancel</button>
              <button type="submit" className="btn primary">Apply to draft</button>
            </div>
          </form>
        </div>
      ) : null}
      {tip?.entry && !showDrawer ? (
        <div id="schedule-card-detail" role="tooltip" className="detail-pop" style={{ left: tip.left, top: tip.top }}>
          <b>{personName(employees, tip.entry.user_id)}</b>
          <span>{SHORT[tip.entry.day_of_week]} {tip.entry.start_time ? `${hm(tip.entry.start_time)}–${hm(tip.entry.end_time)}` : "No shift"}</span>
          <ul>
            {scheduleCardRows(tip.entry).filter((row) => row.role || row.start_time).map((row, index) => (
              <li key={`${row.role}-${index}`}>{row.role ? nice(row.role) : "No role"}{row.start_time ? ` ${hm(row.start_time)}–${hm(row.end_time)}` : " · Not split"}</li>
            ))}
            {visibleBreaks(tip.entry).map((slot, index) => (
              <li key={`break-${index}`}>{slot.start_time ? `Timed break ${hm(slot.start_time)}–${hm(slot.end_time)}` : `Untimed break ${slot.minutes}m`}</li>
            ))}
            {(tip.tasks || []).map((task) => <li key={task.id || task.role}>{nice(task.role)}{task.assignment_group_id ? " · shared activity" : ""}</li>)}
          </ul>
          {tip.entry.start_time ? (
            <span>
              Role {staffingFigures(tip.entry).role.toFixed(1)}h · Unallocated {staffingFigures(tip.entry).unallocated.toFixed(1)}h · Total {staffingFigures(tip.entry).total.toFixed(1)}h · Net {staffingFigures(tip.entry).net.toFixed(1)}h
              {staffingFigures(tip.entry).review ? " · review duplicate breaks" : ""}
            </span>
          ) : <span>This task is not attached to a shift.</span>}
        </div>
      ) : null}
      {planner?.legacy_template ? null : null}
    </div>
  );
}
