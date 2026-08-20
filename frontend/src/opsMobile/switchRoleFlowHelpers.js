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

/**
 * Employee-facing role label. Stored value may remain "Folder" / "Operator" / "Sort".
 */
export function displayRoleLabel(roleOrName) {
  const name =
    typeof roleOrName === "string" ? String(roleOrName || "").trim() : resolveRoleName(roleOrName);
  const code =
    typeof roleOrName === "object" && roleOrName
      ? String(roleOrName.role_code || roleOrName.code || "").trim().toUpperCase()
      : "";
  const key = name.toLowerCase();
  if (code === "FOLDER" || key === "folder" || key === "folding" || key === "fold") return "Fold";
  if (code === "OPERATOR" || key === "operator") return "Wash-Dry";
  if (code === "SORT" || key === "sort" || key === "sorter" || key === "sorting") return "Sort";
  if (key === "wash-dry" || key === "wash dry" || key === "wash_dry") return "Wash-Dry";
  return name;
}

/** Compact helper under role cards. */
export function roleHelperText(roleOrName) {
  const name =
    typeof roleOrName === "string" ? String(roleOrName || "").trim() : resolveRoleName(roleOrName);
  const key = name.toLowerCase();
  if (key === "operator" || key === "wash-dry" || key === "wash dry" || key === "wash_dry") {
    return "Washing & drying";
  }
  if (key === "sort" || key === "sorter" || key === "sorting") return "Sorting & prep";
  if (key === "folder" || key === "folding" || key === "fold") return "Folding completed orders";
  return "";
}

/** Visual bucket for one-screen role selector (Rinse WF / Rinse HD / Non-Rinse). */
export function categoryDisplayBucket(category) {
  const name = resolveCategoryName(category).toLowerCase();
  const code = String(category?.code || category?.category_code || "").toLowerCase();
  if (name.includes("rinse wf") || name.includes("wash & fold") || name.includes("wash and fold") || code === "rinse_wf") {
    return "Rinse Wash & Fold";
  }
  if (name.includes("rinse hd") || name.includes("hang dry") || code === "rinse_hd") {
    return "Rinse Hang Dry";
  }
  return "Non-Rinse";
}

/** Employee-facing "Wash-Dry | Rinse Wash & Fold" status line. */
export function formatEmployeeAssignmentLabel({
  roleName,
  roleCode,
  categoryName,
  categoryCode,
  role,
  category,
} = {}) {
  const roleLabel = displayRoleLabel(
    role || { role_name: roleName, role_code: roleCode, name: roleName, code: roleCode },
  );
  const work = categoryDisplayBucket(
    category || { name: categoryName, code: categoryCode, category_code: categoryCode },
  );
  if (roleLabel && work) return `${roleLabel} | ${work}`;
  return roleLabel || work || "";
}

const CATEGORY_BUCKET_ORDER = ["Rinse Wash & Fold", "Rinse Hang Dry", "Non-Rinse"];
const ROLE_LABEL_ORDER = ["Wash-Dry", "Sort", "Fold"];
export const PRIMARY_ROLE_ORDER = ROLE_LABEL_ORDER;
const RINSE_WORK_TYPE_ORDER = ["Rinse Wash & Fold", "Rinse Hang Dry"];

/**
 * Flatten selection tree into category×role combos for one-tap switching.
 * Preserves backend category_id + role_id pairs unchanged.
 */
export function flattenRoleCombos(selectionTree) {
  const tree = Array.isArray(selectionTree) ? selectionTree : [];
  const combos = [];
  for (const cat of tree) {
    const roles = Array.isArray(cat?.roles) ? cat.roles : [];
    for (const role of roles) {
      const categoryId = resolveCategoryId(cat);
      const roleId = resolveRoleId(role);
      if (categoryId == null || roleId == null) continue;
      combos.push({
        categoryId,
        roleId,
        category: cat,
        role,
        bucket: categoryDisplayBucket(cat),
        categoryName: resolveCategoryName(cat),
        roleLabel: displayRoleLabel(role),
        comboLabel: formatEmployeeAssignmentLabel({ role, category: cat }),
      });
    }
  }
  return combos;
}

