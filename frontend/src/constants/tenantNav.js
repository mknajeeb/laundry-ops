import {
  hasPlatformAdminRole,
  isTenantModuleEnabled,
  TENANT_PORTAL_ROLES,
  TENANT_STANDARD_OPS_ROLES,
  userSatisfiesRoleGate,
} from "../utils/platformAccess";

const OPS = [...TENANT_STANDARD_OPS_ROLES];
/** Checkout counter + clock + notifications for front-line staff without full ops roles. */
const PORTAL = [...TENANT_PORTAL_ROLES];

/** Tenant app sidebar / mobile drawer — single source of truth. */
export const TENANT_NAV_ITEMS = [
  { to: "/", labelKey: "nav.home", anyTenantUser: true, moduleKey: "home" },
  { to: "/dashboard", labelKey: "nav.dashboard", roles: OPS, moduleKey: "dashboard" },
  { to: "/orders", labelKey: "nav.orders", roles: OPS, moduleKey: "orders" },
  { to: "/checkout", labelKey: "nav.checkout", roles: PORTAL, moduleKey: "checkout" },
  { to: "/upload", labelKey: "nav.upload", roles: ["ADMIN", "OPS"], moduleKey: "upload" },
  { to: "/discrepancies", labelKey: "nav.discrepancies", roles: ["ADMIN", "OPS"], moduleKey: "discrepancies" },
  { to: "/inventory", labelKey: "nav.inventory", roles: ["ADMIN", "OPS", "FRONT_DESK"], moduleKey: "inventory" },
  { to: "/clock", labelKey: "nav.clock", roles: PORTAL, moduleKey: "clock" },
  { to: "/issues", labelKey: "nav.issues", roles: OPS, moduleKey: "issues" },
  { to: "/production", labelKey: "nav.production", roles: OPS, moduleKey: "production" },
  { to: "/scoreboard", labelKey: "nav.scoreboard", roles: OPS, moduleKey: "scoreboard" },
  { to: "/maintenance", labelKey: "nav.maintenance", roles: OPS, moduleKey: "maintenance" },
  { to: "/employees", labelKey: "nav.people", roles: ["ADMIN"], moduleKey: "people" },
  { to: "/documents", labelKey: "nav.documents", roles: ["ADMIN"], moduleKey: "people" },
  { to: "/payroll", labelKey: "nav.payrollMgmt", roles: ["ADMIN", "OPS"], moduleKey: "payroll" },
  { to: "/organization", labelKey: "nav.organization", roles: ["ADMIN"], moduleKey: "organization" },
  { to: "/notifications", labelKey: "nav.notifications", roles: PORTAL, moduleKey: "notifications" },
  { to: "/permissions", labelKey: "nav.permissions", roles: ["ADMIN"], moduleKey: "permissions" },
  {
    to: "/platform",
    labelKey: "nav.platformTenants",
    roles: [],
    skipModuleCheck: true,
  },
];

/**
 * Sidebar / drawer visibility (roles + tenant module toggles + payroll nav flag).
 */
export function tenantNavItemVisible(user, item, payrollNavVisible = true) {
  if (item.to === "/payroll" && payrollNavVisible === false) return false;
  if (item.skipModuleCheck) return hasPlatformAdminRole(user);
  if (item.anyTenantUser) return isTenantModuleEnabled(user, item.moduleKey || "home");
  if (!item.roles?.length) return false;
  if (!userSatisfiesRoleGate(user, item.roles)) return false;
  return isTenantModuleEnabled(user, item.moduleKey || "home");
}

/** Longest nav prefix match for nested routes (e.g. /employees/12 → /employees). */
export function tenantNavItemForPath(pathname) {
  const p = pathname || "/";
  const exact = TENANT_NAV_ITEMS.find((i) => i.to === p);
  if (exact) return exact;
  const nested = [...TENANT_NAV_ITEMS]
    .filter((i) => i.to !== "/")
    .sort((a, b) => b.to.length - a.to.length)
    .find((i) => p.startsWith(`${i.to}/`));
  return nested || null;
}
