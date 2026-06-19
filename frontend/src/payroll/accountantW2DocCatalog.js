/** W-2 employee documents on the Accountant screen — signed uploads except direct deposit. */

export const ACCOUNTANT_W2_DOCS = [
  {
    code: "direct_deposit",
    label: "Direct Deposit Authorization",
    kind: "generated",
    allowUpload: false,
  },
  {
    code: "w2_proof_employability",
    label: "Proof of Employability",
    kind: "uploaded",
    allowUpload: true,
  },
  {
    code: "hiring_documents",
    label: "Hiring Documents",
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

/** Legacy per-form codes consolidated under hiring_documents (read-only alias for existing uploads). */
export const LEGACY_HIRING_DOC_CODES = [
  "uscis_i9",
  "irs_w4",
  "ny_it2104",
  "ny_ls54",
];

/** Match uploaded document record by code (case-insensitive). */
export function findDocRecord(records, code) {
  const c = String(code || "").toUpperCase();
  return (records || []).find((r) => String(r.document_code || "").toUpperCase() === c);
}

/** All records for a catalog code, including legacy hiring aliases. */
export function findDocRecordsForCode(records, code) {
  const c = String(code || "").toUpperCase();
  if (c === "HIRING_DOCUMENTS") {
    const codes = new Set([
      "HIRING_DOCUMENTS",
      ...LEGACY_HIRING_DOC_CODES.map((lc) => lc.toUpperCase()),
    ]);
    return (records || []).filter((r) => codes.has(String(r.document_code || "").toUpperCase()));
  }
  const one = findDocRecord(records, code);
  return one ? [one] : [];
}

/** Primary record for view/print/delete — prefers hiring_documents, then latest legacy with file. */
export function resolvePrimaryDocRecord(records, code) {
  if (String(code || "").toUpperCase() === "HIRING_DOCUMENTS") {
    const primary = findDocRecord(records, "hiring_documents");
    if (primary?.file_uri) return primary;
    const legacyWithFile = (records || [])
      .filter(
        (r) =>
          LEGACY_HIRING_DOC_CODES.some(
            (lc) => lc.toUpperCase() === String(r.document_code || "").toUpperCase(),
          ) && r.file_uri,
      )
      .sort((a, b) => Number(b.id || 0) - Number(a.id || 0));
    return legacyWithFile[0] || primary || null;
  }
  return findDocRecord(records, code);
}

export function hasDocOnFile(records, code) {
  if (String(code || "").toUpperCase() === "HIRING_DOCUMENTS") {
    return findDocRecordsForCode(records, code).some((r) => r.file_uri);
  }
  return !!findDocRecord(records, code)?.file_uri;
}
