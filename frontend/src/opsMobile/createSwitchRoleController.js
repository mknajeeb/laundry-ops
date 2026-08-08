/**
 * Imperative controller for Switch Role selection (testable without React Testing Library).
 * Flow: Role → Category → API (or no-op when already current).
 */
import {
  categoriesForRole,
  isCurrentRoleAssignment,
  resolveCategoryId,
  resolveRoleId,
  shouldCallRoleSwitchApi,
  switchRoleEmployeeError,
  uniqueRolesFromTree,
} from "./switchRoleFlowHelpers";

export function createSwitchRoleController({
  selectionTree = [],
  currentCategoryId = null,
  currentRoleId = null,
  pin,
  hubToken = "",
  slug,
  switchRoleApi,
  createIdempotencyKey,
  onSuccess,
  successDelayMs = 900,
}) {
  // Always open on Operator / Folder (role list). Never skip to categories just because
  // a current role exists — that felt like an intermediate screen from the PIN Hub.
  let roleId = null;
  let categoryId = null;
  let step = "role";
  let pending = false;
  let pendingCategoryId = null;
  let error = "";
  let successLabel = "";
  let phase = "select"; // select | success
  let idempotencyKey = null;
  let listeners = new Set();

  const snapshot = () => ({
    step,
    roleId,
    categoryId,
    pending,
    pendingCategoryId,
    pendingRoleId: roleId, // alias for older UI that keyed busy on role
    error,
    successLabel,
    phase,
    roles: uniqueRolesFromTree(selectionTree),
    categories: categoriesForRole(selectionTree, roleId),
  });

  const emit = () => {
    const snap = snapshot();
    listeners.forEach((fn) => fn(snap));
  };

  const runSwitch = async (cid, rid) => {
    if (
      !shouldCallRoleSwitchApi({
        categoryId: cid,
        roleId: rid,
        currentCategoryId,
        currentRoleId,
        pending,
      })
    ) {
      return { called: false, reason: "skipped" };
    }
    pending = true;
    pendingCategoryId = cid;
    error = "";
    if (!idempotencyKey) idempotencyKey = createIdempotencyKey();
    emit();
    try {
      const res = await switchRoleApi(slug, pin, {
        category_id: cid,
        role_id: rid,
        idempotency_key: idempotencyKey,
        ...(hubToken ? { hubToken } : {}),
      });
      const status = res?.status ?? 0;
      const body = res?.data && typeof res.data === "object" ? res.data : {};
      if (status >= 200 && status < 300 && body.ok) {
        successLabel =
          body.display_label || body.segment?.display_label || "Role updated";
        phase = "success";
        pending = false;
        pendingCategoryId = null;
        idempotencyKey = null;
        emit();
        globalThis.setTimeout(() => onSuccess?.(body), successDelayMs);
        return { called: true, ok: true, body };
      }
      error = switchRoleEmployeeError(body, status);
      pending = false;
      pendingCategoryId = null;
      emit();
      return { called: true, ok: false, body };
    } catch (e) {
      error = switchRoleEmployeeError(e?.response?.data, e?.response?.status, {
        network: !e?.response,
        timeout: e?.code === "ECONNABORTED",
      });
      pending = false;
      pendingCategoryId = null;
      emit();
      return { called: true, ok: false, error };
    }
  };

  return {
    getState: snapshot,
    subscribe(fn) {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
    setRole(role) {
      if (pending) return;
      const rid = resolveRoleId(role);
      roleId = rid;
      categoryId = null;
      step = "category";
      error = "";
      emit();
    },
    /** Legacy alias — category-first callers. */
    setCategory(id) {
      if (pending) return;
      categoryId = id;
      error = "";
      emit();
    },
    backToRoles() {
      if (pending) return;
      step = "role";
      categoryId = null;
      error = "";
      emit();
    },
    isCurrentCategory(category) {
      const cid = resolveCategoryId(category);
      return isCurrentRoleAssignment(cid, roleId, currentCategoryId, currentRoleId);
    },
    isCurrentRole(role) {
      const rid = resolveRoleId(role);
      return Number(rid) === Number(currentRoleId) && currentRoleId != null;
    },
    /**
     * Confirm category for the selected role (API or no-op).
     */
    async selectCategory(category) {
      const cid = typeof category === "object" ? resolveCategoryId(category) : category;
      categoryId = cid;
      return runSwitch(cid, roleId);
    },
    /**
     * Legacy: select role while category may already be set (tests / old UI).
     * If category is unset, prefer current category or the only category for that role.
     */
    async selectRole(role) {
      const rid = resolveRoleId(role);
      roleId = rid;
      let cid = categoryId;
      if (cid == null) {
        const cats = categoriesForRole(selectionTree, rid);
        if (
          currentCategoryId != null &&
          cats.some((c) => Number(resolveCategoryId(c)) === Number(currentCategoryId))
        ) {
          cid = Number(currentCategoryId);
        } else if (cats.length === 1) {
          cid = resolveCategoryId(cats[0]);
        }
      }
      categoryId = cid;
      return runSwitch(cid, rid);
    },
    clearError() {
      error = "";
      emit();
    },
  };
}
