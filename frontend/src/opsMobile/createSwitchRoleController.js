/**
 * Imperative controller for Switch Role selection (testable without React Testing Library).
 */
import {
  initialCategoryId,
  isCurrentRoleAssignment,
  resolveRoleId,
  rolesForCategory,
  shouldCallRoleSwitchApi,
  switchRoleEmployeeError,
} from "./switchRoleFlowHelpers";

export function createSwitchRoleController({
  selectionTree = [],
  currentCategoryId = null,
  currentRoleId = null,
  pin,
  slug,
  switchRoleApi,
  createIdempotencyKey,
  onSuccess,
  successDelayMs = 900,
}) {
  let categoryId = initialCategoryId(selectionTree, currentCategoryId);
  let pending = false;
  let pendingRoleId = null;
  let error = "";
  let successLabel = "";
  let phase = "select"; // select | success
  let idempotencyKey = null;
  let listeners = new Set();

  const snapshot = () => ({
    categoryId,
    pending,
    pendingRoleId,
    error,
    successLabel,
    phase,
    roles: rolesForCategory(selectionTree, categoryId),
  });

  const emit = () => {
    const snap = snapshot();
    listeners.forEach((fn) => fn(snap));
  };

  return {
    getState: snapshot,
    subscribe(fn) {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
    setCategory(id) {
      if (pending) return;
      categoryId = id;
      error = "";
      emit();
    },
    isCurrent(role) {
      const rid = resolveRoleId(role);
      return isCurrentRoleAssignment(categoryId, rid, currentCategoryId, currentRoleId);
    },
    async selectRole(role) {
      const rid = resolveRoleId(role);
      if (
        !shouldCallRoleSwitchApi({
          categoryId,
          roleId: rid,
          currentCategoryId,
          currentRoleId,
          pending,
        })
      ) {
        return { called: false, reason: "skipped" };
      }
      pending = true;
      pendingRoleId = rid;
      error = "";
      if (!idempotencyKey) idempotencyKey = createIdempotencyKey();
      emit();
      try {
        const res = await switchRoleApi(slug, pin, {
          category_id: categoryId,
          role_id: rid,
          idempotency_key: idempotencyKey,
        });
        const status = res?.status ?? 0;
        const body = res?.data && typeof res.data === "object" ? res.data : {};
        if (status >= 200 && status < 300 && body.ok) {
          successLabel =
            body.display_label || body.segment?.display_label || "Role updated";
          phase = "success";
          pending = false;
          pendingRoleId = null;
          idempotencyKey = null;
          emit();
          globalThis.setTimeout(() => onSuccess?.(body), successDelayMs);
          return { called: true, ok: true, body };
        }
        error = switchRoleEmployeeError(body, status);
        pending = false;
        pendingRoleId = null;
        emit();
        return { called: true, ok: false, body };
      } catch (e) {
        error = switchRoleEmployeeError(e?.response?.data, e?.response?.status, {
          network: !e?.response,
          timeout: e?.code === "ECONNABORTED",
        });
        pending = false;
        pendingRoleId = null;
        emit();
        return { called: true, ok: false, error };
      }
    },
    clearError() {
      error = "";
      emit();
    },
  };
}
