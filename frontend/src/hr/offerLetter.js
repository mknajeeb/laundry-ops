/** Offer letter field defaults and timeline helpers for HR Timeline. */

export const OFFER_LETTER_CONTACT_EMAIL = "care@veewash.com";

/** Employer name from org settings / HR prefill — never a mixed brand string. */
export function resolveOfferLetterCompanyName(source = {}) {
  const name = String(source?.company_name || "").trim();
  return name || "VeeWash";
}

export function isContractorLane(workerLane) {
  return String(workerLane || "").startsWith("contractor") || workerLane === "contractor_1099";
}

export function formatOfferCompensation(rate) {
  if (rate == null || rate === "") return "";
  const n = Number(rate);
  if (Number.isNaN(n)) return String(rate).trim();
  return `$${n.toFixed(2)}/hour`;
}

export function defaultOfferLetterFields({ prefill, workerName, workerEmail = "", managerName, workerLane }) {
  const isContractor = isContractorLane(workerLane);
  const p = prefill || {};
  const today = new Date().toISOString().slice(0, 10);
  return {
    candidate_name: workerName || p.full_name || "",
    candidate_email: String(workerEmail || p.email || "").trim(),
    candidate_address: p.address || "",
    position: p.job_title || (isContractor ? "Laundry Service Contractor" : "Laundry Production Associate"),
    position_details: "",
    contact_email: OFFER_LETTER_CONTACT_EMAIL,
    start_date: p.start_date || p.hire_date || "",
    hourly_rate: p.rate_per_hour != null && p.rate_per_hour !== "" ? String(p.rate_per_hour) : "",
    compensation: formatOfferCompensation(p.rate_per_hour),
    work_location: p.primary_location || "",
    schedule: isContractor
      ? "As assigned; acceptance required per assignment."
      : "Scheduled shifts per weekly roster and supervisor direction.",
    pay_frequency: p.payment_cycle || "Biweekly",
    manager_name: managerName || p.company_supervisor_name || p.supervisor_name || "",
    manager_title: "",
    offer_date: today,
    response_deadline: "",
    additional_terms: "",
    is_contractor: isContractor,
    company_name: resolveOfferLetterCompanyName(p),
  };
}

export function offerLetterDocumentTitle(isContractor) {
  return isContractor ? "Offer of Assignment" : "Offer of Employment";
}

export function buildOfferLetterTimelineDescription(fields) {
  const title = offerLetterDocumentTitle(fields?.is_contractor);
  const parts = [
    `${title} generated.`,
    fields?.position ? `Position: ${fields.position}.` : null,
    fields?.start_date ? `Start date: ${fields.start_date}.` : null,
    fields?.compensation ? `Compensation: ${fields.compensation}.` : null,
    fields?.work_location ? `Location: ${fields.work_location}.` : null,
  ].filter(Boolean);
  return parts.join(" ");
}

function lineOrNull(label, value) {
  const s = String(value ?? "").trim();
  return s ? `- ${label}: ${s}` : null;
}

export function buildOfferLetterEmailFilename(fields = {}) {
  const slug = (val, fallback) =>
    String(val || fallback)
      .trim()
      .replace(/[^\w\s-]/g, "")
      .replace(/\s+/g, "-")
      .slice(0, 48) || fallback;
  const name = slug(fields.candidate_name, "candidate");
  const position = slug(fields.position, "offer");
  return `Offer-${name}-${position}.pdf`;
}

/** Plain-text email for mailto / timeline logging. */
export function buildOfferLetterEmail(fields = {}, { includeAttachmentNote = false } = {}) {
  const docTitle = offerLetterDocumentTitle(fields.is_contractor);
  const candidate = String(fields.candidate_name || "[Name]").trim() || "[Name]";
  const firstName = candidate.split(/\s+/)[0] || candidate;
  const position = String(fields.position || "[position]").trim() || "[position]";
  const contactEmail = String(fields.contact_email || OFFER_LETTER_CONTACT_EMAIL).trim()
    || OFFER_LETTER_CONTACT_EMAIL;
  const manager = String(fields.manager_name || "").trim();
  const managerTitle = String(fields.manager_title || "").trim();
  const responseDeadline = fields.response_deadline
    ? formatDisplayDate(fields.response_deadline)
    : "";
  const companyName = resolveOfferLetterCompanyName(fields);

  const subject = `${docTitle} — ${position} — ${candidate}`;

  const summaryLines = [
    lineOrNull("Position", position),
    lineOrNull("Position details", fields.position_details),
    lineOrNull("Start date", fields.start_date ? formatDisplayDate(fields.start_date) : ""),
    lineOrNull("Work location", fields.work_location),
    lineOrNull("Schedule", fields.schedule),
    lineOrNull(
      fields.is_contractor ? "Service rate" : "Hourly rate",
      fields.compensation || formatOfferCompensation(fields.hourly_rate),
    ),
    lineOrNull("Pay frequency", fields.pay_frequency),
  ].filter(Boolean);

  const acceptanceLine = responseDeadline
    ? `Please confirm your acceptance by ${responseDeadline} by emailing ${contactEmail}.`
    : `Please confirm your acceptance by emailing ${contactEmail}.`;

  const bodyLines = [
    `Dear ${firstName},`,
    "",
    `${companyName} is pleased to extend an ${docTitle.toLowerCase()} for the position of ${position}.`,
    "",
    includeAttachmentNote
      ? "Please review the attached offer letter PDF for full details."
      : null,
    includeAttachmentNote ? "" : null,
    "Offer summary:",
    ...summaryLines,
    "",
    acceptanceLine,
    "Your start is contingent upon satisfactory completion of required onboarding.",
    "",
    "We look forward to working with you.",
    "",
    manager || "[Manager Name]",
    managerTitle || "[Title]",
    companyName,
  ].filter((line) => line !== null);

  if (String(fields.additional_terms || "").trim()) {
    bodyLines.splice(
      bodyLines.indexOf(acceptanceLine),
      0,
      "",
      "Additional terms:",
      String(fields.additional_terms).trim(),
    );
  }

  return { subject, body: bodyLines.join("\n") };
}

export function formatDisplayDate(val) {
  if (!val) return "[date]";
  const s = String(val).slice(0, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(s)) return s;
  const [y, m, d] = s.split("-").map(Number);
  const dt = new Date(y, m - 1, d);
  if (Number.isNaN(dt.getTime())) return s;
  return dt.toLocaleDateString("en-US", { year: "numeric", month: "long", day: "numeric" });
}
