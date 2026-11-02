import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { addDaysYmd, weekStartFromDate } from "../../utils/businessTime";
import {
  checklistItemLabel,
  completionChipColor,
  completionLabel,
  friendlyStatusLabel,
  isChecklistTimestamp,
  overallLabel,
  participationLabel,
  dashboardHeadlineMetrics,
  formatDurationHm,
  participationStatusOf,
  participationSummary,
  showPerEmployeeChecklist,
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
    expect(checklistItemLabel("pending_verification")).toBe("Waiting for Verification");
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
    ).toBe("1/2 employees finished · 0/2 checklist items completed");
  });

  it("counts employees separately from completed activities", () => {
    const counts = dashboardHeadlineMetrics([
      {
        completion_status: "completed",
        verification_status: "verified",
        overall_status: "verified",
        contributions: [
          { participation_status: "finished" },
          { participation_status: "finished" },
        ],
      },
    ]);
    expect(counts.employeesAssigned).toBe(2);
    expect(counts.employeesStarted).toBe(2);
    expect(counts.employeesFinished).toBe(2);
    expect(counts.activitiesAssigned).toBe(1);
    expect(counts.completedActivities).toBe(1);
    expect(counts.verifiedActivities).toBe(1);
    expect(counts.pendingVerification).toBe(0);
    expect(counts.overdue).toBe(0);
  });

  it("formats durations in hours and minutes and sums participation without checklist rows", () => {
    expect(formatDurationHm(45 * 60)).toBe("45m");
    expect(formatDurationHm(75 * 60)).toBe("1h 15m");
    expect(formatDurationHm(125 * 60)).toBe("2h 05m");
    const counts = dashboardHeadlineMetrics([
      {
        completion_status: "completed",
        contributions: [
          { participation_status: "finished", activity: { duration_seconds: 1527 } },
          {
            participation_status: "finished",
            activity: { duration_seconds: 60, activity_kind: "group_item" },
          },
          { participation_status: "finished", activity: { duration_seconds: 1466 } },
        ],
      },
    ]);
    expect(counts.totalTimeLabel).toBe("50m");
    expect(counts.employeesAssigned).toBe(3);
    expect(counts.activitiesAssigned).toBe(1);
  });

  it("hides per-employee checklist badges when the shared checklist is complete", () => {
    const row = {
      shared_checklist_items: [
        { task_code: "custom_check_washer_residue", status: "completed", completed_by_name: "Gabriela" },
        { task_code: "floor_cleaning", status: "completed", completed_by_name: "Yesenia" },
      ],
    };
    const yesenia = {
      employee_name: "Yesenia",
      group_items: [{ task_code: "floor_cleaning", display_status: "pending_verification" }],
    };
    expect(showPerEmployeeChecklist(row, yesenia)).toBe(false);
    expect(checklistItemLabel("pending_verification")).not.toBe("Not checked off");
    expect(showPerEmployeeChecklist({ shared_checklist_items: [] }, yesenia)).toBe(true);
  });

  it("keeps Sunday and daylight-saving calendar dates in America/New_York", () => {
    expect(addDaysYmd("2026-11-01", 0)).toBe("2026-11-01");
    expect(addDaysYmd("2026-11-01", 6)).toBe("2026-11-07");
    expect(addDaysYmd("2026-03-08", 1)).toBe("2026-03-09");
    expect(weekStartFromDate("2026-11-01", 6)).toBe("2026-11-01");
    expect(weekStartFromDate("2026-11-02", 6)).toBe("2026-11-01");
  });

  it("prints the selected dashboard from an isolated letter document", () => {
    const here = dirname(fileURLToPath(import.meta.url));
    const page = readFileSync(resolve(here, "../../pages/ManagementTasksPage.jsx"), "utf8");
    const printer = readFileSync(resolve(here, "./taskDashboardPrint.js"), "utf8");
    expect(page).toContain("printTaskDashboard");
    expect(page).not.toContain("window.print");
    expect(printer).toContain("VeeWash Task Dashboard");
    expect(printer).toContain("letter portrait");
    expect(printer).not.toContain("window.print");
  });
});
