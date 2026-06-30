/** Worker business entity / employer affiliation — mirrors backend/payroll_employer_affiliation.py */

import {
  BUSINESS_ENTITY,
  WORKER_ENTITY_OPTIONS,
  defaultEntityForOrg,
  entityLabel,
  entitySummaryTitle,
  normalizeWorkerEntity,
  resolveStoredWorkerEntity,
  workerEntityOptionsForOrganization,
} from "./businessEntity";

/** @deprecated use entityLabel(defaultEntityForOrg(slug)) */
export const NON_RINSE_EMPLOYER_LABEL = "WashPro";

export const EMPLOYER_AFFILIATION = BUSINESS_ENTITY;

export const EMPLOYER_AFFILIATION_OPTIONS = WORKER_ENTITY_OPTIONS;

export { entityLabel, entitySummaryTitle, workerEntityOptionsForOrganization, resolveStoredWorkerEntity };

function streamFlag(value) {
  return value !== false && value !== 0;
}

export function employerAffiliationFromFlags(worker, organizationSlug = null) {
  if (!worker) return defaultEntityForOrg(organizationSlug);
  const explicit = normalizeWorkerEntity(worker.business_entity || worker.employer_affiliation, organizationSlug);
  if (explicit) return explicit;

  const rinse = streamFlag(worker.can_work_rinse);
  const dropOff = streamFlag(worker.can_work_drop_off);
  const both = streamFlag(worker.can_work_both);
  if (!rinse && !dropOff && !both) return BUSINESS_ENTITY.NONE;
  if (rinse && dropOff && both) return BUSINESS_ENTITY.SHARED;
  if (rinse && !dropOff && !both) return BUSINESS_ENTITY.RINSE_EXCLUSIVE;
  if (dropOff && !rinse) return defaultEntityForOrg(organizationSlug);
  if (rinse && !dropOff) return BUSINESS_ENTITY.RINSE_EXCLUSIVE;
  return defaultEntityForOrg(organizationSlug);
}

export function flagsFromEmployerAffiliation(affiliation) {
  const aff = normalizeWorkerEntity(affiliation) || defaultEntityForOrg(null);
  if (aff === BUSINESS_ENTITY.NONE) {
    return { can_work_rinse: false, can_work_drop_off: false, can_work_both: false };
  }
  if (aff === BUSINESS_ENTITY.RINSE_EXCLUSIVE) {
    return { can_work_rinse: true, can_work_drop_off: false, can_work_both: false };
  }
  if (aff === BUSINESS_ENTITY.SHARED) {
    return { can_work_rinse: true, can_work_drop_off: true, can_work_both: true };
  }
  return { can_work_rinse: false, can_work_drop_off: true, can_work_both: false };
}

export function employerAffiliationLabel(affiliation) {
  return EMPLOYER_AFFILIATION_OPTIONS.find((opt) => opt.value === affiliation)?.label || affiliation || "—";
}
