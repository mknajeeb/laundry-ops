/** Employer affiliation on worker profiles — mirrors backend/payroll_employer_affiliation.py */

export const EMPLOYER_AFFILIATION = {
  RINSE_EXCLUSIVE: "rinse_exclusive",
  VEEWASH: "veewash",
  BOTH: "both",
  NONE: "none",
};

export const EMPLOYER_AFFILIATION_OPTIONS = [
  { value: EMPLOYER_AFFILIATION.RINSE_EXCLUSIVE, label: "Rinse Exclusive" },
  { value: EMPLOYER_AFFILIATION.VEEWASH, label: "VeeWash" },
  { value: EMPLOYER_AFFILIATION.BOTH, label: "Both" },
  { value: EMPLOYER_AFFILIATION.NONE, label: "None" },
];

function streamFlag(value) {
  return value !== false && value !== 0;
}

export function employerAffiliationFromFlags(worker) {
  if (!worker) return EMPLOYER_AFFILIATION.VEEWASH;
  const rinse = streamFlag(worker.can_work_rinse);
  const dropOff = streamFlag(worker.can_work_drop_off);
  const both = streamFlag(worker.can_work_both);
  if (!rinse && !dropOff && !both) return EMPLOYER_AFFILIATION.NONE;
  if (rinse && dropOff && both) return EMPLOYER_AFFILIATION.BOTH;
  if (rinse && !dropOff && !both) return EMPLOYER_AFFILIATION.RINSE_EXCLUSIVE;
  if (!rinse && dropOff && !both) return EMPLOYER_AFFILIATION.VEEWASH;
  if (rinse && !dropOff) return EMPLOYER_AFFILIATION.RINSE_EXCLUSIVE;
  if (dropOff) return EMPLOYER_AFFILIATION.VEEWASH;
  return EMPLOYER_AFFILIATION.VEEWASH;
}

export function flagsFromEmployerAffiliation(affiliation) {
  const aff = String(affiliation || "").trim().toLowerCase();
  if (aff === EMPLOYER_AFFILIATION.NONE) {
    return { can_work_rinse: false, can_work_drop_off: false, can_work_both: false };
  }
  if (aff === EMPLOYER_AFFILIATION.RINSE_EXCLUSIVE) {
    return { can_work_rinse: true, can_work_drop_off: false, can_work_both: false };
  }
  if (aff === EMPLOYER_AFFILIATION.BOTH) {
    return { can_work_rinse: true, can_work_drop_off: true, can_work_both: true };
  }
  return { can_work_rinse: false, can_work_drop_off: true, can_work_both: false };
}

export function employerAffiliationLabel(affiliation) {
  return EMPLOYER_AFFILIATION_OPTIONS.find((opt) => opt.value === affiliation)?.label || affiliation || "—";
}
