/** Position confirmation letter defaults and timeline helpers for HR Timeline. */

import { formatDisplayDate, resolveOfferLetterCompanyName } from "./offerLetter";

export const POSITION_CONFIRMATION_DOCUMENT_TITLE = "Position Confirmation Letter";

export function defaultPositionConfirmationFields({
  prefill,
  workerName,
  workerEmail = "",
  managerName,
}) {
  const p = prefill || {};
  const today = new Date().toISOString().slice(0, 10);
  return {
    employee_name: workerName || p.full_name || "",
    employee_email: String(workerEmail || p.email || "").trim(),
    employee_address: p.address || "",
    position: p.job_title || "",
    letter_date: today,
    effective_date: today,
    employment_status: "Regular Employee",
    work_location: p.primary_location || "",
    reporting_to: "Managing Director or designated supervisor",
    signatory_name: managerName || p.company_supervisor_name || "Muhammad Kamran Najeeb",
    signatory_title: "Managing Director",
    company_name: resolveOfferLetterCompanyName(p),
  };
}

export function buildPositionConfirmationTimelineDescription(fields) {
  const parts = [
    `${POSITION_CONFIRMATION_DOCUMENT_TITLE} generated.`,
    fields?.position ? `Position: ${fields.position}.` : null,
    fields?.effective_date
      ? `Effective date: ${formatDisplayDate(fields.effective_date)}.`
      : null,
    fields?.employment_status ? `Status: ${fields.employment_status}.` : null,
  ].filter(Boolean);
  return parts.join(" ");
}

export function buildPositionConfirmationEmailFilename(fields = {}) {
  const slug = (val, fallback) =>
    String(val || fallback)
      .trim()
      .replace(/[^\w\s-]/g, "")
      .replace(/\s+/g, "-")
      .slice(0, 48) || fallback;
  const name = slug(fields.employee_name, "employee");
  const position = slug(fields.position, "confirmation");
  return `Position-Confirmation-${name}-${position}.pdf`;
}

export function buildPositionConfirmationEmail(fields = {}, { includeAttachmentNote = false } = {}) {
  const employee = String(fields.employee_name || "[Name]").trim() || "[Name]";
  const firstName = employee.split(/\s+/)[0] || employee;
  const position = String(fields.position || "[position]").trim() || "[position]";
  const companyName = resolveOfferLetterCompanyName(fields);
  const effectiveDate = formatDisplayDate(fields.effective_date);
  const signatory = String(fields.signatory_name || "[Signatory Name]").trim();
  const signatoryTitle = String(fields.signatory_title || "Managing Director").trim();

  const subject = `${POSITION_CONFIRMATION_DOCUMENT_TITLE} — ${position} — ${employee}`;

  const bodyLines = [
    `Dear ${firstName},`,
    "",
    includeAttachmentNote
      ? "Please review the attached position confirmation letter for full details."
      : null,
    includeAttachmentNote ? "" : null,
    `We are pleased to confirm that, effective ${effectiveDate}, you have successfully completed your probationary period and are now confirmed as a ${String(fields.employment_status || "Regular Employee").trim()} of ${companyName} in the position of ${position}.`,
    "",
    "Congratulations on successfully completing your probationary period. We look forward to your continued contributions.",
    "",
    "Sincerely,",
    "",
    signatory,
    signatoryTitle,
    companyName,
  ].filter((line) => line !== null);

  return { subject, body: bodyLines.join("\n") };
}