/** Group flat combos by visual bucket for one-screen layout. */
export function groupCombosByBucket(combos) {
  const groups = Object.fromEntries(CATEGORY_BUCKET_ORDER.map((b) => [b, []]));
  for (const combo of combos || []) {
    const bucket = combo.bucket || "Non-Rinse";
    if (!groups[bucket]) groups[bucket] = [];
    groups[bucket].push(combo);
  }
  return CATEGORY_BUCKET_ORDER.filter((b) => groups[b]?.length).map((bucket) => ({
    bucket,
    combos: [...groups[bucket]].sort((a, b) => {
      const ai = ROLE_LABEL_ORDER.indexOf(a.roleLabel);
      const bi = ROLE_LABEL_ORDER.indexOf(b.roleLabel);
      return (ai < 0 ? 99 : ai) - (bi < 0 ? 99 : bi);
    }),
  }));
}

/** Compact work-type label shown under a primary role. */
export function workTypeLabel(combo) {
  if (!combo) return "";
  if (combo.bucket === "Non-Rinse") return "Non-Rinse";
  return combo.bucket || combo.categoryName || "";
}

/**
 * Pick which Non-Rinse category×role combo to use for switch/current.
 * Preserves backend category_id: prefer the current assignment, else the
 * same category as the current segment, else a stable Drop Off → DHS order.
 * Never invents category ids — only selects among provided combos.
 */
export function pickNonRinseCombo(
  nonRinseCombos = [],
  currentCategoryId = null,
  currentRoleId = null,
) {
  const list = Array.isArray(nonRinseCombos) ? nonRinseCombos.filter(Boolean) : [];
  if (!list.length) return null;
  const current = list.find((c) =>
    isCurrentRoleAssignment(c.categoryId, c.roleId, currentCategoryId, currentRoleId),
  );
  if (current) return current;
  if (currentCategoryId != null) {
    const sameCat = list.find((c) => Number(c.categoryId) === Number(currentCategoryId));
    if (sameCat) return sameCat;
  }
  if (list.length === 1) return list[0];
  return [...list].sort((a, b) => nonRinseCategoryRank(a) - nonRinseCategoryRank(b))[0];
}

function nonRinseCategoryRank(combo) {
  const name = String(combo?.categoryName || "").toLowerCase();
  const code = String(combo?.category?.code || combo?.category?.category_code || "").toLowerCase();
  if (name.includes("drop") || code.includes("drop")) return 0;
  if (name.includes("dhs") || code.includes("dhs")) return 1;
  return 2;
}

/**
 * Role-first grouping: Wash-Dry / Sort / Fold, each with available work types.
 * Rinse buckets stay named; DHS / Drop Off collapse to one employee-facing Non-Rinse.
 */
export function groupCombosByPrimaryRole(
  combos,
  { currentCategoryId = null, currentRoleId = null } = {},
) {
  const byRole = new Map();
  for (const combo of combos || []) {
    const roleLabel = combo.roleLabel || "Other";
    if (!byRole.has(roleLabel)) byRole.set(roleLabel, []);
    byRole.get(roleLabel).push(combo);
  }
  const roleOrder = [...PRIMARY_ROLE_ORDER];
  for (const key of byRole.keys()) {
    if (!roleOrder.includes(key)) roleOrder.push(key);
  }
  return roleOrder
    .filter((roleLabel) => (byRole.get(roleLabel) || []).length)
    .map((roleLabel) => {
      const list = byRole.get(roleLabel) || [];
      const workTypes = [];
      for (const bucket of RINSE_WORK_TYPE_ORDER) {
        const match = list.find((c) => c.bucket === bucket);
        if (match) {
          workTypes.push({
            key: `${roleLabel}:${bucket}:${match.categoryId}`,
            label: workTypeLabel(match),
            combo: match,
          });
        }
      }
      const nonRinse = list.filter((c) => c.bucket === "Non-Rinse");
      const picked = pickNonRinseCombo(nonRinse, currentCategoryId, currentRoleId);
      if (picked) {
        workTypes.push({
          key: `${roleLabel}:non_rinse`,
          label: "Non-Rinse",
          combo: picked,
          nonRinseCombos: nonRinse,
        });
      }
      return { roleLabel, workTypes };
    });
}

