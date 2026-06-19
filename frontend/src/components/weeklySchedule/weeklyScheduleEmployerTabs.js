/** Employer tab filtering — Rinse Exclusive vs VeeWash staff (frontend-only, no schedule mutation). */

export const EMPLOYER_TAB = {
  VEEWASH: "veewash",
  RINSE_EXCLUSIVE: "rinse_exclusive",
};

export const EMPLOYER_TAB_LABELS = {
  [EMPLOYER_TAB.VEEWASH]: "VeeWash",
  [EMPLOYER_TAB.RINSE_EXCLUSIVE]: "Rinse Exclusive",
};

function streamFlag(value) {
  return value !== false && value !== 0;
}

/** Rinse-only staff: flagged for Rinse stream but not Drop Off or Both. */
export function isRinseExclusiveEmployee(employee) {
  const rinse = streamFlag(employee?.can_work_rinse);
  const dropOff = streamFlag(employee?.can_work_drop_off);
  const both = streamFlag(employee?.can_work_both);
  return rinse && !dropOff && !both;
}

export function matchesEmployerTab(employee, tab) {
  if (tab === EMPLOYER_TAB.RINSE_EXCLUSIVE) return isRinseExclusiveEmployee(employee);
  return !isRinseExclusiveEmployee(employee);
}

export function filterEmployeesByEmployerTab(employees, tab) {
  return (employees || []).filter((employee) => matchesEmployerTab(employee, tab));
}

export function countEmployeesForEmployerTab(employees, tab) {
  return filterEmployeesByEmployerTab(employees, tab).length;
}

/** Default to whichever tab has more employees (VeeWash when tied). */
export function pickDefaultEmployerTab(employees) {
  const rinseCount = countEmployeesForEmployerTab(employees, EMPLOYER_TAB.RINSE_EXCLUSIVE);
  const veewashCount = countEmployeesForEmployerTab(employees, EMPLOYER_TAB.VEEWASH);
  return veewashCount >= rinseCount ? EMPLOYER_TAB.VEEWASH : EMPLOYER_TAB.RINSE_EXCLUSIVE;
}
