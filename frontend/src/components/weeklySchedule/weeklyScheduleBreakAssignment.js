import { parseTimeToMinutes } from "../../payroll/schedulePlanner";
import { normalizeTimeHm } from "../datetime/scheduleTimeUi";
import { entryShiftInterval, makeBreakSlot } from "./weeklyScheduleRoles";

function slotDurationMinutes(slot) {
  const start = parseTimeToMinutes(normalizeTimeHm(slot?.start_time));
  const end = parseTimeToMinutes(normalizeTimeHm(slot?.end_time));
  if (start == null || end == null || start === end) return 0;
  return end > start ? end - start : end + 1440 - start;
}

function toHm(minutes) {
  const value = ((minutes % 1440) + 1440) % 1440;
  return `${String(Math.floor(value / 60)).padStart(2, "0")}:${String(value % 60).padStart(2, "0")}`;
}

/** Employee/date pairs in the selection that have no shift. */
export function unscheduledAssignmentPairs(entries, people, days) {
  const pairs = [];
  for (const person of people || []) {
    const userId = Number(person.user_id);
    for (const day of days || []) {
      const scheduled = (entries || []).some(
        (entry) => Number(entry.user_id) === userId && Number(entry.day_of_week) === Number(day),
      );
      if (!scheduled) {
        pairs.push({
          userId,
          day: Number(day),
          name: person.display_name || `User #${userId}`,
        });
      }
    }
  }
  return pairs;
}

/** Timed slots plus a duration-only break. A shift with neither has no break. */
export function breakSummary(entry) {
  const slots = (Array.isArray(entry?.break_slots) ? entry.break_slots : []).filter(
    (slot) => slot?.start_time && slot?.end_time,
  );
  const unscheduled = Math.max(0, Number(entry?.unscheduled_break_minutes || 0));
  const timedMinutes = slots.reduce((sum, slot) => sum + slotDurationMinutes(slot), 0);
  return {
    slots,
    unscheduled,
    timedMinutes,
    totalMinutes: timedMinutes + unscheduled,
    hasBreak: slots.length > 0 || unscheduled > 0,
  };
}

/** A 30-minute break centred in the shift, on a quarter hour. Does not replace an existing break. */
export function suggestedBreakSlot(entry, minutes = 30) {
  const shift = entryShiftInterval(entry);
  if (!shift) return makeBreakSlot();
  const length = Math.max(5, Math.min(minutes, shift.end - shift.start));
  const centred = shift.start + Math.floor((shift.end - shift.start - length) / 2);
  const start = Math.max(shift.start, Math.min(shift.end - length, Math.round(centred / 15) * 15));
  return makeBreakSlot({ start_time: toHm(start), end_time: toHm(start + length) });
}

/**
 * One row per selected employee and date. Shifts already on that date are listed separately
 * so a change can target one shift instead of every selection.
 */
export function breakTargets({ people = [], days = [], entries = [] } = {}) {
  return people.flatMap((person) => {
    const userId = Number(person.user_id);
    const name = person.display_name || `User #${userId}`;
    return days.map((day) => ({
      key: `${userId}:${Number(day)}`,
      userId,
      name,
      day: Number(day),
      shifts: (entries || []).filter(
        (entry) => Number(entry.user_id) === userId && Number(entry.day_of_week) === Number(day),
      ),
    }));
  });
}

export function slotMinutes(slot) {
  return slotDurationMinutes(slot);
}
