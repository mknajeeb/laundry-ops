/** US-centric helpers for payroll / HR forms. */

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** Calendar date in the user's local timezone as YYYY-MM-DD (matches `<input type="date">`). */
export function localDateYmd() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

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

/** Display US phone as (XXX) XXX-XXXX when 10 digits are available. */
export function formatUsPhoneDisplay(s) {
  const d = normalizeUsPhoneDigits(s);
  if (d.length !== 10) {
    const t = String(s || "").trim();
    return t || null;
  }
  return `(${d.slice(0, 3)}) ${d.slice(3, 6)}-${d.slice(6)}`;
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
