/** Contractor document checklist — signed service docs only; discipline via HR Timeline. */

export const IRS_W9_URL = "https://www.irs.gov/pub/irs-pdf/fw9.pdf";

export const REGULAR_CONTRACTOR_DOCS = [
  { code: "contractor_w9", name: "W-9", required: true },
  { code: "contractor_ic_agreement", name: "Independent Contractor Agreement", required: true },
  { code: "contractor_service_guide", name: "Contractor Service Standards Guide" },
  { code: "contractor_performance_addendum", name: "Performance Standards Addendum" },
  { code: "contractor_first_time_packet", name: "First-Time Contractor Packet", required: true },
  { code: "contractor_rate_confirmation", name: "Contractor Rate / Payment Confirmation" },
  { code: "contractor_invoice_payment", name: "Contractor Invoice & Payment Receipts" },
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
