/** W-2 employee documents on the Accountant screen — signed uploads except direct deposit. */

export const ACCOUNTANT_W2_DOCS = [
  {
    code: "direct_deposit",
    label: "Direct Deposit Authorization",
    kind: "generated",
    allowUpload: false,
  },
  {
    code: "uscis_i9",
    label: "Form I-9",
    kind: "uploaded",
    allowUpload: true,
  },
  {
    code: "irs_w4",
    label: "Form W-4",
    kind: "uploaded",
    allowUpload: true,
  },
  {
    code: "w2_proof_employability",
    label: "Proof of Employability",
    kind: "uploaded",
    allowUpload: true,
  },
  {
    code: "ny_it2104",
    label: "NY IT-2104",
    kind: "uploaded",
    allowUpload: true,
  },
  {
    code: "ny_ls54",
    label: "NY LS-54 (Wage Notice)",
    kind: "uploaded",
    allowUpload: true,
  },
  {
    code: "w2_handbook_other",
    label: "Employee Handbook / Other Letters & Correspondence",
    kind: "uploaded",
    allowUpload: true,
  },
];

/** Match uploaded document record by code (case-insensitive). */
export function findDocRecord(records, code) {
  const c = String(code || "").toUpperCase();
  return (records || []).find((r) => String(r.document_code || "").toUpperCase() === c);
}
