import { describe, expect, it } from "vitest";
import {
  POSITION_CONFIRMATION_DOCUMENT_TITLE,
  buildPositionConfirmationEmail,
  buildPositionConfirmationTimelineDescription,
  defaultPositionConfirmationFields,
} from "./positionConfirmationLetter";

describe("positionConfirmationLetter", () => {
  it("defaults fields from worker prefill", () => {
    const fields = defaultPositionConfirmationFields({
      prefill: {
        full_name: "Tarannum Mithila",
        email: "tarannum.mithila01@gmail.com",
        address: "9161 116th Street\nRichmond Hill, NY 11418",
        job_title: "Operations Intelligence Analyst",
        primary_location: "Richmond Hill, NY 11418",
      },
      workerName: "Tarannum Mithila",
      workerEmail: "tarannum.mithila01@gmail.com",
      managerName: "Muhammad Kamran Najeeb",
    });
    expect(fields.employee_name).toBe("Tarannum Mithila");
    expect(fields.position).toBe("Operations Intelligence Analyst");
    expect(fields.employment_status).toBe("Regular Employee");
    expect(fields.work_location).toBe("Richmond Hill, NY 11418");
    expect(fields.signatory_name).toBe("Muhammad Kamran Najeeb");
  });

  it("builds email subject and body", () => {
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
    expect(email.subject).toContain("Operations Intelligence Analyst");
    expect(email.body).toContain("Dear Tarannum,");
    expect(email.body).toContain("July 1, 2026");
    expect(email.body).toContain("Muhammad Kamran Najeeb");
  });

  it("builds timeline description", () => {
    const desc = buildPositionConfirmationTimelineDescription({
      position: "Operations Intelligence Analyst",
      effective_date: "2026-07-01",
      employment_status: "Regular Employee",
    });
    expect(desc).toContain("Position Confirmation Letter generated.");
    expect(desc).toContain("Operations Intelligence Analyst");
  });
});
