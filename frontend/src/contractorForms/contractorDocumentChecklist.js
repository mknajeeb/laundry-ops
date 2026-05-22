/** Contractor document checklist (replaces old C-document compliance for 1099/temp). */

export const IRS_W9_URL = "https://www.irs.gov/pub/irs-pdf/fw9.pdf";

export const REGULAR_CONTRACTOR_DOCS = [
  { code: "contractor_w9", name: "W-9", required: true },
  { code: "contractor_first_time_packet", name: "First-Time Contractor Packet", required: true },
  { code: "contractor_rate_confirmation", name: "Contractor Rate / Payment Confirmation" },
  { code: "contractor_invoice_payment", name: "Contractor Invoice & Payment Receipts" },
  { code: "contractor_written_warning", name: "Written Warning / Notice, if any" },
  { code: "contractor_probation_review", name: "Two-Week Probation Review, if any" },
  { code: "contractor_final_warning", name: "Final Warning, if any" },
  { code: "contractor_termination_notice", name: "Termination / Non-Offer Notice, if any" },
  { code: "contractor_incident_report", name: "Incident / Injury Report, if any" },
  { code: "contractor_clock_payment_correction", name: "Clock / Payment Correction Request, if any" },
  { code: "contractor_property_return", name: "Property / Access Return Checklist, if any" },
];

export const TEMP_CONTRACTOR_DOCS = [
  { code: "contractor_invoice_payment", name: "Contractor Invoice & Payment Receipt" },
  { code: "contractor_incident_report", name: "Incident / Injury Report, if any" },
  { code: "contractor_payment_proof", name: "Payment proof, if separate" },
  { code: "contractor_w9", name: "W-9 (if collected / required later)" },
];

export function checklistForType(contractorType) {
  if (contractorType === "regular") return REGULAR_CONTRACTOR_DOCS;
  return TEMP_CONTRACTOR_DOCS;
}
