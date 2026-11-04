/** Split one shared checklist into the viewer's items and the rest. Each item appears once. */

export const TEAM_RESPONSIBILITY_LABEL = "Any assigned employee";

const GENERIC_SECTION = /^(section\s*\d+|secci[oó]n\s*\d+|general|checklist)$/i;
const TEAM_LABELS = new Set([
  "Anyone on Team",
  "Cualquiera del equipo",
  TEAM_RESPONSIBILITY_LABEL,
]);

export function responsibilityLabel(item) {
  const explicit = String(item?.responsibility_label || "").trim();
  const mode = String(item?.responsibility_mode || "team");
  const names = item?.responsibility_names || [];
  if (mode === "named" && names.length) return names.join(", ");
  if (explicit && !TEAM_LABELS.has(explicit)) return explicit;
  return TEAM_RESPONSIBILITY_LABEL;
}

/** Hide a redundant or generic section heading. Stored names are not rewritten. */
export function visibleSectionLabel(label, sectionCount = 1) {
  const raw = String(label || "").trim();
  if (Number(sectionCount) <= 1) return "";
  if (!raw || GENERIC_SECTION.test(raw)) return "";
  return raw;
}

const CHECK_DONE = new Set(["completed", "approved", "verified"]);

export function employeeCheckSummary(checks) {
  return (Array.isArray(checks) ? checks : []).map((check) => ({
    userId: Number(check?.user_id),
    name: check?.employee_name || "",
    done: CHECK_DONE.has(String(check?.status || "").toLowerCase()),
    completedAt: check?.completed_at || null,
  }));
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
    if (!groups.has(label)) {
      groups.set(label, {
        label,
        labelEs: String(item?.section_label_es || "").trim(),
        order,
        items: [],
      });
    }
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
