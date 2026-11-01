import { afterEach, describe, expect, it, vi } from "vitest";
import { currentWeekStart, formatDayDate, normalizeWeekStart, shiftWeek } from "./weeklyScheduleDates";

describe("weeklyScheduleDates", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("normalizes to the Monday of the Monday–Sunday week", () => {
    expect(normalizeWeekStart("2026-07-25")).toBe("2026-07-20");
    expect(normalizeWeekStart("2026-07-19")).toBe("2026-07-13");
    expect(normalizeWeekStart("2026-07-20")).toBe("2026-07-20");
    expect(normalizeWeekStart("2026-07-26")).toBe("2026-07-20");
  });

  it("uses America/New_York today, not UTC, for current week", () => {
    // Saturday evening ET is already Sunday in UTC — the week is still Jul 20–26.
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-26T00:30:00.000Z")); // Sat Jul 25 8:30pm EDT
    expect(currentWeekStart()).toBe("2026-07-20");
  });

  it("opens the following Monday on Sunday and keeps Sunday on the previous week", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-11-01T18:00:00.000Z")); // Sun Nov 1, 1:00pm EST
    expect(normalizeWeekStart("2026-11-01")).toBe("2026-10-26");
    expect(currentWeekStart()).toBe("2026-11-02");
    expect(formatDayDate("2026-11-02", 1)).toMatch(/Nov 2, 2026/);
    expect(formatDayDate("2026-11-02", 0)).toMatch(/Nov 8, 2026/);
  });

  it("shifts weeks without UTC day rollback", () => {
    expect(shiftWeek("2026-11-02", 1)).toBe("2026-11-09");
    expect(shiftWeek("2026-11-02", -1)).toBe("2026-10-26");
    expect(shiftWeek("2026-07-20", 1)).toBe("2026-07-27");
  });
});
