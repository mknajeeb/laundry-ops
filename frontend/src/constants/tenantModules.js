/** Keys must match backend TENANT_MODULE_KEYS + route mapping in Sidebar. */
export const TENANT_MODULES = [
  { key: "home", labelKey: "nav.home", path: "/" },
  { key: "dashboard", labelKey: "nav.dashboard", path: "/dashboard" },
  { key: "checkout", labelKey: "nav.checkout", path: "/checkout" },
  { key: "upload", labelKey: "nav.upload", path: "/upload" },
  { key: "discrepancies", labelKey: "nav.discrepancies", path: "/discrepancies" },
  { key: "inventory", labelKey: "nav.inventory", path: "/inventory" },
  { key: "clock", labelKey: "nav.clock", path: "/clock" },
  { key: "issues", labelKey: "nav.issues", path: "/issues" },
  { key: "production", labelKey: "nav.production", path: "/production" },
  { key: "scoreboard", labelKey: "nav.scoreboard", path: "/scoreboard" },
  { key: "maintenance", labelKey: "nav.maintenance", path: "/maintenance" },
  { key: "people", labelKey: "nav.people", path: "/employees" },
  { key: "payroll", labelKey: "nav.payrollMgmt", path: "/payroll" },
  { key: "organization", labelKey: "nav.organization", path: "/organization" },
  { key: "notifications", labelKey: "nav.notifications", path: "/notifications" },
  { key: "permissions", labelKey: "nav.permissions", path: "/permissions" },
];

export const TENANT_MODULE_KEY_SET = new Set(TENANT_MODULES.map((m) => m.key));
