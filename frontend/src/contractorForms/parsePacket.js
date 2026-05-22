/** Split veewash_1099_contractor_packet.md into numbered sections for print templates. */

/** Remove PART A/B/C dividers and trailing content that belongs to the next part. */
export function trimSectionBody(text) {
  let body = String(text || "");
  body = body.split(/\n# PART\s+[A-Z]/i)[0];
  body = body.split(/\n##\s+PART\s+/i)[0];
  body = body.replace(/^# PART\s+[^\n]+\n*/gim, "");
  body = body.replace(/^# [^\n]+\n*FIRST-TIME[^\n]*\n*/gim, "");
  body = body.replace(/^>\s.*$/gm, "");
  body = body.replace(/^---\s*$/gm, "");
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
    const title = m[2].trim();
    const bodyText = trimSectionBody(m[3] || "");
    const body = `## ${num}. ${title}\n\n${bodyText}`.trim();
    sections[num] = { num, title, body };
  }
  return sections;
}

export function buildFormMarkdown(sectionsByNum, sectionNums) {
  const parts = [];
  for (const n of sectionNums || []) {
    const s = sectionsByNum[n];
    if (s?.body) parts.push(s.body);
  }
  return parts.join("\n\n<!-- PAGE_BREAK -->\n\n");
}
