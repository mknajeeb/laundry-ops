/** Whether a Time Records row may be approved, and the reason when it may not.

Worker category (W-2, 1099, temp) does not change this. Finalized payroll stays
locked. The permission flag must match the approve API
(`ta.settings`, `ta.override`, or `users.edit`).
*/

export function approvalActionForRecord(row, { canApprove = false } = {}) {
  if (canApprove == null) {
    return { action: "pending", reason: "" };
  }
  if (!canApprove) {
    return {
      action: "blocked",
      reason: "You do not have permission to approve time",
    };
  }
  if (row?.payroll_finalized) {
    return { action: "blocked", reason: "Finalized payroll — hours stay locked" };
  }
  if (row?.has_open_break) {
    return {
      action: "blocked",
      reason: "Close or remove the open break before approving",
    };
  }
  if (row?.status === "approved" || row?.payroll_hours_approved) {
    return { action: "approved", reason: "" };
  }
  if (row?.status === "open") {
    return {
      action: "blocked",
      reason: row?.clock_out_at ? "Shift is still marked open" : "Clock out before approving",
    };
  }
  if (row?.status === "pending_approval" || row?.status === "completed") {
    return { action: "approve", reason: "" };
  }
  return { action: "blocked", reason: "This record cannot be approved" };
}

export function canApproveRecord(row, options) {
  return approvalActionForRecord(row, options).action === "approve";
}
