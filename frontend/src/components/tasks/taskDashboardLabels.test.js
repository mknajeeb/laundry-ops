import { describe, expect, it } from "vitest";
import { friendlyStatusLabel, statusChipColor } from "./taskDashboardLabels";

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
});
