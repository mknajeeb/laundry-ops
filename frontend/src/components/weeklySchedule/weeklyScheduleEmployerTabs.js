/** Entity tab filtering for weekly schedule — WashPro / WashMate / VeeWash / Rinse Exclusive. */

import { EMPLOYER_AFFILIATION, employerAffiliationFromFlags } from "../../payroll/employerAffiliation";
import {
  BUSINESS_ENTITY,
  ENTITY_LABELS,
  entitiesForOrganization,
  normalizeOrgSlug,
  normalizeShiftEntity,
  normalizeWorkerEntity,
  shiftMatchesEntityTab,
  workerMatchesEntityTab,
} from "../../payroll/businessEntity";

export const ENTITY_TAB = BUSINESS_ENTITY;

export const ENTITY_TAB_LABELS = ENTITY_LABELS;

/** @deprecated use ENTITY_TAB */
export const EMPLOYER_TAB = {
  WASHPRO: BUSINESS_ENTITY.WASHPRO,
  WASHMATE: BUSINESS_ENTITY.WASHMATE,
  VEEWASH: BUSINESS_ENTITY.VEEWASH,
  RINSE_EXCLUSIVE: BUSINESS_ENTITY.RINSE_EXCLUSIVE,
  COMBINED: BUSINESS_ENTITY.COMBINED,
  /** legacy alias */
  VEEWASH_LEGACY: "veewash",
};

export const EMPLOYER_TAB_LABELS = ENTITY_TAB_LABELS;

export const SHIFT_ENTITY = {
  WASHPRO: BUSINESS_ENTITY.WASHPRO,
  WASHMATE: BUSINESS_ENTITY.WASHMATE,
  VEEWASH: BUSINESS_ENTITY.VEEWASH,
  RINSE_EXCLUSIVE: BUSINESS_ENTITY.RINSE_EXCLUSIVE,
};

/** @deprecated */
export const SHIFT_EMPLOYER_AFFILIATION = SHIFT_ENTITY;

export function resolveEmployeeEntity(employee, organizationSlug = null) {
  const explicit = employee?.business_entity || employee?.employer_affiliation;
  return normalizeWorkerEntity(explicit, organizationSlug) || employerAffiliationFromFlags(employee, organizationSlug);
}

export function resolveEntryEntity(entry, employee, organizationSlug = null) {
  const raw = entry?.employer_affiliation;
  const normalized = normalizeShiftEntity(raw, organizationSlug);
  if (normalized) return normalized;
  const profile = resolveEmployeeEntity(employee, organizationSlug);
  if (profile === BUSINESS_ENTITY.NONE) return null;
  if (profile === BUSINESS_ENTITY.RINSE_EXCLUSIVE) return SHIFT_ENTITY.RINSE_EXCLUSIVE;
  if (profile === BUSINESS_ENTITY.SHARED) return defaultShiftEntityForTab(BUSINESS_ENTITY.WASHPRO, organizationSlug);
  if (profile === BUSINESS_ENTITY.WASHMATE) return SHIFT_ENTITY.WASHMATE;
  if (profile === BUSINESS_ENTITY.VEEWASH) return SHIFT_ENTITY.VEEWASH;
  return SHIFT_ENTITY.WASHPRO;
}

export function visibleEntityTabs(entityScope) {
  const tabs = entityScope?.entity_tabs || entitiesForOrganization(entityScope?.organization_slug, {
    isPrivileged: entityScope?.combined_is_admin_view,
  });
  return tabs.filter((tab) => tab !== BUSINESS_ENTITY.COMBINED || entityScope?.combined_is_admin_view);
}

export function matchesEntityTab(employee, tab, organizationSlug = null) {
  return workerMatchesEntityTab(resolveEmployeeEntity(employee, organizationSlug), tab, organizationSlug);
}

export function matchesEntryEntityTab(entry, tab, employeesById = null, organizationSlug = null) {
  if (tab === BUSINESS_ENTITY.COMBINED) return true;
  const employee = employeesById?.get(Number(entry?.user_id));
  const workerEntity = resolveEmployeeEntity(employee, organizationSlug);
  if (workerEntity === BUSINESS_ENTITY.NONE) return false;
  const shiftEntity = resolveEntryEntity(entry, employee, organizationSlug);
  return shiftMatchesEntityTab(shiftEntity, tab, organizationSlug);
}

