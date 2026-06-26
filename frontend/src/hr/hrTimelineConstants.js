/** HR Timeline entry types, categories, and discipline email template metadata. */

export const HR_TIMELINE_ENTRY_TYPES = [
  { id: "coaching", label: "Coaching" },
  { id: "warning", label: "Warning" },
  { id: "attendance_issue", label: "Attendance Issue" },
  { id: "performance_issue", label: "Performance Issue" },
  { id: "safety_issue", label: "Safety Issue" },
  { id: "customer_complaint", label: "Customer Complaint" },
  { id: "recognition", label: "Recognition" },
  { id: "separation_note", label: "Separation Note" },
  { id: "management_note", label: "Management Note" },
  { id: "offer_letter", label: "Offer Letter" },
];

export const HR_TIMELINE_CATEGORIES = [
  "Attendance & Reliability",
  "Productivity",
  "Quality",
  "Customer Item Care",
  "Conduct & Professionalism",
  "Safety",
  "Recognition",
  "General",
];

export const HR_DISCIPLINE_EMAIL_TEMPLATES = [
  {
    id: "coaching_late_arrival",
    label: "Coaching – Late Arrival",
    entryType: "coaching",
    category: "Attendance & Reliability",
  },
  {
    id: "warning_pattern_tardiness",
    label: "Warning – Pattern of Tardiness",
    entryType: "warning",
    category: "Attendance & Reliability",
  },
  {
    id: "warning_attendance_reliability",
    label: "Warning – Attendance / Reliability",
    entryType: "warning",
    category: "Attendance & Reliability",
  },
  {
    id: "separation_attendance",
    label: "Separation – Attendance",
    entryType: "separation_note",
    category: "Attendance & Reliability",
  },
  {
    id: "warning_performance",
    label: "Warning – Performance",
    entryType: "warning",
    category: "Productivity",
  },
  {
    id: "separation_performance",
    label: "Separation – Performance",
    entryType: "separation_note",
    category: "Productivity",
  },
  {
    id: "warning_customer_quality",
    label: "Warning – Customer Item Care / Quality",
    entryType: "warning",
    category: "Customer Item Care",
  },
  {
    id: "separation_customer_serious",
    label: "Separation – Customer Care / Serious Incident",
    entryType: "separation_note",
    category: "Customer Item Care",
  },
];

export function entryTypeLabel(id) {
  return HR_TIMELINE_ENTRY_TYPES.find((t) => t.id === id)?.label || id;
}

export function disciplineTemplateById(id) {
  return HR_DISCIPLINE_EMAIL_TEMPLATES.find((t) => t.id === id) || null;
}

/** Archived worker-facing discipline forms — replaced by email + HR Timeline. */
export const ARCHIVED_W2_DISCIPLINE_FORM_IDS = ["corrective_action", "separation_checklist"];

export const ARCHIVED_CONTRACTOR_DISCIPLINE_FORM_IDS = [
  "written_warning",
  "probation_review",
  "final_warning",
  "termination_notice",
];
