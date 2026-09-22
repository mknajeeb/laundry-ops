/** Coalesced silent Performance reconcile after mutations.

Prevents overlapping full GETs and ignores stale responses that finish
after a newer mutation patch or a newer requested reconcile.
*/

export const MUTATION_RECONCILE_DEBOUNCE_MS = 750;

/**
 * @param {object} opts
 * @param {() => Promise<unknown>} opts.runLoad - invokes silent load; must honor loadGen itself
 * @param {number} [opts.debounceMs]
 */
export function createMutationReconciler({
  runLoad,
  debounceMs = MUTATION_RECONCILE_DEBOUNCE_MS,
} = {}) {
  let timer = null;
  let pending = false;
  let inFlight = false;
  let disposed = false;
  let requestSeq = 0;
  let mutationEpoch = 0;

  const flush = async () => {
    timer = null;
    if (disposed) return;
    if (!pending) return;
    if (inFlight) {
      // Another flush will run after the current load; keep pending.
      return;
    }
    pending = false;
    inFlight = true;
    const seq = ++requestSeq;
    const epochAtStart = mutationEpoch;
    try {
      await runLoad({
        reconcileSeq: seq,
        mutationEpochAtStart: epochAtStart,
        getMutationEpoch: () => mutationEpoch,
      });
    } finally {
      inFlight = false;
      if (!disposed && pending) {
        // Coalesce follow-up with debounce (never tight-loop while load is busy).
        timer = setTimeout(() => {
          void flush();
        }, debounceMs);
      }
    }
  };

  const schedule = () => {
    if (disposed) return;
    if (timer != null) clearTimeout(timer);
    timer = setTimeout(() => {
      void flush();
    }, debounceMs);
  };

  return {
    /** Call after applying an authoritative employee_day patch. */
    noteMutation() {
      mutationEpoch += 1;
      pending = true;
      schedule();
    },
    /**
     * Re-queue a coalesce pass without bumping mutationEpoch
     * (e.g. silent GET was busy / skipped).
     */
    markPending() {
      pending = true;
      if (inFlight) return;
      schedule();
    },
    /** Drop pending work on unmount / navigation. */
    dispose() {
      disposed = true;
      pending = false;
      if (timer != null) {
        clearTimeout(timer);
        timer = null;
      }
    },
    getMutationEpoch() {
      return mutationEpoch;
    },
    /** Test/inspect helpers */
    _isPending() {
      return pending;
    },
    _isInFlight() {
      return inFlight;
    },
  };
}

/**
 * Decide whether a silent GET payload may replace local state.
 * Reject when a newer mutation patch landed while the GET was in flight.
 */
export function shouldApplyReconcileResponse({
  mutationEpochAtStart,
  currentMutationEpoch,
  disposed,
} = {}) {
  if (disposed) return false;
  if (
    mutationEpochAtStart != null &&
    currentMutationEpoch != null &&
    Number(currentMutationEpoch) > Number(mutationEpochAtStart)
  ) {
    return false;
  }
  return true;
}
