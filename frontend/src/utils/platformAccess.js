/** Roles that use day-to-day Laundry Ops (tenant portal). */
export const TENANT_PORTAL_ROLES = [
  "ADMIN",
  "OPS",
  "FRONT_DESK",
  "OPERATIONS",
  "SUPERVISOR",
  "PAYROLL_ADMIN",
  "FINANCE",
];

/** Platform operators: manage tenants and entitlements (not operational laundry UI). */
export const PLATFORM_ADMIN_ROLES = ["SUPER_ADMIN", "PLATFORM_ADMIN"];

export function normalizedRoles(user) {
  return (user?.roles || []).map((r) => String(r).toUpperCase());
}

export function hasPlatformAdminRole(user) {
  const r = normalizedRoles(user);
  return PLATFORM_ADMIN_ROLES.some((x) => r.includes(x));
}

export function hasTenantPortalAccess(user) {
  const r = normalizedRoles(user);
  return TENANT_PORTAL_ROLES.some((x) => r.includes(x));
}

/** Super admin with no operational tenant role: platform-only shell. */
export function isPlatformOnlyUser(user) {
  return hasPlatformAdminRole(user) && !hasTenantPortalAccess(user);
}

export function isTenantModuleEnabled(user, moduleKey) {
  const tm = user?.tenant_modules;
  if (!tm || typeof tm !== "object") return true;
  if (moduleKey in tm) return tm[moduleKey] !== false;
  return true;
}
