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
