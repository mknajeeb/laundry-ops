import { describe, expect, it } from "vitest";
import {
  MOBILE_PIN_ACCESS_MODULES,
  mobilePinAccessSaveBody,
  normalizeMobilePinAccess,
} from "./MobilePinAccessPanel";

describe("MobilePinAccessPanel contracts", () => {
  it("exposes Role + Take a Break and optional apps without Clock", () => {
    expect(MOBILE_PIN_ACCESS_MODULES.map((m) => m.key)).toEqual([
      "switch_role",
      "take_break",
      "checklist",
      "inventory",
      "revenue_cost",
      "team_status",
    ]);
    expect(MOBILE_PIN_ACCESS_MODULES.map((m) => m.label)).toEqual([
      "Role",
      "Take a Break",
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
        take_break: 1,
        checklist: true,
        inventory: false,
        revenue_cost: "1",
        team_status: 1,
        hang_dry: 1,
        extra: true,
      }),
    ).toEqual({
      switch_role: false,
      take_break: true,
      checklist: true,
      inventory: false,
      revenue_cost: true,
      team_status: true,
    });
  });

  it("save body always sends People app booleans without Clock", () => {
    expect(
      mobilePinAccessSaveBody({
        clock: true,
        inventory: true,
        hang_dry: true,
      }),
    ).toEqual({
      switch_role: false,
      take_break: false,
      checklist: false,
      inventory: true,
      revenue_cost: false,
      team_status: false,
    });
  });
});
