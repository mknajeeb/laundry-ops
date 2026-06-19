import { applyFormValuesToMarkdown } from "../contractorForms/applyFormValues";
import {
  applyPrefillToMarkdown as applyContractorPrefill,
  markdownToPrintHtml,
  sanitizePacketMarkdown,
} from "../contractorForms/prefillMarkdown";
import { miniHeadHtml } from "../contractorForms/ContractorPrintShell";
import { applyW2FormValuesToMarkdown } from "./applyW2FormValues";

const EMPLOYEE_LABEL_MAP = [
  ["Employee Name", "full_name"],
  ["Employee ID", "employee_id"],
  ["Job Title / Function", "job_title"],
  ["Primary Work Location", "primary_location"],
  ["Primary Pay Method", "primary_pay_method"],
  ["Pay Period / Cycle", "pay_period_cycle"],
  ["Hourly Rate ($)", "hourly_rate"],
  ["Separation Type", "separation_type"],
];

function val(prefill, key) {
  const v = prefill?.[key];
  if (v == null || v === "") return "";
  return String(v).trim();
}

function fillLabelLine(md, label, value) {
  if (!value) return md;
  const esc = label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const patterns = [
    new RegExp(`(\\*\\*${esc}:?\\*\\*)\\s*_{2,}`, "gi"),
    new RegExp(`(^${esc}:)\\s*_{2,}`, "gim"),
  ];
  let out = md;
  for (const re of patterns) {
    out = out.replace(re, `$1 ${value}`);
  }
  return out;
}

/** Map W-2 prefill onto workforce markdown (employee-specific labels). */
export function applyW2PrefillToMarkdown(md, prefill, extra = {}) {
  const merged = {
    full_name: val(prefill, "full_name"),
    employee_id: val(prefill, "employee_id"),
    job_title: val(prefill, "job_title"),
    primary_location: val(prefill, "primary_location"),
    company_name: val(prefill, "company_name"),
    company_address: val(prefill, "company_address"),
    start_date: val(prefill, "start_date"),
    hire_date: val(prefill, "hire_date"),
    rate_per_hour: prefill?.rate_per_hour,
    payment_method: val(prefill, "payment_method"),
    payment_cycle: val(prefill, "payment_cycle"),
    pay_period_cycle: val(extra, "pay_period_cycle") || val(prefill, "payment_cycle"),
    primary_pay_method: val(extra, "primary_pay_method") || val(prefill, "payment_method"),
    hourly_rate:
      extra.hourly_rate != null && extra.hourly_rate !== ""
        ? extra.hourly_rate
        : prefill?.rate_per_hour,
    separation_type: val(extra, "separation_type"),
    ...extra,
  };
  let out = sanitizePacketMarkdown(md);
  out = applyContractorPrefill(out, { ...prefill, ...merged }, merged);
  for (const [label, key] of EMPLOYEE_LABEL_MAP) {
    out = fillLabelLine(out, label, merged[key]);
  }
  if (merged.full_name) {
    out = out.replace(/(\*\*Employee Name:\*\*\s*)_{2,}/gi, `$1 ${merged.full_name}`);
  }
  if (merged.rate_per_hour != null && merged.rate_per_hour !== "") {
    out = out.replace(/\$\s*_{5,}/, `$${Number(merged.rate_per_hour).toFixed(2)}`);
  }
  return out;
}

export function buildW2MultiSectionPrintHtml(
  sectionsByNum,
  sectionNums,
  prefill,
  extra = {},
  options = {},
) {
  const { formId, formValues, editorFormId } = options;
  const parts = [];
  (sectionNums || []).forEach((n, index) => {
    const s = sectionsByNum[n];
    if (!s?.body) return;
    let md = applyW2PrefillToMarkdown(s.body, prefill, extra);
    const applyId = editorFormId || formId;
    if (applyId && formValues && Object.keys(formValues).length) {
      md = applyFormValuesToMarkdown(md, applyId, formValues, prefill);
      md = applyW2FormValuesToMarkdown(md, applyId, formValues, prefill);
    }
    const inner = markdownToPrintHtml(md);
    const pageClass = index > 0 ? " cform-page--new" : "";
    const mini = index > 0 ? miniHeadHtml(prefill) : "";
    parts.push(`<section class="cform-page${pageClass}">${mini}${inner}</section>`);
  });
  return parts.join("\n");
}
