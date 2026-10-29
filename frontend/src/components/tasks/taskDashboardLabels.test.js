import { describe, expect, it } from "vitest";
import {
  completionChipColor,
  completionLabel,
  friendlyStatusLabel,
  statusChipColor,
  verificationChipColor,
  verificationLabel,
} from "./taskDashboardLabels";

describe("taskDashboardLabels", () => {
  it("maps storage codes to friendly labels", () => {
    expect(friendlyStatusLabel("pending_approval")).toBe("Waiting for Verification");
    expect(friendlyStatusLabel("approved")).toBe("Verified");
    expect(friendlyStatusLabel("rejected")).toBe("Needs Correction");
    expect(friendlyStatusLabel("overdue")).toBe("Overdue");
  });

  it("uses distinct chip colors for overdue vs verified", () => {
    expect(statusChipColor("overdue")).toBe("error");
    expect(statusChipColor("approved")).toBe("success");
  });

  it("keeps completion and verification labels separate", () => {
    expect(completionLabel("completed")).toBe("Completed");
    expect(completionLabel("in_progress")).toBe("In Progress");
    expect(verificationLabel("waiting")).toBe("Waiting for Verification");
    expect(verificationLabel("partial")).toBe("Partially Verified");
    expect(verificationLabel("not_required")).toBe("Not Required");
    expect(verificationLabel("needs_correction")).toBe("Needs Correction");
    expect(completionChipColor("completed")).toBe("success");
    expect(verificationChipColor("waiting")).toBe("warning");
    expect(verificationChipColor("partial")).toBe("warning");
    expect(verificationChipColor("verified")).toBe("success");
  });
});
