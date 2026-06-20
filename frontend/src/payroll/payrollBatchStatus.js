/** Single user-facing payroll status model — mirrors backend/payroll_status_display.py */

export const DISPLAY_STATUS_LABELS = {
  draft: "Draft",
  ready_for_payroll: "Ready For Payroll",
  ready_to_pay: "Ready To Pay",
  paid: "Paid",
};

export const DISPLAY_STATUS_COLORS = {
  draft: "default",
  ready_for_payroll: "info",
  ready_to_pay: "warning",
  paid: "success",
};

export function getPayrollDisplay(batch) {
  return batch?.payroll_display || {};
}

export function displayStatus(batch) {
  return getPayrollDisplay(batch).display_status || "draft";
}

export function displayStatusLabel(batch) {
  return getPayrollDisplay(batch).display_status_label || DISPLAY_STATUS_LABELS.draft;
}

export function displayStatusColor(batch) {
  return getPayrollDisplay(batch).display_status_color || DISPLAY_STATUS_COLORS.draft;
}

export function primaryAction(batch) {
  return getPayrollDisplay(batch).primary_action || null;
}

export function payrollSummary(batch) {
  return getPayrollDisplay(batch).payroll_summary || {};
}

export function formatPayrollMoney(val) {
  if (val == null || val === "") return "—";
  const n = Number(val);
  if (!Number.isFinite(n)) return "—";
  return `$${n.toFixed(2)}`;
}

export function batchVisibleForDetails(batch) {
  const st = displayStatus(batch);
  return st !== "draft";
}
