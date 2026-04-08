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

/**
 * Sidebar + `<GuardedRoute />`: platform operators may use the full tenant app in org context
 * without a duplicate ADMIN/OPS assignment in user_roles.
 */
export function userSatisfiesRoleGate(user, requiredRoles) {
  if (!requiredRoles?.length) return true;
  const r = normalizedRoles(user);
  if (PLATFORM_ADMIN_ROLES.some((x) => r.includes(x))) return true;
  return requiredRoles.some((req) => r.includes(String(req).toUpperCase()));
}

/**
 * True when this session should use the platform-only shell (no tenant ops UI).
 * Platform operators who also belong to a real tenant (e.g. logged in via /login/washpro)
 * must not be forced to /platform just because SUPER_ADMIN/PLATFORM_ADMIN is not listed
 * alongside ADMIN in user_roles.
 */
export function isPlatformOnlyUser(user) {
  if (!hasPlatformAdminRole(user) || hasTenantPortalAccess(user)) return false;
  const slug = String(user?.organization_slug || "").toLowerCase();
  if (slug && slug !== "platform") return false;
  return true;
}

export function isTenantModuleEnabled(user, moduleKey) {
  const tm = user?.tenant_modules;
  if (!tm || typeof tm !== "object") return true;
  if (moduleKey in tm) return tm[moduleKey] !== false;
  return true;
}
