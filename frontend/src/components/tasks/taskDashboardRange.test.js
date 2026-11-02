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
