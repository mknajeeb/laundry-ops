import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import axios from "axios";
import { getWashproApiBase } from "../api";
import "./operationsPlanner.css";
import "./plannerSurface.css";
import {
  BREAK_OVERLAP_CAP,
  DAY_NAMES,
  DAY_ORDER,
  autoScrollDelta,
  breakAccounting,
  clockMinutes,
  entriesForPeriod,
  hourCoverage,
  minutesToClock,
  movedShift,
  overlappingBreakCount,
  periodLabel,
  pointerToMinutes,
  roleCoverage,
  shiftHours,
  taskRollup,
} from "./plannerModel";
import { printDocumentHtml, scheduleCardSvg, scheduleCsv, schedulePdf } from "./scheduleExport";
import PlannerWorkspace from "./PlannerWorkspace";
import { asList, draftOperations, relocateShift, shiftKey, splitHalves, storedRoleSegments } from "./plannerGeometry";
import { copyDay, copyEmployeeDay, copyEmployeeWeek, copyWeekShifts, copiedShift } from "./plannerCopy";
import { laborComparison } from "./plannerLabor";
import { patternCells, reviewLines, scopeDecision, staffingChanges, taskChanges } from "./plannerReview";
import { recordDraft, redoDraftHistory, undoDraftHistory } from "./draftHistory";

const LENSES = [
  ["employees", "Employees"],
  ["roles", "Roles"],
  ["breaks", "Breaks"],
  ["tasks", "Tasks"],
];

function api(path, config = {}) {
  return axios({ baseURL: getWashproApiBase(), url: path, ...config });
}

