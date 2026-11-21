import { describe, expect, it } from "vitest";
import {
  canGoNext,
  customRange,
  dayRange,
  rangeFor,
  rangeLabel,
  shiftRange,
  statusesForIssue,
  weekRange,
} from "./pinIssuesRange";

const TODAY = "2026-11-21";

describe("pin issues date ranges", () => {
  it("keeps a day, a Monday week, and a custom span in Eastern calendar dates", () => {
    expect(dayRange("2026-11-20")).toEqual({
      mode: "day",
      anchor: "2026-11-20",
      from: "2026-11-20",
      to: "2026-11-20",
    });
    expect(weekRange("2026-11-21")).toMatchObject({
      mode: "week",
      from: "2026-11-16",
      to: "2026-11-22",
    });
    expect(customRange("2026-11-18", "2026-11-12")).toMatchObject({
      from: "2026-11-12",
      to: "2026-11-18",
    });
  });

  it("moves to the previous day and back, and stops at today", () => {
    const yesterday = shiftRange(dayRange(TODAY), -1, TODAY);
    expect(yesterday.from).toBe("2026-11-20");
    expect(rangeLabel(yesterday, TODAY)).toBe("Yesterday");
    expect(canGoNext(yesterday, TODAY)).toBe(true);
    const back = shiftRange(yesterday, 1, TODAY);
    expect(back.from).toBe(TODAY);
    expect(rangeLabel(back, TODAY)).toBe("Today");
    expect(canGoNext(back, TODAY)).toBe(false);
    expect(shiftRange(back, 1, TODAY).from).toBe(TODAY);
  });

  it("shifts a week and a custom range without passing today", () => {
    const week = rangeFor("week", "2026-11-12", null, null, TODAY);
    expect(week.from).toBe("2026-11-09");
    expect(week.to).toBe("2026-11-15");
    const nextWeek = shiftRange(week, 1, TODAY);
    expect(nextWeek.from).toBe("2026-11-16");
    expect(nextWeek.to).toBe(TODAY);
    const custom = rangeFor("custom", "2026-11-01", "2026-11-01", "2026-11-03", TODAY);
    const shifted = shiftRange(custom, 1, TODAY);
    expect(shifted).toMatchObject({ from: "2026-11-04", to: "2026-11-06" });
  });

  it("uses the report's own status list", () => {
    expect(statusesForIssue({ source: "rinse" })).toContain("investigating");
    expect(statusesForIssue({ source: "employee", category: "orphan" })).toContain("stored");
    expect(statusesForIssue({ source: "employee", category: "equipment" })).not.toContain("stored");
  });
});
