import { asList } from "./plannerGeometry";

let draftSerial = 0;

export function nextDraftId() {
  draftSerial += 1;
  return `draft-${Date.now()}-${draftSerial}`;
}

/** A schedule copy. Task rows and completion history are not part of the shift. */
export function copiedShift(entry, { userId = entry.user_id, dayOfWeek = entry.day_of_week, id = nextDraftId() } = {}) {
  return {
    id,
    user_id: Number(userId),
    day_of_week: Number(dayOfWeek),
    start_time: String(entry.start_time || "").slice(0, 5),
    end_time: String(entry.end_time || "").slice(0, 5),
    role: entry.role || "",
    break_minutes: Number(entry.break_minutes || 0),
    break_slots: asList(entry.break_slots).map((slot) => ({ ...slot })),
    role_assignments: asList(entry.role_assignments)
      .filter((item) => item && item.full_shift !== true && item.role)
      .map((item) => ({ ...item })),
  };
}

function sameCell(entry, userId, day) {
  return Number(entry.user_id) === Number(userId) && Number(entry.day_of_week) === Number(day);
}

export function copyEmployeeDay(entries, userId, fromDay, toDay) {
  const source = (entries || []).filter((entry) => sameCell(entry, userId, fromDay));
  return [...(entries || []), ...source.map((entry) => copiedShift(entry, { userId, dayOfWeek: toDay }))];
}

export function copyEmployeeWeek(entries, fromUser, toUser) {
  const source = (entries || []).filter((entry) => Number(entry.user_id) === Number(fromUser));
  return [...(entries || []), ...source.map((entry) => copiedShift(entry, { userId: toUser, dayOfWeek: entry.day_of_week }))];
}

export function copyDay(entries, fromDay, toDay) {
  const source = (entries || []).filter((entry) => Number(entry.day_of_week) === Number(fromDay));
  return [...(entries || []), ...source.map((entry) => copiedShift(entry, { userId: entry.user_id, dayOfWeek: toDay }))];
}

/** Shifts for another week. The caller loads that week and keeps these as unsaved drafts. */
export function copyWeekShifts(entries) {
  return (entries || []).map((entry) => copiedShift(entry, { userId: entry.user_id, dayOfWeek: entry.day_of_week }));
}
