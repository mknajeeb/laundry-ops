/**
 * Normalize `hr.work_json` from GET /hr-profile (object, or JSON string from some clients/caches).
 */
/** Detect legacy bad saves where work_json was stored as an object under emergency_contacts_json. */
export function emergencyContactsJsonLooksLikeWorkJsonSpill(raw) {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return false;
  if (raw.i9 && typeof raw.i9 === "object") return true;
  if (raw.w4 && typeof raw.w4 === "object") return true;
  if (raw.ny_it2104 && typeof raw.ny_it2104 === "object" && Object.keys(raw.ny_it2104).length > 0) {
    return true;
  }
  const keys = [
    "middle_initial",
    "job_title",
    "language_preference",
    "supervisor_name",
    "rehire_start_date",
    "mailing_address_line1",
    "address_line1",
  ];
  let n = 0;
  for (const k of keys) {
    if (raw[k] != null && String(raw[k]).trim() !== "") n += 1;
  }
  return n >= 3;
}

/**
 * Prefer hr.work_json; if empty/missing and emergency_contacts_json is a work-shaped object, use it
 * (server also repairs this, but keeps older clients/API caches working).
 */
export function coalesceWorkJsonFromHr(hr) {
  const w = parseHrWorkJson(hr?.work_json);
  const ec = hr?.emergency_contacts_json;
  if (!ec || typeof ec !== "object" || Array.isArray(ec)) return w;
  if (!emergencyContactsJsonLooksLikeWorkJsonSpill(ec)) return w;
  const spill = ec;
  if (!w || Object.keys(w).length === 0) return { ...spill };
  return { ...spill, ...w };
}

export function parseHrWorkJson(raw) {
  if (raw == null || raw === "") return {};
  let cur = raw;
  for (let i = 0; i < 4; i++) {
    if (cur && typeof cur === "object" && !Array.isArray(cur)) return cur;
    if (typeof cur === "string" && cur.trim()) {
      try {
        cur = JSON.parse(cur);
      } catch {
        return {};
      }
    } else {
      return {};
    }
  }
  return cur && typeof cur === "object" && !Array.isArray(cur) ? cur : {};
}

/**
 * Fill missing work_json mailing fields from payroll_profiles.address (multi-line blob).
 * Matches backend hr_pdf_acroform / hr_compliance loose-address parsing.
 */
export function mergePayrollMailingIntoWork(work, payroll) {
  const w = work && typeof work === "object" ? { ...work } : {};
  const raw = String(payroll?.address || "").trim();
  if (!raw) return w;

  const lines = raw
    .split(/\r?\n/)
    .map((s) => s.trim())
    .filter(Boolean);
  if (!lines.length) return w;

  if (lines.length === 1) {
    const m = lines[0].match(/^(.+),\s*(.+?)\s+([A-Za-z]{2})\s+(\d{5}(?:-\d{4})?)\s*$/);
    if (m) {
      if (!String(w.address_line1 || w.mailing_address_line1 || "").trim()) {
        w.address_line1 = m[1].trim();
        w.mailing_address_line1 = m[1].trim();
      }
      if (!String(w.city || "").trim()) w.city = m[2].trim();
      if (!String(w.state || "").trim()) w.state = m[3].toUpperCase();
      if (!String(w.zip || w.zip_code || "").trim()) {
        w.zip = m[4];
        w.zip_code = m[4];
      }
      return w;
    }
  }

  const line1 = () => String(w.address_line1 || w.mailing_address_line1 || "").trim();
  if (!line1()) {
    w.address_line1 = lines[0];
    w.mailing_address_line1 = lines[0];
  }

  if (lines.length >= 2) {
    const last = lines[lines.length - 1];
    const m = last.match(/^([^,]+),\s*([A-Za-z]{2})\s*(\d{5}(?:-\d{4})?)$/);
    if (m) {
      if (!String(w.city || "").trim()) w.city = m[1].trim();
      if (!String(w.state || "").trim()) w.state = m[2].toUpperCase();
      if (!String(w.zip || w.zip_code || "").trim()) {
        w.zip = m[3];
        w.zip_code = m[3];
      }
    }
  }
  return w;
}
