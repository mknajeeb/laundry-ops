/** US-centric helpers for payroll / HR forms. */

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function isValidEmail(s) {
  const t = String(s || "").trim();
  if (!t || t.length > 254) return false;
  return EMAIL_RE.test(t);
}

/** Keep up to 10 digits (US phone); strip formatting. */
export function normalizeUsPhoneDigits(s) {
  return String(s || "").replace(/\D/g, "").slice(0, 10);
}

export function isValidUsPhone10(digits) {
  return digits.length === 10;
}

/** SSN / ITIN: 9 digits only for storage and PDF prefill. */
export function normalizeTaxIdDigits(s) {
  return String(s || "").replace(/\D/g, "").slice(0, 9);
}

export function isValidSsnOrItin9(digits) {
  return digits.length === 9;
}

/** Display mask: show only last 4 digits. */
export function maskTaxIdLast4(digitsOrRaw) {
  const d = String(digitsOrRaw || "").replace(/\D/g, "");
  if (d.length < 4) return "";
  return `***-**-${d.slice(-4)}`;
}
