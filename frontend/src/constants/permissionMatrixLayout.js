/**
 * Sort order for permission modules (route_key).
 * Matches tenant entitlement modules (TENANT_MODULE_KEYS) first, then People & access, TA, payroll admin, org, TA permissions UI.
 */
export const MODULE_ROUTE_ORDER = [
  "home",
  "dashboard",
  "orders",
  "checkout",
  "upload",
  "discrepancies",
  "inventory",
  "clock",
  "issues",
  "production",
  "scoreboard",
  "maintenance",
  "access",
  "time_attendance",
  "payroll",
  "organization",
  "permissions",
  "general",
];

/** Tab/function order within Time & attendance and globally when merging. */
export const FUNCTIONALITY_SECTION_ORDER = [
  "Module access",
  "Dashboard",
  "Stock Check",
  "Purchase Orders",
  "Reports",
  "Settings",
  "Task List",
  "User accounts",
  "Overrides & corrections",
  "Clock / sessions",
  "Geofences, categories, settings",
  "Live monitor",
  "Payroll payments",
  "Reports & exports",
];

/** Row labels / copy overrides (permission key → display description). */
export const PERMISSION_DESCRIPTION_OVERRIDES = {
  "users.deactivate": "Delete users",
};

/** Show friendlier permission id in the matrix (canonical `perm_key` is unchanged for saves/API). */
export const PERMISSION_KEY_DISPLAY_OVERRIDES = {
  "users.deactivate": "users.delete",
};

export function displayPermissionKey(permKey) {
  const pk = String(permKey || "");
  return PERMISSION_KEY_DISPLAY_OVERRIDES[pk] || pk;
}

export function inferActionKeyFromPermKey(pk) {
  const last = String(pk || "").split(".").pop() || "view";
  if (last === "add") return "create";
  if (last === "deactivate") return "delete";
  return last;
}

/** First segment of perm_key when it names a tenant app module (orders.view → orders). */
const TENANT_MODULE_ROUTE_PREFIXES = new Set([
  "home",
  "dashboard",
  "orders",
  "checkout",
  "upload",
  "discrepancies",
  "inventory",
  "clock",
  "issues",
  "production",
  "scoreboard",
  "maintenance",
  "payroll",
  "organization",
  "permissions",
]);

/** Map permission keys → tab/function section when DB columns are missing. */
export function sectionLabelForPermKey(permKey) {
  const pk = String(permKey || "");
  if (pk.startsWith("users.")) return "User accounts";
  if (pk === "ta.override") return "Overrides & corrections";
  if (pk === "ta.clock") return "Clock / sessions";
  if (pk === "ta.settings") return "Geofences, categories, settings";
  if (pk === "ta.monitor") return "Live monitor";
  if (pk === "finance.payments") return "Payroll payments";
  if (pk === "ta.reports") return "Reports & exports";
  if (pk.startsWith("inventory.dashboard.")) return "Dashboard";
  if (pk.startsWith("inventory.check.")) return "Stock Check";
  if (pk.startsWith("inventory.orders.")) return "Purchase Orders";
  if (pk.startsWith("inventory.reports.")) return "Reports";
  if (pk.startsWith("inventory.settings.")) return "Settings";
  if (pk.startsWith("maintenance.tasks.")) return "Task List";
  const prefix = pk.split(".")[0] || "";
  if (TENANT_MODULE_ROUTE_PREFIXES.has(prefix)) return "Module access";
  return null;
}

export function inferRouteKeyFromPermKey(permKey) {
  const pk = String(permKey || "");
  if (pk.startsWith("users.")) return "access";
  if (pk.startsWith("ta.") || pk.startsWith("finance.")) return "time_attendance";
  const prefix = pk.split(".")[0] || "";
  if (TENANT_MODULE_ROUTE_PREFIXES.has(prefix)) return prefix;
  return "general";
}

const ROUTE_LABEL_OVERRIDES = {
  home: "Home",
  dashboard: "Dashboard",
  orders: "Orders",
  checkout: "Checkout",
  upload: "Upload",
  discrepancies: "Discrepancies",
  inventory: "Inventory",
  clock: "Clock",
  issues: "Issues",
  production: "Production",
  scoreboard: "Scoreboard",
  maintenance: "Maintenance",
  payroll: "Payroll",
  organization: "Organization",
  permissions: "TA permissions",
  access: "People & access",
  time_attendance: "Time & attendance",
  general: "Other modules",
};

