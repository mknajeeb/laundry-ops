/**
 * Checklist lines for HR hub: translations use key hub.checklist.<formId> with lines separated by |.
 */
export function getFormChecklistLines(formId, t, titleHint) {
  const key = `hub.checklist.${formId}`;
  let raw = t(key);
  if (!raw || raw === key) {
    const gen = t("hub.checklistGeneric");
    if (!gen || gen === "hub.checklistGeneric") return [];
    const label = (titleHint || String(formId)).trim();
    raw = gen.replace("{title}", label);
  }
  return String(raw)
    .split("|")
    .map((s) => s.trim())
    .filter(Boolean);
}
