/** Inventory role tiers — maps Washpro roles to UI access. */

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

export function canAccessInventoryTab(tier, tabKey) {
  const floor = ["dashboard", "check"];
  const supervisor = [...floor, "orders", "reports"];
  const admin = [...supervisor, "settings"];
  if (tier === "admin") return admin.includes(tabKey);
  if (tier === "supervisor") return supervisor.includes(tabKey);
  return floor.includes(tabKey);
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
