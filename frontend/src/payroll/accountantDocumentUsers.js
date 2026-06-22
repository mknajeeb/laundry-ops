/** Payroll Documents — worker lists by category (W-2 employees on payroll, not platform login accounts). */

import { PAYROLL_DOCUMENT_CATEGORY_OPTIONS } from "./payrollDocumentChecklists";

/** Accountant Documents tab: W-2 only for now (expand later). */
export const ACCOUNTANT_DOC_CATEGORY_OPTIONS = PAYROLL_DOCUMENT_CATEGORY_OPTIONS.filter(
  (o) => o.value === "w2",
);

/** Normalized display names for non-payroll system accounts (Alliance, VeeWash admin). */
export const SYSTEM_USER_KNOWN_DISPLAY_NAMES = new Set([
  "alliance business consultant",
  "new veewash admin",
]);

/** Backup ids when display names differ across tenants (org3 VeeWash admin). */
export const SYSTEM_USER_KNOWN_IDS = new Set([15]);

const SYSTEM_ROLE_CODES = new Set(["ACCOUNTANT", "ADMIN", "PLATFORM_ADMIN", "SUPER_ADMIN"]);
const PORTAL_SYSTEM_ONLY_ROLES = new Set(["RINSE"]);

export function normalizeDocumentUserName(name) {
  return String(name || "")
    .trim()
    .replace(/\s+/g, " ")
    .toLowerCase();
}

export function formatAccountantDocumentUserLabel(user) {
  const name = `${user?.first_name || ""} ${user?.last_name || ""}`.trim();
  return name || user?.display_name || user?.email || `#${user?.id}`;
}

function userRoleCodes(user) {
  const raw = user?.role_codes;
  if (!raw) return [];
  if (Array.isArray(raw)) return raw.map((c) => String(c).toUpperCase());
  return String(raw)
    .split(",")
    .map((c) => c.trim().toUpperCase())
    .filter(Boolean);
}

function matchesKnownSystemUser(user) {
  const label = normalizeDocumentUserName(formatAccountantDocumentUserLabel(user));
  if (SYSTEM_USER_KNOWN_DISPLAY_NAMES.has(label)) return true;
  const displayName = normalizeDocumentUserName(user?.display_name);
  if (displayName && SYSTEM_USER_KNOWN_DISPLAY_NAMES.has(displayName)) return true;
  const uid = Number(user?.id ?? user?.user_id);
  return Number.isFinite(uid) && SYSTEM_USER_KNOWN_IDS.has(uid);
}

export function isPortalSystemOnlyUser(user) {
  const roles = userRoleCodes(user);
  if (!roles.length) return false;
  if (roles.some((r) => !PORTAL_SYSTEM_ONLY_ROLES.has(r))) return false;
  return roles.some((r) => PORTAL_SYSTEM_ONLY_ROLES.has(r));
}

/** Platform / accountant / partner portal login accounts — not W-2 payroll workers for document filing. */
export function isAccountantSystemUser(user) {
  if (!user) return false;
  if (isPortalSystemOnlyUser(user)) return true;
  if (matchesKnownSystemUser(user)) return true;

  const roles = userRoleCodes(user);
  if (!roles.length) return false;
  const onlySystemRoles = roles.every((r) => SYSTEM_ROLE_CODES.has(r));
  if (!onlySystemRoles) return false;

  const label = normalizeDocumentUserName(formatAccountantDocumentUserLabel(user));
  return /\b(admin|consultant)\b/.test(label);
}

export function isW2Employee(user) {
  const lanes = user?.hr_form_lanes || [];
  return lanes.includes("employee_w2");
}

export function isW2EmployeeForDocuments(user) {
  return isW2Employee(user) && !isAccountantSystemUser(user);
}

export function filterAccountantDocumentUsers(users, category) {
  const list = users || [];
  if (category !== "w2") return [];
  return list.filter(isW2EmployeeForDocuments);
}

function hasLane(user, lane) {
  const lanes = user?.hr_form_lanes || [];
  return lanes.includes(lane);
}

/** Payroll workers eligible for HR Timeline by category (mirrors document filing scope). */
export function filterPayrollTimelineUsers(users, category) {
  const list = users || [];
  if (category === "w2") return list.filter(isW2EmployeeForDocuments);
  if (category === "contractor_1099") {
    return list.filter((u) => hasLane(u, "contractor_1099") && !isAccountantSystemUser(u));
  }
  if (category === "temp") {
    return list.filter(
      (u) => (hasLane(u, "contractor_temp") || hasLane(u, "temp")) && !isAccountantSystemUser(u),
    );
  }
  return [];
}

export function workerLaneForCategory(category) {
  if (category === "contractor_1099") return "contractor_1099";
  if (category === "temp") return "contractor_temp";
  return "employee_w2";
}

export function mapAccountantDocumentUserOption(user) {
  return {
    id: user.id ?? user.user_id,
    label: formatAccountantDocumentUserLabel(user),
  };
}
