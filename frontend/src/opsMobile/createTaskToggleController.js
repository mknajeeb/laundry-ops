/**
 * Imperative task-toggle controller — testable without React Testing Library.
 * Calls existing patch persistence exactly once per deliberate toggle.
 */
import { applyTaskCompletionLocal } from "../utils/maintenanceTaskListHelpers";

export function createTaskToggleController({
  getList,
  setList,
  patchItem,
  onError,
  isReadOnly,
}) {
  const pending = new Set();

  return {
    isPending(itemId) {
      return pending.has(Number(itemId));
    },
    async toggle(item) {
      const list = getList?.();
      if (!list?.id || !item?.id) return { called: false, reason: "missing" };
      if (isReadOnly?.()) return { called: false, reason: "readonly" };
      const id = Number(item.id);
      if (pending.has(id)) return { called: false, reason: "pending" };

      const nextCompleted = !item.completed;
      const previous = list;
      pending.add(id);
      setList?.(applyTaskCompletionLocal(list, id, nextCompleted));

      try {
        const res = await patchItem({
          listId: list.id,
          itemId: id,
          completed: nextCompleted,
        });
        const status = res?.status ?? 0;
        const body = res?.data && typeof res.data === "object" ? res.data : {};
        if (status >= 200 && status < 300 && body.list) {
          setList?.(body.list);
          return { called: true, ok: true };
        }
        if (status === 409) {
          setList?.(previous);
          onError?.(body.error || "List is submitted");
          return { called: true, ok: false, conflict: true };
        }
        setList?.(previous);
        onError?.("Couldn’t save. Try again.");
        return { called: true, ok: false };
      } catch {
        setList?.(previous);
        onError?.("Couldn’t save. Try again.");
        return { called: true, ok: false };
      } finally {
        pending.delete(id);
      }
    },
  };
}
