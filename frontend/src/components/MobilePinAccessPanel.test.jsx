import { describe, expect, it } from "vitest";
import {
  MOBILE_PIN_ACCESS_MODULES,
  mobilePinAccessSaveBody,
  normalizeMobilePinAccess,
} from "./MobilePinAccessPanel";

describe("MobilePinAccessPanel contracts", () => {
  it("exposes module checkboxes without Hang Dry", () => {
    expect(MOBILE_PIN_ACCESS_MODULES.map((m) => m.key)).toEqual([
      "clock",
      "switch_role",
      "checklist",
      "inventory",
      "revenue_cost",
      "team_status",
    ]);
    expect(MOBILE_PIN_ACCESS_MODULES.map((m) => m.label)).toEqual([
      "Clock",
      "Role",
      "End-of-Day Checklist",
      "Inventory",
      "Revenue / Cash",
      "Team Status",
    ]);
  });

  it("normalizes loaded API values into module booleans", () => {
    expect(
      normalizeMobilePinAccess({
        clock: 1,
        switch_role: 0,
        checklist: true,
        inventory: false,
        revenue_cost: "1",
        team_status: 1,
        hang_dry: 1,
        extra: true,
      }),
    ).toEqual({
      clock: true,
      switch_role: false,
      checklist: true,
      inventory: false,
      revenue_cost: true,
      team_status: true,
    });
  });

  it("save body always sends all module booleans", () => {
    expect(
      mobilePinAccessSaveBody({
        clock: true,
        inventory: true,
        hang_dry: true,
      }),
    ).toEqual({
      clock: true,
      switch_role: false,
      checklist: false,
      inventory: true,
      revenue_cost: false,
      team_status: false,
    });
  });
});
