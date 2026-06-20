/** Format net paid / tax withheld for accountant payroll tables. */

export function isPayoutDetailsFinalized(lineOrBatch) {
  if (!lineOrBatch || typeof lineOrBatch !== "object") return false;
  if (lineOrBatch.payout_details_finalized != null) {
    return Boolean(lineOrBatch.payout_details_finalized);
  }
  return Boolean(lineOrBatch.payout_details_finalized_at);
}

export function formatNetPaidDisplay(line, { pendingLabel = "Pending" } = {}) {
  if (!isPayoutDetailsFinalized(line)) return pendingLabel;
  const val = line?.net_paid;
  if (val == null || val === "") return pendingLabel;
  const n = Number(val);
  if (!Number.isFinite(n)) return pendingLabel;
  return `$${n.toFixed(2)}`;
}

export function formatTaxWithheldDisplay(line, { pendingLabel = "Pending" } = {}) {
  if (!isPayoutDetailsFinalized(line)) return pendingLabel;
  const val = line?.tax_withheld;
  if (val == null || val === "") return pendingLabel;
  const n = Number(val);
  if (!Number.isFinite(n)) return pendingLabel;
  return `$${n.toFixed(2)}`;
}

export function hasTaxWithheldBreakdown(line) {
  const b = line?.tax_withheld_breakdown;
  if (!b || typeof b !== "object") return false;
  const skip = new Set(["total_tax_withheld", "total_employee_taxes", "total_tax_liability"]);
  return Object.keys(b).some((k) => !skip.has(k) && Number(b[k]) !== 0);
}

export const TAX_WITHHELD_BREAKDOWN_LABELS = [
  { key: "federal_income_tax", label: "Federal Income Tax" },
  { key: "social_security", label: "Social Security" },
  { key: "medicare", label: "Medicare" },
  { key: "state_tax", label: "NY State Tax" },
  { key: "local_tax", label: "NYC Local Tax" },
  { key: "other_deduction", label: "Other Deduction" },
  { key: "total_employee_taxes", label: "Total estimated withholding (liability)" },
  { key: "prior_tax_balance", label: "Prior period estimated balance" },
  { key: "total_tax_liability", label: "Total estimated withholding liability" },
  { key: "actual_tax_withheld", label: "Estimated withholding entered" },
  { key: "tax_balance_owed", label: "Estimated withholding balance (period)" },
  { key: "remaining_balance", label: "Remaining estimated balance" },
  { key: "tax_catch_up_adjustment", label: "Estimated withholding catch-up" },
  { key: "prior_period_adjustment", label: "Prior period adjustment" },
  { key: "total_tax_withheld", label: "Total estimated withholding" },
];
