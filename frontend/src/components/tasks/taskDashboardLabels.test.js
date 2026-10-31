import { describe, expect, it } from "vitest";
import {
  checklistItemLabel,
  completionChipColor,
  completionLabel,
  friendlyStatusLabel,
  isChecklistTimestamp,
  overallLabel,
  participationLabel,
  participationStatusOf,
  participationSummary,
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
    expect(verificationLabel("waiting")).toBe("Pending Verification");
    expect(verificationLabel("partial")).toBe("Partially Verified");
    expect(verificationLabel("not_required")).toBe("Not Required");
    expect(verificationLabel("needs_correction")).toBe("Needs Correction");
    expect(completionChipColor("completed")).toBe("success");
    expect(verificationChipColor("waiting")).toBe("warning");
    expect(verificationChipColor("partial")).toBe("warning");
    expect(verificationChipColor("verified")).toBe("success");
  });

  it("labels checklist check-off separately from assignment Not Started", () => {
    expect(checklistItemLabel("pending")).toBe("Not checked off");
    expect(checklistItemLabel("completed")).toBe("Checked off");
    expect(checklistItemLabel("approved")).toBe("Verified");
    expect(isChecklistTimestamp({ activity_kind: "group_item" })).toBe(true);
    expect(isChecklistTimestamp({ timestamp_kind: "checklist_checkoff" })).toBe(true);
    expect(isChecklistTimestamp({ activity_kind: "group" })).toBe(false);
  });

  it("keeps employee participation separate from assignment completion", () => {
    expect(participationStatusOf({ status: "completed" })).toBe("finished");
    expect(participationStatusOf({ status: "pending" })).toBe("not_started");
    expect(participationStatusOf({ participation_status: "not_started", status: "completed" })).toBe(
      "not_started"
    );
    expect(participationLabel("finished")).toBe("Finished");
    expect(participationLabel("in_progress")).toBe("In Progress");
    expect(overallLabel("in_progress")).toBe("In Progress");
    expect(overallLabel("pending_verification")).toBe("Pending Verification");
    expect(
      participationSummary({ finished: 1, assigned: 2, checklistDone: 0, checklistRequired: 2 })
    ).toBe("1 of 2 employees finished · 0 of 2 checklist items completed");
  });
});
