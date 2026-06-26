/** Offer letter field defaults and timeline helpers for HR Timeline. */

export const OFFER_LETTER_CONTACT_EMAIL = "care@veewash.com";

export function isContractorLane(workerLane) {
  return String(workerLane || "").startsWith("contractor") || workerLane === "contractor_1099";
}

export function formatOfferCompensation(rate) {
  if (rate == null || rate === "") return "";
  const n = Number(rate);
  if (Number.isNaN(n)) return String(rate).trim();
  return `$${n.toFixed(2)}/hour`;
}

export function defaultOfferLetterFields({ prefill, workerName, managerName, workerLane }) {
  const isContractor = isContractorLane(workerLane);
  const p = prefill || {};
  const today = new Date().toISOString().slice(0, 10);
  return {
    candidate_name: workerName || p.full_name || "",
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

export function formatDisplayDate(val) {
  if (!val) return "[date]";
  const s = String(val).slice(0, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(s)) return s;
  const [y, m, d] = s.split("-").map(Number);
  const dt = new Date(y, m - 1, d);
  if (Number.isNaN(dt.getTime())) return s;
  return dt.toLocaleDateString("en-US", { year: "numeric", month: "long", day: "numeric" });
}
