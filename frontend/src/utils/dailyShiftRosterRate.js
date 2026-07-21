/** Default hourly rates for daily shift roster entries (not payroll processing). */

export const ROSTER_DEFAULT_W2_RATE = 19.5;
export const ROSTER_DEFAULT_CONTRACTOR_RATE = 17;

export function isContractorCategory(category) {
  const cat = String(category || "").trim().toLowerCase();
  return cat === "contractor_1099" || cat === "temp" || cat === "1099";
}

export function categoryDefaultHourlyRate(category) {
  return isContractorCategory(category) ? ROSTER_DEFAULT_CONTRACTOR_RATE : ROSTER_DEFAULT_W2_RATE;
}

/** Profile rate first, then W2 / contractor category default. */
export function resolveRosterHourlyRate(worker) {
  if (!worker) return ROSTER_DEFAULT_W2_RATE;
  const profileRate = Number(worker.default_hourly_rate || worker.hourly_rate || 0);
  if (Number.isFinite(profileRate) && profileRate > 0) return profileRate;
  return categoryDefaultHourlyRate(worker.worker_category);
}

export function normalizeRosterNameKey(name) {
  return String(name || "").trim().toLowerCase();
}

export function stripParentheticalSuffix(name) {
  const text = String(name || "").trim();
  const idx = text.indexOf(" (");
  return idx > 0 ? text.slice(0, idx).trim() : text;
}

export function findWorkerForEmployeeName(workers = [], employeeName, foldingOptions = []) {
  const name = String(employeeName || "").trim();
  if (!name) return null;

  const foldingOpt = foldingOptions.find((o) => o.user_name === name);
  if (foldingOpt?.mapped_user_id) {
    const byId = workers.find((w) => Number(w.user_id) === Number(foldingOpt.mapped_user_id));
    if (byId) return byId;
  }

  const keys = new Set([
    normalizeRosterNameKey(name),
    normalizeRosterNameKey(stripParentheticalSuffix(name)),
  ]);

  for (const worker of workers) {
    const candidates = [worker.worker_name, worker.display_name];
    for (const candidate of candidates) {
      if (keys.has(normalizeRosterNameKey(candidate))) return worker;
    }
  }
  return null;
}

export function resolveRosterRateForEmployeeName(workers = [], employeeName, foldingOptions = []) {
  return resolveRosterHourlyRate(findWorkerForEmployeeName(workers, employeeName, foldingOptions));
}

export function formatRosterRateInput(rate) {
  const v = Number(rate);
  if (!Number.isFinite(v) || v <= 0) return "";
  return v.toFixed(2);
}

function parseRosterTimeValue(value) {
  if (value == null || value === "") return null;
  const text = String(value).trim();
  const match = /^(\d{1,2}):(\d{2})(?::(\d{2}))?$/.exec(text);
  if (!match) return null;
  const hours = Number(match[1]);
  const minutes = Number(match[2]);
  if (!Number.isFinite(hours) || !Number.isFinite(minutes)) return null;
  if (hours < 0 || hours > 23 || minutes < 0 || minutes > 59) return null;
  return { hours, minutes };
}

function rosterTimeToMinutes(value) {
  const parsed = parseRosterTimeValue(value);
  if (!parsed) return null;
  return parsed.hours * 60 + parsed.minutes;
}

function calcRosterHours(startTime, endTime, breakMinutes = 0) {
  const start = rosterTimeToMinutes(startTime);
  const end = rosterTimeToMinutes(endTime);
  if (start == null || end == null) return null;
  let endMinutes = end;
  if (endMinutes <= start) endMinutes += 24 * 60;
  const workedMinutes = Math.max(0, endMinutes - start - Math.max(0, Number(breakMinutes) || 0));
  return Math.round((workedMinutes / 60) * 10000) / 10000;
}

function calcRosterCost(hours, rate) {
  const h = Number(hours);
  const r = Number(rate);
  if (!Number.isFinite(h) || !Number.isFinite(r)) return null;
  return Math.round(h * r * 100) / 100;
}

function rosterTimesModified(entry) {
  if (!entry || typeof entry !== "object") return false;
  const originalStart = parseRosterTimeValue(entry.original_start_time);
  if (!originalStart) return false;
  const currentStart = parseRosterTimeValue(entry.start_time);
  const currentEnd = parseRosterTimeValue(entry.end_time);
  const originalEnd = parseRosterTimeValue(entry.original_end_time);
  if (
    currentStart?.hours !== originalStart.hours
    || currentStart?.minutes !== originalStart.minutes
  ) {
    return true;
  }
  if (
    originalEnd
    && (
      currentEnd?.hours !== originalEnd.hours
      || currentEnd?.minutes !== originalEnd.minutes
    )
  ) {
    return true;
  }
  return false;
}

/** Normalize a payroll-prefill or draft roster row after dialog edits. */
export function serializeRosterDraftEntry(data = {}) {
  const shiftOpen = Boolean(data.shift_open || !data.end_time);
  const breakMinutes = Math.max(0, Number(data.break_minutes) || 0);
  const rate = Math.round(Math.max(0, Number(data.rate) || 0) * 100) / 100;
  const startTime = data.start_time || null;
  const endTime = shiftOpen ? null : (data.end_time || null);
  let hours = null;
  let cost = null;
  if (startTime && endTime && !shiftOpen) {
    hours = calcRosterHours(startTime, endTime, breakMinutes);
    cost = hours != null ? calcRosterCost(hours, rate) : null;
  }

  const out = {
    ...data,
    employee_name: String(data.employee_name || "").trim(),
    role: String(data.role || "folder").trim().toLowerCase() || "folder",
    start_time: startTime,
    end_time: endTime,
    original_start_time: data.original_start_time || null,
    original_end_time: data.original_end_time || null,
    break_minutes: breakMinutes,
    rate,
    notes: String(data.notes || "").trim() || null,
    excluded: Boolean(data.excluded),
    shift_open: shiftOpen,
    hours,
    cost,
  };
  out.times_modified = rosterTimesModified(out);
  return out;
}

/**
 * Lightweight hours/cost calculator for a roster entry.
 * Kept from the stashed branch as a public helper; implemented on the shared
 * time helpers above so both branches' behavior is preserved without a
 * duplicate time parser.
 */
export function calcRosterEntryMetrics(entry) {
  const shiftOpen = Boolean(entry?.shift_open || !entry?.end_time);
  const startMin = rosterTimeToMinutes(entry?.start_time);
  const endMin = rosterTimeToMinutes(entry?.end_time);
  const rate = Number(entry?.rate) || 0;
  if (shiftOpen || startMin == null || endMin == null) {
    return { hours: null, cost: null, shift_open: shiftOpen };
  }
  const hours = calcRosterHours(entry?.start_time, entry?.end_time, entry?.break_minutes);
  const cost = hours != null ? calcRosterCost(hours, rate) : null;
  return { hours, cost, shift_open: false };
}
