/**
 * Shared Mobile Ops role/work-type display helpers.
 * Canonical English tokens stay stable for grouping; pass t() for locale.
 */

import {
  categoryDisplayBucket,
  displayRoleLabel,
  formatEmployeeAssignmentLabel as formatAssignmentEn,
} from "./switchRoleFlowHelpers";

export const ROLE_I18N_KEYS = {
  "Wash-Dry": "mobileOps.role.washDry",
  Sort: "mobileOps.role.sort",
  Fold: "mobileOps.role.fold",
  "Wash-Dry-Fold": "mobileOps.role.washDryFold",
};

export const WORK_I18N_KEYS = {
  "Rinse Wash & Fold": "mobileOps.work.rinseWashFold",
  "Rinse Hang Dry": "mobileOps.work.rinseHangDry",
  "Non-Rinse": "mobileOps.work.nonRinse",
};

const identityT = (key) => key;

/** Employee-facing role from backend role_code / role object. */
export function displayRole(roleOrCode, t = identityT) {
  const canonical =
    typeof roleOrCode === "string" && !roleOrCode.includes(" ")
      ? displayRoleLabel({ role_code: roleOrCode, role_name: roleOrCode })
      : displayRoleLabel(roleOrCode);
  const key = ROLE_I18N_KEYS[canonical];
  return key ? t(key) : canonical;
}

/** Employee-facing work type from category code / category object. */
export function displayWorkType(categoryOrCode, t = identityT) {
  const cat =
    typeof categoryOrCode === "string"
      ? { code: categoryOrCode, name: categoryOrCode }
      : categoryOrCode;
  const canonical = categoryDisplayBucket(cat);
  const key = WORK_I18N_KEYS[canonical];
  return key ? t(key) : canonical;
}

/** Localized "Wash-Dry | Rinse Wash & Fold" assignment line. */
export function formatEmployeeAssignmentLabel(args = {}, t = identityT) {
  const en = formatAssignmentEn(args);
  if (!en || !t || t === identityT) return en;
  const roleLabel = displayRole(
    args.role || {
      role_name: args.roleName,
      role_code: args.roleCode,
      name: args.roleName,
      code: args.roleCode,
    },
    t,
  );
  const work = displayWorkType(
    args.category || {
      name: args.categoryName,
      code: args.categoryCode,
      category_code: args.categoryCode,
    },
    t,
  );
  if (roleLabel && work) return `${roleLabel} | ${work}`;
  return roleLabel || work || en;
}

export function translateCanonicalRoleLabel(canonical, t = identityT) {
  const key = ROLE_I18N_KEYS[canonical];
  return key ? t(key) : canonical;
}

export function translateCanonicalWorkLabel(canonical, t = identityT) {
  const key = WORK_I18N_KEYS[canonical];
  return key ? t(key) : canonical;
}

/** Build localized success line from switch API body. */
export function successAssignmentLabelFromBody(body, t = identityT) {
  const seg = body?.segment && typeof body.segment === "object" ? body.segment : {};
  const fromCodes = formatEmployeeAssignmentLabel(
    {
      roleCode: seg.role_code || body?.role_code,
      roleName: seg.role_name_snapshot || body?.role_name,
      categoryCode: seg.category_code || body?.category_code,
      categoryName: seg.category_name_snapshot || body?.category_name,
    },
    t,
  );
  if (fromCodes) return fromCodes;
  // Prefer employee-facing fields; never invent Operator/Folder/RINSE_* from raw display_label.
  return (
    body?.employee_display_label ||
    body?.display_label ||
    seg.employee_display_label ||
    ""
  );
}
