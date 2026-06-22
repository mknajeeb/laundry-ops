/** Printable contractor form catalog — discipline via HR Timeline; onboarding/service docs only. */

export const CONTRACTOR_FORMS = [
  {
    id: "first_time_packet",
    title: "First-Time Contractor Packet",
    sections: ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"],
    description: "Full onboarding packet — signed once.",
  },
  {
    id: "rate_confirmation",
    title: "Contractor Rate / Payment Confirmation",
    sections: ["3"],
  },
  {
    id: "incident_report",
    title: "Incident / Injury Report",
    sections: ["17"],
  },
  {
    id: "clock_payment_correction",
    title: "Clock / Payment Correction Request",
    sections: ["18"],
  },
  {
    id: "property_return_checklist",
    title: "Property / Access Return Checklist",
    sections: ["19"],
  },
  {
    id: "engagement_verification_letter",
    title: "Contractor Engagement & Payment Verification Letter",
    sections: [],
    letterOnly: true,
  },
];

/** Archived — use HR Timeline + email templates instead. */
export const ARCHIVED_CONTRACTOR_FORMS = [
  { id: "written_warning", title: "Written Warning / Notice (archived)" },
  { id: "probation_review", title: "Two-Week Probation Review (archived)" },
  { id: "final_warning", title: "Final Warning (archived)" },
  { id: "termination_notice", title: "Termination Notice (archived)" },
];

export function findContractorForm(id) {
  return CONTRACTOR_FORMS.find((f) => f.id === id) || null;
}
