/** Split veewash_1099_contractor_packet.md into numbered sections for print templates. */

export function parsePacketSections(markdown) {
  const sections = {};
  if (!markdown || typeof markdown !== "string") return sections;
  const chunks = markdown.split(/^## /m);
  for (const chunk of chunks.slice(1)) {
    const m = chunk.match(/^(\d+)\.\s+([^\n]+)\n?([\s\S]*)/);
    if (!m) continue;
    const num = m[1];
    const title = m[2].trim();
    const body = `## ${num}. ${title}\n${m[3] || ""}`.trim();
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
  return parts.join("\n\n---\n\n");
}
