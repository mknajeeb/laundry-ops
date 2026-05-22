/** Apply contractor prefill values into markdown underscore blanks (form snapshot labels). */

const LABEL_MAP = [
  ["Contractor Printed Name", "full_name"],
  ["Contractor Name", "full_name"],
  ["Contractor:", "full_name"],
  ["Company:", "company_name"],
  ["Company Representative", "company_representative"],
  ["Issued By", "issued_by"],
  ["Reviewed By", "reviewed_by"],
  ["Reported To", "reported_to"],
  ["Emergency Contact Name", "emergency_contact_name"],
  ["Emergency Contact Phone", "emergency_contact_phone"],
  ["Effective Date", "effective_date"],
  ["Notice Date", "notice_date"],
  ["Date of Notice", "notice_date"],
  ["Invoice Date", "invoice_date"],
  ["Review Date", "review_date"],
  ["Date Submitted", "date_submitted"],
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

export function applyPrefillToMarkdown(md, prefill, extra = {}) {
  const merged = {
    full_name: val(prefill, "full_name"),
    company_name: val(prefill, "company_name"),
    company_address: val(prefill, "company_address"),
    business_name: val(prefill, "business_name"),
    address: val(prefill, "address"),
    phone: val(prefill, "phone"),
    email: val(prefill, "email"),
    emergency_contact: val(prefill, "emergency_contact"),
    service_type: val(prefill, "service_type"),
    payment_method: val(prefill, "payment_method"),
    contractor_id: val(prefill, "contractor_id"),
    start_date: val(prefill, "start_date"),
    ...extra,
  };
  if (merged.emergency_contact && !merged.emergency_contact_name) {
    const parts = merged.emergency_contact.split(" — ");
    merged.emergency_contact_name = parts[0] || merged.emergency_contact;
    merged.emergency_contact_phone = parts[1] || "";
  }
  let out = md;
  for (const [label, key] of LABEL_MAP) {
    out = fillLabelLine(out, label, merged[key]);
  }
  if (merged.full_name) {
    out = out.replace(
      /\*\*Contractor:\*\*\s*_{5,}/gi,
      `**Contractor:** ${merged.full_name}`,
    );
  }
  if (merged.address) {
    out = fillLabelLine(out, "Address", merged.address);
    out = out.replace(
      /\*\*Address:\*\*\s*_{5,}/gi,
      `**Address:** ${merged.address}`,
    );
  }
  if (merged.rate_per_hour != null && merged.rate_per_hour !== "") {
    out = out.replace(/\$\s*_{5,}\s*per hour/gi, `$${merged.rate_per_hour} per hour`);
    out = out.replace(/☐ \$_{5,} per hour/gi, `☐ $${merged.rate_per_hour} per hour`);
  }
  return out;
}

/** Minimal markdown → HTML for print (headings, bold, tables, checkboxes). */
export function markdownToPrintHtml(md) {
  const lines = String(md || "").split("\n");
  const html = [];
  let inTable = false;
  let tableRows = [];

  const flushTable = () => {
    if (!tableRows.length) return;
    html.push('<table class="cform-table">');
    tableRows.forEach((row, i) => {
      const tag = i === 0 ? "th" : "td";
      html.push("<tr>");
      row.forEach((cell) => {
        html.push(`<${tag}>${escapeHtml(cell)}</${tag}>`);
      });
      html.push("</tr>");
    });
    html.push("</table>");
    tableRows = [];
    inTable = false;
  };

  for (let line of lines) {
    if (/^\|.+\|$/.test(line.trim())) {
      if (/^\|[\s\-:|]+\|$/.test(line.trim())) continue;
      const cells = line
        .trim()
        .slice(1, -1)
        .split("|")
        .map((c) => inlineFormat(c.trim()));
      tableRows.push(cells);
      inTable = true;
      continue;
    }
    if (inTable) flushTable();
    if (/^---+$/.test(line.trim())) {
      html.push("<hr />");
      continue;
    }
    if (/^### /.test(line)) {
      html.push(`<h3>${inlineFormat(line.slice(4))}</h3>`);
      continue;
    }
    if (/^## /.test(line)) {
      html.push(`<h2>${inlineFormat(line.slice(3))}</h2>`);
      continue;
    }
    if (/^# /.test(line)) {
      html.push(`<h1>${inlineFormat(line.slice(2))}</h1>`);
      continue;
    }
    if (!line.trim()) {
      html.push("<br />");
      continue;
    }
    html.push(`<p>${inlineFormat(line)}</p>`);
  }
  flushTable();
  return html.join("\n");
}

function inlineFormat(text) {
  let s = escapeHtml(text);
  s = s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  s = s.replace(/☐/g, '<span class="cform-box">☐</span>');
  return s;
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
