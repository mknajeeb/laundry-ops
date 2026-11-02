import { describe, expect, it } from "vitest";
import { inclusiveSpanDays, taskDashboardRange } from "./taskDashboardRange";

const SUNDAY = "2026-11-01";

describe("taskDashboardRange", () => {
  it("uses Eastern calendar days and Monday-Sunday weeks", () => {
    expect(taskDashboardRange("today", SUNDAY)).toEqual({ start: SUNDAY, end: SUNDAY });
    expect(taskDashboardRange("yesterday", SUNDAY)).toEqual({
      start: "2026-10-31",
      end: "2026-10-31",
    });
    expect(taskDashboardRange("this_week", SUNDAY)).toEqual({
      start: "2026-10-26",
      end: "2026-11-01",
    });
    expect(taskDashboardRange("last_week", SUNDAY)).toEqual({
      start: "2026-10-19",
      end: "2026-10-25",
    });
    expect(taskDashboardRange("last_7", SUNDAY)).toEqual({
      start: "2026-10-26",
      end: "2026-11-01",
    });
    expect(taskDashboardRange("last_30", SUNDAY)).toEqual({
      start: "2026-10-03",
      end: "2026-11-01",
    });
    expect(taskDashboardRange("month", SUNDAY)).toEqual({
      start: "2026-11-01",
      end: "2026-11-30",
    });
  });

  it("keeps the November 1 daylight-saving Sunday on the Eastern calendar", () => {
    expect(taskDashboardRange("today", "2026-11-01")).toEqual({
      start: "2026-11-01",
      end: "2026-11-01",
    });
    expect(taskDashboardRange("yesterday", "2026-11-01").start).toBe("2026-10-31");
    expect(taskDashboardRange("this_week", "2026-11-01")).toEqual({
      start: "2026-10-26",
      end: "2026-11-01",
    });
    expect(taskDashboardRange("last_week", "2026-11-01")).toEqual({
      start: "2026-10-19",
      end: "2026-10-25",
    });
  });

  it("crosses month and year boundaries on calendar dates", () => {
    expect(taskDashboardRange("yesterday", "2026-03-01")).toEqual({
      start: "2026-02-28",
      end: "2026-02-28",
    });
    expect(taskDashboardRange("yesterday", "2024-03-01")).toEqual({
      start: "2024-02-29",
      end: "2024-02-29",
    });
    expect(taskDashboardRange("month", "2026-12-15")).toEqual({
      start: "2026-12-01",
      end: "2026-12-31",
    });
    expect(taskDashboardRange("month", "2026-01-01")).toEqual({
      start: "2026-01-01",
      end: "2026-01-31",
    });
    expect(taskDashboardRange("this_week", "2026-01-01")).toEqual({
      start: "2025-12-29",
      end: "2026-01-04",
    });
    expect(taskDashboardRange("custom", "2026-11-01", "2026-12-28", "2027-01-03")).toEqual({
      start: "2026-12-28",
      end: "2027-01-03",
    });
  });

  it("keeps a custom range intact and orders the endpoints", () => {
    expect(taskDashboardRange("custom", SUNDAY, "2026-08-01", "2026-10-15")).toEqual({
      start: "2026-08-01",
      end: "2026-10-15",
    });
    expect(taskDashboardRange("custom", SUNDAY, "2026-10-15", "2026-08-01")).toEqual({
      start: "2026-08-01",
      end: "2026-10-15",
    });
    expect(inclusiveSpanDays("2026-01-01", "2026-12-31")).toBe(365);
    expect(inclusiveSpanDays("2024-01-01", "2024-12-31")).toBe(366);
  });
});
