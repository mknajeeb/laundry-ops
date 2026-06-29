/** Employer tab filtering — Rinse Exclusive vs Washpro (non-Rinse; per-shift + worker profile). */

import {
  EMPLOYER_AFFILIATION,
  NON_RINSE_EMPLOYER_LABEL,
  employerAffiliationFromFlags,
} from "../../payroll/employerAffiliation";

export const EMPLOYER_TAB = {
  VEEWASH: "veewash",
  RINSE_EXCLUSIVE: "rinse_exclusive",
  COMBINED: "combined",
};

export const EMPLOYER_TAB_LABELS = {
  [EMPLOYER_TAB.VEEWASH]: NON_RINSE_EMPLOYER_LABEL,
  [EMPLOYER_TAB.RINSE_EXCLUSIVE]: "Rinse Exclusive",
  [EMPLOYER_TAB.COMBINED]: "Combined",
};

export const SHIFT_EMPLOYER_AFFILIATION = {
  VEEWASH: EMPLOYER_AFFILIATION.VEEWASH,
  RINSE_EXCLUSIVE: EMPLOYER_AFFILIATION.RINSE_EXCLUSIVE,
};

/** @deprecated use employerAffiliationFromFlags */
export function isRinseExclusiveEmployee(employee) {
  return resolveEmployeeEmployerAffiliation(employee) === EMPLOYER_AFFILIATION.RINSE_EXCLUSIVE;
}

export function resolveEmployeeEmployerAffiliation(employee) {
  return employerAffiliationFromFlags(employee);
}

export function resolveEntryEmployerAffiliation(entry, employee) {
  const raw = entry?.employer_affiliation;
  if (raw === SHIFT_EMPLOYER_AFFILIATION.VEEWASH || raw === SHIFT_EMPLOYER_AFFILIATION.RINSE_EXCLUSIVE) {
    return raw;
  }
  const profile = resolveEmployeeEmployerAffiliation(employee);
  if (profile === EMPLOYER_AFFILIATION.NONE) return null;
  if (profile === EMPLOYER_AFFILIATION.RINSE_EXCLUSIVE || profile === EMPLOYER_AFFILIATION.BOTH) {
    return SHIFT_EMPLOYER_AFFILIATION.RINSE_EXCLUSIVE;
  }
  return SHIFT_EMPLOYER_AFFILIATION.VEEWASH;
}

export function matchesEmployerTab(employee, tab) {
  const affiliation = resolveEmployeeEmployerAffiliation(employee);
  if (affiliation === EMPLOYER_AFFILIATION.NONE) return tab === EMPLOYER_TAB.COMBINED;
  if (tab === EMPLOYER_TAB.COMBINED) return true;
  if (tab === EMPLOYER_TAB.RINSE_EXCLUSIVE) {
    return affiliation === EMPLOYER_AFFILIATION.RINSE_EXCLUSIVE || affiliation === EMPLOYER_AFFILIATION.BOTH;
  }
  if (tab === EMPLOYER_TAB.VEEWASH) {
    return affiliation === EMPLOYER_AFFILIATION.VEEWASH || affiliation === EMPLOYER_AFFILIATION.BOTH;
  }
  return true;
}

export function matchesEntryEmployerTab(entry, tab, employeesById = null) {
  if (tab === EMPLOYER_TAB.COMBINED) return true;
  const employee = employeesById?.get(Number(entry?.user_id));
  const employeeAff = resolveEmployeeEmployerAffiliation(employee);
  if (employeeAff === EMPLOYER_AFFILIATION.NONE) return false;
  const affiliation = resolveEntryEmployerAffiliation(entry, employee);
  if (!affiliation) return false;
  if (tab === EMPLOYER_TAB.RINSE_EXCLUSIVE) return affiliation === SHIFT_EMPLOYER_AFFILIATION.RINSE_EXCLUSIVE;
  if (tab === EMPLOYER_TAB.VEEWASH) return affiliation === SHIFT_EMPLOYER_AFFILIATION.VEEWASH;
  return true;
}

export function filterEntriesByEmployerTab(entries, tab, employees = null) {
  if (tab === EMPLOYER_TAB.COMBINED) return entries || [];
  const employeesById = new Map((employees || []).map((row) => [Number(row.user_id), row]));
  return (entries || []).filter((entry) => matchesEntryEmployerTab(entry, tab, employeesById));
}

export function filterEmployeesByEmployerTab(employees, tab, entries = null) {
  const list = employees || [];
  if (tab === EMPLOYER_TAB.COMBINED) return list;

  const allEntries = entries || [];
  const tabEntries = filterEntriesByEmployerTab(allEntries, tab, list);
  const userIdsWithTabEntries = new Set(tabEntries.map((entry) => Number(entry.user_id)));

  return list.filter((employee) => {
    const uid = Number(employee.user_id);
    const affiliation = resolveEmployeeEmployerAffiliation(employee);
    if (affiliation === EMPLOYER_AFFILIATION.NONE) return false;
    if (userIdsWithTabEntries.has(uid)) return true;
    const hasAnyEntry = allEntries.some((entry) => Number(entry.user_id) === uid);
    if (hasAnyEntry) return false;
    return matchesEmployerTab(employee, tab);
  });
}

/** Tab badge count — employees with at least one shift assigned to this employer. */
export function countEmployeesForEmployerTab(employees, tab, entries = null) {
  if (tab === EMPLOYER_TAB.COMBINED) {
    return filterEmployeesByEmployerTab(employees, tab, entries).length;
  }
  const tabEntries = filterEntriesByEmployerTab(entries || [], tab, employees);
  return new Set(tabEntries.map((entry) => Number(entry.user_id))).size;
}

/** Default to whichever tab has more employees (Washpro when tied). */
export function pickDefaultEmployerTab(employees, entries = null) {
  const rinseCount = countEmployeesForEmployerTab(employees, EMPLOYER_TAB.RINSE_EXCLUSIVE, entries);
  const veewashCount = countEmployeesForEmployerTab(employees, EMPLOYER_TAB.VEEWASH, entries);
  return veewashCount >= rinseCount ? EMPLOYER_TAB.VEEWASH : EMPLOYER_TAB.RINSE_EXCLUSIVE;
}

export function defaultShiftEmployerForTab(tab) {
  if (tab === EMPLOYER_TAB.RINSE_EXCLUSIVE) return SHIFT_EMPLOYER_AFFILIATION.RINSE_EXCLUSIVE;
  return SHIFT_EMPLOYER_AFFILIATION.VEEWASH;
}
