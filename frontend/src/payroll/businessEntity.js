/** Business entity model — mirrors backend/business_entity.py */

export const BUSINESS_ENTITY = {
  WASHPRO: "washpro",
  WASHMATE: "washmate",
  VEEWASH: "veewash",
  RINSE_EXCLUSIVE: "rinse_exclusive",
  SHARED: "shared",
  NONE: "none",
  COMBINED: "combined",
};

export const ENTITY_LABELS = {
  [BUSINESS_ENTITY.WASHPRO]: "WashPro",
  [BUSINESS_ENTITY.WASHMATE]: "WashMate",
  [BUSINESS_ENTITY.VEEWASH]: "VeeWash",
  [BUSINESS_ENTITY.RINSE_EXCLUSIVE]: "Rinse Exclusive",
  [BUSINESS_ENTITY.SHARED]: "Shared",
  [BUSINESS_ENTITY.NONE]: "None",
  [BUSINESS_ENTITY.COMBINED]: "Combined (Admin)",
};

export const WORKER_ENTITY_OPTIONS = [
  { value: BUSINESS_ENTITY.WASHPRO, label: ENTITY_LABELS[BUSINESS_ENTITY.WASHPRO] },
  { value: BUSINESS_ENTITY.WASHMATE, label: ENTITY_LABELS[BUSINESS_ENTITY.WASHMATE] },
  { value: BUSINESS_ENTITY.VEEWASH, label: ENTITY_LABELS[BUSINESS_ENTITY.VEEWASH] },
  { value: BUSINESS_ENTITY.RINSE_EXCLUSIVE, label: ENTITY_LABELS[BUSINESS_ENTITY.RINSE_EXCLUSIVE] },
  { value: BUSINESS_ENTITY.SHARED, label: ENTITY_LABELS[BUSINESS_ENTITY.SHARED] },
  { value: BUSINESS_ENTITY.NONE, label: ENTITY_LABELS[BUSINESS_ENTITY.NONE] },
];

export function normalizeOrgSlug(raw) {
  return String(raw || "washpro").trim().toLowerCase() || "washpro";
}

export function defaultEntityForOrg(orgSlug) {
  const slug = normalizeOrgSlug(orgSlug);
  if (slug === "washmate") return BUSINESS_ENTITY.WASHMATE;
  if (slug === "veewash") return BUSINESS_ENTITY.VEEWASH;
  return BUSINESS_ENTITY.WASHPRO;
}

export function normalizeWorkerEntity(raw, organizationSlug = null) {
  const aff = String(raw || "").trim().toLowerCase();
  if (aff === "both") return BUSINESS_ENTITY.SHARED;
  if (Object.values(BUSINESS_ENTITY).includes(aff)) return aff;
  return null;
}

export function normalizeShiftEntity(raw, organizationSlug = null) {
  const aff = String(raw || "").trim().toLowerCase();
  if (aff === "veewash") {
    return normalizeOrgSlug(organizationSlug) === "veewash"
      ? BUSINESS_ENTITY.VEEWASH
      : BUSINESS_ENTITY.WASHPRO;
  }
  if (
    aff === BUSINESS_ENTITY.WASHPRO ||
    aff === BUSINESS_ENTITY.WASHMATE ||
    aff === BUSINESS_ENTITY.VEEWASH ||
    aff === BUSINESS_ENTITY.RINSE_EXCLUSIVE
  ) {
    return aff;
  }
  return null;
}

export function entityLabel(entity) {
  return ENTITY_LABELS[String(entity || "").toLowerCase()] || entity || "—";
}

/** Worker entity options allowed for this tenant login. */
export function workerEntityOptionsForOrganization(orgSlug) {
  const slug = normalizeOrgSlug(orgSlug);
  if (slug === "washmate") {
    return WORKER_ENTITY_OPTIONS.filter((opt) =>
      [BUSINESS_ENTITY.WASHMATE, BUSINESS_ENTITY.SHARED, BUSINESS_ENTITY.NONE].includes(opt.value),
    );
  }
  if (slug === "veewash") {
    return WORKER_ENTITY_OPTIONS.filter((opt) =>
      [BUSINESS_ENTITY.VEEWASH, BUSINESS_ENTITY.SHARED, BUSINESS_ENTITY.NONE].includes(opt.value),
    );
  }
  return WORKER_ENTITY_OPTIONS.filter((opt) =>
    [
      BUSINESS_ENTITY.WASHPRO,
      BUSINESS_ENTITY.RINSE_EXCLUSIVE,
      BUSINESS_ENTITY.SHARED,
      BUSINESS_ENTITY.NONE,
    ].includes(opt.value),
  );
}

export function entitySummaryTitle(orgSlug) {
  const slug = normalizeOrgSlug(orgSlug);
  if (slug === "washmate") return "WashMate · Shared · None";
  if (slug === "veewash") return "VeeWash · Shared · None";
  return "WashPro · Rinse Exclusive · Shared · None";
}

export function resolveStoredWorkerEntity(row, organizationSlug = null) {
  const raw = row?.business_entity || row?.employer_affiliation;
  const normalized = normalizeWorkerEntity(raw, organizationSlug);
  if (normalized) return normalized;
  return null;
}

export function entitiesForOrganization(orgSlug, { isPrivileged = false } = {}) {
  const slug = normalizeOrgSlug(orgSlug);
  let tabs;
  if (slug === "washmate") tabs = [BUSINESS_ENTITY.WASHMATE];
  else if (slug === "veewash") tabs = [BUSINESS_ENTITY.VEEWASH];
  else tabs = [BUSINESS_ENTITY.WASHPRO, BUSINESS_ENTITY.RINSE_EXCLUSIVE];
  if (isPrivileged) tabs = [...tabs, BUSINESS_ENTITY.COMBINED];
  return tabs;
}

export function workerMatchesEntityTab(workerEntity, tab, organizationSlug = null) {
  const tabKey = String(tab || "").toLowerCase();
  const entity = normalizeWorkerEntity(workerEntity, organizationSlug) || BUSINESS_ENTITY.NONE;
  if (tabKey === BUSINESS_ENTITY.COMBINED) return entity !== BUSINESS_ENTITY.NONE;
  if (entity === BUSINESS_ENTITY.NONE) return false;
  if (entity === BUSINESS_ENTITY.SHARED) {
    return entitiesForOrganization(organizationSlug).includes(tabKey);
  }
  return entity === tabKey;
}

export function shiftMatchesEntityTab(shiftEntity, tab, organizationSlug = null) {
  const tabKey = String(tab || "").toLowerCase();
  const entity = normalizeShiftEntity(shiftEntity, organizationSlug);
  if (tabKey === BUSINESS_ENTITY.COMBINED) return Boolean(entity);
  return entity === tabKey;
}
