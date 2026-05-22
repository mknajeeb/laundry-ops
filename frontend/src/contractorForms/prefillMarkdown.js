import { miniHeadHtml } from "./ContractorPrintShell";

/** Apply contractor prefill values into markdown; convert to print HTML. */

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
  let out = sanitizePacketMarkdown(md);
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

export function sanitizePacketMarkdown(md) {
  let out = String(md || "");
  out = out.replace(/^# PART\s+[A-Z][^\n]*\n*/gim, "");
  out = out.replace(/^# [^\n]*1099 Contractor Packet[^\n]*\n*/gim, "");
  out = out.replace(/^## Implementation Intent[^\n]*\n[\s\S]*?(?=\n## \d+\.|\n# PART|$)/gim, "");
  out = out.replace(/^>\s.*$/gm, "");
  out = out.replace(/\*\*VeeWash \/ Washpro\*\*\s*\n\*\*10438[^\n]*\n*/gi, "");
  out = out.replace(/\n{3,}/g, "\n\n");
  return out.trim();
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function inlineFormat(text) {
  let s = escapeHtml(text);
  s = s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  s = s.replace(/☐/g, '<span class="cform-check" aria-hidden="true"></span>');
  return s;
}

/** Markdown → HTML for print (headings, bold, tables, checkboxes). */
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
        html.push(`<${tag}>${cell}</${tag}>`);
      });
      html.push("</tr>");
    });
    html.push("</table>");
    tableRows = [];
    inTable = false;
  };

  for (let line of lines) {
    const trimmed = line.trim();
    if (trimmed === "<!-- PAGE_BREAK -->") {
      if (inTable) flushTable();
      html.push('<div class="cform-page-break"></div>');
      continue;
    }
    if (/^\|.+\|$/.test(trimmed)) {
      if (/^\|[\s\-:|]+\|$/.test(trimmed)) continue;
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
    if (/^#### /.test(line)) {
      html.push(`<h4 class="cform-h4">${inlineFormat(line.slice(5))}</h4>`);
      continue;
    }
    if (/^### /.test(line)) {
      html.push(`<h3 class="cform-h3">${inlineFormat(line.slice(4))}</h3>`);
      continue;
    }
    if (/^## /.test(line)) {
      html.push(`<h2 class="cform-h2">${inlineFormat(line.slice(3))}</h2>`);
      continue;
    }
    if (/^# /.test(line)) {
      html.push(`<h2 class="cform-h2">${inlineFormat(line.slice(2))}</h2>`);
      continue;
    }
    if (/^[-*]\s+/.test(trimmed)) {
      html.push(`<p class="cform-bullet">${inlineFormat(trimmed.replace(/^[-*]\s+/, ""))}</p>`);
      continue;
    }
    if (!trimmed) {
      continue;
    }
    html.push(`<p class="cform-p">${inlineFormat(line)}</p>`);
  }
  flushTable();
  return html.join("\n");
}

/** Build HTML for one or more packet sections with page breaks between sections. */
export function buildMultiSectionPrintHtml(sectionsByNum, sectionNums, prefill, extra = {}) {
  const parts = [];
  (sectionNums || []).forEach((n, index) => {
    const s = sectionsByNum[n];
    if (!s?.body) return;
    const md = applyPrefillToMarkdown(s.body, prefill, extra);
    const inner = markdownToPrintHtml(md);
    const pageClass = index > 0 ? " cform-page--new" : "";
    const mini = index > 0 ? miniHeadHtml(prefill) : "";
    parts.push(`<section class="cform-page${pageClass}">${mini}${inner}</section>`);
  });
  return parts.join("\n");
}
