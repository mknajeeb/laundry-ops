import { describe, expect, it } from "vitest";
import { buildPinLauncherTiles, clockTileLabel } from "./buildPinLauncherTiles";

describe("clockTileLabel", () => {
  it("uses reliable clocked state only", () => {
    expect(clockTileLabel({ clocked_in: false })).toBe("Clock In");
    expect(clockTileLabel({ clocked_in: true })).toBe("Clock Out");
    expect(clockTileLabel({})).toBe("Clock");
    expect(clockTileLabel({ clocked_in: null })).toBe("Clock");
    expect(clockTileLabel(null)).toBe("Clock");
  });
});

describe("buildPinLauncherTiles", () => {
  it("shows Clock In when shared device is on and clocked out", () => {
    const tiles = buildPinLauncherTiles({
      features: {
        switch_role: { allowed: true },
        checklist: { allowed: true },
        inventory: { allowed: true },
      },
      featureOrder: ["switch_role", "checklist", "inventory"],
      attendance: { shared_device_enabled: true, clocked_in: false, on_break: false },
    });
    expect(tiles.map((t) => t.id)).toEqual(["clock", "checklist", "inventory"]);
    expect(tiles[0].label).toBe("Clock In");
    expect(tiles.find((t) => t.id === "inventory")?.label).toBe("Stock");
    expect(tiles.find((t) => t.id === "checklist")?.label).toBe("Tasks");
  });

  it("hides Role unless confirmed clocked in", () => {
    const out = buildPinLauncherTiles({
      features: { switch_role: { allowed: true }, checklist: { allowed: false }, inventory: { allowed: false } },
      attendance: { shared_device_enabled: true, clocked_in: false },
    });
    expect(out.map((t) => t.id)).toEqual(["clock"]);

    const unknown = buildPinLauncherTiles({
      features: { switch_role: { allowed: true } },
      attendance: { shared_device_enabled: true },
    });
    expect(unknown.map((t) => [t.id, t.label])).toEqual([["clock", "Clock"]]);
    expect(unknown.some((t) => t.id === "switch_role")).toBe(false);

    const inn = buildPinLauncherTiles({
      features: { switch_role: { allowed: true }, checklist: { allowed: false }, inventory: { allowed: false } },
      attendance: { shared_device_enabled: true, clocked_in: true },
    });
    expect(inn.map((t) => [t.id, t.label])).toEqual([
      ["clock", "Clock Out"],
      ["switch_role", "Role"],
    ]);
  });

  it("omits Clock when shared device attendance is disabled", () => {
    const tiles = buildPinLauncherTiles({
      features: { inventory: { allowed: true } },
      attendance: { shared_device_enabled: false, clocked_in: false },
    });
    expect(tiles.map((t) => t.id)).toEqual(["inventory"]);
    expect(tiles[0].label).toBe("Stock");
  });

  it("does not invent a Break tile", () => {
    const tiles = buildPinLauncherTiles({
      features: { switch_role: { allowed: true } },
      attendance: { shared_device_enabled: true, clocked_in: true, on_break: true },
    });
    expect(tiles.some((t) => t.id === "break")).toBe(false);
  });
});
