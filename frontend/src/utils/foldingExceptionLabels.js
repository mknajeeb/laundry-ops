/** Plain-English labels for folding exception / warning codes. */

const LABELS = {
  MISSING_SCAN_EVENTS: "No scan events are stored for this bag.",
  MISSING_FOLDING: "No FOLDING rack scan was found.",
  MISSING_CLEAN: "No CLEAN rack scan was found after folding.",
  CLEAN_BEFORE_FOLDING: "A CLEAN scan occurred before the folding scan.",
  INVALID_TIMESTAMPS: "Folding or clean scan timestamps could not be parsed.",
  MISSING_ASSIGNED_USER: "No user on the folding or end clean scan.",
  MULTIPLE_FOLDING_SCANS: "More than one FOLDING scan; cannot auto-calculate.",
  FOLDING_DURATION_TOO_SHORT: "Folding interval is under 10 minutes.",
  MULTIPLE_CLEAN_SCANS:
    "Multiple CLEAN scans after folding; duration uses first FOLDING and last CLEAN after folding. Still counts in scoring unless excluded.",
};

export function foldingExceptionLabel(code) {
  const c = String(code || "").trim();
  if (!c) return "";
  return LABELS[c] || c.replace(/_/g, " ").toLowerCase();
}
