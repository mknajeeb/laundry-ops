import { describe, expect, it } from "vitest";
import { actionsForBagStatus } from "./step1BagActions.js";

describe("actionsForBagStatus", () => {
  it("exposes Edit Bag and hides separate correction flows", () => {
    const acts = actionsForBagStatus("pending");
    expect(acts.editBag).toBe(true);
    expect(acts.correctEntry).toBe(false);
    expect(acts.correctWeight).toBe(false);
    expect(acts.returnPending).toBe(false);
    expect(acts.moveToReview).toBe(true);
  });

  it("shows Return to Pending for Review Required", () => {
    const acts = actionsForBagStatus("review_required");
    expect(acts.returnPending).toBe(true);
    expect(acts.editBag).toBe(true);
    expect(acts.moveToReview).toBe(false);
  });

  it("shows reopen actions for Completed", () => {
    const acts = actionsForBagStatus("completed");
    expect(acts.markCompleted).toBe(false);
    expect(acts.returnPending).toBe(true);
    expect(acts.editBag).toBe(true);
  });
});
