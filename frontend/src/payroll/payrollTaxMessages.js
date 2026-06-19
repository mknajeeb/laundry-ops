export const MANUAL_DEDUCTIONS_NOTICE =
  "Tax deductions are entered manually in Payout Details after the batch is approved.";

export const ESTIMATE_DISCLAIMER =
  "Estimated withholding — verify with accountant/payroll provider.";

export const PAYROLL_ESTIMATE_PURPOSE =
  "Internal payroll estimate and accountant review tool only. Not a certified payroll tax filing engine. Final withholding, filings, and payments must be verified by your accountant or payroll provider.";

export const SEND_TO_ACCOUNTANT_W2_CONFIRM =
  "Confirm this W-2 batch is ready for accountant review. Tax deductions will be entered manually in Payout Details.";

/** Shown to accountant after payroll confirms the batch is ready. */
export const ACCOUNTANT_BATCH_READY_MESSAGE =
  "Payroll confirmed this W-2 batch is ready for your review. You may proceed with direct deposit forms and payroll processing.";

export const ESTIMATED_WITHHOLDING_NOTICE = ESTIMATE_DISCLAIMER;

/** Display money or em dash when tax values must not be shown. */
export function formatTaxAmount(val, { incomplete = false } = {}) {
  if (incomplete || val == null || val === "") return "—";
  const n = Number(val);
  if (Number.isNaN(n)) return "—";
  return `$${n.toFixed(2)}`;
}

export function isLineTaxIncomplete(line) {
  return line?.tax_calc_status === "profile_incomplete";
}
