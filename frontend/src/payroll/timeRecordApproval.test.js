import { describe, expect, it } from "vitest";
import { approvalActionForRecord, canApproveRecord } from "./timeRecordApproval";

const permitted = { canApprove: true };

describe("approvalActionForRecord", () => {
  it("shows Approve for a completed record when the user may approve", () => {
    expect(approvalActionForRecord({ status: "completed" }, permitted).action).toBe("approve");
  });

  it("shows Approve for a manual correction that is pending", () => {
    expect(
      approvalActionForRecord({ status: "pending_approval", manual_override: true }, permitted).action,
    ).toBe("approve");
  });

  it("shows no button and no extra reason once the record is approved", () => {
    const result = approvalActionForRecord(
      { status: "approved", payroll_hours_approved: true },
      permitted,
    );
    expect(result).toEqual({ action: "approved", reason: "" });
    expect(canApproveRecord({ status: "approved" }, permitted)).toBe(false);
  });

  it("explains an open shift, including one that already has a clock-out", () => {
    expect(approvalActionForRecord({ status: "open" }, permitted).reason).toMatch(/Clock out/i);
    expect(
      approvalActionForRecord({ status: "open", clock_out_at: "2026-10-27T11:25:16" }, permitted).reason,
    ).toMatch(/still marked open/i);
  });

  it("explains an open break", () => {
    expect(
      approvalActionForRecord({ status: "completed", has_open_break: true }, permitted).reason,
    ).toMatch(/open break/i);
  });

  it("keeps finalized payroll locked", () => {
    const result = approvalActionForRecord(
      { status: "completed", payroll_finalized: true },
      permitted,
    );
    expect(result.action).toBe("blocked");
    expect(result.reason).toMatch(/Finalized/);
  });

  it("does not treat worker category as an approval rule", () => {
    for (const worker_category of ["w2", "contractor_1099", "temp"]) {
      expect(
        approvalActionForRecord({ status: "completed", worker_category }, permitted).action,
      ).toBe("approve");
    }
  });

  it("hides Approve when the user lacks the approve permission", () => {
    const result = approvalActionForRecord({ status: "completed" }, { canApprove: false });
    expect(result.action).toBe("blocked");
    expect(result.reason).toMatch(/permission/i);
    expect(canApproveRecord({ status: "completed" }, { canApprove: false })).toBe(false);
  });
});
