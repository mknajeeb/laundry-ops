/** W-2 employee letter templates (VF forms from workforce pack). */

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
    id: "corrective_action",
    title: "VF-07 — Corrective action / written warning",
    sections: ["7"],
    description: "Document performance, attendance, safety, or conduct issues.",
    editorFormId: "written_warning",
  },
  {
    id: "separation_checklist",
    title: "VF-08 — Separation / termination checklist",
    sections: ["8"],
    description: "Property return, access removal, and final pay checklist.",
    editorFormId: "separation_checklist",
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

export function findW2Form(id) {
  return W2_FORMS.find((f) => f.id === id) || null;
}

export function editorFormIdFor(formDef) {
  if (!formDef) return "";
  return formDef.editorFormId || formDef.id;
}