export function inferRouteLabelFromRouteKey(routeKey) {
  const k = String(routeKey || "");
  if (ROUTE_LABEL_OVERRIDES[k]) return ROUTE_LABEL_OVERRIDES[k];
  return k
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export function sortFlatSections(sections) {
  const rank = (label) => {
    const i = FUNCTIONALITY_SECTION_ORDER.indexOf(label);
    if (label === "Other capabilities" || label === "General") return 2500;
    return i === -1 ? 2000 + String(label || "").charCodeAt(0) : i;
  };
  return [...sections].sort((a, b) => rank(a.section_label) - rank(b.section_label));
}

export function sortHierarchyRoutes(routes) {
  const rank = (r) => {
    const k = r.route_key || "";
    const i = MODULE_ROUTE_ORDER.indexOf(k);
    return i === -1 ? 800 + String(k).charCodeAt(0) : i;
  };
  return [...routes].sort((a, b) => rank(a) - rank(b));
}

/**
 * Normalize API hierarchy: sort modules and sections inside each module.
 */
export function normalizeHierarchyRoutes(routes) {
  return sortHierarchyRoutes(
    (routes || []).map((r) => ({
      ...r,
      sections: sortFlatSections(r.sections || []),
    })),
  );
}

/**
 * Build full module → section → actions tree from flat `permissions` rows
 * (used when hierarchy is empty but permissions[] is present).
 */
export function buildSyntheticModuleHierarchy(permissions) {
  const routeMap = new Map();

  for (const p of permissions || []) {
    const pk = p.perm_key || "";
    if (!pk) continue;

    let rk = String(p.route_key || "").trim();
    let rl = String(p.route_label || "").trim();
    let sk = String(p.section_key || "").trim();
    let sl = String(p.section_label || "").trim();

    if (!rk) rk = inferRouteKeyFromPermKey(pk);
    if (!rl) rl = inferRouteLabelFromRouteKey(rk);
    if (!sl) sl = sectionLabelForPermKey(pk) || (sk ? sk.replace(/_/g, " ") : "") || "General";
    if (!sk)
      sk = sl
        .replace(/\s+/g, "_")
        .toLowerCase()
        .replace(/[^a-z0-9_]/g, "") || "general";

    if (!routeMap.has(rk)) {
      routeMap.set(rk, { route_key: rk, route_label: rl, sectionsMap: new Map() });
    }
    const route = routeMap.get(rk);
    if (rl) route.route_label = rl;

    if (!route.sectionsMap.has(sk)) {
      route.sectionsMap.set(sk, {
        section_key: sk,
        section_label: sl,
        resources: [{ resource_key: "", resource_label: "", actions: [] }],
      });
    }
    const sec = route.sectionsMap.get(sk);
    sec.resources[0].actions.push({
      id: p.id,
      perm_key: pk,
      action_key: String(p.action_key || inferActionKeyFromPermKey(pk)).toLowerCase(),
      description: p.description,
      sort_order: Number(p.sort_order) || 0,
    });
  }

  const routes = [];
  for (const r of routeMap.values()) {
    const sections = sortFlatSections([...r.sectionsMap.values()]);
    for (const sec of sections) {
      const acts = sec.resources[0]?.actions || [];
      acts.sort(
        (a, b) => (a.sort_order - b.sort_order) || String(a.perm_key).localeCompare(String(b.perm_key)),
      );
    }
    routes.push({
      route_key: r.route_key,
      route_label: r.route_label,
      sections,
    });
  }
  return sortHierarchyRoutes(routes);
}

/** @deprecated use buildSyntheticModuleHierarchy */
export function buildSyntheticFlatSections(permissions) {
  const routes = buildSyntheticModuleHierarchy(permissions);
  const flat = [];
  for (const r of routes) {
    for (const s of r.sections || []) {
      flat.push({ ...s, _route_key: r.route_key, _route_label: r.route_label });
    }
  }
  return sortFlatSections(flat);
}
