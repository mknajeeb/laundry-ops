import { foldingExceptionLabel } from "./foldingExceptionLabels";

export function parseWarningCodes(raw) {
  if (!raw) return [];
  if (Array.isArray(raw)) return raw.filter(Boolean);
  const s = String(raw).trim();
  if (!s) return [];
  try {
    const parsed = JSON.parse(s);
    return Array.isArray(parsed) ? parsed.filter(Boolean) : [];
  } catch {
    return [];
  }
}

/** Primary exception + secondary warnings for tables. */
export function formatExceptionDisplay(row) {
  const primary = row?.exception_code || null;
  const warnings = parseWarningCodes(row?.warning_codes).filter(
    (c) => c && c !== primary
  );
  return { primary, warnings };
}

export function primaryExceptionLabel(row) {
  const { primary } = formatExceptionDisplay(row);
  if (!primary) return "—";
  return foldingExceptionLabel(primary);
}

export function warningExceptionLabels(row) {
  return formatExceptionDisplay(row).warnings.map((c) => ({
    code: c,
    label: foldingExceptionLabel(c),
  }));
}