function easternMonday(now = new Date()) {
  const parts = Object.fromEntries(new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    weekday: "short",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(now).map((part) => [part.type, part.value]));
  const weekday = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 }[parts.weekday];
  const offset = weekday === 0 ? -6 : 1 - weekday;
  return new Date(Date.UTC(Number(parts.year), Number(parts.month) - 1, Number(parts.day) + offset)).toISOString().slice(0, 10);
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
    id: entry.id,
    user_id: Number(entry.user_id),
    day_of_week: Number(entry.day_of_week),
    start_time: String(entry.start_time || "").slice(0, 5),
    end_time: String(entry.end_time || "").slice(0, 5),
    role: entry.role || "",
    break_minutes: Number(entry.break_minutes || 0),
    break_slots: asList(entry.break_slots),
    role_assignments: storedRoleSegments(entry),
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
  const [laterChoice, setLaterChoice] = useState(null);
  const [drag, setDrag] = useState(null);
  const [dragPreview, setDragPreview] = useState("");
  const [pickedEmployees, setPickedEmployees] = useState([]);
  const [draftBundle, setDraftBundle] = useState(null);
  const [history, setHistory] = useState([]);
  const [future, setFuture] = useState([]);
  const [selectedKey, setSelectedKey] = useState("");
  const [editorOpen, setEditorOpen] = useState(false);
  const [leavePrompt, setLeavePrompt] = useState("");
  const [pinOpen, setPinOpen] = useState(false);
  const [clipboard, setClipboard] = useState(null);
  const [lifecycle, setLifecycle] = useState(null);
  const [copyJob, setCopyJob] = useState(null);
  const weekCopyRef = useRef(null);
  const commandRef = useRef(null);

  const load = useCallback(async (weekStart) => {
    const previewMode = new URLSearchParams(window.location.search).get("preview");
    if (import.meta.env.DEV && (previewMode === "1" || previewMode === "veewash")) {
      setFlags({ manager_pilot: true, employee_pilot: false, paystub_access: false });
      if (previewMode === "veewash") {
        const snapshot = await import("./fixtures/veewash-2027-01-04.json");
        setPayload(snapshot.default);
        if (!weekStart) setWeek("2027-01-04");
      } else {
        setPayload(previewPayload());
        if (!weekStart) setWeek("2026-11-09");
      }
      return;
    }
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
    load(week).catch((err) => {
      const data = err.response?.data;
      if (data?.code === "migration_required") {
        setError(`The planner migration has not been applied (${(data.missing || []).join(", ")}). Apply backend/sql/operations_planner_v2.sql. This page does not create tables.`);
        return;
      }
      setError(data?.error || err.message);
    });
  }, [load, week]);

  useEffect(() => {
    const root = document.documentElement;
    if (full) root.setAttribute("data-ops-planner-fullscreen", "1");
    else root.removeAttribute("data-ops-planner-fullscreen");
    return () => root.removeAttribute("data-ops-planner-fullscreen");
  }, [full]);

  useEffect(() => {
    function onKey(event) {
      const cmd = commandRef.current;
      if (!cmd || cmd.blocked) return;
      const tag = String(event.target?.tagName || "");
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || event.target?.isContentEditable) return;
      const meta = event.metaKey || event.ctrlKey;
      const key = event.key.toLowerCase();
      const chosen = cmd.entries.find((entry) => shiftKey(entry) === cmd.selectedKey);
      if (meta && key === "z" && !event.shiftKey) {
        event.preventDefault();
        cmd.undoDraft();
      } else if (meta && (key === "y" || (key === "z" && event.shiftKey))) {
        event.preventDefault();
        cmd.redoDraft();
      } else if (meta && key === "c" && chosen) {
        event.preventDefault();
        cmd.copyShift(chosen);
      } else if (meta && key === "v" && cmd.clipboard) {
        event.preventDefault();
        cmd.pasteShift(
          chosen ? Number(chosen.user_id) : cmd.employees[0]?.user_id,
          chosen ? Number(chosen.day_of_week) : cmd.day,
        );
      } else if ((event.key === "Delete" || event.key === "Backspace") && chosen) {
        event.preventDefault();
        cmd.removeShift(chosen);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const employees = payload?.employees || [];
  const loadedEntries = useMemo(() => (payload?.entries || []).map(entryShift), [payload]);
  const loadedRequirements = payload?.planner?.staffing_requirements || [];
  const loadedTasks = payload?.daily_responsibilities || [];
  const entries = draftBundle ? draftBundle.entries : loadedEntries;
  const requirements = draftBundle ? draftBundle.requirements : loadedRequirements;
  const responsibilities = draftBundle ? draftBundle.tasks : loadedTasks;
  useEffect(() => {
    const pendingCopy = weekCopyRef.current;
    if (pendingCopy?.applied && payload?.planner?.week_monday === pendingCopy.target) return;
    setDraftBundle(null);
    setHistory([]);
    setFuture([]);
    setSelectedKey("");
    setEditorOpen(false);
    if (!pendingCopy || pendingCopy.applied || payload?.planner?.week_monday !== pendingCopy.target) return;
    pendingCopy.applied = true;
    const base = (payload.entries || []).map(entryShift);
    const clones = copyWeekShifts(pendingCopy.entries);
    const requirements = payload.planner?.staffing_requirements || [];
    const tasks = payload.daily_responsibilities || [];
    setHistory([null]);
    setDraftBundle({ entries: [...base, ...clones], requirements, tasks });
    setNotice(`Copied ${clones.length} shifts onto the week of ${pendingCopy.target}. Completed tasks were not copied. Review save before anything is written.`);
  }, [payload]);
  const visibleEntries = entriesForPeriod(entries, { mode, day });
  const planner = payload?.planner || {};
  const period = periodLabel(mode, payload?.week_label || week, DAY_NAMES[day]);

  function rowsFor(list) {
    return list.map((entry) => {
      const person = employees.find((employee) => Number(employee.user_id) === Number(entry.user_id));
      const slot = (entry.break_slots || []).map((item) => `${item.start_time}–${item.end_time}${item.timed === false ? " untimed" : ""}`).join("; ");
      const breaks = slot || (Number(entry.break_minutes) > 0 ? `${entry.break_minutes} min, no clock time` : "");
      return {
        employee: person?.display_name || `Employee ${entry.user_id}`,
        day: DAY_NAMES[entry.day_of_week],
        start: entry.start_time,
        end: entry.end_time,
        role: entry.role,
        breaks,
        tasks: "",
        when: `${DAY_NAMES[entry.day_of_week]} ${entry.start_time}–${entry.end_time}`,
        detail: `${entry.role} ${breaks}`.trim(),
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
    setLaterChoice(null);
    setStopTemplate(false);
    setPending({ command });
    setError("");
  }

  function currentBundle() {
    return { entries, requirements, tasks: responsibilities };
  }

  function applyHistory(step, label) {
    setHistory(step.history);
    setFuture(step.future);
    setDraftBundle(step.draft);
    if (label) setNotice(label);
    setError("");
  }

  function applyDraft(next, label) {
    const patch = Array.isArray(next) ? { entries: next } : next;
    const current = currentBundle();
    applyHistory(
      recordDraft(history, future, draftBundle ? current : null, { ...current, ...patch }),
      label || "Draft updated. Nothing is saved.",
    );
  }

  function undoDraft() {
    if (!history.length) return;
    applyHistory(undoDraftHistory(history, future, draftBundle), "Undid the last draft change.");
  }

  function redoDraft() {
    if (!future.length) return;
    applyHistory(redoDraftHistory(history, future, draftBundle), "Redid the draft change.");
  }

  function discardDraft() {
    setDraftBundle(null);
    setHistory([]);
    setFuture([]);
    setPending(null);
    setSelectedKey("");
    setEditorOpen(false);
    setNotice("");
  }

  function requestWeek(next) {
    if (snapshot) return;
    if (!next || next === (week || planner.week_monday || "")) return;
    if (draftBundle) {
      setLeavePrompt(next);
      return;
    }
    setWeek(next);
  }

  function openEditor(entry) {
    if (!entry) return;
    setSelectedKey(shiftKey(entry));
    setDay(Number(entry.day_of_week));
    setEditorOpen(true);
  }

  function reviewBundle(kind) {
    if (kind === "requirements") {
      queueChange({ action: "save_staffing_requirements", requirements });
      return;
    }
    queueChange({
      action: "assign_tasks",
      tasks: responsibilities.filter((task) => task.draft || task.remove),
    });
  }

  function reviewDraft() {
    const operations = draftOperations(loadedEntries, entries);
    const tasks = taskChanges(loadedTasks, responsibilities);
    const staffing = staffingChanges(loadedRequirements, requirements);
    if (!operations.length && !tasks.length && !staffing.length) {
      setError("Nothing in this draft is different from the saved week.");
      return;
    }
    const decision = scopeDecision(loadedEntries, entries);
    queueChange({
      action: "apply_shift_set",
      operations,
      scopeMode: decision.recurring ? "choice" : "this_week_only",
      scopeReason: decision.reason,
      cells: patternCells(loadedEntries, entries),
      lines: reviewLines(loadedEntries, entries, employees),
      taskLines: tasks,
      staffingLines: staffing,
      hoursBefore: laborComparison(loadedEntries, employees),
      hoursAfter: laborComparison(entries, employees),
    });
  }

  function moveDraft(entry, userId, dayOfWeek) {
    const next = { ...relocateShift(entry, entry.start_time, Number(dayOfWeek)), user_id: Number(userId) };
    applyDraft(entries.map((item) => (shiftKey(item) === shiftKey(entry) ? next : item)), "Moved the shift in the draft. Not saved.");
    setSelectedKey(shiftKey(next));
  }

  function runCopy(job) {
    if (!job) return;
    if (job.kind === "shift") {
      const id = `draft-${Date.now()}`;
      applyDraft([...entries, copiedShift(job.entry, { userId: job.userId, dayOfWeek: job.toDay ?? job.day, id })], "Copied the shift into the draft. Not saved.");
      setSelectedKey(id);
    } else if (job.kind === "employee-day") {
      applyDraft(copyEmployeeDay(entries, job.userId, job.fromDay, job.toDay), "Copied that employee's day. Not saved.");
    } else if (job.kind === "employee-week") {
      applyDraft(copyEmployeeWeek(entries, job.userId, job.toUser), "Copied that employee's week onto another employee. Tasks were not copied. Not saved.");
    } else if (job.kind === "day") {
      applyDraft(copyDay(entries, job.fromDay, job.toDay), "Copied the day. Tasks were not copied. Not saved.");
    } else if (job.kind === "week") {
      weekCopyRef.current = { entries, target: job.target };
      setWeek(job.target);
    }
    setCopyJob(null);
  }

  function addShift(userId, dayOfWeek) {
    const id = `draft-${Date.now()}`;
    const chosen = Number(userId) || employees[0]?.user_id;
    const chosenDay = Number.isFinite(Number(dayOfWeek)) ? Number(dayOfWeek) : day;
    if (!chosen) return;
    applyDraft([...entries, {
      id,
      user_id: chosen,
      day_of_week: chosenDay,
      start_time: "08:00",
      end_time: "16:00",
      role: "",
      break_minutes: 0,
      break_slots: [],
      role_assignments: [],
    }], "Added a draft shift. Not saved.");
    setSelectedKey(String(id));
    setDay(chosenDay);
    setMode("day");
  }

  function copyShift(entry) {
    if (!entry) return;
    setClipboard({ ...entry });
    setNotice(`Copied ${entry.role || "shift"} ${String(entry.start_time).slice(0, 5)}–${String(entry.end_time).slice(0, 5)}. Paste places a new draft shift. Copy image is a picture of the schedule, not this shift.`);
  }

  function pasteShift(userId, dayOfWeek) {
    if (!clipboard) return;
    const id = `draft-${Date.now()}`;
    applyDraft([...entries, {
      ...clipboard,
      id,
      user_id: Number(userId) || clipboard.user_id,
      day_of_week: Number.isFinite(Number(dayOfWeek)) ? Number(dayOfWeek) : clipboard.day_of_week,
    }], "Pasted a draft copy. Not saved.");
    setSelectedKey(String(id));
  }

  function duplicateShift(entry) {
    const index = DAY_ORDER.indexOf(Number(entry.day_of_week));
    const nextDay = DAY_ORDER[(index + 1) % DAY_ORDER.length];
    setCopyJob({ kind: "shift", entry, userId: Number(entry.user_id), fromDay: Number(entry.day_of_week), toDay: nextDay, toUser: Number(entry.user_id), target: shiftIso(week, 7) });
  }

  function splitShift(entry) {
    const halves = splitHalves(entry);
    if (!halves) {
      setNotice("This shift is too short to split.");
      return;
    }
    const second = { ...halves.second, id: `draft-${Date.now()}` };
    applyDraft(
      entries.flatMap((item) => (shiftKey(item) === shiftKey(entry) ? [halves.first, second] : [item])),
      "Split the shift in the draft. Both halves are saved together.",
    );
    setSelectedKey(shiftKey(halves.first));
  }

  function removeShift(entry) {
    applyDraft(entries.filter((item) => shiftKey(item) !== shiftKey(entry)), "Removed the shift from the draft. Not saved.");
    setSelectedKey("");
    setEditorOpen(false);
  }

  async function send(path) {
    if (snapshot) {
      setError("This snapshot does not write. Cancel restores the loaded week.");
      return;
    }
    const action = pending.command.action;
    if (action === "save_staffing_requirements" || action === "assign_tasks") {
      const target = action === "save_staffing_requirements"
        ? { path: "/operations-planner/v2/staffing-requirements", method: "PUT", data: { requirements: pending.command.requirements } }
        : {
          path: "/operations-planner/v2/task-assignments",
          method: "POST",
          data: {
            week_start: week,
            tasks: (pending.command.tasks || []).filter((task) => task.draft && !task.remove),
            updates: (pending.command.tasks || []).filter((task) => task.changed && !task.draft && !task.remove && task.id),
            removals: (pending.command.tasks || []).filter((task) => task.remove && !task.draft && task.id).map((task) => task.id),
          },
        };
      const response = await api(target.path, { method: target.method, data: target.data, validateStatus: () => true });
      if (response.status >= 400) {
        setError(response.data?.error || "Could not save the draft");
        return;
      }
      setPending(null);
      setNotice(action === "assign_tasks"
        ? `Saved ${response.data.inserted || 0} assignment${response.data.inserted === 1 ? "" : "s"}. Completed records were left as stored.`
        : "Saved the staffing requirements.");
      await load(week);
      return;
    }
    if (action === "apply_shift_set" && scope !== "this_week" && pending.command.scopeMode !== "choice") {
      setError(pending.command.scopeReason || "This save stays on this week.");
      return;
    }
    const repeating = action === "apply_shift_set" && scope !== "this_week";
    const body = {
      ...(repeating ? { action: "apply_cell_scopes", cells: pending.command.cells } : pending.command),
      scope,
      week_start: week,
      anchor: week,
      expected_schedule_token: payload?.planner?.schedule_token,
      selected_weeks: selectedWeeks.split(",").map((item) => item.trim()).filter(Boolean),
      include_published: publishedChoice,
      replace_exceptions: exceptionChoice,
      replace_later_patterns: laterChoice,
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
      if (response.data?.code === "schedule_changed") await load(week);
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

  function targetsFor(userId) {
    const ids = pickedEmployees.map(Number).filter(Boolean);
    if (!ids.includes(Number(userId))) ids.unshift(Number(userId));
    return ids;
  }

  function onDrop(event, userId, dayOfWeek) {
    event.preventDefault();
    if (!drag?.shift) return;
    if (drag.kind && !["move", "timeline"].includes(drag.kind)) {
      const lane = event.currentTarget.querySelector?.(".ops-lane")?.getBoundingClientRect() || event.currentTarget.getBoundingClientRect();
      const minutes = pointerToMinutes(event.clientX, lane);
      if (minutes != null) resizeEntry(drag.shift, drag.kind, minutes, drag.index || 0);
      setDrag(null);
      setDragPreview("");
      return;
    }
    const copy = event.altKey || drag.copy;
    const lane = event.currentTarget.getBoundingClientRect();
    const minutes = pointerToMinutes(event.clientX, lane);
    const startTime = drag.kind === "timeline" && minutes != null ? minutesToClock(minutes) : drag.shift.start_time;
    const next = movedShift(drag.shift, { dayOfWeek, startTime });
    const userIds = copy ? targetsFor(userId) : [Number(userId)];
    queueChange({
      action: copy ? "copy" : "move",
      user_id: Number(userId),
      user_ids: userIds,
      from_user_id: drag.shift.user_id,
      from_day_of_week: drag.shift.day_of_week,
      day_of_week: dayOfWeek,
      previous_shift: drag.shift,
      shift: { ...next, user_id: Number(userId) },
    });
    setDrag(null);
    setDragPreview("");
  }

  function resizeEntry(entry, kind, minutes, index = 0) {
    const clock = minutesToClock(minutes);
    if (!clock) return;
    if (kind === "shift-move") {
      const next = movedShift(entry, { dayOfWeek: entry.day_of_week, startTime: clock });
      queueChange({
        action: "move",
        user_id: Number(entry.user_id),
        user_ids: [Number(entry.user_id)],
        from_user_id: Number(entry.user_id),
        from_day_of_week: Number(entry.day_of_week),
        day_of_week: Number(entry.day_of_week),
        previous_shift: entry,
        shift: next,
      });
      return;
    }
    const next = {
      ...entry,
      role_assignments: (entry.role_assignments || []).map((item) => ({ ...item })),
      break_slots: (entry.break_slots || []).map((item) => ({ ...item })),
    };
    if (kind === "shift-start") next.start_time = clock;
    if (kind === "shift-end") next.end_time = clock;
    if (kind === "segment-start" || kind === "segment-end") {
      next.role_assignments = next.role_assignments.map((item, itemIndex) => (
        itemIndex === index ? { ...item, [kind === "segment-start" ? "start_time" : "end_time"]: clock } : item
      ));
    }
    if (kind === "break-start" || kind === "break-end") {
      next.break_slots = next.break_slots.map((item, itemIndex) => (
        itemIndex === index ? { ...item, [kind === "break-start" ? "start_time" : "end_time"]: clock } : item
      ));
    }
    editShift(entry, next);
  }

  function editShift(shift, next) {
    queueChange({
      action: "upsert",
      user_id: Number(shift.user_id),
      user_ids: targetsFor(shift.user_id),
      day_of_week: Number(next.day_of_week ?? shift.day_of_week),
      shift: { ...shift, ...next, user_id: Number(shift.user_id) },
    });
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
  const snapshot = Boolean(payload?.snapshot);
  const labor = laborComparison(entries, employees);
  const breakTotals = breakAccounting(entries);
  const scheduledCount = new Set(entries.map((entry) => Number(entry.user_id))).size;
  const unsplitCount = entries.filter((entry) => !asList(entry.role_assignments).length).length;
  const coverageLabel = loadedRequirements.length ? "Set" : "Not set";
  const statusName = snapshot ? "snapshot" : (planner.status || "draft");
  const monday = week || planner.week_monday || "";
  commandRef.current = {
    undoDraft,
    redoDraft,
    copyShift,
    pasteShift,
    removeShift,
    entries,
    selectedKey,
    clipboard,
    employees,
    day,
    blocked: Boolean(pending || copyJob || lifecycle || leavePrompt || pinOpen || snapshot),
  };

  return (
    <div className={`ops-planner ops-v2 ${full ? "fullscreen" : ""}`}>
      <header className="top">
        <div className="brand">
          <span className="mark" aria-hidden="true">
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M2 6.5 4.5 9 10 3" stroke="white" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /></svg>
          </span>
          <strong>Operations Planner</strong>
          <em>VeeWash</em>
        </div>
        <div className="when-week">
          <button type="button" aria-label="Previous week" disabled={snapshot} onClick={() => requestWeek(shiftIso(monday, -7))}>‹</button>
          <span>{payload?.week_label || period}</span>
          <button type="button" aria-label="Next week" disabled={snapshot} onClick={() => requestWeek(shiftIso(monday, 7))}>›</button>
          <button type="button" disabled={snapshot} onClick={() => requestWeek(easternMonday())}>Today</button>
        </div>
        <span className={`status-pill ${statusName}`}>{statusName}{planner.revision ? ` · rev ${planner.revision}` : ""}{planner.published_revision ? ` · published ${planner.published_revision}` : ""}</span>
        <div className="seg" role="group" aria-label="Calendar span">
          <button type="button" aria-pressed={mode === "week"} onClick={() => setMode("week")}>Week</button>
          <button type="button" aria-pressed={mode === "day"} onClick={() => {
            const chosen = entries.find((entry) => shiftKey(entry) === selectedKey);
            if (chosen) setDay(Number(chosen.day_of_week));
            setMode("day");
          }}>Day</button>
        </div>
        {mode === "day" || lens === "roles" || lens === "breaks" || lens === "tasks" ? (
          <div className="days" role="group" aria-label="Day">
            {DAY_ORDER.map((value) => {
              const offset = value === 0 ? 6 : value - 1;
              const date = Number(String(shiftIso(monday, offset)).slice(8, 10));
              return (
                <button key={value} type="button" aria-pressed={day === value} onClick={() => setDay(value)}>
                  {DAY_NAMES[value].slice(0, 3)} {Number.isFinite(date) ? date : ""}
                </button>
              );
            })}
          </div>
        ) : null}
        <button type="button" className="btn" onClick={() => addShift(employees[0]?.user_id, mode === "day" ? day : 1)}>Add shift</button>
        <div className="spacer" />
        <details className="menu">
          <summary>Actions</summary>
          <div className="menu-panel">
            {flags && !flags.manager_pilot ? <button type="button" onClick={() => saveFlags({ manager_pilot: true }).catch((err) => setError(err.response?.data?.error || err.message))}>Enable manager pilot</button> : null}
            <button type="button" disabled={snapshot} onClick={() => setLifecycle("approve")}>Approve week…</button>
            <button type="button" disabled={snapshot} onClick={() => setLifecycle("publish")}>Publish week…</button>
            <button type="button" onClick={() => copyCard(scheduleCardSvg({ title: `Schedule · ${period}`, subtitle: planner.status || "draft", rows: exportRows }))}>Copy image</button>
            <button type="button" onClick={() => download(`schedule-${week || "week"}.csv`, scheduleCsv(exportRows), "text/csv")}>CSV</button>
            <button type="button" onClick={() => download(`schedule-${week || "week"}.pdf`, schedulePdf({ title: `Schedule · ${period}`, subtitle: planner.status || "draft", rows: exportRows }), "application/pdf")}>PDF</button>
            <button type="button" onClick={() => {
              const html = printDocumentHtml({ title: `${lens} · ${period}`, subtitle: week, sections: [{ heading: lens, rows: exportRows }] });
              const popup = window.open("", "_blank");
              if (!popup) return;
              popup.document.write(html);
              popup.document.close();
              popup.focus();
              popup.print();
            }}>Print</button>
            <label>Week starting <input aria-label="Week starting" type="date" value={monday} disabled={snapshot} onChange={(event) => requestWeek(event.target.value)} /></label>
            <button type="button" onClick={() => setPinOpen(true)}>Employee PIN access</button>
            <button type="button" onClick={() => setFull((value) => !value)}>{full ? "Exit full screen" : "Expand"}</button>
          </div>
        </details>
        <nav className="tabs" aria-label="Schedule">
          {LENSES.map(([id, label]) => (
            <button key={id} type="button" aria-pressed={lens === id} onClick={() => {
              if (id === "roles" || id === "breaks" || id === "tasks") {
                const chosen = entries.find((entry) => shiftKey(entry) === selectedKey);
                if (chosen) setDay(Number(chosen.day_of_week));
              }
              setLens(id);
            }}>{label}</button>
          ))}
        </nav>
      </header>
      {payload ? (
        <div className="metrics" aria-label="Schedule summary">
          <div className="metric"><b>{entries.length}</b><span>Shifts</span></div>
          <div className="metric" title="Sum of every shift. Overlapping shifts for the same person are counted in each shift."><b>{labor.assignmentGross.toFixed(1)}</b><span>Assignment gross</span></div>
          <div className="metric" title="Each person's overlapping shifts are counted once. The larger break on an overlap is kept. This is time on the clock, not the Weekly Schedule role split."><b>{labor.uniqueGross.toFixed(1)}</b><span>Unique working</span></div>
          <div className="metric" title="Weekly Schedule's role timeline. Overlap is counted once, then hours are split by role. A break that is not placed on a role is left out of that split."><b>{labor.scheduleGross.toFixed(1)}</b><span>Schedule gross</span></div>
          <div className="metric" title="Break deducted by the Weekly Schedule role timeline."><b>{labor.scheduleBreak.toFixed(1)}</b><span>Schedule breaks</span></div>
          <div className="metric" title="Schedule gross minus the Weekly Schedule break deduction."><b>{labor.scheduleNet.toFixed(1)}</b><span>Schedule net</span></div>
          <div className="metric"><b>{scheduledCount}</b><span>Scheduled</span></div>
          <div className="metric"><b>{Math.max(0, employees.length - scheduledCount)}</b><span>Unscheduled</span></div>
          <div className="metric"><b>{coverageLabel}</b><span>Coverage</span></div>
          <div className="flags">
            {breakTotals.unscheduledCount ? <p className="flag"><i />{breakTotals.unscheduledCount} breaks have no clock time</p> : null}
            {unsplitCount ? <p className="flag"><i />{unsplitCount} shifts have no role split</p> : null}
            {!loadedRequirements.length ? <p className="flag"><i />Staffing need not set</p> : null}
            {labor.overlapHours > 0 ? <p className="flag" title="Assignment gross adds every shift. Schedule gross is the Weekly Schedule total: overlapping time is counted once, then breaks follow that screen's role rules."><i />{labor.overlapHours.toFixed(1)}h overlap</p> : null}
            {snapshot ? <p className="flag" title="Draft edits stay in this browser. Nothing is written."><i />Read-only snapshot</p> : null}
          </div>
        </div>
      ) : null}
      {flags === null && !error ? <p className="ops-note">Loading the schedule…</p> : null}
      {error ? <p className="ops-note ops-warn">{error}</p> : null}
      {notice ? <p className="ops-note">{notice}</p> : null}
      {payload ? (
        <PlannerWorkspace
          lens={lens}
          mode={mode}
          day={day}
          weekStart={monday}
          employees={employees}
          entries={entries}
          tasks={responsibilities}
          requirements={requirements}
          planner={planner}
          selectedKey={selectedKey}
          dirty={Boolean(draftBundle)}
          canUndo={history.length > 0}
          canRedo={future.length > 0}
          editorOpen={editorOpen}
          onSelect={setSelectedKey}
          onEdit={openEditor}
          onCloseEditor={() => setEditorOpen(false)}
          onCommit={applyDraft}
          onUndo={undoDraft}
          onRedo={redoDraft}
          onDiscard={discardDraft}
          onReview={reviewDraft}
          onReviewBundle={reviewBundle}
          onAdd={addShift}
          onCopy={copyShift}
          onPaste={pasteShift}
          canPaste={Boolean(clipboard)}
          onDuplicate={duplicateShift}
          onSplit={splitShift}
          onRemove={removeShift}
          onOpenDay={(value) => { setLens("employees"); setMode("day"); setDay(Number(value)); }}
          onMove={moveDraft}
          onCopyRequest={(kind, target) => {
            const chosen = target?.entry || entries.find((entry) => shiftKey(entry) === selectedKey);
            if (!chosen && kind !== "week" && kind !== "day") return;
            const fromDay = Number.isFinite(Number(target?.day)) ? Number(target.day) : (chosen ? Number(chosen.day_of_week) : day);
            const userId = Number(target?.userId) || (chosen ? Number(chosen.user_id) : employees[0]?.user_id);
            setCopyJob({
              kind,
              entry: chosen,
              userId,
              fromDay,
              toDay: DAY_ORDER[(DAY_ORDER.indexOf(fromDay) + 1) % 7],
              toUser: employees.find((employee) => Number(employee.user_id) !== Number(userId))?.user_id || "",
              target: shiftIso(monday, 7),
            });
          }}
          catalog={payload?.role_catalog || []}
        />
      ) : null}
      {lifecycle && !snapshot ? (
        <div className="ops-dialog-back">
          <form className="ops-dialog" onSubmit={(event) => {
            event.preventDefault();
            const path = lifecycle === "approve" ? "/operations-planner/v2/weeks/approve" : "/operations-planner/v2/weeks/publish";
            api(path, { method: "POST", data: { weeks: [week] } }).then(() => {
              setLifecycle(null);
              load(week);
            });
          }}>
            <h2>{lifecycle === "approve" ? "Approve this week?" : "Publish this week?"}</h2>
            <p>Week of {monday}. Current status {statusName}{planner.revision ? `, revision ${planner.revision}` : ""}. {scheduledCount} scheduled employees. Schedule net {labor.scheduleNet.toFixed(1)} hours. Assignment gross {labor.assignmentGross.toFixed(1)} hours includes {labor.overlapHours.toFixed(1)} hours of overlap.</p>
            <p>Confirm writes the publication status for this week. Cancel leaves it unchanged.</p>
            <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
              <button type="button" onClick={() => setLifecycle(null)}>Cancel</button>
              <button type="submit" className="primary">Confirm {lifecycle}</button>
            </div>
          </form>
        </div>
      ) : null}
      {leavePrompt ? (
        <div className="ops-dialog-back">
          <form className="ops-dialog" onSubmit={(event) => {
            event.preventDefault();
            const next = leavePrompt;
            setLeavePrompt("");
            setDraftBundle(null);
            setHistory([]);
            setFuture([]);
            setPending(null);
            setEditorOpen(false);
            setWeek(next);
            setNotice("Discarded unsaved edits and opened the other week.");
          }}>
            <h2>Keep the unsaved schedule?</h2>
            <p>This week has edits that are not saved. Opening another week leaves those edits here until you discard them.</p>
            <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
              <button type="button" onClick={() => setLeavePrompt("")}>Stay on this week</button>
              <button type="submit" className="primary">Discard and switch</button>
            </div>
          </form>
        </div>
      ) : null}
      {pinOpen && !snapshot ? (
        <div className="ops-dialog-back">
          <div className="ops-dialog pin-box">
            <h2>Employee PIN access</h2>
            <AccessEditor employees={employees} onSaved={() => load(week)} onError={setError} />
            {planner.legacy_template ? <p className="ops-warn">The old repeating template is still on. A recurring save will ask to stop it.</p> : null}
            <button type="button" className="btn" onClick={() => setPinOpen(false)}>Close</button>
          </div>
        </div>
      ) : null}
      {copyJob ? (
        <div className="ops-dialog-back">
          <form className="ops-dialog" onSubmit={(event) => { event.preventDefault(); runCopy(copyJob); }}>
            <h2>{copyJob.kind === "week" ? "Copy this week" : copyJob.kind === "day" ? "Copy this day" : copyJob.kind === "employee-week" ? "Copy this employee's week" : copyJob.kind === "employee-day" ? "Copy this employee's day" : "Duplicate this shift"}</h2>
            <p>The copy is a draft. Completed tasks and pay records are not copied. Nothing is written until Review save.</p>
            {copyJob.kind !== "week" && copyJob.kind !== "day" ? (
              <label>Employee
                <select aria-label="Copy target employee" value={String(copyJob.kind === "employee-week" ? copyJob.toUser : copyJob.userId)} onChange={(event) => setCopyJob({ ...copyJob, userId: Number(event.target.value), toUser: Number(event.target.value) })}>
                  {employees.map((employee) => <option key={employee.user_id} value={employee.user_id}>{employee.display_name}</option>)}
                </select>
              </label>
            ) : null}
            {copyJob.kind !== "week" && copyJob.kind !== "employee-week" ? (
              <label>Day
                <select aria-label="Copy target day" value={String(copyJob.toDay)} onChange={(event) => setCopyJob({ ...copyJob, toDay: Number(event.target.value), day: Number(event.target.value) })}>
                  {DAY_ORDER.map((value) => <option key={value} value={value}>{DAY_NAMES[value]}</option>)}
                </select>
              </label>
            ) : null}
            {copyJob.kind === "week" ? (
              <label>Week starting Monday
                <input aria-label="Target week" type="date" value={copyJob.target} onChange={(event) => setCopyJob({ ...copyJob, target: event.target.value })} />
              </label>
            ) : null}
            <div style={{ display: "flex", gap: 8 }}>
              <button type="submit" className="btn primary">Copy into draft</button>
              <button type="button" className="btn" onClick={() => setCopyJob(null)}>Cancel</button>
            </div>
          </form>
        </div>
      ) : null}
      {pending ? (
        <div className="ops-dialog-back">
          <form className="ops-dialog" onSubmit={(event) => { event.preventDefault(); if (!snapshot) send("/operations-planner/v2/apply"); }}>
            <h2>How should this change apply?</h2>
            <p>
              {pending.command.action === "save_staffing_requirements"
                ? `${(pending.command.requirements || []).length} staffing interval${(pending.command.requirements || []).length === 1 ? "" : "s"}. Hours without an interval stay unconfigured.`
                : pending.command.action === "assign_tasks"
                  ? `${(pending.command.tasks || []).length} new assignment${(pending.command.tasks || []).length === 1 ? "" : "s"}. Completed records are not rewritten.`
                  : pending.command.action === "apply_shift_set"
                    ? "Every addition, change, and removal below is saved together. If one half fails, nothing is written."
                    : `${pending.command.action} · employee ${pending.command.user_id} · ${DAY_NAMES[pending.command.day_of_week] || ""}`}
            </p>
            {pending.command.action === "apply_shift_set" ? (
              <>
                <p>{pending.command.scopeReason}</p>
                {pending.command.hoursBefore ? (
                  <p>
                    Assignment gross {pending.command.hoursBefore.assignmentGross.toFixed(1)} → {pending.command.hoursAfter.assignmentGross.toFixed(1)}.
                    Unique working {pending.command.hoursBefore.uniqueGross.toFixed(1)} → {pending.command.hoursAfter.uniqueGross.toFixed(1)}.
                    Schedule gross {pending.command.hoursBefore.scheduleGross.toFixed(1)} → {pending.command.hoursAfter.scheduleGross.toFixed(1)}.
                    Schedule net {pending.command.hoursBefore.scheduleNet.toFixed(1)} → {pending.command.hoursAfter.scheduleNet.toFixed(1)}.
                  </p>
                ) : null}
                <ul className="review-list">
                  {(pending.command.lines || []).map((line, index) => (
                    <li key={`${line.kind}-${index}`}>{line.kind} · {line.employee} · {line.day} · {line.before} → {line.after}</li>
                  ))}
                  {(pending.command.taskLines || []).map((line, index) => (
                    <li key={`task-${index}`}>Task · employee {line.employee} · {line.day} · {line.detail}</li>
                  ))}
                  {(pending.command.staffingLines || []).map((line, index) => (
                    <li key={`staff-${index}`}>{line.detail}</li>
                  ))}
                </ul>
              </>
            ) : pending.command.action === "assign_tasks" || pending.command.action === "save_staffing_requirements" ? (
              <ul className="review-list">
                {(pending.command.taskLines || []).map((line, index) => (
                  <li key={`task-${index}`}>{line.kind} · {line.detail}</li>
                ))}
                {(pending.command.staffingLines || []).map((line, index) => (
                  <li key={`staff-${index}`}>{line.detail}</li>
                ))}
              </ul>
            ) : null}
            {snapshot ? <p>Confirm is off for this snapshot. Cancel restores the loaded week, including fields this edit did not change.</p> : null}
            {pending.command.action === "apply_shift_set" ? (
              pending.command.scopeMode !== "choice" ? <p>{pending.command.scopeReason}</p> : ["this_week", "this_and_future", "future_only", "selected_weeks"].map((value) => (
                <label key={value} style={{ display: "block", marginBottom: 6 }}>
                  <input type="radio" name="scope" checked={scope === value} onChange={() => setScope(value)} /> {value.replaceAll("_", " ")}
                </label>
              ))
            ) : <p>This task or staffing change is saved on the week of {week}.</p>}
            {scope === "selected_weeks" ? (
              <label>
                Full Monday–Sunday weeks. Enter the Monday that starts each week, including weeks that are not next to each other.
                <input value={selectedWeeks} onChange={(event) => setSelectedWeeks(event.target.value)} placeholder="2026-11-16, 2026-12-07" />
              </label>
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
            {preview?.later_pattern_weeks?.length ? (
              <fieldset>
                <legend>A later schedule already starts on {preview.later_pattern_weeks.join(", ")}</legend>
                <button type="button" className={laterChoice === false ? "active" : ""} onClick={() => setLaterChoice(false)}>Keep that later schedule</button>
                <button type="button" className={laterChoice === true ? "active" : ""} onClick={() => setLaterChoice(true)}>Replace that later schedule</button>
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
              <button type="button" disabled={snapshot} onClick={() => { if (!snapshot) send("/operations-planner/v2/preview"); }}>Review</button>
              <button type="submit" className="primary" disabled={snapshot}>Confirm</button>
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

  return (
    <div>
      <p>Employee PIN access</p>
      <select value={userId} onChange={(event) => setUserId(event.target.value)}>
        {employees.map((employee) => (
          <option key={employee.user_id} value={employee.user_id}>{employee.display_name}</option>
        ))}
      </select>
      <p>Paystubs stay off. A PIN and date of birth are not enough on a shared device.</p>
      {access ? (
        <form onSubmit={(event) => {
          event.preventDefault();
          api(`/operations-planner/v2/employees/${userId}/access`, {
            method: "PUT",
            data: {
              schedule_enabled: event.target.elements.schedule.checked,
              hours_enabled: event.target.elements.hours.checked,
            },
          }).then((response) => {
            setAccess(response.data.access);
            onSaved();
          }).catch((err) => onError(err.response?.data?.error || err.message));
        }}>
          <label style={{ display: "block", fontSize: 13 }}>
            <input name="schedule" type="checkbox" defaultChecked={Boolean(access.schedule_enabled)} /> Schedule. A published week is what an employee can see, and only after access is saved. Drafts stay hidden.
          </label>
          <label style={{ display: "block", fontSize: 13 }}>
            <input name="hours" type="checkbox" defaultChecked={Boolean(access.hours_enabled)} /> Hours. Paystub access is not changed here.
          </label>
          <button type="submit" className="btn">Save access</button>
        </form>
      ) : null}
    </div>
  );
}

function names(employees, userId) {
  return employees.find((employee) => Number(employee.user_id) === Number(userId))?.display_name || `Employee ${userId}`;
}

function DayTimeline({ employees, entries, day, preview, onResize, onPreview, onDragStart, onDragOver, onDrop }) {
  const hours = [];
  for (let hour = 6; hour <= 21; hour += 1) hours.push(hour);
  return (
    <div className="ops-timeline">
      <div className="ops-timeline-hours"><span /><div>{hours.map((hour) => <span key={hour}>{hour}</span>)}</div></div>
      {preview ? <p className="ops-preview">{preview}</p> : null}
      {employees.map((employee) => (
        <div
          key={employee.user_id}
          className="ops-timeline-row"
          onDragOver={(event) => {
            event.preventDefault();
            onDragOver(event);
          }}
          onDrop={(event) => onDrop(event, Number(employee.user_id), day)}
        >
          <strong>{employee.display_name}</strong>
          <div className="ops-lane">
            {entries.filter((entry) => Number(entry.user_id) === Number(employee.user_id)).map((entry) => (
              <ShiftBar
                key={`${entry.user_id}-${entry.start_time}`}
                entry={entry}
                onResize={onResize}
                onPreview={onPreview}
                onDragStart={onDragStart}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function trackPointer(event, onMove, onEnd) {
  event.preventDefault();
  event.stopPropagation();
  const lane = event.currentTarget.closest(".ops-lane")?.getBoundingClientRect();
  if (!lane) return;
  const move = (pointer) => {
    const minutes = pointerToMinutes(pointer.clientX, lane);
    if (minutes != null) onMove(minutes);
  };
  const finish = (pointer) => {
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", finish);
    const minutes = pointerToMinutes(pointer.clientX, lane);
    if (minutes != null) onEnd(minutes);
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", finish);
}

function ShiftBar({ entry, onResize, onPreview, onDragStart }) {
  function nudge(kind, delta, index = 0) {
    const source = kind.startsWith("segment")
      ? entry.role_assignments?.[index]
      : kind.startsWith("break")
        ? entry.break_slots?.[index]
        : entry;
    const field = kind.endsWith("end") ? "end_time" : "start_time";
    const current = clockMinutes(source?.[field] || entry.start_time);
    if (current == null) return;
    onResize(entry, kind, current + delta, index);
  }
  return (
    <div className={`ops-bar role-${entry.role || "fold"}`} style={barStyle(entry.start_time, entry.end_time)} draggable onDragStart={() => onDragStart(entry, "timeline")}>
      <button
        type="button"
        className="ops-handle start"
        aria-label={`Change shift start for ${entry.start_time}`}
        onPointerDown={(event) => trackPointer(event, (minutes) => onPreview(`Start ${minutesToClock(minutes)}`), (minutes) => onResize(entry, "shift-start", minutes))}
        onKeyDown={(event) => {
          if (event.key === "ArrowLeft") nudge("shift-start", -15);
          if (event.key === "ArrowRight") nudge("shift-start", 15);
        }}
      />
      <span className="ops-bar-label">{entry.start_time}–{entry.end_time} {entry.role}</span>
      <button
        type="button"
        className="ops-handle end"
        aria-label={`Change shift end for ${entry.end_time}`}
        draggable
        onDragStart={(event) => {
          event.stopPropagation();
          event.dataTransfer?.setData("text/plain", "shift-end");
          onDragStart(entry, "shift-end");
        }}
        onPointerDown={(event) => trackPointer(event, (minutes) => onPreview(`End ${minutesToClock(minutes)}`), (minutes) => onResize(entry, "shift-end", minutes))}
        onKeyDown={(event) => {
          if (event.key === "ArrowLeft") nudge("shift-end", -15);
          if (event.key === "ArrowRight") nudge("shift-end", 15);
        }}
      />
      {(entry.role_assignments || []).map((segment, index) => (
        <span key={`${segment.role}-${segment.start_time}`} className="ops-segment" style={pieceStyle(entry, segment)}>
          <button type="button" aria-label={`Change ${segment.role} start`} onPointerDown={(event) => trackPointer(event, (minutes) => onPreview(`${segment.role} start ${minutesToClock(minutes)}`), (minutes) => onResize(entry, "segment-start", minutes, index))} onKeyDown={(event) => { if (event.key === "ArrowLeft") nudge("segment-start", -15, index); if (event.key === "ArrowRight") nudge("segment-start", 15, index); }} />
          <em>{segment.role}</em>
          <button type="button" aria-label={`Change ${segment.role} end`} onPointerDown={(event) => trackPointer(event, (minutes) => onPreview(`${segment.role} end ${minutesToClock(minutes)}`), (minutes) => onResize(entry, "segment-end", minutes, index))} onKeyDown={(event) => { if (event.key === "ArrowLeft") nudge("segment-end", -15, index); if (event.key === "ArrowRight") nudge("segment-end", 15, index); }} />
        </span>
      ))}
      {(entry.break_slots || []).map((slot, index) => (
        <span key={`${slot.start_time}-${index}`} className="ops-break-chip" style={pieceStyle(entry, slot)}>
          <button type="button" aria-label={`Change break start ${slot.start_time}`} onPointerDown={(event) => trackPointer(event, (minutes) => onPreview(`Break start ${minutesToClock(minutes)}`), (minutes) => onResize(entry, "break-start", minutes, index))} onKeyDown={(event) => { if (event.key === "ArrowLeft") nudge("break-start", -15, index); if (event.key === "ArrowRight") nudge("break-start", 15, index); }} />
          <button type="button" aria-label={`Change break end ${slot.end_time}`} onPointerDown={(event) => trackPointer(event, (minutes) => onPreview(`Break end ${minutesToClock(minutes)}`), (minutes) => onResize(entry, "break-end", minutes, index))} onKeyDown={(event) => { if (event.key === "ArrowLeft") nudge("break-end", -15, index); if (event.key === "ArrowRight") nudge("break-end", 15, index); }} />
        </span>
      ))}
    </div>
  );
}

export function DevPlannerShell() {
  const [hidden, setHidden] = useState(false);
  useEffect(() => {
    const root = document.documentElement;
    const sync = () => setHidden(root.getAttribute("data-ops-planner-fullscreen") === "1");
    sync();
    const observer = new MutationObserver(sync);
    observer.observe(root, { attributes: true, attributeFilter: ["data-ops-planner-fullscreen"] });
    return () => observer.disconnect();
  }, []);
  return (
    <div className="ops-dev-shell">
      {hidden ? null : <nav className="ops-dev-nav" aria-label="Main menu">Schedule</nav>}
      <OperationsPlannerV2Page />
    </div>
  );
}

function pieceStyle(shift, piece) {
  const open = clockMinutes(shift.start_time);
  let close = clockMinutes(shift.end_time);
  const begin = clockMinutes(piece.start_time);
  let finish = clockMinutes(piece.end_time);
  if (open == null || close == null || begin == null || finish == null || close === open) return { left: "0%", width: "0%" };
  if (close <= open) close += 24 * 60;
  return {
    left: `${Math.max(0, ((begin - open) / (close - open)) * 100)}%`,
    width: `${Math.max(4, ((finish - begin) / (close - open)) * 100)}%`,
  };
}

function barStyle(start, end) {
  const open = 6 * 60;
  const span = 16 * 60;
  const begin = ((Number(start.slice(0, 2)) * 60 + Number(start.slice(3, 5))) - open) / span;
  const finish = ((Number(end.slice(0, 2)) * 60 + Number(end.slice(3, 5))) - open) / span;
  return { left: `${Math.max(0, begin) * 100}%`, width: `${Math.max(2, (finish - begin) * 100)}%` };
}

function TimeEditor({ employees, day, picked, onToggle, onEdit }) {
  const [userId, setUserId] = useState(employees[0] ? String(employees[0].user_id) : "");
  const [start, setStart] = useState("08:00");
  const [end, setEnd] = useState("16:00");
  const [role, setRole] = useState("fold");
  const [breakStart, setBreakStart] = useState("12:00");
  const [breakEnd, setBreakEnd] = useState("12:30");
  return (
    <form
      className="ops-editor"
      onSubmit={(event) => {
        event.preventDefault();
        onEdit(
          { user_id: Number(userId), day_of_week: day, start_time: start, end_time: end, role, break_slots: [], role_assignments: [] },
          {
            start_time: start,
            end_time: end,
            role,
            role_assignments: [{ role, start_time: start, end_time: end }],
            break_slots: [{ start_time: breakStart, end_time: breakEnd, timed: true }],
          },
        );
      }}
    >
      <p>Keyboard edit. Saving asks which weeks to update. Check extra employees to apply the same times.</p>
      <select value={userId} onChange={(event) => setUserId(event.target.value)}>
        {employees.map((employee) => <option key={employee.user_id} value={employee.user_id}>{employee.display_name}</option>)}
      </select>
      <label>Start <input type="time" step="900" value={start} onChange={(event) => setStart(event.target.value)} /></label>
      <label>End <input type="time" step="900" value={end} onChange={(event) => setEnd(event.target.value)} /></label>
      <label>Role <input value={role} onChange={(event) => setRole(event.target.value)} /></label>
      <label>Break <input type="time" step="900" value={breakStart} onChange={(event) => setBreakStart(event.target.value)} /></label>
      <label>Until <input type="time" step="900" value={breakEnd} onChange={(event) => setBreakEnd(event.target.value)} /></label>
      {employees.map((employee) => (
        <label key={employee.user_id}>
          <input
            type="checkbox"
            checked={picked.map(String).includes(String(employee.user_id))}
            onChange={(event) => {
              const id = String(employee.user_id);
              onToggle(event.target.checked ? [...picked, id] : picked.filter((item) => item !== id));
            }}
          />
          {employee.display_name}
        </label>
      ))}
      <button type="submit" className="primary">Save times</button>
    </form>
  );
}

function RoleBoard({ entries, employees, settings, onAssign, onHeadcount }) {
  const roles = [...new Set([
    ...settings.map((row) => row.role),
    ...entries.flatMap((entry) => (entry.role_assignments || []).map((item) => item.role).concat(entry.role)),
  ].filter(Boolean))];
  const hours = [];
  for (let hour = 6; hour <= 21; hour += 1) hours.push(hour);
  return (
    <div>
      {roles.map((role) => {
        const setting = settings.find((row) => row.role === role) || {};
        return (
          <div
            key={role}
            className="lane"
            onDragOver={(event) => event.preventDefault()}
            onDrop={(event) => {
              const raw = event.dataTransfer.getData("text/plain");
              if (!raw) return;
              onAssign(JSON.parse(raw), role);
            }}
          >
            <div className="ops-role-head">
            <strong>{role}</strong>
            <label>
              Required
              <input
                type="number"
                min="0"
                defaultValue={setting.required_headcount ?? ""}
                onBlur={(event) => onHeadcount(role, { required_headcount: event.target.value })}
              />
            </label>
            </div>
            <div className="ops-hours">
              {hours.map((hour) => {
                const required = setting.hourly_headcount?.[String(hour)] ?? setting.required_headcount;
                const cell = roleCoverage(entries, role, hour, required);
                return (
                  <div key={hour} className="ops-hour-card">
                    <strong>{hour}:00</strong>
                    <div>Required {cell.required ?? "—"}</div>
                    <div>Scheduled {cell.scheduled.length}</div>
                    <div>Active {cell.available.length}</div>
                    <div>On break {cell.onBreak.length}</div>
                    <div>{cell.shortage ? `Short ${cell.shortage}` : cell.surplus ? `Extra ${cell.surplus}` : "Covered"}</div>
                    <input
                      aria-label={`${role} required at ${hour}`}
                      type="number"
                      min="0"
                      defaultValue={setting.hourly_headcount?.[String(hour)] ?? ""}
                      onBlur={(event) => onHeadcount(role, {
                        hourly_headcount: { ...(setting.hourly_headcount || {}), [hour]: event.target.value },
                      })}
                    />
                  </div>
                );
              })}
            </div>
            {entries.filter((entry) => entry.role === role || (entry.role_assignments || []).some((item) => item.role === role)).map((entry) => (
              <button
                key={`${role}-${entry.user_id}-${entry.start_time}`}
                type="button"
                draggable
                onDragStart={(event) => event.dataTransfer.setData("text/plain", JSON.stringify(entry))}
              >
                {names(employees, entry.user_id)} {entry.start_time}–{entry.end_time}
              </button>
            ))}
          </div>
        );
      })}
    </div>
  );
}

function BreakBoard({ entries, employees, onMove, onCopyPattern }) {
  const hours = [];
  for (let hour = 6; hour <= 21; hour += 1) hours.push(hour);
  const overlap = overlappingBreakCount(entries);
  return (
    <div>
      {overlap > BREAK_OVERLAP_CAP ? <p className="ops-warn">{overlap} people have a timed break at the same time. The limit is {BREAK_OVERLAP_CAP}.</p> : <p>Timed breaks overlap by {overlap}. Active coverage excludes people on a timed break.</p>}
      <div className="ops-break-grid">
        {hours.map((hour) => {
          const cell = hourCoverage(entries, hour);
          return (
            <div
              key={hour}
              className="hour-cell"
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => {
                const raw = event.dataTransfer.getData("text/plain");
                if (!raw) return;
                onMove(JSON.parse(raw), `${String(hour).padStart(2, "0")}:00`);
              }}
            >
              <strong>{hour}:00</strong>
              <div>{cell.available.length} active · {cell.scheduled.length} scheduled · {cell.onBreak.length} on break</div>
              {cell.onBreak.map((entry) => (
                <button
                  key={entry.user_id}
                  type="button"
                  draggable
                  onDragStart={(event) => event.dataTransfer.setData("text/plain", JSON.stringify(entry))}
                >
                  {names(employees, entry.user_id)}
                </button>
              ))}
            </div>
          );
        })}
      </div>
      {entries.filter((entry) => (entry.break_slots || []).length).map((entry) => (
        <button key={`copy-${entry.user_id}-${entry.day_of_week}`} type="button" onClick={() => onCopyPattern(entry)}>
          Apply {names(employees, entry.user_id)} break to checked employees
        </button>
      ))}
    </div>
  );
}

function TaskBoard({ tasks, employees, entries, day, onEdit }) {
  const [userId, setUserId] = useState(employees[0] ? String(employees[0].user_id) : "");
  const [role, setRole] = useState("");
  const [shared, setShared] = useState(false);
  const byPerson = new Map();
  for (const task of tasks) {
    const key = Number(task.user_id);
    if (!byPerson.has(key)) byPerson.set(key, []);
    byPerson.get(key).push(task);
  }
  return (
    <div>
      <form
        className="ops-editor"
        onSubmit={(event) => {
          event.preventDefault();
          const entry = entries.find((item) => String(item.user_id) === String(userId) && Number(item.day_of_week) === Number(day));
          if (!entry || !role.trim()) return;
          const members = shared ? employees.map((employee) => Number(employee.user_id)) : [Number(userId)];
          const current = tasks
            .filter((task) => String(task.user_id) === String(userId) && Number(task.day_of_week) === Number(day))
            .map((task) => ({
              role: task.role,
              name: task.role,
              shared: Boolean(task.assignment_group_id),
              user_ids: task.user_ids || [Number(task.user_id)],
              execution_mode: task.assignment_group_id ? "shared" : "individual",
            }));
          onEdit(entry, {
            tasks: [...current.filter((task) => task.role !== role.trim()), {
              role: role.trim(),
              name: role.trim(),
              shared,
              user_ids: members,
              execution_mode: shared ? "shared" : "individual",
            }],
          });
        }}
      >
        <p>Assign an existing task role. Completed work stays on the employee record. A shared task uses one activity group.</p>
        <select value={userId} onChange={(event) => setUserId(event.target.value)}>
          {employees.map((employee) => <option key={employee.user_id} value={employee.user_id}>{employee.display_name}</option>)}
        </select>
        <input value={role} onChange={(event) => setRole(event.target.value)} placeholder="Existing task role code" />
        <label><input type="checkbox" checked={shared} onChange={(event) => setShared(event.target.checked)} /> Shared activity group</label>
        <button type="submit">Assign task</button>
      </form>
      {[...byPerson.entries()].map(([personId, rows]) => {
        const rollup = taskRollup(rows);
        return (
          <div key={personId} className="lane">
            <strong>{names(employees, personId)}</strong>
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

function previewPayload() {
  return {
    week_label: "Nov 9–15, 2026",
    employees: [
      { user_id: 7, display_name: "Amina Cole" },
      { user_id: 8, display_name: "Luis Ortega" },
      { user_id: 9, display_name: "Priya Shah" },
    ],
    entries: [
      { id: 1, user_id: 7, day_of_week: 1, start_time: "08:00", end_time: "16:00", role: "wash", break_slots: [{ start_time: "12:00", end_time: "12:30", timed: true }], role_assignments: [{ role: "wash", start_time: "08:00", end_time: "12:00" }, { role: "fold", start_time: "12:30", end_time: "16:00" }] },
      { id: 2, user_id: 8, day_of_week: 1, start_time: "09:00", end_time: "17:00", role: "fold", break_slots: [{ start_time: "12:00", end_time: "12:30", timed: true }], role_assignments: [{ role: "fold", start_time: "09:00", end_time: "17:00" }] },
      { id: 3, user_id: 9, day_of_week: 1, start_time: "10:00", end_time: "18:00", role: "fold", break_slots: [{ start_time: "13:00", end_time: "13:30", timed: true }], role_assignments: [{ role: "fold", start_time: "10:00", end_time: "18:00" }] },
      { id: 4, user_id: 7, day_of_week: 2, start_time: "05:00", end_time: "13:00", role: "sort", break_minutes: 30, break_slots: null, role_assignments: [{ role: "sort", start_time: "05:00", end_time: "09:00" }, { role: "fold", start_time: "09:00", end_time: "13:00" }] },
    ],
    daily_responsibilities: [
      { id: 11, user_id: 7, day_of_week: 1, role: "floor_reset", status: "completed", assignment_group_id: "g1" },
      { id: 12, user_id: 8, day_of_week: 1, role: "floor_reset", status: "in_progress", assignment_group_id: "g1" },
      { id: 13, user_id: 9, day_of_week: 1, role: "trash", status: "pending" },
    ],
    planner: {
      week_monday: "2026-11-09",
      status: "draft",
      revision: 3,
      flags: { manager_pilot: true },
      role_settings: [
        { role: "wash", required_headcount: 1, hourly_headcount: { 8: 1, 12: 1 }, show_on_rinse_dashboard: false, visible_to_rinse: false },
        { role: "fold", required_headcount: 2, hourly_headcount: { 12: 2 }, show_on_rinse_dashboard: true, visible_to_rinse: true },
      ],
    },
  };
}
