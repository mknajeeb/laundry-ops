/**
 * Imperative controller for Switch Role selection (testable without React Testing Library).
 * One-screen flow: tap category×role combo → API (or no-op when already current).
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
  let roleId = null;
  let categoryId = null;
  let pending = false;
  let pendingCategoryId = null;
  let pendingRoleId = null;
  let error = "";
  let successLabel = "";
  let phase = "select"; // select | success
  let idempotencyKey = null;
  let listeners = new Set();

  const snapshot = () => ({
    roleId,
    categoryId,
    pending,
    pendingCategoryId,
    pendingRoleId,
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
    pendingRoleId = rid;
    roleId = rid;
    categoryId = cid;
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
          body.display_label ||
          body.employee_display_label ||
          body.segment?.employee_display_label ||
          body.segment?.display_label ||
          "Role updated";
        phase = "success";
        pending = false;
        pendingCategoryId = null;
        pendingRoleId = null;
        idempotencyKey = null;
        emit();
        globalThis.setTimeout(() => onSuccess?.(body), successDelayMs);
        return { called: true, ok: true, body };
      }
      error = switchRoleEmployeeError(body, status);
      pending = false;
      pendingCategoryId = null;
      pendingRoleId = null;
      emit();
      return { called: true, ok: false, body };
    } catch (e) {
      error = switchRoleEmployeeError(e?.response?.data, e?.response?.status, {
        network: !e?.response,
        timeout: e?.code === "ECONNABORTED",
      });
      pending = false;
      pendingCategoryId = null;
      pendingRoleId = null;
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
    /** One-tap combo selection — primary path for one-screen UI. */
    async selectCombo(combo) {
      if (!combo || pending) return { called: false, reason: "blocked" };
      const cid =
        combo.categoryId ??
        resolveCategoryId(combo.category ?? combo);
      const rid =
        combo.roleId ??
        resolveRoleId(combo.role ?? combo);
      return runSwitch(cid, rid);
    },
    /** Legacy two-step helpers — kept for tests and clock-in flows. */
    setRole(role) {
      if (pending) return;
      roleId = resolveRoleId(role);
      categoryId = null;
      error = "";
      emit();
    },
    setCategory(id) {
      if (pending) return;
      categoryId = id;
      error = "";
      emit();
    },
    backToRoles() {
      if (pending) return;
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
    async selectCategory(category) {
      const cid = typeof category === "object" ? resolveCategoryId(category) : category;
      categoryId = cid;
      return runSwitch(cid, roleId);
    },
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
