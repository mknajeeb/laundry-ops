export const ESTIMATE_DISCLAIMER =
  "Estimated withholding — verify with accountant/payroll provider.";

export const PAYROLL_ESTIMATE_PURPOSE =
  "Internal payroll estimate and accountant review tool only. Not a certified payroll tax filing engine. Final withholding, filings, and payments must be verified by your accountant or payroll provider.";

export const SEND_TO_ACCOUNTANT_W2_CONFIRM =
  "This W-2 payroll includes estimated tax calculations only. Final payroll tax withholding, filings, and payments must be verified by accountant/payroll provider.";

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
