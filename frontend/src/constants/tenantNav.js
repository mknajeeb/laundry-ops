import {
  hasPlatformAdminRole,
  isPayrollManagementOnlyUser,
  isRinseScheduleOnlyUser,
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
  {
    to: "/dashboard",
    labelKey: "nav.dashboard",
    roles: OPS,
    /** Matches TA matrix (custom roles may have permissions without OPS role code). */
    permissionsAnyOf: ["dashboard.view", "dashboard.update"],
    moduleKey: "dashboard",
  },
  {
    to: "/checkout",
    labelKey: "nav.checkout",
    roles: PORTAL,
    moduleKey: "checkout",
  },
  { to: "/checkout-history", labelKey: "nav.checkoutHistory", roles: OPS, moduleKey: "checkout" },
  {
    to: "/upload",
    labelKey: "nav.upload",
    roles: ["ADMIN", "OPS", "UPLOAD"],
    permissionsAnyOf: ["upload.view", "upload.create"],
    moduleKey: "upload",
  },
  { to: "/discrepancies", labelKey: "nav.discrepancies", roles: ["ADMIN", "OPS"], moduleKey: "discrepancies" },
  { to: "/inventory", labelKey: "nav.inventory", roles: ["ADMIN", "OPS", "FRONT_DESK"], moduleKey: "inventory", permissionsAnyOf: ["inventory.view", "inventory.dashboard.view", "inventory.check.view", "inventory.orders.view", "inventory.reports.view", "inventory.settings.view", "inventory.settings.manage"] },
  {
    to: "/clock",
    labelKey: "nav.clock",
    roles: PORTAL,
    permissionsAnyOf: ["ta.clock", "clock.view"],
    moduleKey: "clock",
  },
  { to: "/issues", labelKey: "nav.issues", roles: OPS, moduleKey: "issues" },
  { to: "/production", labelKey: "nav.production", roles: OPS, moduleKey: "production" },
  { to: "/scoreboard", labelKey: "nav.scoreboard", roles: OPS, moduleKey: "scoreboard" },
  {
    to: "/performance",
    labelKey: "nav.shiftAnalysis",
    roles: ["ADMIN", "OPS"],
    moduleKey: "scoreboard",
  },
  {
    to: "/performance/daily-roster",
    labelKey: "nav.dailyShiftRoster",
    roles: ["ADMIN", "OPS"],
    moduleKey: "scoreboard",
  },
  {
    to: "/performance/scan-chronology",
    labelKey: "nav.scanChronology",
    roles: ["ADMIN", "OPS"],
    moduleKey: "scoreboard",
  },
  {
    to: "/performance/operations-timeline",
    labelKey: "nav.operationsTimeline",
    roles: ["ADMIN", "OPS"],
    moduleKey: "scoreboard",
  },
  {
    to: "/performance/shift-capacity-planner",
    labelKey: "nav.shiftCapacityPlanner",
    roles: ["ADMIN", "OPS"],
    moduleKey: "scoreboard",
  },
  {
    to: "/performance/weekly-schedule",
    labelKey: "nav.weeklySchedule",
    roles: ["ADMIN", "OPS", "RINSE"],
    moduleKey: "scoreboard",
  },
  {
    to: "/performance/settings",
    labelKey: "nav.performanceSettings",
    roles: ["ADMIN", "OPS"],
    moduleKey: "scoreboard",
  },
  {
    to: "/performance/user-mapping",
    labelKey: "nav.performanceUserMapping",
    roles: ["ADMIN", "OPS"],
    moduleKey: "scoreboard",
  },
  {
    to: "/rinse/order-search",
    labelKey: "nav.rinseOrderSearch",
    roles: ["ADMIN"],
    moduleKey: "scoreboard",
  },
  {
    to: "/rinse/scheduled-sync",
    labelKey: "nav.rinseScheduledSync",
    roles: ["ADMIN"],
    moduleKey: "scoreboard",
  },
  { to: "/rinse/folding-tv", labelKey: "nav.foldingTv", roles: OPS, moduleKey: "scoreboard" },
  { to: "/maintenance", labelKey: "nav.maintenance", roles: OPS, moduleKey: "maintenance" },
  {
    to: "/maintenance/task-lists",
    labelKey: "nav.maintenanceTaskLists",
    roles: OPS,
    moduleKey: "maintenance",
    permissionsAnyOf: ["maintenance.tasks.reports", "maintenance.tasks.manage"],
  },
  {
    to: "/maintenance/task-settings",
    labelKey: "nav.maintenanceTaskSettings",
    roles: ["ADMIN"],
    moduleKey: "maintenance",
    permissionsAnyOf: ["maintenance.tasks.manage"],
  },
  { to: "/maintenance/supply-usage", labelKey: "nav.supplyUsage", roles: OPS, moduleKey: "maintenance" },
  { to: "/maintenance/machine-configuration", labelKey: "nav.machineConfiguration", roles: OPS, moduleKey: "maintenance" },
  { to: "/employees", labelKey: "nav.people", roles: ["ADMIN"], moduleKey: "people" },
  { to: "/documents", labelKey: "nav.documents", roles: ["ADMIN"], moduleKey: "people" },
  { to: "/payroll", labelKey: "nav.payrollMgmt", roles: ["ADMIN", "OPS", "FINANCE", "ACCOUNTANT", "PAYROLL_ANALYTICS"], permissionsAnyOf: ["users.view", "payroll.view", "payroll.analytics.view"], moduleKey: "payroll" },
  {
    to: "/management",
    labelKey: "nav.managementHub",
    roles: ["ADMIN", "OPS", "MANAGER"],
    moduleKey: "scoreboard",
  },
  { to: "/operations/daily", labelKey: "nav.dailyOperations", roles: ["ADMIN", "OPS", "MANAGER"], moduleKey: "finance" },
  { to: "/finance/daily-revenue-cost", labelKey: "nav.dailyRevenueCost", roles: ["ADMIN"], moduleKey: "finance" },
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
 * Sidebar / drawer visibility (roles + optional TA permission keys + tenant module toggles).
 * @param {(key: string) => boolean} [hasPerm] — from `useAuth()`; when omitted, only role gates apply.
 */
export function tenantNavItemVisible(user, item, payrollNavVisible = true, hasPerm = null) {
  if (isPayrollManagementOnlyUser(user)) {
    if (item.to !== "/payroll") return false;
    if (payrollNavVisible === false) return false;
    return isTenantModuleEnabled(user, item.moduleKey || "payroll");
  }
  if (isRinseScheduleOnlyUser(user)) {
    if (item.to !== "/performance/weekly-schedule") return false;
    return true;
  }
  if (item.to === "/payroll" && payrollNavVisible === false) return false;
  if (item.skipModuleCheck) return hasPlatformAdminRole(user);
  if (item.anyTenantUser) return isTenantModuleEnabled(user, item.moduleKey || "home");

  const moduleOk = () => isTenantModuleEnabled(user, item.moduleKey || "home");
  const permKeys = item.permissionsAnyOf;
  if (permKeys?.length && typeof hasPerm === "function") {
    if (permKeys.some((k) => hasPerm(k))) return moduleOk();
  }

  if (!item.roles?.length) return false;
  if (!userSatisfiesRoleGate(user, item.roles)) return false;
  return moduleOk();
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
