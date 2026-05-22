/** Apply UI checkbox/text values onto markdown before HTML print. */

function escRe(s) {
  return String(s).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function markCheckboxLine(md, label, checked) {
  if (!label) return md;
  const esc = escRe(label.trim());
  const re = new RegExp(`☐(\\s*${esc})`, "i");
  if (checked) return md.replace(re, "☑$1");
  return md;
}

function fillMoneyLine(md, pattern, amount) {
  if (amount == null || amount === "") return md;
  const val = Number(amount);
  if (Number.isNaN(val)) return md;
  return md.replace(pattern, `$${val.toFixed(2)}`);
}

function fillOtherLine(md, prefix, text) {
  if (!text || !String(text).trim()) return md;
  const esc = escRe(prefix);
  return md.replace(
    new RegExp(`(${esc}[^\\n]*?)_{3,}`, "i"),
    `$1 ${String(text).trim()}`,
  );
}

export function applyFormValuesToMarkdown(md, formId, values = {}, prefill = {}) {
  let out = String(md || "");
  const v = values || {};

  if (formId === "rate_confirmation") {
    out = fillMoneyLine(out, /☐\s*\$_{5,}\s*per hour/i, v.rate_per_hour);
    out = fillMoneyLine(out, /☐\s*\$_{5,}\s*per assignment/i, v.rate_per_assignment);
    const schema = [
      ["service_type", "Laundry support / folding", "laundry"],
      ["service_type", "Pickup / delivery support", "pickup"],
      ["service_type", "Cleaning / maintenance support", "cleaning"],
      ["payment_cycle", "Biweekly", "biweekly"],
      ["payment_cycle", "Weekly", "weekly"],
      ["payment_method", "Business check", "check"],
      ["payment_method", "ACH", "ach"],
      ["payment_method", "Zelle", "zelle"],
      ["payment_method", "Venmo business payment", "venmo"],
      ["payment_method", "Cash with signed receipt", "cash"],
    ];
    for (const [group, label, id] of schema) {
      out = markCheckboxLine(out, label, !!v[`${group}__${id}`]);
    }
    out = fillOtherLine(out, "Other:", v.service_other_text || v.payment_method_other);
  }

  if (formId === "written_warning") {
    const issues = [
      ["Performance / speed standard", "performance"],
      ["Quality issue", "quality"],
      ["Attendance / reliability", "attendance"],
      ["Clock-in / clock-out issue", "clock"],
      ["Safety issue", "safety"],
      ["Hygiene issue", "hygiene"],
      ["Customer-property handling", "property"],
      ["Premises conduct / break rules", "conduct"],
      ["Confidentiality / customer information", "confidentiality"],
      ["Failure to report incident", "incident_fail"],
      ["Other:", "issue_other"],
    ];
    for (const [label, id] of issues) {
      out = markCheckboxLine(out, label, !!v[`issue_type__${id}`]);
    }
    if (v.issue_description) {
      out = out.replace(
        /_{10,}/,
        String(v.issue_description).slice(0, 2000),
      );
    }
  }

  if (v.company_representative) {
    out = out.replace(
      /(\*\*Company (?:Representative|Signature):\*\*\s*)_{2,}/gi,
      `$1 ${v.company_representative}`,
    );
  }
  if (v.issued_by) {
    out = out.replace(/(\*\*Issued By:\*\*\s*)_{2,}/gi, `$1 ${v.issued_by}`);
    out = out.replace(/(\*\*Reviewed By:\*\*\s*)_{2,}/gi, `$1 ${v.issued_by}`);
  }

  if (prefill.full_name) {
    out = out.replace(
      /(\*\*Contractor Name:\*\*\s*)_{2,}/gi,
      `$1 ${prefill.full_name}`,
    );
  }

  return out;
}
