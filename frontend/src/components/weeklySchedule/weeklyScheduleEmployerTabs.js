/** Employer tab filtering — Rinse Exclusive vs VeeWash (per-shift + worker profile). */

import { EMPLOYER_AFFILIATION, employerAffiliationFromFlags } from "../../payroll/employerAffiliation";

export const EMPLOYER_TAB = {
  VEEWASH: "veewash",
  RINSE_EXCLUSIVE: "rinse_exclusive",
  COMBINED: "combined",
};

export const EMPLOYER_TAB_LABELS = {
  [EMPLOYER_TAB.VEEWASH]: "VeeWash",
  [EMPLOYER_TAB.RINSE_EXCLUSIVE]: "Rinse Exclusive",
  [EMPLOYER_TAB.COMBINED]: "Combined",
};

export const SHIFT_EMPLOYER_AFFILIATION = {
  VEEWASH: EMPLOYER_AFFILIATION.VEEWASH,
  RINSE_EXCLUSIVE: EMPLOYER_AFFILIATION.RINSE_EXCLUSIVE,
};

/** @deprecated use employerAffiliationFromFlags */
export function isRinseExclusiveEmployee(employee) {
  return employerAffiliationFromFlags(employee) === EMPLOYER_AFFILIATION.RINSE_EXCLUSIVE;
}

export function resolveEntryEmployerAffiliation(entry, employee) {
  const raw = entry?.employer_affiliation;
  if (raw === SHIFT_EMPLOYER_AFFILIATION.VEEWASH || raw === SHIFT_EMPLOYER_AFFILIATION.RINSE_EXCLUSIVE) {
    return raw;
  }
  const profile = employerAffiliationFromFlags(employee);
  if (profile === EMPLOYER_AFFILIATION.RINSE_EXCLUSIVE) return SHIFT_EMPLOYER_AFFILIATION.RINSE_EXCLUSIVE;
  return SHIFT_EMPLOYER_AFFILIATION.VEEWASH;
}

export function matchesEmployerTab(employee, tab) {
  const affiliation = employerAffiliationFromFlags(employee);
  if (affiliation === EMPLOYER_AFFILIATION.NONE) return false;
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
  const affiliation = resolveEntryEmployerAffiliation(entry, employee);
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

  const tabEntries = filterEntriesByEmployerTab(entries || [], tab, list);
  const userIdsWithTabEntries = new Set(tabEntries.map((entry) => Number(entry.user_id)));

  return list.filter((employee) => {
    const uid = Number(employee.user_id);
    if (userIdsWithTabEntries.has(uid)) return true;
    return matchesEmployerTab(employee, tab);
  });
}

export function countEmployeesForEmployerTab(employees, tab, entries = null) {
  return filterEmployeesByEmployerTab(employees, tab, entries).length;
}

/** Default to whichever tab has more employees (VeeWash when tied). */
export function pickDefaultEmployerTab(employees, entries = null) {
  const rinseCount = countEmployeesForEmployerTab(employees, EMPLOYER_TAB.RINSE_EXCLUSIVE, entries);
  const veewashCount = countEmployeesForEmployerTab(employees, EMPLOYER_TAB.VEEWASH, entries);
  return veewashCount >= rinseCount ? EMPLOYER_TAB.VEEWASH : EMPLOYER_TAB.RINSE_EXCLUSIVE;
}

export function defaultShiftEmployerForTab(tab) {
  if (tab === EMPLOYER_TAB.RINSE_EXCLUSIVE) return SHIFT_EMPLOYER_AFFILIATION.RINSE_EXCLUSIVE;
  return SHIFT_EMPLOYER_AFFILIATION.VEEWASH;
}
