import { displayRoleLabel } from "../opsMobile/switchRoleFlowHelpers.js";

function text(value) {
  return String(value || "").trim();
}

function savedId(value) {
  if (value == null || value === "") return "";
  return String(value);
}

function savedTag(saved) {
  return saved && typeof saved === "object" ? saved : {};
}

/**
 * Active operational categories for a time-record role dropdown.
 * A saved category that is no longer in the active tree keeps its stored name.
 */
export function categoryMenuOptions(selectionTree, saved) {
  const tag = savedTag(saved);
  const tree = Array.isArray(selectionTree) ? selectionTree : [];
  const options = [];
  const seen = new Set();
  for (const cat of tree) {
    const id = savedId(cat?.id);
    const label = text(cat?.name || cat?.category_name);
    if (!id || !label || seen.has(id)) continue;
    seen.add(id);
    options.push({ id, label });
  }
  const currentId = savedId(tag.categoryId);
  if (currentId && !seen.has(currentId)) {
    const label = text(tag.categoryName);
    if (label) options.push({ id: currentId, label });
  }
  return options;
}

/**
 * Roles assigned to the selected category. Ids are ta_task_roles ids, not
 * assignment ids. A saved role stays visible only on its original category.
 */
export function roleMenuOptions(selectionTree, categoryId, saved) {
  const tag = savedTag(saved);
  const tree = Array.isArray(selectionTree) ? selectionTree : [];
  const cat = tree.find((row) => String(row?.id) === String(categoryId));
  const roles = Array.isArray(cat?.roles) ? cat.roles : [];
  const options = [];
  const seen = new Set();
  for (const role of roles) {
    const id = savedId(role?.role_id ?? role?.id);
    const label = text(displayRoleLabel(role));
    if (!id || !label || seen.has(id)) continue;
    seen.add(id);
    options.push({ id, label });
  }
  const currentCategory = savedId(tag.categoryId);
  const currentRole = savedId(tag.roleId);
  if (
    currentRole &&
    currentCategory &&
    String(categoryId) === currentCategory &&
    !seen.has(currentRole)
  ) {
    const label = text(displayRoleLabel(tag.roleName || ""));
    if (label) options.push({ id: currentRole, label });
  }
  return options;
}
