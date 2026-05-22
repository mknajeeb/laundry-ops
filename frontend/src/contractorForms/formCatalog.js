/** Printable contractor form catalog (content from veewash_1099_contractor_packet.md). */

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
    id: "written_warning",
    title: "Written Warning / Notice",
    sections: ["13"],
  },
  {
    id: "probation_review",
    title: "Two-Week Probation Review",
    sections: ["14"],
  },
  {
    id: "final_warning",
    title: "Final Warning / Last Opportunity Notice",
    sections: ["15"],
  },
  {
    id: "termination_notice",
    title: "Termination / Non-Offer of Future Assignments Notice",
    sections: ["16"],
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
];

export function findContractorForm(id) {
  return CONTRACTOR_FORMS.find((f) => f.id === id) || null;
}
