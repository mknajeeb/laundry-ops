import { describe, expect, it } from "vitest";
import { actionsForBagStatus } from "./step1BagActions.js";

describe("actionsForBagStatus", () => {
  it("exposes Edit Bag and hides separate correction flows", () => {
    const acts = actionsForBagStatus("pending");
    expect(acts.editBag).toBe(true);
    expect(acts.viewDetails).toBe(false);
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
    expect(acts.isSettled).toBe(false);
  });

  it("shows View Details for Completed without specialty work", () => {
    const acts = actionsForBagStatus("completed");
    expect(acts.markCompleted).toBe(false);
    expect(acts.returnPending).toBe(true);
    expect(acts.editBag).toBe(false);
    expect(acts.viewDetails).toBe(true);
    expect(acts.moveToReview).toBe(false);
    expect(acts.isSettled).toBe(true);
    expect(acts.statusLabel).toBe("COMPLETED");
  });

  it("keeps Review when completed but specialty still unresolved", () => {
    const acts = actionsForBagStatus("completed", {
      specialtyReviewUnresolved: true,
      reasonCodes: ["WF_BULK_WORKITEM_REVIEW"],
    });
    expect(acts.isSettled).toBe(false);
    expect(acts.editBag).toBe(true);
    expect(acts.viewDetails).toBe(false);
    expect(acts.statusLabel).toBe(null);
  });

  it("shows REVIEWED + View Details when specialty review resolved", () => {
    const acts = actionsForBagStatus("pending", { specialtyReviewResolved: true });
    expect(acts.editBag).toBe(false);
    expect(acts.viewDetails).toBe(true);
    expect(acts.moveToReview).toBe(false);
    expect(acts.statusLabel).toBe("REVIEWED");
  });
});
