/** Employer tab filtering — Rinse Exclusive vs VeeWash staff (from worker profile flags). */

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

/** @deprecated use employerAffiliationFromFlags */
export function isRinseExclusiveEmployee(employee) {
  return employerAffiliationFromFlags(employee) === EMPLOYER_AFFILIATION.RINSE_EXCLUSIVE;
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
