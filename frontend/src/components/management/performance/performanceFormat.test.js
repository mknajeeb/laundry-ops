import { describe, expect, it } from "vitest";
import { fmtCount, fmtDelta, fmtHours, fmtLbs, fmtRate, recordedDay } from "./performanceFormat";

describe("performanceFormat", () => {
  it("formats rates and weights for KPI display", () => {
    expect(fmtRate(2.14)).toBe("2.1");
    expect(fmtRate(null)).toBe("—");
    expect(fmtLbs(1940, { compact: true })).toBe("1,940 lb");
    expect(fmtCount(89)).toBe("89");
    expect(fmtDelta(12.4)).toBe("+12%");
    expect(fmtDelta(-3.2)).toBe("-3%");
  });

  it("uses total pounds over total hours", () => {
    const day = recordedDay({
      recorded_total_pre_lbs: 110,
      recorded_performance_hours: 10,
      recorded_orders_completed: 5,
      recorded_lbs_per_hour: 11,
    });
    expect(day.rate).toBe(11);
    expect(day.bags).toBe(5);
    const fromTotals = recordedDay({
      all_visible_total_pre_lbs: 110,
      all_visible_performance_hours: 10,
    });
    expect(fromTotals.rate).toBe(11);
  });

  it("formats total hours for the WF KPI strip", () => {
    expect(fmtHours(12.46)).toBe("12.5");
    expect(fmtHours(4.14)).toBe("4.1");
    expect(fmtHours(null)).toBe("—");
  });
});
