/** Inventory role tiers + tab-level permission helpers. */

export const INVENTORY_TAB_KEYS = ["dashboard", "check", "orders", "reports", "settings"];

export const INVENTORY_TAB_VIEW_PERMS = {
  dashboard: "inventory.dashboard.view",
  check: "inventory.check.view",
  orders: "inventory.orders.view",
  reports: "inventory.reports.view",
  settings: "inventory.settings.view",
};

export function getInventoryRoleTier(user) {
  const roles = new Set((user?.roles || []).map((r) => String(r).toUpperCase()));
  if (roles.has("ADMIN") || roles.has("SUPER_ADMIN") || roles.has("PLATFORM_ADMIN")) {
    return "admin";
  }
  if (roles.has("OPS")) {
    return "supervisor";
  }
  return "floor";
}

function _hasAnyInventoryTabPerm(hasPerm) {
  if (typeof hasPerm !== "function") return false;
  if (hasPerm("inventory.settings.manage")) return true;
  return INVENTORY_TAB_KEYS.some((key) => hasPerm(INVENTORY_TAB_VIEW_PERMS[key]));
}

/** Prefer explicit tab permissions when present; otherwise fall back to Washpro role tiers. */
export function canAccessInventoryTab(tier, tabKey, hasPerm) {
  const viewPerm = INVENTORY_TAB_VIEW_PERMS[tabKey];
  if (typeof hasPerm === "function" && viewPerm) {
    if (hasPerm(viewPerm)) return true;
    if (tabKey === "settings" && hasPerm("inventory.settings.manage")) return true;
    if (_hasAnyInventoryTabPerm(hasPerm)) return false;
  }

  const floor = ["dashboard", "check"];
  const supervisor = [...floor, "orders", "reports"];
  const admin = [...supervisor, "settings"];
  if (tier === "admin") return admin.includes(tabKey);
  if (tier === "supervisor") return supervisor.includes(tabKey);
  return floor.includes(tabKey);
}

export function canManageInventorySettings(tier, hasPerm) {
  if (typeof hasPerm === "function") {
    if (hasPerm("inventory.settings.manage")) return true;
    if (hasPerm("inventory.create") || hasPerm("inventory.update")) return true;
    if (_hasAnyInventoryTabPerm(hasPerm)) return false;
  }
  return tier === "admin";
}

export const ORDER_STATUS_COLORS = {
  DRAFT: "default",
  ORDERED: "info",
  PARTIALLY_RECEIVED: "warning",
  RECEIVED: "success",
  CANCELLED: "error",
};

export const VARIANCE_REASON_LABELS = {
  DAMAGED: "Damaged",
  USED: "Used",
  MISSING: "Missing",
  COUNT_CORRECTION: "Count correction",
  OTHER: "Other",
};

export const ADJUSTMENT_REASON_LABELS = {
  DAMAGED: "Damaged",
  LOST: "Lost",
  EMPLOYEE_USE: "Employee use",
  CUSTOMER_USE: "Customer use",
  CORRECTION: "Correction",
  TRANSFER: "Transfer",
  OTHER: "Other",
};

export const STATUS_LEVEL_LABELS = {
  OK: "OK",
  LOW: "Low",
  OUT: "Out",
};

export const TRACKING_MODE_LABELS = {
  QUANTITY: "Count quantity",
  STATUS: "Status only (OK / Low / Out)",
};

export const STOCK_CHECK_QUICK_NOTES = [
  "Opened new box",
  "Damaged",
  "Missing",
  "Received today",
];
