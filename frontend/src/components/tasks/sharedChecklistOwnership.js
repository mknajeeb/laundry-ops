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
