import { parseHrWorkJson } from "../utils/mailingMerge";

/** Build print prefill for W-2 letter templates from HR profile API payload. */
export function buildW2PrefillFromHrProfile(data) {
  const payroll = data?.payroll || {};
  const hr = data?.hr || {};
  const org = data?.org_settings || {};
  const work = parseHrWorkJson(hr.work_json);
  const first = String(payroll.first_name || "").trim();
  const last = String(payroll.last_name || "").trim();
  const fullName =
    `${first} ${last}`.trim() ||
    String(payroll.washpro_display_name || "").trim() ||
    String(hr.preferred_name || "").trim();
  const addr = String(payroll.address || work.address_line1 || work.mailing_address_line1 || "").trim();
  const rate = payroll.hourly_rate ?? work.hourly_rate ?? work.rate_per_hour;
  return {
    user_id: payroll.user_id,
    employee_id: String(payroll.employee_id || payroll.user_id || "").trim(),
    full_name: fullName,
    first_name: first,
    last_name: last,
    preferred_name: String(hr.preferred_name || "").trim(),
    phone: String(payroll.mobile || work.phone || hr.alternate_phone || "").trim(),
    email: String(payroll.email || work.email || "").trim(),
    address: addr,
    job_title: String(work.job_title || work.title || payroll.job_title || "").trim(),
    primary_location: String(work.primary_work_location || work.work_location || "").trim(),
    supervisor_name: String(work.supervisor_name || "").trim(),
    start_date: payroll.hire_date ? String(payroll.hire_date).slice(0, 10) : "",
    hire_date: payroll.hire_date ? String(payroll.hire_date).slice(0, 10) : "",
    rate_per_hour: rate != null && rate !== "" ? Number(rate) : null,
    payment_method: String(work.payment_method || payroll.payment_method || "").trim(),
    payment_cycle: String(work.payment_cycle || "Biweekly").trim(),
    company_name: String(org.employer_name || "VeeWash / Washpro").trim(),
    company_address: String(
      org.employer_address || "10438 Jamaica Avenue, Richmond Hill, NY 11418",
    ).trim(),
    company_phone: String(org.employer_phone || "(917) 341-5161").trim(),
    company_supervisor_name: String(org.company_supervisor_name || "").trim(),
    organization_logo_url: payroll.organization_logo_url || org.organization_logo_url,
  };
}
