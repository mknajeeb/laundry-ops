/** Split veewash_1099_contractor_packet.md into numbered sections for print templates. */

/** Sections that are internal-only and must never appear on contractor-facing printouts. */
export const INTERNAL_ONLY_SECTIONS = new Set(["12"]);

/** Remove PART dividers, internal blocks, and meta copy from section bodies. */
export function trimSectionBody(text) {
  let body = String(text || "");
  body = body.split(/\n# PART\s+[A-Z]/i)[0];
  body = body.split(/\n##\s+PART\s+/i)[0];
  body = body.replace(/^# PART\s+[^\n]+\n*/gim, "");
  body = body.replace(/^# [^\n]+\n*FIRST-TIME[^\n]*\n*/gim, "");
  body = body.replace(/^## Simple Internal Rule[\s\S]*/gim, "");
  body = body.replace(/^>\s.*$/gm, "");
  body = body.replace(/^---\s*$/gm, "");
  body = body.replace(/\*\*VeeWash \/ Washpro\*\*\s*\n\*\*10438[^\n]*\n*/gi, "");
  return body.trim();
}

export function parsePacketSections(markdown) {
  const sections = {};
  if (!markdown || typeof markdown !== "string") return sections;
  const chunks = markdown.split(/^## /m);
  for (const chunk of chunks.slice(1)) {
    const m = chunk.match(/^(\d+)\.\s+([^\n]+)\n?([\s\S]*)/);
    if (!m) continue;
    const num = m[1];
    if (INTERNAL_ONLY_SECTIONS.has(num)) continue;
    let title = m[2].trim();
    title = title.replace(/\s+Template\s*$/i, "");
    title = title.replace(/\s*\(Company use only[^)]*\)\s*$/i, "");
    const bodyText = trimSectionBody(m[3] || "");
    const body = `## ${num}. ${title}\n\n${bodyText}`.trim();
    sections[num] = { num, title, body };
  }
  return sections;
}

export function buildFormMarkdown(sectionsByNum, sectionNums) {
  const parts = [];
  for (const n of sectionNums || []) {
    if (INTERNAL_ONLY_SECTIONS.has(String(n))) continue;
    const s = sectionsByNum[n];
    if (s?.body) parts.push(s.body);
  }
  return parts.join("\n\n<!-- PAGE_BREAK -->\n\n");
}
