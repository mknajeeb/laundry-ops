import { describe, expect, it, vi } from "vitest";
import {
  createFloorRevisionedAutosave,
  FLOOR_DRAFT_CONFLICT_MESSAGE,
} from "./createFloorRevisionedAutosave";

describe("createFloorRevisionedAutosave", () => {
  it("sends expected_revision and uses returned revision for the next save", async () => {
    vi.useFakeTimers();
    let revision = 0;
    const calls = [];
    const controller = createFloorRevisionedAutosave({
      debounceMs: 450,
      buildLines: () => [{ item_id: 1, counted_qty: 1 }],
      getExpectedRevision: () => revision,
      saveDraft: async ({ expected_revision }) => {
        calls.push(expected_revision);
        revision = expected_revision + 1;
        return { draft_revision: revision, lines: [] };
      },
      onSaved: (data) => {
        revision = data.draft_revision;
      },
      onError: vi.fn(),
      onConflict: vi.fn(),
    });
    controller.schedule();
    await vi.advanceTimersByTimeAsync(450);
    await Promise.resolve();
    controller.schedule();
    await vi.advanceTimersByTimeAsync(450);
    await Promise.resolve();
    expect(calls).toEqual([0, 1]);
    expect(revision).toBe(2);
    vi.useRealTimers();
  });

  it("serializes rapid edits instead of concurrent writes", async () => {
    vi.useFakeTimers();
    let inFlight = 0;
    let maxInFlight = 0;
    let revision = 0;
    let counted = 1;
    const controller = createFloorRevisionedAutosave({
      debounceMs: 450,
      buildLines: () => [{ item_id: 1, counted_qty: counted }],
      getExpectedRevision: () => revision,
      saveDraft: async ({ expected_revision, lines }) => {
        inFlight += 1;
        maxInFlight = Math.max(maxInFlight, inFlight);
        await new Promise((r) => setTimeout(r, 30));
        inFlight -= 1;
        revision = expected_revision + 1;
        return { draft_revision: revision, lines };
      },
      onSaved: (data) => {
        revision = data.draft_revision;
      },
      onError: vi.fn(),
      onConflict: vi.fn(),
    });
    controller.schedule();
    await vi.advanceTimersByTimeAsync(450);
    // First save in flight; more edits must queue, not parallelize.
    counted = 2;
    controller.schedule();
    counted = 3;
    controller.schedule();
    await vi.advanceTimersByTimeAsync(100);
    await Promise.resolve();
    expect(maxInFlight).toBe(1);
    // Drain dirty follow-up
    await vi.advanceTimersByTimeAsync(100);
    await Promise.resolve();
    expect(revision).toBeGreaterThanOrEqual(1);
    vi.useRealTimers();
  });

  it("after an in-flight save, newer local generation is saved with the new revision", async () => {
    vi.useFakeTimers();
    let revision = 0;
    const savedCounts = [];
    let counted = 1;
    let resolveFirst;
    const controller = createFloorRevisionedAutosave({
      debounceMs: 450,
      buildLines: () => [{ item_id: 1, counted_qty: counted }],
      getExpectedRevision: () => revision,
      saveDraft: async ({ expected_revision, lines }) => {
        if (expected_revision === 0) {
          await new Promise((r) => {
            resolveFirst = r;
          });
        }
        revision = expected_revision + 1;
        savedCounts.push(lines[0].counted_qty);
        return { draft_revision: revision };
      },
      onSaved: (data) => {
        revision = data.draft_revision;
      },
      onError: vi.fn(),
      onConflict: vi.fn(),
    });
    controller.schedule();
    await vi.advanceTimersByTimeAsync(450);
    counted = 9;
    controller.schedule(); // dirty while first in flight
    resolveFirst();
    await Promise.resolve();
    await Promise.resolve();
    await vi.advanceTimersByTimeAsync(50);
    expect(savedCounts).toEqual([1, 9]);
    expect(revision).toBe(2);
    vi.useRealTimers();
  });

  it("409 refreshes revision path via onConflict and preserves retry with latest local lines", async () => {
    let revision = 0;
    const onConflict = vi.fn(async () => {
      revision = 1; // server advanced by another client
    });
    const linesAtRetry = [];
    let localCount = 5;
    const controller = createFloorRevisionedAutosave({
      debounceMs: 0,
      buildLines: () => [{ item_id: 1, counted_qty: localCount }],
      getExpectedRevision: () => revision,
      saveDraft: async ({ expected_revision, lines }) => {
        if (expected_revision === 0) {
          const err = new Error("conflict");
          err.response = { status: 409, data: { error: FLOOR_DRAFT_CONFLICT_MESSAGE } };
          throw err;
        }
        linesAtRetry.push(lines[0].counted_qty);
        revision = expected_revision + 1;
        return { draft_revision: revision };
      },
      onSaved: (data) => {
        revision = data.draft_revision;
      },
      onError: vi.fn(),
      onConflict,
    });
    const first = await controller.flushNow();
    expect(first.conflict).toBe(true);
    expect(onConflict).toHaveBeenCalled();
    expect(controller.hasConflict()).toBe(true);
    // Local value preserved by caller; retry uses refreshed revision.
    localCount = 5;
    controller.clearConflict();
    const second = await controller.flushNow();
    expect(second.ok).toBe(true);
    expect(linesAtRetry).toEqual([5]);
    expect(revision).toBe(2);
  });

  it("flushNow returns conflict and does not submit-ready when unresolved", async () => {
    const controller = createFloorRevisionedAutosave({
      debounceMs: 0,
      buildLines: () => [{ item_id: 1, counted_qty: 1 }],
      getExpectedRevision: () => 0,
      saveDraft: async () => {
        const err = new Error("conflict");
        err.response = { status: 409 };
        throw err;
      },
      onSaved: vi.fn(),
      onError: vi.fn(),
      onConflict: vi.fn(),
    });
    await controller.flushNow();
    const again = await controller.flushNow();
    expect(again.conflict).toBe(true);
    expect(again.ok).toBe(false);
  });
});
