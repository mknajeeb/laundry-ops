/**
 * Phase 5D floor-count autosave with server optimistic locking.
 *
 * - Every save sends expected_revision
 * - At most one in-flight write per draft
 * - Edits during flight mark dirty and flush again with the new revision
 * - 409 conflict does not overwrite local values
 */

export const FLOOR_DRAFT_CONFLICT_MESSAGE =
  "This stock count was updated on another device. Review the latest saved values, then retry your changes.";

function isConflictError(err) {
  return Number(err?.response?.status) === 409;
}

/**
 * @param {object} opts
 * @param {(body: object) => Promise<any>} opts.saveDraft
 * @param {() => any[]} [opts.buildLines] Phase 5D shape
 * @param {(ctx: {expected_revision: number}) => object} [opts.buildPayload] generic body builder
 * @param {() => number} opts.getExpectedRevision
 */
export function createFloorRevisionedAutosave({
  saveDraft,
  buildLines,
  buildPayload,
  getExpectedRevision,
  onSaved,
  onError,
  onConflict,
  debounceMs = 450,
  isBlocked,
}) {
  let timer = null;
  let inFlight = false;
  let dirty = false;
  let conflict = false;
  let generation = 0;
  let chain = Promise.resolve();

  const runPipeline = () => {
    chain = chain.then(async () => {
      if (isBlocked?.() || conflict) {
        return { called: false, ok: false, reason: conflict ? "conflict" : "blocked", conflict };
      }
      if (inFlight) {
        dirty = true;
        return { called: false, ok: false, reason: "queued" };
      }

      inFlight = true;
      const myGen = ++generation;
      try {
        do {
          if (isBlocked?.() || conflict) {
            return {
              called: false,
              ok: false,
              reason: conflict ? "conflict" : "blocked",
              conflict,
            };
          }
          dirty = false;
          const expected_revision = getExpectedRevision?.();
          const body =
            typeof buildPayload === "function"
              ? buildPayload({ expected_revision })
              : { lines: buildLines?.() || [], expected_revision };
          const result = await saveDraft(body);
          // Apply revision immediately so a follow-up dirty pass uses the new value.
          onSaved?.(result);
        } while (dirty);

        return { called: true, ok: true };
      } catch (err) {
        if (isConflictError(err)) {
          conflict = true;
          if (myGen === generation) {
            await onConflict?.(err);
          }
          return { called: true, ok: false, conflict: true, error: err };
        }
        if (myGen === generation) {
          onError?.(err?.response?.data?.error || "Couldn’t save. Try again.");
        }
        return { called: true, ok: false, error: err };
      } finally {
        inFlight = false;
      }
    });
    return chain;
  };

  return {
    isPending() {
      return inFlight;
    },
    hasConflict() {
      return conflict;
    },
    clearConflict() {
      conflict = false;
    },
    schedule() {
      if (conflict || isBlocked?.()) return;
      if (inFlight) {
        dirty = true;
        return;
      }
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => {
        timer = null;
        runPipeline();
      }, debounceMs);
    },
    async flushNow() {
      if (timer) {
        clearTimeout(timer);
        timer = null;
      }
      if (conflict) {
        return { called: false, ok: false, reason: "conflict", conflict: true };
      }
      if (inFlight) {
        dirty = true;
        return chain;
      }
      return runPipeline();
    },
    dispose() {
      if (timer) clearTimeout(timer);
      timer = null;
      generation += 1;
      dirty = false;
      conflict = false;
    },
  };
}
