import { DAY_NAMES } from "./plannerModel";
import { draftOperations } from "./plannerGeometry";

function cellKey(userId, day) {
  return `${Number(userId)}:${Number(day)}`;
}

/** Every changed day can repeat, including a day that holds more than one shift. */
export function scopeDecision(before, after) {
  const operations = draftOperations(before, after);
  return {
    operations,
    recurring: operations.length > 0,
    blocked: [],
    reason: "This week is a temporary exception. This week and future, future only, and selected weeks repeat every shift on the changed days, including a second shift on the same day.",
  };
}

export function patternCells(before, after) {
  const decision = scopeDecision(before, after);
  if (!decision.recurring) return [];
  const keys = [...new Set(decision.operations.map((op) => cellKey(op.user_id, op.day_of_week)))];
  return keys.map((key) => {
    const [userId, day] = key.split(":").map(Number);
    const shifts = (after || []).filter((entry) => cellKey(entry.user_id, entry.day_of_week) === key);
    return { user_id: userId, day_of_week: day, shift: shifts[0] || null, shifts };
  });
}

function clockLabel(entry) {
  if (!entry) return "removed";
  const slots = Array.isArray(entry.break_slots) ? entry.break_slots : [];
  const timed = slots.filter((slot) => slot?.start_time && slot?.end_time).map((slot) => `${String(slot.start_time).slice(0, 5)}–${String(slot.end_time).slice(0, 5)}`);
  const breakText = timed.length ? `break ${timed.join(", ")}` : (Number(entry.break_minutes) > 0 ? `break ${entry.break_minutes} min, no clock time` : "no break");
  return `${String(entry.start_time || "").slice(0, 5)}–${String(entry.end_time || "").slice(0, 5)} · ${entry.role || "no role"} · ${breakText}`;
}

export function reviewLines(before, after, employees = []) {
  const nameOf = (userId) => employees.find((employee) => Number(employee.user_id) === Number(userId))?.display_name || `Employee ${userId}`;
  return draftOperations(before, after).map((op) => {
    const saved = (before || []).find((entry) => String(entry.id) === String(op.id));
    return {
      kind: op.op === "create" ? "Add" : op.op === "delete" ? "Remove" : "Change",
      employee: nameOf(op.user_id),
      day: DAY_NAMES[op.day_of_week] || "",
      before: op.op === "create" ? "—" : clockLabel(saved),
      after: op.op === "delete" ? "removed" : clockLabel(op.shift),
    };
  });
}

function taskDetail(task) {
  if (!task) return "removed";
  const clock = task.timing_mode === "specific_time" && task.start_time ? ` at ${String(task.start_time).slice(0, 5)}` : " · no clock time";
  return `${task.role || "task"} · employee ${task.user_id} · ${DAY_NAMES[task.day_of_week] || ""}${clock}`;
}

export function taskChanges(before, after) {
  const prior = new Map((before || []).filter((task) => task.id).map((task) => [String(task.id), task]));
  return (after || []).flatMap((task) => {
    if (task.remove && !task.draft) {
      return [{ kind: "Remove task", employee: task.user_id, day: DAY_NAMES[task.day_of_week] || "", detail: `${taskDetail(prior.get(String(task.id)) || task)} → removed` }];
    }
    if (task.draft && !task.remove) {
      return [{ kind: "Add task", employee: task.user_id, day: DAY_NAMES[task.day_of_week] || "", detail: `— → ${taskDetail(task)}` }];
    }
    const saved = prior.get(String(task.id));
    if (task.changed && saved && taskDetail(saved) !== taskDetail(task)) {
      return [{ kind: "Change task", employee: task.user_id, day: DAY_NAMES[task.day_of_week] || "", detail: `${taskDetail(saved)} → ${taskDetail(task)}` }];
    }
    return [];
  });
}

export function staffingChanges(before, after) {
  const stamp = (item) => `${item.role}|${item.day_of_week ?? "all"}|${item.start_time}|${item.end_time}|${item.required_headcount}`;
  const prior = new Set((before || []).map(stamp));
  return (after || []).filter((item) => !prior.has(stamp(item))).map((item) => ({
    kind: "Staffing",
    detail: `${item.role} ${item.day_of_week == null ? "every day" : DAY_NAMES[item.day_of_week]} ${item.start_time}–${item.end_time} need ${item.required_headcount}`,
  }));
}