/** Caption on the primary role tile when this role is the current assignment. */
export function currentRoleCaption(combo) {
  if (!combo) return "Current";
  const label = workTypeLabel(combo);
  return label ? `${label} · Current` : "Current";
}

/**
 * Role-first tap: one work type switches immediately; several work types expand in place.
 */
export function resolvePrimaryRoleTap({
  workTypes = [],
  expandedRole = null,
  roleLabel,
  currentCategoryId = null,
  currentRoleId = null,
}) {
  if (!workTypes.length) return { action: "noop" };
  if (workTypes.length === 1) {
    const combo = workTypes[0].combo;
    if (
      isCurrentRoleAssignment(
        combo?.categoryId,
        combo?.roleId,
        currentCategoryId,
        currentRoleId,
      )
    ) {
      return { action: "noop" };
    }
    return { action: "switch", combo };
  }
  if (expandedRole === roleLabel) return { action: "collapse" };
  return { action: "expand", roleLabel };
}

export function resolveCategoryId(category) {
  if (!category || typeof category !== "object") return null;
  const id = category.id ?? category.category_id;
  if (id == null || id === "") return null;
  const n = Number(id);
  return Number.isFinite(n) ? n : null;
}

export function resolveCategoryName(category) {
  if (!category || typeof category !== "object") return "";
  return String(category.name || category.category_name || "").trim();
}

export function isCurrentRoleAssignment(categoryId, roleId, currentCategoryId, currentRoleId) {
  if (categoryId == null || roleId == null) return false;
  if (currentCategoryId == null || currentRoleId == null) return false;
  return Number(categoryId) === Number(currentCategoryId) && Number(roleId) === Number(currentRoleId);
}

/** Unique roles across the selection tree (by role id), preserving first-seen order. */
export function uniqueRolesFromTree(selectionTree) {
  const tree = Array.isArray(selectionTree) ? selectionTree : [];
  const seen = new Set();
  const out = [];
  for (const cat of tree) {
    const roles = Array.isArray(cat?.roles) ? cat.roles : [];
    for (const role of roles) {
      const rid = resolveRoleId(role);
      if (rid == null || seen.has(rid)) continue;
      seen.add(rid);
      out.push(role);
    }
  }
  return out;
}

/** Categories that include the given role id. */
export function categoriesForRole(selectionTree, roleId) {
  const tree = Array.isArray(selectionTree) ? selectionTree : [];
  if (roleId == null) return [];
  return tree.filter((cat) => {
    const roles = Array.isArray(cat?.roles) ? cat.roles : [];
    return roles.some((r) => Number(resolveRoleId(r)) === Number(roleId));
  });
}

/** Prefer current role when present; else auto single role; else null. */
export function initialRoleId(selectionTree, currentRoleId) {
  const roles = uniqueRolesFromTree(selectionTree);
  if (currentRoleId != null) {
    const match = roles.find((r) => Number(resolveRoleId(r)) === Number(currentRoleId));
    if (match) return resolveRoleId(match);
  }
  if (roles.length === 1) return resolveRoleId(roles[0]);
  return null;
}

/** Auto-select the only category when the tree has exactly one — matches existing UX. */
export function autoSelectCategoryId(selectionTree) {
  const tree = Array.isArray(selectionTree) ? selectionTree : [];
  if (tree.length !== 1) return null;
  return resolveCategoryId(tree[0]);
}

/**
 * Prefer current category when present in tree; else auto single category; else null.
 * Kept for compatibility with older category-first callers/tests.
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
 * Decide whether a category+role confirm should call the switch API.
 * Current combination → no request.
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
