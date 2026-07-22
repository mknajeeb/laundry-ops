import { describe, expect, it } from "vitest";
import { actionsForBagStatus } from "./step1BagActions.js";

describe("actionsForBagStatus", () => {
  it("hides Return to Pending for an already Pending bag", () => {
    const acts = actionsForBagStatus("pending");
    expect(acts.returnPending).toBe(false);
    expect(acts.moveToReview).toBe(true);
    expect(acts.markCompleted).toBe(true);
    expect(acts.correctEntry).toBe(true);
    expect(acts.correctWeight).toBe(true);
    expect(acts.exclude).toBe(true);
  });

  it("shows Return to Pending for Review Required", () => {
    const acts = actionsForBagStatus("review_required");
    expect(acts.returnPending).toBe(true);
    expect(acts.moveToReview).toBe(false);
    expect(acts.markCompleted).toBe(true);
  });

  it("shows reopen actions for Completed", () => {
    const acts = actionsForBagStatus("completed");
    expect(acts.markCompleted).toBe(false);
    expect(acts.returnPending).toBe(true);
    expect(acts.moveToReview).toBe(false);
    expect(acts.correctCompletion).toBe(true);
  });
});
