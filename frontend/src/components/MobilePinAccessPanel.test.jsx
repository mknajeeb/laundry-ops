import { describe, expect, it } from "vitest";
import {
  ISSUES_ACCESS_CHOICES,
  MOBILE_PIN_ACCESS_MODULES,
  issuesAccessHelp,
  mobilePinAccessSaveBody,
  normalizeMobilePinAccess,
} from "./MobilePinAccessPanel";

describe("MobilePinAccessPanel contracts", () => {
  it("exposes Role + Take a Break and optional apps without Clock", () => {
    expect(MOBILE_PIN_ACCESS_MODULES.map((m) => m.key)).toEqual([
      "switch_role",
      "take_break",
      "cleaning_tasks",
      "cleaning_task_review",
      "checklist",
      "inventory",
      "revenue_cost",
      "team_status",
    ]);
    expect(MOBILE_PIN_ACCESS_MODULES.map((m) => m.label)).toEqual([
      "Role",
      "Take a Break",
      "Tasks",
      "Task Review (supervisor)",
      "End-of-Day Checklist",
      "Inventory",
      "Revenue / Cash",
      "Team Status",
    ]);
    expect(ISSUES_ACCESS_CHOICES.map((choice) => choice.value)).toEqual([
      "inherited",
      "allow",
      "deny",
    ]);
  });

  it("normalizes loaded API values into module booleans", () => {
    expect(
      normalizeMobilePinAccess({
        clock: 1,
        switch_role: 0,
        take_break: 1,
        cleaning_tasks: 1,
        cleaning_task_review: 0,
        checklist: true,
        inventory: false,
        revenue_cost: "1",
        team_status: 1,
        issues_access: "inherited",
        issues_effective: true,
        hang_dry: 1,
        extra: true,
      }),
    ).toEqual({
      switch_role: false,
      take_break: true,
      cleaning_tasks: true,
      cleaning_task_review: false,
      checklist: true,
      inventory: false,
      revenue_cost: true,
      team_status: true,
      issues_access: "inherited",
      issues_effective: true,
    });
  });

  it("keeps inherited Issues out of an unrelated tile save and sends an explicit choice only when selected", () => {
    expect(
      mobilePinAccessSaveBody({
        clock: true,
        inventory: true,
        hang_dry: true,
      }),
    ).toEqual({
      switch_role: false,
      take_break: false,
      cleaning_tasks: false,
      cleaning_task_review: false,
      checklist: false,
      inventory: true,
      revenue_cost: false,
      team_status: false,
    });
    expect(
      mobilePinAccessSaveBody({
        inventory: true,
        issues_access: "inherited",
        issues_effective: true,
      }).issues,
    ).toBeNull();
    expect(mobilePinAccessSaveBody({ issues_access: "allow" }).issues).toBe(true);
    expect(mobilePinAccessSaveBody({ issues_access: "deny" }).issues).toBe(false);
    expect(issuesAccessHelp("inherited", true)).toMatch(/Inherited/);
    expect(issuesAccessHelp("allow", false)).toMatch(/Explicit allow/);
    expect(issuesAccessHelp("deny", true)).toMatch(/Explicit deny/);
  });
});
