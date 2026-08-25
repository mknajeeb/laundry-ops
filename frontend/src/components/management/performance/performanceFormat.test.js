import { describe, expect, it } from "vitest";
import { fmtCount, fmtDelta, fmtHours, fmtLbs, fmtRate } from "./performanceFormat";

describe("performanceFormat", () => {
  it("formats rates and weights for KPI display", () => {
    expect(fmtRate(2.14)).toBe("2.1");
    expect(fmtRate(null)).toBe("—");
    expect(fmtLbs(1940, { compact: true })).toBe("1,940 lb");
    expect(fmtCount(89)).toBe("89");
    expect(fmtDelta(12.4)).toBe("+12%");
    expect(fmtDelta(-3.2)).toBe("-3%");
  });

  it("formats total hours for the WF KPI strip", () => {
    expect(fmtHours(12.46)).toBe("12.5");
    expect(fmtHours(4.14)).toBe("4.1");
    expect(fmtHours(null)).toBe("—");
  });
});
