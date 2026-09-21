import { describe, expect, it } from "vitest";
import {
  EMPLOYMENT_REFERENCE_DOCUMENT_TITLE,
  EMPLOYMENT_REFERENCE_ENTRY_TYPE,
  buildEmploymentPeriodText,
  buildEmploymentReferenceEmail,
  buildEmploymentReferenceEmailFilename,
  buildEmploymentReferenceTimelineDescription,
  defaultEmploymentReferenceFields,
} from "./employmentReferenceLetter";
import {
  POSITION_CONFIRMATION_DOCUMENT_TITLE,
  buildPositionConfirmationEmail,
  defaultPositionConfirmationFields,
} from "./positionConfirmationLetter";
import { HR_TIMELINE_ENTRY_TYPES } from "./hrTimelineConstants";

describe("employmentReferenceLetter", () => {
  it("defaults fields from worker prefill", () => {
    const fields = defaultEmploymentReferenceFields({
      prefill: {
        full_name: "Tarannum Mithila",
        email: "tarannum.mithila01@gmail.com",
        address: "9161 116th Street\nRichmond Hill, NY 11418",
        job_title: "Operations Intelligence Analyst",
        primary_location: "Richmond Hill, NY 11418",
        hire_date: "2025-01-15",
        start_date: "2025-01-15",
        company_name: "VeeWash LLC",
      },
      workerName: "Tarannum Mithila",
      workerEmail: "tarannum.mithila01@gmail.com",
      managerName: "Muhammad Kamran Najeeb",
    });
    expect(fields.employee_name).toBe("Tarannum Mithila");
    expect(fields.employee_email).toBe("tarannum.mithila01@gmail.com");
    expect(fields.employee_address).toContain("9161 116th Street");
    expect(fields.position).toBe("Operations Intelligence Analyst");
    expect(fields.employment_start_date).toBe("2025-01-15");
    expect(fields.employment_end_date).toBe("");
    expect(fields.employment_status).toBe("Current Employee");
    expect(fields.work_location).toBe("Richmond Hill, NY 11418");
    expect(fields.signatory_name).toBe("Muhammad Kamran Najeeb");
    expect(fields.character_statement).toContain("Tarannum Mithila");
    expect(fields.character_statement).toContain("VeeWash LLC");
    expect(fields.employment_details).toBe("");
    expect(fields.custom_content).toBe("");
  });

  it("builds employment period for current and ended employment", () => {
    expect(
      buildEmploymentPeriodText({
        employment_start_date: "2025-01-15",
        employment_end_date: "",
      }),
    ).toContain("to present");
    expect(
      buildEmploymentPeriodText({
        employment_start_date: "2025-01-15",
        employment_end_date: "2026-03-01",
      }),
    ).toContain("to March 1, 2026");
  });

  it("builds email subject, body, and PDF filename", () => {
    const fields = {
      employee_name: "Tarannum Mithila",
      position: "Operations Intelligence Analyst",
      employment_start_date: "2025-01-15",
      employment_end_date: "",
      company_name: "VeeWash LLC",
      signatory_name: "Muhammad Kamran Najeeb",
      signatory_title: "Managing Director",
    };
    const email = buildEmploymentReferenceEmail(fields);
    expect(email.subject).toContain(EMPLOYMENT_REFERENCE_DOCUMENT_TITLE);
    expect(email.subject).toContain("Operations Intelligence Analyst");
    expect(email.body).toContain("Dear Tarannum,");
    expect(email.body).toContain("to present");
    expect(email.body).toContain("Muhammad Kamran Najeeb");

    const withPdf = buildEmploymentReferenceEmail(fields, { includeAttachmentNote: true });
    expect(withPdf.body).toContain("attached character and employment reference letter");

    expect(buildEmploymentReferenceEmailFilename(fields)).toBe(
      "Employment-Reference-Tarannum-Mithila-Operations-Intelligence-Analyst.pdf",
    );
  });

  it("builds timeline description with letter snapshot for audit", () => {
    const desc = buildEmploymentReferenceTimelineDescription({
      employee_name: "Tarannum Mithila",
      position: "Operations Intelligence Analyst",
      employment_start_date: "2025-01-15",
      employment_end_date: "",
      employment_status: "Current Employee",
      work_location: "Richmond Hill, NY 11418",
      character_statement: "Demonstrated professionalism.",
      signatory_name: "Muhammad Kamran Najeeb",
      company_name: "VeeWash LLC",
    });
    expect(desc).toContain("Character and Employment Reference Letter generated.");
    expect(desc).toContain("Operations Intelligence Analyst");
    expect(desc).toContain("Employment end: present.");
    expect(desc).toContain("[letter_snapshot]");
    expect(desc).toContain('"character_statement":"Demonstrated professionalism."');
  });

  it("registers in HR Timeline entry types alongside existing letters", () => {
    expect(EMPLOYMENT_REFERENCE_ENTRY_TYPE).toBe("employment_reference_letter");
    expect(HR_TIMELINE_ENTRY_TYPES.some((t) => t.id === "offer_letter")).toBe(true);
    expect(HR_TIMELINE_ENTRY_TYPES.some((t) => t.id === "position_confirmation_letter")).toBe(true);
    expect(
      HR_TIMELINE_ENTRY_TYPES.some(
        (t) =>
          t.id === "employment_reference_letter" &&
          t.label === "Character and Employment Reference Letter",
      ),
    ).toBe(true);
  });
});

describe("existing letter regression", () => {
  it("does not alter position confirmation defaults or email", () => {
    const fields = defaultPositionConfirmationFields({
      prefill: {
        full_name: "Tarannum Mithila",
        job_title: "Operations Intelligence Analyst",
        primary_location: "Richmond Hill, NY 11418",
      },
      workerName: "Tarannum Mithila",
      managerName: "Muhammad Kamran Najeeb",
    });
    expect(fields.position).toBe("Operations Intelligence Analyst");
    expect(fields.probation_summary).toContain("operational excellence");

    const email = buildPositionConfirmationEmail({
      employee_name: "Tarannum Mithila",
      position: "Operations Intelligence Analyst",
      effective_date: "2026-07-01",
      employment_status: "Regular Employee",
      company_name: "VeeWash",
      signatory_name: "Muhammad Kamran Najeeb",
      signatory_title: "Managing Director",
    });
    expect(email.subject).toContain(POSITION_CONFIRMATION_DOCUMENT_TITLE);
    expect(email.body).toContain("Dear Tarannum,");
    expect(email.body).toContain("probationary period");
  });
});
