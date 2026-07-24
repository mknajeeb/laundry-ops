/**
 * Checklist submit controller — preserves existing submit API contract.
 * Exactly one submit call while pending; failures keep list editable.
 */
import { allTasksChecked, isCompletedStatus } from "../utils/maintenanceTaskListHelpers";

export function createTaskSubmitController({
  getList,
  setList,
  submitList,
  onError,
  getSessionToken,
}) {
  let pending = false;

  return {
    isPending() {
      return pending;
    },
    canSubmit() {
      const list = getList?.();
      if (!list?.id) return false;
      if (isCompletedStatus(list.status) || list.read_only) return false;
      return allTasksChecked(list);
    },
    async submit() {
      const list = getList?.();
      if (!list?.id) return { called: false, reason: "missing" };
      if (isCompletedStatus(list.status) || list.read_only) {
        return { called: false, reason: "readonly" };
      }
      if (!allTasksChecked(list)) return { called: false, reason: "incomplete" };
      if (pending) return { called: false, reason: "pending" };
      const token = getSessionToken?.();
      if (!token) return { called: false, reason: "nosession" };

      pending = true;
      try {
        const res = await submitList({ token, listId: list.id });
        const status = res?.status ?? 0;
        const body = res?.data && typeof res.data === "object" ? res.data : {};
        if (status >= 200 && status < 300 && body.ok && body.list) {
          setList?.(body.list);
          return { called: true, ok: true };
        }
        onError?.("Couldn’t submit. Try again.");
        return { called: true, ok: false };
      } catch {
        onError?.("Couldn’t submit. Try again.");
        return { called: true, ok: false };
      } finally {
        pending = false;
      }
    },
  };
}
