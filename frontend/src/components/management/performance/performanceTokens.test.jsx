import { describe, expect, it } from "vitest";
import { perfKpiGridSx, perfKpiInlineSx, perfKpiStripSx, perfRowSx } from "./performanceTokens";

describe("performance row density", () => {
  it("uses compact padding for employee rows", () => {
    const row = perfRowSx();
    expect(row.py).toEqual({ xs: 0.55, sm: 0.45, md: 0.4 });
    expect(row.px).toEqual({ xs: 0.85, sm: 1, md: 1.05 });
    expect(row.boxShadow).toBeUndefined();
  });

  it("uses compact padding for KPI strip", () => {
    const strip = perfKpiStripSx();
    expect(strip.py).toEqual({ xs: 0.45, sm: 0.4 });
    expect(strip.mb).toBe(0.75);
  });

  it("wraps WF KPIs into a 3-column mobile grid without horizontal scroll", () => {
    const grid = perfKpiGridSx();
    expect(grid.display).toEqual({ xs: "grid", sm: "none" });
    expect(grid.gridTemplateColumns).toBe("repeat(3, minmax(0, 1fr))");
    const inline = perfKpiInlineSx();
    expect(inline.display).toEqual({ xs: "none", sm: "block" });
  });
});
