/**
 * Pure helpers for PIN Switch Role mobile flow.
 * No API/business-rule changes — presentation/orchestration only.
 */

export function resolveRoleId(role) {
  if (!role || typeof role !== "object") return null;
  const id = role.role_id ?? role.id;
  if (id == null || id === "") return null;
  const n = Number(id);
  return Number.isFinite(n) ? n : null;
}

export function resolveRoleName(role) {
  if (!role || typeof role !== "object") return "";
  return String(role.role_name || role.name || "").trim();
}

export function resolveCategoryId(category) {
  if (!category || typeof category !== "object") return null;
  const id = category.id ?? category.category_id;
  if (id == null || id === "") return null;
  const n = Number(id);
  return Number.isFinite(n) ? n : null;
}

export function isCurrentRoleAssignment(categoryId, roleId, currentCategoryId, currentRoleId) {
  if (categoryId == null || roleId == null) return false;
  if (currentCategoryId == null || currentRoleId == null) return false;
  return Number(categoryId) === Number(currentCategoryId) && Number(roleId) === Number(currentRoleId);
}

/** Auto-select the only category when the tree has exactly one — matches existing UX. */
export function autoSelectCategoryId(selectionTree) {
  const tree = Array.isArray(selectionTree) ? selectionTree : [];
  if (tree.length !== 1) return null;
  return resolveCategoryId(tree[0]);
}

/**
 * Prefer current category when present in tree; else auto single category; else null.
 */
export function initialCategoryId(selectionTree, currentCategoryId) {
  const tree = Array.isArray(selectionTree) ? selectionTree : [];
  if (currentCategoryId != null) {
    const match = tree.find((c) => Number(resolveCategoryId(c)) === Number(currentCategoryId));
    if (match) return resolveCategoryId(match);
  }
  return autoSelectCategoryId(tree);
}

export function rolesForCategory(selectionTree, categoryId) {
  const tree = Array.isArray(selectionTree) ? selectionTree : [];
  const cat = tree.find((c) => Number(resolveCategoryId(c)) === Number(categoryId));
  return Array.isArray(cat?.roles) ? cat.roles : [];
}

/** Employee-facing errors — never raw server strings. */
export function switchRoleEmployeeError(body, status, { network = false, timeout = false } = {}) {
  if (timeout) return "Couldn’t change role. Try again.";
  if (network) return "Couldn’t change role. Try again.";
  const raw = String(body?.error || "").toLowerCase();
  if (status === 429 || raw.includes("too many")) return "Couldn’t change role. Try again.";
  if (raw.includes("clocked in") || raw.includes("fichado")) {
    return "Role change isn’t available right now.";
  }
  if (raw.includes("disabled") || raw.includes("desactiv")) {
    return "Role change isn’t available right now.";
  }
  if (status === 401 || raw.includes("invalid pin")) {
    return "Role change isn’t available right now.";
  }
  if (status >= 500) return "Couldn’t change role. Try again.";
  return "Couldn’t change role. Try again.";
}

export function openRoleFlowEmployeeError(body, status, opts = {}) {
  const raw = String(body?.error || "").toLowerCase();
  if (
    opts.network ||
    opts.timeout ||
    status === 429 ||
    status >= 500 ||
    raw.includes("clocked in") ||
    raw.includes("disabled") ||
    raw.includes("kiosk") ||
    status === 401
  ) {
    return "Role change isn’t available right now.";
  }
  return "Role change isn’t available right now.";
}

/**
 * Decide whether a role card tap should call the switch API.
 * Current role → no request.
 */
export function shouldCallRoleSwitchApi({
  categoryId,
  roleId,
  currentCategoryId,
  currentRoleId,
  pending,
}) {
  if (pending) return false;
  if (categoryId == null || roleId == null) return false;
  if (isCurrentRoleAssignment(categoryId, roleId, currentCategoryId, currentRoleId)) {
    return false;
  }
  return true;
}
