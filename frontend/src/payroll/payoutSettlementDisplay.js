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
  return Object.keys(b).some((k) => k !== "total_tax_withheld" && Number(b[k]) !== 0);
}

export const TAX_WITHHELD_BREAKDOWN_LABELS = [
  { key: "federal_income_tax", label: "Federal Income Tax" },
  { key: "social_security", label: "Social Security" },
  { key: "medicare", label: "Medicare" },
  { key: "state_tax", label: "State Tax" },
  { key: "local_tax", label: "Local Tax" },
  { key: "other_deduction", label: "Other Deduction" },
  { key: "prior_period_adjustment", label: "Prior Period Adjustment" },
  { key: "total_tax_withheld", label: "Total Tax Withheld" },
];
