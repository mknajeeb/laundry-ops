import { describe, expect, it } from "vitest";
import { recordDraft, redoDraftHistory, undoDraftHistory } from "./draftHistory";

describe("planner draft history", () => {
  it("undo returns to the saved week and redo restores the edit", () => {
    const edited = { entries: [{ id: "draft-1" }] };
    const recorded = recordDraft([], [], null, edited);
    const undone = undoDraftHistory(recorded.history, recorded.future, recorded.draft);
    expect(undone.draft).toBeNull();
    expect(undone.future).toEqual([edited]);
    const redone = redoDraftHistory(undone.history, undone.future, undone.draft);
    expect(redone.draft).toEqual(edited);
    expect(redone.future).toEqual([]);
  });

  it("a new edit drops the redo stack", () => {
    const first = recordDraft([], [], null, { entries: [1] });
    const undone = undoDraftHistory(first.history, first.future, first.draft);
    const second = recordDraft(undone.history, undone.future, undone.draft, { entries: [2] });
    expect(second.future).toEqual([]);
    expect(second.draft).toEqual({ entries: [2] });
  });

  it("undo and redo walk a two-step draft", () => {
    const first = recordDraft([], [], null, { n: 1 });
    const second = recordDraft(first.history, first.future, first.draft, { n: 2 });
    const once = undoDraftHistory(second.history, second.future, second.draft);
    expect(once.draft).toEqual({ n: 1 });
    const twice = undoDraftHistory(once.history, once.future, once.draft);
    expect(twice.draft).toBeNull();
    const forward = redoDraftHistory(twice.history, twice.future, twice.draft);
    expect(forward.draft).toEqual({ n: 1 });
  });
});
