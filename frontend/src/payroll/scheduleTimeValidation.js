import { computeScheduledHours, parseTimeToMinutes } from "./schedulePlanner";

function rangesOverlap(st1, et1, st2, et2) {
  const a0 = parseTimeToMinutes(st1);
  const a1 = parseTimeToMinutes(et1);
  const b0 = parseTimeToMinutes(st2);
  const b1 = parseTimeToMinutes(et2);
  if (a0 == null || a1 == null || b0 == null || b1 == null) return false;
  let endA = a1;
  let endB = b1;
  if (endA <= a0) endA += 24 * 60;
  if (endB <= b0) endB += 24 * 60;
  return a0 < endB && b0 < endA;
}

/**
 * @returns {{ errors: string[], warnings: string[] }}
 */
export function validateScheduleTimes({
  startTime,
  endTime,
  breakMinutes = 0,
  maxShiftHours,
  overnightEnabled = false,
  workDate,
  workerProfileId,
  editEntryId,
  draftEntries = [],
  worker,
  settings,
}) {
  const errors = [];
  const warnings = [];

  if (!normalize(startTime)) errors.push("Start time is required");
  if (!normalize(endTime)) errors.push("End time is required");
  if (errors.length) return { errors, warnings };

  const st = parseTimeToMinutes(startTime);
  const et = parseTimeToMinutes(endTime);
  if (st == null || et == null) return { errors, warnings };

  if (!overnightEnabled && et <= st) {
    errors.push("End time must be after start time (enable overnight shift for cross-midnight)");
  }

  const grossMins = et > st ? et - st : et - st + 24 * 60;
  const grossHours = grossMins / 60;
  const scheduled = computeScheduledHours(startTime, endTime, breakMinutes);

  if (maxShiftHours != null && Number(maxShiftHours) > 0 && scheduled > Number(maxShiftHours)) {
    errors.push(`Shift exceeds max allowed hours (${Number(maxShiftHours).toFixed(1)}h)`);
  }

  if (worker && workDate) {
    const dow = dayOfWeekMon0(workDate);
    const avail = (worker.availability || []).find((a) => Number(a.day_of_week) === dow);
    if (avail?.unavailable_flag) {
      warnings.push("This is outside worker availability (marked unavailable)");
    } else if (avail?.available_from && avail?.available_to) {
      const af = parseTimeToMinutes(avail.available_from);
      const at = parseTimeToMinutes(avail.available_to);
      if (af != null && at != null && (st < af || et > at)) {
        warnings.push("This is outside worker availability");
      }
    }
  }

  const sameDay = (draftEntries || []).filter(
    (e) =>
      String(e.worker_profile_id) === String(workerProfileId) &&
      String(e.work_date).slice(0, 10) === String(workDate).slice(0, 10) &&
      e.status !== "cancelled" &&
      e.status !== "replaced" &&
      String(e.id) !== String(editEntryId),
  );
  for (const other of sameDay) {
    if (rangesOverlap(startTime, endTime, other.start_time, other.end_time)) {
      errors.push("This overlaps another shift for the same worker");
      break;
    }
  }

  if (settings && workerProfileId && workDate) {
    const threshold = Number(settings?.overtime_threshold_hours || settings?.ot_weekly_threshold || 40);
    const weekStart = settings._weekStart;
    if (weekStart && threshold > 0) {
      const weekEntries = (draftEntries || []).filter(
        (e) =>
          String(e.worker_profile_id) === String(workerProfileId) &&
          String(e.work_date).slice(0, 10) >= weekStart &&
          e.status !== "cancelled" &&
          e.status !== "replaced" &&
          String(e.id) !== String(editEntryId),
      );
      let weekH = weekEntries.reduce((s, e) => s + Number(e.scheduled_hours || 0), 0);
      weekH += scheduled;
      if (weekH > threshold) {
        warnings.push("This may cause overtime");
      }
    }
  }

  return { errors, warnings };
}

function normalize(t) {
  if (!t) return "";
  return String(t).slice(0, 5);
}

function dayOfWeekMon0(ymd) {
  const [y, m, d] = ymd.split("-").map((x) => parseInt(x, 10));
  const dow = new Date(Date.UTC(y, m - 1, d, 12, 0, 0)).getUTCDay();
  return dow === 0 ? 6 : dow - 1;
}
