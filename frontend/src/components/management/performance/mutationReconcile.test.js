import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  createMutationReconciler,
  shouldApplyReconcileResponse,
  MUTATION_RECONCILE_DEBOUNCE_MS,
} from "./mutationReconcile";

describe("mutationReconcile", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("coalesces rapid noteMutation into one load after debounce", async () => {
    const runLoad = vi.fn(async () => {});
    const r = createMutationReconciler({ runLoad, debounceMs: MUTATION_RECONCILE_DEBOUNCE_MS });
    r.noteMutation();
    r.noteMutation();
    r.noteMutation();
    expect(runLoad).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(MUTATION_RECONCILE_DEBOUNCE_MS);
    expect(runLoad).toHaveBeenCalledTimes(1);
    r.dispose();
  });

  it("does not start a second overlapping load while one is in flight", async () => {
    let release;
    const runLoad = vi.fn(
      () =>
        new Promise((resolve) => {
          release = resolve;
        })
    );
    const r = createMutationReconciler({ runLoad, debounceMs: 10 });
    r.noteMutation();
    await vi.advanceTimersByTimeAsync(10);
    expect(runLoad).toHaveBeenCalledTimes(1);
    r.noteMutation();
    r.noteMutation();
    await vi.advanceTimersByTimeAsync(10);
    expect(runLoad).toHaveBeenCalledTimes(1);
    release();
    await Promise.resolve();
    await vi.advanceTimersByTimeAsync(10);
    // Follow-up coalesced after in-flight completes (debounced, not tight-loop).
    expect(runLoad).toHaveBeenCalledTimes(2);
    r.dispose();
  });

  it("markPending requeues without bumping mutation epoch", async () => {
    const runLoad = vi.fn(async () => {});
    const r = createMutationReconciler({ runLoad, debounceMs: 20 });
    r.noteMutation();
    const epoch = r.getMutationEpoch();
    r.markPending();
    expect(r.getMutationEpoch()).toBe(epoch);
    await vi.advanceTimersByTimeAsync(20);
    expect(runLoad).toHaveBeenCalledTimes(1);
    r.dispose();
  });

  it("dispose prevents applying and clears timer", async () => {
    const runLoad = vi.fn(async () => {});
    const r = createMutationReconciler({ runLoad, debounceMs: 50 });
    r.noteMutation();
    r.dispose();
    await vi.advanceTimersByTimeAsync(50);
    expect(runLoad).not.toHaveBeenCalled();
  });

  it("10 rapid mutations coalesce to one expensive GET", async () => {
    const runLoad = vi.fn(async () => {});
    const r = createMutationReconciler({ runLoad, debounceMs: MUTATION_RECONCILE_DEBOUNCE_MS });
    for (let i = 0; i < 10; i += 1) r.noteMutation();
    expect(runLoad).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(MUTATION_RECONCILE_DEBOUNCE_MS);
    expect(runLoad).toHaveBeenCalledTimes(1);
    expect(r.getMutationEpoch()).toBe(10);
    r.dispose();
  });

  it("shouldApplyReconcileResponse rejects stale GET after newer mutation", () => {
    expect(
      shouldApplyReconcileResponse({
        mutationEpochAtStart: 1,
        currentMutationEpoch: 2,
        disposed: false,
      })
    ).toBe(false);
    expect(
      shouldApplyReconcileResponse({
        mutationEpochAtStart: 2,
        currentMutationEpoch: 2,
        disposed: false,
      })
    ).toBe(true);
    expect(
      shouldApplyReconcileResponse({
        mutationEpochAtStart: 2,
        currentMutationEpoch: 2,
        disposed: true,
      })
    ).toBe(false);
  });
});
