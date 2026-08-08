import { describe, expect, it } from "vitest";
import {
  buildPinLauncherTiles,
  clockTileLabel,
  CLOCK_DISABLED_HELPER,
  ROLE_CLOCK_IN_FIRST_MESSAGE,
  isClockAllowedFromHub,
} from "./buildPinLauncherTiles";

describe("clockTileLabel", () => {
  it("uses reliable clocked state only", () => {
    expect(clockTileLabel({ clocked_in: false })).toBe("Clock In");
    expect(clockTileLabel({ clocked_in: true })).toBe("Clock Out");
    expect(clockTileLabel({})).toBe("Clock");
    expect(clockTileLabel({ clocked_in: null })).toBe("Clock");
    expect(clockTileLabel(null)).toBe("Clock");
  });
});

describe("isClockAllowedFromHub", () => {
  it("defaults on when field is absent", () => {
    expect(isClockAllowedFromHub({})).toBe(true);
    expect(isClockAllowedFromHub(null)).toBe(true);
    expect(isClockAllowedFromHub({ allow_clock_from_hub: true })).toBe(true);
    expect(isClockAllowedFromHub({ allow_clock_from_hub: false })).toBe(false);
  });
});

describe("buildPinLauncherTiles", () => {
  it("always shows Clock; disables when allow_clock_from_hub is false", () => {
    const enabled = buildPinLauncherTiles({
      features: {
        switch_role: { allowed: true },
        checklist: { allowed: true },
        inventory: { allowed: true },
      },
      featureOrder: ["switch_role", "checklist", "inventory"],
      attendance: { shared_device_enabled: true, clocked_in: false, on_break: false },
    });
    expect(enabled.map((t) => t.id)).toEqual(["clock", "switch_role", "checklist", "inventory"]);
    expect(enabled[0].label).toBe("Clock In");
    expect(enabled[0].disabled).toBe(false);
    expect(enabled.find((t) => t.id === "inventory")?.label).toBe("Inventory");
    expect(enabled.find((t) => t.id === "checklist")?.label).toBe("End-of-Day Checklist");
    expect(enabled.find((t) => t.id === "switch_role")?.requiresClockIn).toBe(true);

    const disabled = buildPinLauncherTiles({
      features: { inventory: { allowed: true } },
      attendance: {
        shared_device_enabled: true,
        allow_clock_from_hub: false,
        clocked_in: false,
      },
    });
    const clock = disabled.find((t) => t.id === "clock");
    expect(clock).toBeTruthy();
    expect(clock.disabled).toBe(true);
    expect(clock.disabledHelper).toBe(CLOCK_DISABLED_HELPER);
    expect(disabled.map((t) => t.id)).toEqual(["clock", "inventory"]);
  });

  it("keeps Clock visible even when shared-device attendance is off", () => {
    const tiles = buildPinLauncherTiles({
      features: { inventory: { allowed: true } },
      attendance: { shared_device_enabled: false, clocked_in: false },
    });
    expect(tiles.map((t) => t.id)).toEqual(["clock", "inventory"]);
    expect(tiles[0].disabled).toBe(false);
  });

  it("shows Role when allowed even if clocked out (requiresClockIn)", () => {
    const out = buildPinLauncherTiles({
      features: {
        switch_role: { allowed: true, requires_clock_in: true },
        checklist: { allowed: false },
        inventory: { allowed: false },
      },
      attendance: { shared_device_enabled: true, clocked_in: false },
    });
    expect(out.map((t) => t.id)).toEqual(["clock", "switch_role"]);
    expect(out.find((t) => t.id === "switch_role")?.requiresClockIn).toBe(true);
    expect(ROLE_CLOCK_IN_FIRST_MESSAGE).toMatch(/shared attendance tablet/i);

    const inn = buildPinLauncherTiles({
      features: { switch_role: { allowed: true }, checklist: { allowed: false }, inventory: { allowed: false } },
      attendance: { shared_device_enabled: true, clocked_in: true },
    });
    expect(inn.map((t) => [t.id, t.label, t.requiresClockIn])).toEqual([
      ["clock", "Clock Out", undefined],
      ["switch_role", "Role", undefined],
    ]);
  });

  it("hides Role when not allowed", () => {
    const tiles = buildPinLauncherTiles({
      features: { switch_role: { allowed: false }, inventory: { allowed: true } },
      attendance: { shared_device_enabled: true, clocked_in: true },
    });
    expect(tiles.map((t) => t.id)).toEqual(["clock", "inventory"]);
  });

  it("shows Revenue & Cost and Inventory labels; hides when not allowed", () => {
    const on = buildPinLauncherTiles({
      features: {
        inventory: { allowed: true },
        revenue_cost: { allowed: true },
      },
      featureOrder: ["inventory", "revenue_cost"],
      attendance: { clocked_in: false, allow_clock_from_hub: true },
    });
    expect(on.find((t) => t.id === "inventory")?.label).toBe("Inventory");
    expect(on.find((t) => t.id === "revenue_cost")?.label).toBe("Revenue & Cost");

    const off = buildPinLauncherTiles({
      features: {
        inventory: { allowed: false },
        revenue_cost: { allowed: false },
      },
      featureOrder: ["inventory", "revenue_cost"],
      attendance: { clocked_in: false, allow_clock_from_hub: true },
    });
    expect(off.map((t) => t.id)).toEqual(["clock"]);
  });

  it("disables Tasks tile when checklist is not assigned today", () => {
    const tiles = buildPinLauncherTiles({
      features: {
        checklist: {
          allowed: true,
          disabled: true,
          disabled_helper: "No maintenance checklist assigned today.",
        },
        inventory: { allowed: false },
      },
      attendance: { shared_device_enabled: true, clocked_in: false, allow_clock_from_hub: true },
    });
    const tasks = tiles.find((t) => t.id === "checklist");
    expect(tasks?.disabled).toBe(true);
    expect(tasks?.disabledHelper).toBe("No maintenance checklist assigned today.");
  });
});