export function filterEntriesByEntityTab(entries, tab, employees = null, organizationSlug = null) {
  if (tab === BUSINESS_ENTITY.COMBINED) return entries || [];
  const employeesById = new Map((employees || []).map((row) => [Number(row.user_id), row]));
  return (entries || []).filter((entry) =>
    matchesEntryEntityTab(entry, tab, employeesById, organizationSlug),
  );
}

export function filterEmployeesByEntityTab(employees, tab, entries = null, organizationSlug = null) {
  const list = employees || [];
  if (tab === BUSINESS_ENTITY.COMBINED) return list;

  const allEntries = entries || [];
  const tabEntries = filterEntriesByEntityTab(allEntries, tab, list, organizationSlug);
  const userIdsWithTabEntries = new Set(tabEntries.map((entry) => Number(entry.user_id)));

  return list.filter((employee) => {
    const uid = Number(employee.user_id);
    const workerEntity = resolveEmployeeEntity(employee, organizationSlug);
    if (workerEntity === BUSINESS_ENTITY.NONE) return false;
    if (userIdsWithTabEntries.has(uid)) return true;
    const hasAnyEntry = allEntries.some((entry) => Number(entry.user_id) === uid);
    if (hasAnyEntry) return false;
    return matchesEntityTab(employee, tab, organizationSlug);
  });
}

export function countEmployeesForEntityTab(employees, tab, entries = null, organizationSlug = null) {
  if (tab === BUSINESS_ENTITY.COMBINED) {
    return filterEmployeesByEntityTab(employees, tab, entries, organizationSlug).length;
  }
  const tabEntries = filterEntriesByEntityTab(entries || [], tab, employees, organizationSlug);
  return new Set(tabEntries.map((entry) => Number(entry.user_id))).size;
}

export function pickDefaultEntityTab(entityScope, employees = null, entries = null) {
  const orgSlug = entityScope?.organization_slug;
  const tabs = visibleEntityTabs(entityScope).filter((tab) => tab !== BUSINESS_ENTITY.COMBINED);
  if (!tabs.length) return BUSINESS_ENTITY.WASHPRO;
  const scored = tabs.map((tab) => ({
    tab,
    count: countEmployeesForEntityTab(employees, tab, entries, orgSlug),
  }));
  scored.sort((a, b) => b.count - a.count);
  return scored[0]?.tab || entityScope?.default_entity || BUSINESS_ENTITY.WASHPRO;
}

export function defaultShiftEntityForTab(tab, organizationSlug = null) {
  if (tab === BUSINESS_ENTITY.RINSE_EXCLUSIVE) return SHIFT_ENTITY.RINSE_EXCLUSIVE;
  if (tab === BUSINESS_ENTITY.WASHMATE) return SHIFT_ENTITY.WASHMATE;
  if (tab === BUSINESS_ENTITY.VEEWASH) return SHIFT_ENTITY.VEEWASH;
  return defaultEntityForOrgTab(organizationSlug);
}

/** Shift entity values assignable from the shift card menu for this tenant. */
export function shiftEntityOptionsForOrg(organizationSlug = null) {
  const slug = normalizeOrgSlug(organizationSlug);
  if (slug === "washmate") return [SHIFT_ENTITY.WASHMATE];
  if (slug === "veewash") return [SHIFT_ENTITY.VEEWASH, SHIFT_ENTITY.RINSE_EXCLUSIVE];
  return [SHIFT_ENTITY.WASHPRO, SHIFT_ENTITY.RINSE_EXCLUSIVE];
}

function defaultEntityForOrgTab(organizationSlug) {
  const slug = normalizeOrgSlug(organizationSlug);
  if (slug === "washmate") return SHIFT_ENTITY.WASHMATE;
  if (slug === "veewash") return SHIFT_ENTITY.VEEWASH;
  return SHIFT_ENTITY.WASHPRO;
}

/** Legacy exports */
export const filterEntriesByEmployerTab = filterEntriesByEntityTab;
export const filterEmployeesByEmployerTab = filterEmployeesByEntityTab;
export const countEmployeesForEmployerTab = countEmployeesForEntityTab;
export const pickDefaultEmployerTab = pickDefaultEntityTab;
export const defaultShiftEmployerForTab = defaultShiftEntityForTab;
export const resolveEntryEmployerAffiliation = resolveEntryEntity;
export const resolveEmployeeEmployerAffiliation = resolveEmployeeEntity;
