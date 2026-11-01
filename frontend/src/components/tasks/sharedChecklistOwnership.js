/** Split one shared checklist into the viewer's items and the rest. Each item appears once. */

export function responsibilityLabel(item) {
  if (item?.responsibility_label) return item.responsibility_label;
  const mode = String(item?.responsibility_mode || "team");
  const names = item?.responsibility_names || [];
  if (mode !== "named" || !names.length) return "Anyone on Team";
  return names.join(", ");
}

export function isMyChecklistItem(item, userId) {
  const mode = String(item?.responsibility_mode || "team");
  const ids = item?.responsibility_user_ids || [];
  const uid = Number(userId);
  if (mode !== "named" || !ids.length) return true;
  return ids.map(Number).includes(uid);
}

export function splitSharedChecklist(items, userId) {
  const list = Array.isArray(items) ? items : [];
  const myItems = [];
  const otherItems = [];
  for (const item of list) {
    if (isMyChecklistItem(item, userId)) myItems.push(item);
    else otherItems.push(item);
  }
  const required = list.filter((item) => item?.required !== false);
  const requiredDone = required.filter((item) =>
    ["completed", "approved", "verified"].includes(String(item?.status || "").toLowerCase())
  ).length;
  return {
    myItems,
    otherItems,
    requiredDone,
    requiredTotal: required.length,
  };
}

const DONE = new Set(["completed", "approved", "verified"]);

export function groupChecklistSections(items) {
  const groups = new Map();
  for (const item of items || []) {
    const label = String(item?.section_label || "Checklist");
    const order = Number(item?.section_order || 0);
    if (!groups.has(label)) groups.set(label, { label, order, items: [] });
    groups.get(label).items.push(item);
  }
  return [...groups.values()]
    .map((group) => {
      const total = group.items.length;
      const done = group.items.filter((item) => DONE.has(String(item?.status || "").toLowerCase())).length;
      return { ...group, done, total };
    })
    .sort((a, b) => a.order - b.order || a.label.localeCompare(b.label));
}
