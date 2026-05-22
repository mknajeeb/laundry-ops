/** Editable field schemas per contractor form (shared across Forms tab + print). */

export const COMMON_META_FIELDS = [
  { key: "company_representative", label: "Company representative", type: "text" },
  { key: "issued_by", label: "Issued by", type: "text" },
  { key: "effective_date", label: "Effective date", type: "date" },
  { key: "notice_date", label: "Notice date", type: "date" },
  { key: "review_date", label: "Review date", type: "date" },
  { key: "date_submitted", label: "Date submitted", type: "date" },
];

function cb(key, label) {
  return { id: key, label };
}

export const FORM_FIELD_SCHEMAS = {
  rate_confirmation: {
    fields: [
      { key: "rate_per_hour", label: "Rate per hour ($)", type: "number" },
      { key: "rate_per_assignment", label: "Rate per assignment ($)", type: "number" },
      { key: "rate_other", label: "Other rate description", type: "text" },
      {
        key: "service_type",
        label: "Service type",
        type: "checkbox_group",
        options: [
          cb("laundry", "Laundry support / folding"),
          cb("pickup", "Pickup / delivery support"),
          cb("cleaning", "Cleaning / maintenance support"),
          cb("service_other", "Other (describe below)"),
        ],
      },
      { key: "service_other_text", label: "Other service type", type: "text" },
      {
        key: "payment_cycle",
        label: "Payment cycle",
        type: "checkbox_group",
        single: true,
        options: [
          cb("biweekly", "Biweekly"),
          cb("weekly", "Weekly"),
          cb("cycle_other", "Other"),
        ],
      },
      {
        key: "payment_method",
        label: "Payment method",
        type: "checkbox_group",
        single: true,
        options: [
          cb("check", "Business check"),
          cb("ach", "ACH"),
          cb("zelle", "Zelle"),
          cb("venmo", "Venmo business payment"),
          cb("cash", "Cash with signed receipt"),
          cb("pm_other", "Other"),
        ],
      },
      { key: "payment_method_other", label: "Other payment method", type: "text" },
    ],
  },
  written_warning: {
    fields: [
      { key: "incident_date", label: "Date of incident / issue", type: "date" },
      {
        key: "issue_type",
        label: "Type of issue",
        type: "checkbox_group",
        options: [
          cb("performance", "Performance / speed standard"),
          cb("quality", "Quality issue"),
          cb("attendance", "Attendance / reliability"),
          cb("clock", "Clock-in / clock-out issue"),
          cb("safety", "Safety issue"),
          cb("hygiene", "Hygiene issue"),
          cb("property", "Customer-property handling"),
          cb("conduct", "Premises conduct / break rules"),
          cb("confidentiality", "Confidentiality / customer information"),
          cb("incident_fail", "Failure to report incident"),
          cb("issue_other", "Other"),
        ],
      },
      { key: "issue_description", label: "Description of issue", type: "multiline" },
      { key: "expected_correction", label: "Expected correction", type: "multiline" },
    ],
  },
  probation_review: {
    fields: [
      { key: "review_period_start", label: "Review period start", type: "date" },
      { key: "review_period_end", label: "Review period end", type: "date" },
      {
        key: "review_result",
        label: "Review result",
        type: "checkbox_group",
        single: true,
        options: [
          cb("passed", "Passed — may continue assignments"),
          cb("improve", "May continue — improvement required"),
          cb("failed", "Did not meet standards"),
          cb("extended", "Review period extended"),
        ],
      },
      { key: "review_notes", label: "Notes / required improvements", type: "multiline" },
    ],
  },
  property_return_checklist: {
    fields: [
      { key: "effective_date", label: "Effective date", type: "date" },
      {
        key: "items_returned",
        label: "Items returned / removed",
        type: "checkbox_group",
        options: [
          cb("keys", "Keys / access cards"),
          cb("app", "App/system access removed"),
          cb("customer_info", "Customer information returned/deleted"),
          cb("bags", "Company/customer bags or labels"),
          cb("supplies", "Supplies / tools / equipment"),
          cb("documents", "Documents / printed records"),
          cb("uniform", "Uniform/shirt/apron, if any"),
          cb("final_summary", "Final payment summary prepared"),
          cb("incident", "Incident/open issue reviewed"),
        ],
      },
    ],
  },
};

export function schemaForForm(formId) {
  return FORM_FIELD_SCHEMAS[formId] || { fields: [] };
}

export function emptyFormValues(formId, prefill = {}) {
  const base = {
    company_representative: "",
    issued_by: "",
    effective_date: prefill.start_date || "",
    notice_date: new Date().toISOString().slice(0, 10),
    review_date: new Date().toISOString().slice(0, 10),
    date_submitted: new Date().toISOString().slice(0, 10),
    rate_per_hour: prefill.rate_per_hour != null ? String(prefill.rate_per_hour) : "",
    rate_per_assignment: "",
    rate_other: "",
    service_other_text: "",
    payment_method_other: "",
    issue_description: "",
    expected_correction: "",
    review_notes: "",
    incident_date: "",
    review_period_start: "",
    review_period_end: "",
  };
  const schema = schemaForForm(formId);
  for (const f of schema.fields || []) {
    if (f.type === "checkbox_group") {
      for (const opt of f.options || []) {
        base[`${f.key}__${opt.id}`] = false;
      }
      if (formId === "rate_confirmation") {
        if (prefill.payment_method) {
          const pm = String(prefill.payment_method).toLowerCase();
          if (pm.includes("check")) base.payment_method__check = true;
          if (pm.includes("ach")) base.payment_method__ach = true;
          if (pm.includes("zelle")) base.payment_method__zelle = true;
          if (pm.includes("venmo")) base.payment_method__venmo = true;
          if (pm.includes("cash")) base.payment_method__cash = true;
        }
        base.payment_cycle__biweekly = true;
        base.service_type__laundry = true;
      }
    }
  }
  return base;
}
