/** Character and employment reference letter defaults and timeline helpers. */

import { formatDisplayDate, resolveOfferLetterCompanyName } from "./offerLetter";

export const EMPLOYMENT_REFERENCE_DOCUMENT_TITLE =
  "Character and Employment Reference Letter";

export const EMPLOYMENT_REFERENCE_ENTRY_TYPE = "employment_reference_letter";

function defaultCharacterStatement(employeeName, companyName) {
  const name = String(employeeName || "[Employee Name]").trim() || "[Employee Name]";
  const company = String(companyName || "VeeWash LLC").trim() || "VeeWash LLC";
  return (
    `During their time with ${company}, ${name} has demonstrated professionalism, ` +
    `reliability, and a responsible approach to their duties. They have worked cooperatively ` +
    `with management and team members and have contributed to our day-to-day operations. ` +
    `Based on our experience working with ${name}, we are pleased to provide this character ` +
    `and employment reference.`
  );
}

export function defaultEmploymentReferenceFields({
  prefill,
  workerName,
  workerEmail = "",
  managerName,
}) {
  const p = prefill || {};
  const today = new Date().toISOString().slice(0, 10);
  const companyName = resolveOfferLetterCompanyName(p);
  const employeeName = workerName || p.full_name || "";
  return {
    employee_name: employeeName,
    employee_email: String(workerEmail || p.email || "").trim(),
    employee_address: p.address || "",
    position: p.job_title || "",
    employment_details: "",
    letter_date: today,
    employment_start_date: p.start_date || p.hire_date || "",
    employment_end_date: "",
    character_statement: defaultCharacterStatement(employeeName, companyName || "VeeWash LLC"),
    custom_content: "",
    additional_terms: "",
    employment_status: "Current Employee",
    work_location: p.primary_location || "",
    reporting_to: "Managing Director or designated supervisor",
    signatory_name: managerName || p.company_supervisor_name || "Muhammad Kamran Najeeb",
    signatory_title: "Managing Director",
    company_name: companyName,
  };
}

export function buildEmploymentPeriodText(fields = {}) {
  const start = fields.employment_start_date
    ? formatDisplayDate(fields.employment_start_date)
    : "[Start Date]";
  const endRaw = String(fields.employment_end_date || "").trim();
  if (endRaw) {
    return `from ${start} to ${formatDisplayDate(endRaw)}`;
  }
  return `from ${start} to present`;
}

export function buildEmploymentReferenceTimelineDescription(fields) {
  const parts = [
    `${EMPLOYMENT_REFERENCE_DOCUMENT_TITLE} generated.`,
    fields?.position ? `Position: ${fields.position}.` : null,
    fields?.employment_start_date
      ? `Employment start: ${formatDisplayDate(fields.employment_start_date)}.`
      : null,
    fields?.employment_end_date
      ? `Employment end: ${formatDisplayDate(fields.employment_end_date)}.`
      : "Employment end: present.",
    fields?.employment_status ? `Status: ${fields.employment_status}.` : null,
    fields?.work_location ? `Location: ${fields.work_location}.` : null,
    fields?.signatory_name ? `Signatory: ${fields.signatory_name}.` : null,
  ].filter(Boolean);

  const snapshot = {
    employee_name: fields?.employee_name || "",
    employee_email: fields?.employee_email || "",
    employee_address: fields?.employee_address || "",
    position: fields?.position || "",
    employment_details: fields?.employment_details || "",
    letter_date: fields?.letter_date || "",
    employment_start_date: fields?.employment_start_date || "",
    employment_end_date: fields?.employment_end_date || "",
    character_statement: fields?.character_statement || "",
    custom_content: fields?.custom_content || "",
    additional_terms: fields?.additional_terms || "",
    employment_status: fields?.employment_status || "",
    work_location: fields?.work_location || "",
    reporting_to: fields?.reporting_to || "",
    signatory_name: fields?.signatory_name || "",
    signatory_title: fields?.signatory_title || "",
    company_name: fields?.company_name || "",
  };
  return `${parts.join(" ")}\n\n[letter_snapshot]\n${JSON.stringify(snapshot)}`;
}

export function buildEmploymentReferenceEmailFilename(fields = {}) {
  const slug = (val, fallback) =>
    String(val || fallback)
      .trim()
      .replace(/[^\w\s-]/g, "")
      .replace(/\s+/g, "-")
      .slice(0, 48) || fallback;
  const name = slug(fields.employee_name, "employee");
  const position = slug(fields.position, "reference");
  return `Employment-Reference-${name}-${position}.pdf`;
}

export function buildEmploymentReferenceEmail(fields = {}, { includeAttachmentNote = false } = {}) {
  const employee = String(fields.employee_name || "[Name]").trim() || "[Name]";
  const firstName = employee.split(/\s+/)[0] || employee;
  const position = String(fields.position || "[position]").trim() || "[position]";
  const companyName = resolveOfferLetterCompanyName(fields);
  const period = buildEmploymentPeriodText(fields);
  const signatory = String(fields.signatory_name || "[Signatory Name]").trim();
  const signatoryTitle = String(fields.signatory_title || "Managing Director").trim();

  const subject = `${EMPLOYMENT_REFERENCE_DOCUMENT_TITLE} — ${position} — ${employee}`;

  const bodyLines = [
    `Dear ${firstName},`,
    "",
    includeAttachmentNote
      ? "Please review the attached character and employment reference letter for full details."
      : null,
    includeAttachmentNote ? "" : null,
    `This message accompanies a character and employment reference letter confirming that you have been employed by ${companyName} as ${position} ${period}.`,
    "",
    "Please feel free to share the attached letter with any party that requires verification of your employment.",
    "",
    "Sincerely,",
    "",
    signatory,
    signatoryTitle,
    companyName,
  ].filter((line) => line !== null);

  return { subject, body: bodyLines.join("\n") };
}
