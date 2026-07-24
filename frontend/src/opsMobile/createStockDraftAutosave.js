/**
 * Debounced stock-check draft autosave — preserves ~450ms contract.
 * Testable without React Testing Library.
 */
export function createStockDraftAutosave({
  saveDraft,
  buildLines,
  getNotesMeta,
  onSaved,
  onError,
  debounceMs = 450,
  isBlocked,
}) {
  let timer = null;
  let pending = false;
  let generation = 0;

  const flush = async () => {
    if (isBlocked?.()) return { called: false, reason: "blocked" };
    const myGen = ++generation;
    pending = true;
    try {
      const lines = buildLines?.() || [];
      await saveDraft({ lines, notes: getNotesMeta?.() || "" });
      if (myGen === generation) onSaved?.();
      return { called: true, ok: true };
    } catch {
      if (myGen === generation) onError?.("Couldn’t save. Try again.");
      return { called: true, ok: false };
    } finally {
      if (myGen === generation) pending = false;
    }
  };

  return {
    isPending() {
      return pending;
    },
    schedule() {
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => {
        timer = null;
        flush();
      }, debounceMs);
    },
    async flushNow() {
      if (timer) {
        clearTimeout(timer);
        timer = null;
      }
      return flush();
    },
    dispose() {
      if (timer) clearTimeout(timer);
      timer = null;
      generation += 1;
    },
  };
}

export function createStockSubmitController({
  buildLines,
  submitCheck,
  onSuccess,
  onError,
  isBlocked,
}) {
  let pending = false;

  return {
    isPending() {
      return pending;
    },
    async submit() {
      if (pending) return { called: false, reason: "pending" };
      if (isBlocked?.()) return { called: false, reason: "blocked" };
      const lines = buildLines?.() || [];
      if (!lines.length) {
        onError?.("Enter at least one count or status before submitting.");
        return { called: false, reason: "empty" };
      }
      pending = true;
      try {
        const res = await submitCheck({ lines });
        onSuccess?.(res);
        return { called: true, ok: true, res };
      } catch (e) {
        onError?.("Couldn’t submit. Try again.");
        return { called: true, ok: false, error: e };
      } finally {
        pending = false;
      }
    },
  };
}
