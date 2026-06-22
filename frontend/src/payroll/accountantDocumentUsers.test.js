import { describe, expect, it } from "vitest";
import {
  filterAccountantDocumentUsers,
  filterPayrollTimelineUsers,
  formatAccountantDocumentUserLabel,
  isAccountantSystemUser,
  isW2EmployeeForDocuments,
  workerLaneForCategory,
} from "./accountantDocumentUsers";

describe("accountantDocumentUsers", () => {
  const alliance = {
    id: 99,
    first_name: "Alliance",
    last_name: "Business Consultant",
    hr_form_lanes: ["employee_w2"],
    role_codes: "ACCOUNTANT",
  };
  const veewashAdmin = {
    id: 15,
    first_name: "New VeeWash",
    last_name: "Admin",
    hr_form_lanes: ["employee_w2"],
    role_codes: "ADMIN",
  };
  const w2Worker = {
    id: 22,
    first_name: "Alec",
    last_name: "Coaxum",
    hr_form_lanes: ["employee_w2"],
    role_codes: "OPERATIONS",
  };

  it("labels users from first and last name", () => {
    expect(formatAccountantDocumentUserLabel(w2Worker)).toBe("Alec Coaxum");
  });

  it("identifies known system users by display name", () => {
    expect(isAccountantSystemUser(alliance)).toBe(true);
    expect(isAccountantSystemUser(veewashAdmin)).toBe(true);
  });

  it("excludes system users from W-2 document employee list", () => {
    expect(isW2EmployeeForDocuments(alliance)).toBe(false);
    expect(isW2EmployeeForDocuments(veewashAdmin)).toBe(false);
    expect(isW2EmployeeForDocuments(w2Worker)).toBe(true);
  });

  it("returns only W-2 payroll workers (no system user category)", () => {
    const users = [alliance, veewashAdmin, w2Worker];
    expect(filterAccountantDocumentUsers(users, "w2")).toEqual([w2Worker]);
    expect(filterAccountantDocumentUsers(users, "system_users")).toEqual([]);
    expect(filterAccountantDocumentUsers(users, "contractor_1099")).toEqual([]);
  });

  it("filters HR timeline workers by category", () => {
    const contractor = {
      id: 40,
      first_name: "Jane",
      last_name: "Contractor",
      hr_form_lanes: ["contractor_1099"],
    };
    const users = [alliance, w2Worker, contractor];
    expect(filterPayrollTimelineUsers(users, "w2")).toEqual([w2Worker]);
    expect(filterPayrollTimelineUsers(users, "contractor_1099")).toEqual([contractor]);
    expect(workerLaneForCategory("contractor_1099")).toBe("contractor_1099");
  });
});
