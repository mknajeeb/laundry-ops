/** Document checklists by worker category (replaces old C-documents). */

export const W2_EMPLOYEE_DOCS = [
  { code: "w2_wage_notice", name: "Employee wage notice / LS form" },
  { code: "w2_w4", name: "W-4, if collected" },
  { code: "w2_i9", name: "I-9, if collected" },
  { code: "w2_handbook", name: "Employee handbook acknowledgment" },
  { code: "w2_sick_leave", name: "Sick leave policy acknowledgment" },
  { code: "w2_paystub", name: "Paystub / pay statements" },
  { code: "w2_incident", name: "Incident reports, if any" },
];

export const CONTRACTOR_1099_DOCS = [
  { code: "contractor_w9", name: "W-9", required: true },
  { code: "contractor_first_time_packet", name: "First-Time Contractor Packet" },
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

export function checklistForWorkerCategory(category) {
  if (category === "w2") return W2_EMPLOYEE_DOCS;
  if (category === "contractor_1099") return CONTRACTOR_1099_DOCS;
  return TEMP_CONTRACTOR_DOCS;
}

export const WORKER_CATEGORY_OPTIONS = [
  { value: "all", label: "All categories" },
  { value: "w2", label: "W-2 Employee" },
  { value: "contractor_1099", label: "1099 Contractor" },
  { value: "temp", label: "Temp / One-Time" },
];
