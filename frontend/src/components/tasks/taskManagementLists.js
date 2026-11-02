/** Presentation only. Catalog rows, codes, and active flags stay as stored. */

export function isActiveCatalogRow(row) {
  return row?.active !== false && row?.active !== 0 && row?.active !== "0";
}

export function visibleCatalogRows(rows, { showInactive = false } = {}) {
  const list = Array.isArray(rows) ? rows : [];
  if (showInactive) return list;
  return list.filter(isActiveCatalogRow);
}

export function groupActivitiesByCategory(groups, categories) {
  const order = (categories || []).map((category) => category.code);
  const buckets = new Map();
  for (const group of groups || []) {
    const code = group?.category_code || "intra_day";
    if (!buckets.has(code)) buckets.set(code, []);
    buckets.get(code).push(group);
  }
  return [...buckets.keys()]
    .sort((left, right) => {
      const leftAt = order.indexOf(left);
      const rightAt = order.indexOf(right);
      return (leftAt === -1 ? 999 : leftAt) - (rightAt === -1 ? 999 : rightAt);
    })
    .map((code) => ({
      code,
      name: (categories || []).find((category) => category.code === code)?.name || code,
      groups: buckets.get(code),
    }));
}

export function checklistSections(items) {
  const sections = new Map();
  for (const item of items || []) {
    const label = String(item?.section_label || "").trim() || "General";
    if (!sections.has(label)) sections.set(label, []);
    sections.get(label).push(item);
  }
  return [...sections.entries()].map(([label, sectionItems]) => ({ label, items: sectionItems }));
}
