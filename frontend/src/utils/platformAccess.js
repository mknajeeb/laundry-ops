/**
 * Operational roles that may use rinse-flow / production modules (not limited “desk only” roles).
 * e.g. CHECKOUT-only staff should see Checkout + Clock, not Dashboard/Orders for everyone.
 */
export const TENANT_STANDARD_OPS_ROLES = [
  "ADMIN",
  "OPS",
  "FRONT_DESK",
  "OPERATIONS",
  "SUPERVISOR",
  "PAYROLL_ADMIN",
  "FINANCE",
];

/** All roles that may sign in to the tenant Laundry Ops app (includes narrow roles like CHECKOUT). */
export const TENANT_PORTAL_ROLES = [...TENANT_STANDARD_OPS_ROLES, "CHECKOUT", "ACCOUNTANT"];

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

/** True when the user is an external accountant with no other tenant portal roles. */
export function isAccountantOnlyUser(user) {
  const r = normalizedRoles(user);
  if (!r.includes("ACCOUNTANT")) return false;
  if (hasPlatformAdminRole(user)) return false;
  return !r.some((role) => role !== "ACCOUNTANT" && TENANT_PORTAL_ROLES.includes(role));
}

/** Post-login / blocked-route landing path for tenant users. */
export function tenantDefaultRoute(user) {
  return isAccountantOnlyUser(user) ? "/payroll" : "/";
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
