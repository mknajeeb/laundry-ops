/** Apply W-2 letter UI values onto markdown before HTML print. */

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

function fillMultilineBlock(md, text) {
  if (!text || !String(text).trim()) return md;
  return md.replace(/_{10,}/, String(text).trim().slice(0, 2000));
}

export function applyW2FormValuesToMarkdown(md, formId, values = {}, prefill = {}) {
  let out = String(md || "");
  const v = values || {};

  if (formId === "handbook_acknowledgment") {
    const items = [
      ["Employee handbook (current edition)", "handbook"],
      ["Safety & hygiene standards", "safety"],
      ["Timekeeping & attendance rules", "timekeeping"],
      ["Customer-property handling procedures", "property"],
      ["Confidentiality & customer information rules", "confidentiality"],
      ["Premises conduct & break rules", "conduct"],
      ["Performance / productivity standards", "performance"],
      ["Payroll & pay method acknowledgment", "payroll"],
    ];
    for (const [label, id] of items) {
      out = markCheckboxLine(out, label, !!v[`handbook_items__${id}`]);
    }
  }

  if (formId === "payroll_timekeeping_ack") {
    const items = [
      ["Direct deposit authorization on file", "direct_deposit"],
      ["Paper check / alternate method documented", "check"],
      ["Time clock / app procedures reviewed", "clock"],
      ["Overtime & break rules explained", "overtime"],
      ["Pay stub / record access explained", "pay_stub"],
    ];
    for (const [label, id] of items) {
      out = markCheckboxLine(out, label, !!v[`payroll_items__${id}`]);
    }
    if (v.pay_period_cycle) {
      out = out.replace(
        /(\*\*Pay Period \/ Cycle:\*\*\s*)_{2,}/gi,
        `$1 ${v.pay_period_cycle}`,
      );
    }
    if (v.primary_pay_method) {
      out = out.replace(
        /(\*\*Primary Pay Method:\*\*\s*)_{2,}/gi,
        `$1 ${v.primary_pay_method}`,
      );
    }
    if (v.hourly_rate != null && v.hourly_rate !== "") {
      out = out.replace(
        /(\*\*Hourly Rate \(\$\):\*\*\s*)_{2,}/gi,
        `$1 ${Number(v.hourly_rate).toFixed(2)}`,
      );
    }
  }

  if (formId === "separation_checklist") {
    const items = [
      ["Keys / access cards returned", "keys"],
      ["App / system access removed", "app"],
      ["Company property / supplies returned", "supplies"],
      ["Uniform / branded items returned", "uniform"],
      ["Final time records reviewed", "time"],
      ["Final pay / PTO notes documented", "final_pay"],
      ["COBRA / benefits notice (if applicable)", "cobra"],
      ["Handbook / policy materials returned", "handbook"],
    ];
    for (const [label, id] of items) {
      out = markCheckboxLine(out, label, !!v[`items_returned__${id}`]);
    }
    if (v.separation_type) {
      out = out.replace(
        /(\*\*Separation Type:\*\*\s*)_{2,}/gi,
        `$1 ${v.separation_type}`,
      );
    }
    if (v.separation_notes) {
      out = fillMultilineBlock(out, v.separation_notes);
    }
  }

  if (prefill.full_name) {
    out = out.replace(/(\*\*Employee Name:\*\*\s*)_{2,}/gi, `$1 ${prefill.full_name}`);
  }

  return out;
}
