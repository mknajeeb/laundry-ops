/** W-2 employee letter templates — signed handbook/addendum only; discipline via HR Timeline. */

export const W2_FORMS = [
  {
    id: "handbook_acknowledgment",
    title: "VF-03 — Handbook & policy acknowledgment",
    sections: ["3"],
    description: "Employee handbook, safety, timekeeping, and policy acknowledgments.",
  },
  {
    id: "payroll_timekeeping_ack",
    title: "VF-06 — Payroll & timekeeping acknowledgment",
    sections: ["6"],
    description: "Pay method, time clock, and pay record review acknowledgment.",
  },
  {
    id: "workforce_pack",
    title: "Full workforce forms pack (DOCX/PDF)",
    downloadOnly: true,
    catalogFormId: "internal_veewash_workforce_pack",
    locale: "bilingual",
    description: "Download the complete bilingual VF pack template from HR assets.",
  },
];

/** Archived — use HR Timeline + email templates instead. */
export const ARCHIVED_W2_FORMS = [
  {
    id: "corrective_action",
    title: "VF-07 — Corrective action / written warning (archived)",
    archived: true,
  },
  {
    id: "separation_checklist",
    title: "VF-08 — Separation checklist (archived)",
    archived: true,
  },
];

export function findW2Form(id) {
  return W2_FORMS.find((f) => f.id === id) || null;
}

export function editorFormIdFor(formDef) {
  if (!formDef) return "";
  return formDef.editorFormId || formDef.id;
}
