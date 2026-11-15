/** Standalone schedule cards. These are documents, not screenshots of the app. */

function escapeXml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

export function scheduleCardSvg({ title, subtitle, rows }) {
  const lines = (rows || []).map((row) => {
    const bits = [row.name, row.when, row.role, row.breaks].filter(Boolean);
    return bits.join(" · ");
  });
  const height = 92 + lines.length * 28;
  const body = lines
    .map((line, index) => `<text x="32" y="${108 + index * 28}" font-size="16" fill="#122033">${escapeXml(line)}</text>`)
    .join("");
  return `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="880" height="${height}" viewBox="0 0 880 ${height}">
  <rect width="880" height="${height}" fill="#ffffff"/>
  <rect x="0" y="0" width="880" height="72" fill="#0f2744"/>
  <text x="32" y="34" font-size="22" font-family="Georgia, serif" fill="#ffffff">${escapeXml(title)}</text>
  <text x="32" y="56" font-size="14" font-family="Georgia, serif" fill="#d5dde6">${escapeXml(subtitle)}</text>
  ${body}
</svg>`;
}

export function scheduleCsv(rows) {
  const header = ["employee", "day", "start", "end", "role", "breaks", "tasks"];
  const lines = [header.join(",")];
  for (const row of rows || []) {
    lines.push(
      [row.employee, row.day, row.start, row.end, row.role, row.breaks, row.tasks]
        .map((value) => `"${String(value ?? "").replace(/"/g, '""')}"`)
        .join(","),
    );
  }
  return lines.join("\n");
}

function pdfEscape(value) {
  return String(value ?? "").replace(/\\/g, "\\\\").replace(/\(/g, "\\(").replace(/\)/g, "\\)");
}

/** A one-page schedule card. This is a real PDF, not a renamed HTML file. */
export function schedulePdf({ title, subtitle, rows }) {
  const lines = [`${title || "Schedule"}`, subtitle || "", ""];
  for (const row of rows || []) {
    lines.push([row.employee, row.day, row.start, row.end, row.role, row.breaks].filter(Boolean).join("  "));
  }
  if (lines.length === 3) lines.push("No shifts in this period.");
  const commands = ["BT", "/F1 11 Tf", "48 760 Td", "14 TL"];
  lines.slice(0, 48).forEach((line, index) => {
    if (index === 0) commands.push(`/F1 16 Tf (${pdfEscape(line)}) Tj`, "/F1 11 Tf");
    else commands.push(`T* (${pdfEscape(line)}) Tj`);
  });
  commands.push("ET");
  const stream = commands.join("\n");
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Count 1 /Kids [3 0 R] >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
    `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`,
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
  ];
  let body = "%PDF-1.4\n";
  const offsets = [0];
  objects.forEach((object, index) => {
    offsets.push(body.length);
    body += `${index + 1} 0 obj\n${object}\nendobj\n`;
  });
  const xref = body.length;
  body += `xref\n0 ${objects.length + 1}\n`;
  body += "0000000000 65535 f \n";
  offsets.slice(1).forEach((offset) => {
    body += `${String(offset).padStart(10, "0")} 00000 n \n`;
  });
  body += `trailer << /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF`;
  return body;
}

export function printDocumentHtml({ title, subtitle, sections }) {
  const body = (sections || [])
    .map((section) => {
      const rows = (section.rows || [])
        .map(
          (row) =>
            `<tr><td>${escapeXml(row.employee)}</td><td>${escapeXml(row.when)}</td><td>${escapeXml(row.detail)}</td></tr>`,
        )
        .join("");
      return `<h2>${escapeXml(section.heading)}</h2><table><thead><tr><th>Employee</th><th>When</th><th>Detail</th></tr></thead><tbody>${rows}</tbody></table>`;
    })
    .join("");
  return `<!DOCTYPE html><html><head><title>${escapeXml(title)}</title>
    <style>
      body { font-family: Georgia, serif; color: #122033; margin: 24px; }
      h1 { font-size: 22px; margin: 0; }
      h2 { font-size: 16px; margin: 24px 0 8px; }
      table { width: 100%; border-collapse: collapse; }
      th, td { border-bottom: 1px solid #d5dde6; text-align: left; padding: 6px 8px; vertical-align: top; }
      @media print { body { margin: 0.4in; } }
    </style></head><body><h1>${escapeXml(title)}</h1><p>${escapeXml(subtitle)}</p>${body}</body></html>`;
}
