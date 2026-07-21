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

  it("excludes Rinse portal logins from W-2 document employee list", () => {
    const rinseViewer = {
      id: 39,
      first_name: "Jordan",
      last_name: "Allen",
      hr_form_lanes: ["employee_w2"],
      role_codes: "RINSE",
    };
    expect(isAccountantSystemUser(rinseViewer)).toBe(true);
    expect(isW2EmployeeForDocuments(rinseViewer)).toBe(false);
    expect(filterAccountantDocumentUsers([rinseViewer, w2Worker], "w2")).toEqual([w2Worker]);
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

  it("filters temp workers by canonical temp_worker lane plus legacy aliases", () => {
    // Backend infer_user_form_lanes emits `temp_worker`; this was the blank-dropdown bug.
    const tempCanonical = {
      id: 41,
      first_name: "Tom",
      last_name: "Temp",
      hr_form_lanes: ["temp_worker"],
    };
    const tempLegacy = {
      id: 42,
      first_name: "Tim",
      last_name: "Legacy",
      hr_form_lanes: ["contractor_temp"],
    };
    const users = [w2Worker, tempCanonical, tempLegacy];
    expect(
      filterPayrollTimelineUsers(users, "temp")
        .map((u) => u.id)
        .sort(),
    ).toEqual([41, 42]);
    expect(workerLaneForCategory("temp")).toBe("temp_worker");
  });
});
