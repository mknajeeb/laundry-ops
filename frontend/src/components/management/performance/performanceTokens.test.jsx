import { describe, expect, it } from "vitest";
import { perfKpiStripSx, perfRowSx } from "./performanceTokens";

describe("performance row density", () => {
  it("uses compact padding for employee rows", () => {
    const row = perfRowSx();
    expect(row.py).toEqual({ xs: 0.7, sm: 0.6 });
    expect(row.px).toEqual({ xs: 1, sm: 1.15 });
    expect(row.boxShadow).toBeUndefined();
  });

  it("uses compact padding for KPI strip", () => {
    const strip = perfKpiStripSx();
    expect(strip.py).toEqual({ xs: 0.55, sm: 0.5 });
    expect(strip.mb).toBe(1);
  });
});
