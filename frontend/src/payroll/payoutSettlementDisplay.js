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
  if (isPaymentRecordedUnpaid(line)) return "UNPAID";
  const val = line?.net_paid;
  if (val == null || val === "") return pendingLabel;
  const n = Number(val);
  if (!Number.isFinite(n)) return pendingLabel;
  return `$${n.toFixed(2)}`;
}

export function isPaymentRecordedUnpaid(line) {
  const rec = String(line?.payment_recorded || line?.settlement?.payment_recorded || "").toLowerCase();
  if (rec === "unpaid") return true;
  if (rec === "paid") return false;
  return String(line?.payment_status || "").toLowerCase() === "unpaid";
}

export function isPaymentRecordedPaid(line) {
  if (isPaymentRecordedUnpaid(line)) return false;
  if (String(line?.payment_recorded || "").toLowerCase() === "paid") return true;
  return String(line?.payment_status || "").toLowerCase() === "paid";
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
  { key: "federal_income_tax", label: "FWT" },
  { key: "social_security", label: "SS W/H" },
  { key: "medicare", label: "MC W/H" },
  { key: "state_tax", label: "NY State Tax" },
  { key: "local_tax", label: "NYC Resident Tax" },
  { key: "ny_sdi", label: "NY SDI" },
  { key: "ny_pfml", label: "NY PFML" },
  { key: "total_employee_taxes", label: "Total estimated withholding (liability)" },
  { key: "prior_tax_balance", label: "Prior period estimated balance" },
  { key: "total_tax_liability", label: "Total estimated withholding liability" },
  { key: "actual_tax_withheld", label: "Estimated withholding entered" },
  { key: "tax_balance_owed", label: "Estimated tax balance (period)" },
  { key: "remaining_balance", label: "Remaining estimated balance" },
  { key: "catch_up_withholding", label: "Catch-up withholding" },
  { key: "prior_period_adjustment", label: "Prior period adjustment (credit)" },
  { key: "total_tax_withheld", label: "Total estimated withholding" },
];
