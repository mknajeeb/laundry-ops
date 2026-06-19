import { describe, expect, it } from "vitest";
import {
  filterAccountantDocumentUsers,
  formatAccountantDocumentUserLabel,
  isAccountantSystemUser,
  isW2EmployeeForDocuments,
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

  it("filters users by category", () => {
    const users = [alliance, veewashAdmin, w2Worker];
    expect(filterAccountantDocumentUsers(users, "w2")).toEqual([w2Worker]);
    expect(filterAccountantDocumentUsers(users, "system_users")).toEqual([alliance, veewashAdmin]);
  });
});
