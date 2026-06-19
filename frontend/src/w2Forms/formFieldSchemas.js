/** Editable field schemas for W-2 letter templates (print pipeline). */

export const COMMON_META_FIELDS = [
  { key: "company_representative", label: "Company representative", type: "text" },
  { key: "issued_by", label: "Issued by", type: "text" },
  { key: "effective_date", label: "Effective date", type: "date" },
  { key: "notice_date", label: "Notice date", type: "date" },
];

function cb(key, label) {
  return { id: key, label };
}

export const FORM_FIELD_SCHEMAS = {
  handbook_acknowledgment: {
    fields: [
      {
        key: "handbook_items",
        label: "Policies acknowledged",
        type: "checkbox_group",
        options: [
          cb("handbook", "Employee handbook (current edition)"),
          cb("safety", "Safety & hygiene standards"),
          cb("timekeeping", "Timekeeping & attendance rules"),
          cb("property", "Customer-property handling procedures"),
          cb("confidentiality", "Confidentiality & customer information rules"),
          cb("conduct", "Premises conduct & break rules"),
          cb("performance", "Performance / productivity standards"),
          cb("payroll", "Payroll & pay method acknowledgment"),
        ],
      },
    ],
  },
  payroll_timekeeping_ack: {
    fields: [
      { key: "pay_period_cycle", label: "Pay period / cycle", type: "text" },
      { key: "hourly_rate", label: "Hourly rate ($)", type: "number" },
      { key: "primary_pay_method", label: "Primary pay method", type: "text" },
      {
        key: "payroll_items",
        label: "Items reviewed",
        type: "checkbox_group",
        options: [
          cb("direct_deposit", "Direct deposit authorization on file"),
          cb("check", "Paper check / alternate method documented"),
          cb("clock", "Time clock / app procedures reviewed"),
          cb("overtime", "Overtime & break rules explained"),
          cb("pay_stub", "Pay stub / record access explained"),
        ],
      },
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
      { key: "expected_correction", label: "Expected correction / improvement plan", type: "multiline" },
    ],
  },
  separation_checklist: {
    fields: [
      { key: "separation_type", label: "Separation type", type: "text" },
      {
        key: "items_returned",
        label: "Items reviewed / returned",
        type: "checkbox_group",
        options: [
          cb("keys", "Keys / access cards returned"),
          cb("app", "App / system access removed"),
          cb("supplies", "Company property / supplies returned"),
          cb("uniform", "Uniform / branded items returned"),
          cb("time", "Final time records reviewed"),
          cb("final_pay", "Final pay / PTO notes documented"),
          cb("cobra", "COBRA / benefits notice (if applicable)"),
          cb("handbook", "Handbook / policy materials returned"),
        ],
      },
      { key: "separation_notes", label: "Notes", type: "multiline" },
    ],
  },
};

export function schemaForForm(formId) {
  return FORM_FIELD_SCHEMAS[formId] || { fields: [] };
}

export function emptyFormValues(formId, prefill = {}) {
  const base = {
    company_representative: "",
    issued_by: prefill.company_supervisor_name || "",
    effective_date: prefill.start_date || prefill.hire_date || "",
    notice_date: new Date().toISOString().slice(0, 10),
    pay_period_cycle: prefill.payment_cycle || "Biweekly",
    hourly_rate: prefill.rate_per_hour != null ? String(prefill.rate_per_hour) : "",
    primary_pay_method: prefill.payment_method || "",
    issue_description: "",
    expected_correction: "",
    incident_date: "",
    separation_type: "",
    separation_notes: "",
  };
  const schema = schemaForForm(formId);
  for (const f of schema.fields || []) {
    if (f.type === "checkbox_group") {
      for (const opt of f.options || []) {
        base[`${f.key}__${opt.id}`] = false;
      }
      if (formId === "handbook_acknowledgment") {
        for (const opt of f.options || []) {
          base[`handbook_items__${opt.id}`] = true;
        }
      }
    }
  }
  return base;
}
