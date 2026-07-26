import { afterEach, describe, expect, it, vi } from "vitest";
import { currentWeekStart, normalizeWeekStart, shiftWeek } from "./weeklyScheduleDates";

describe("weeklyScheduleDates", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("normalizes to Sunday week start", () => {
    expect(normalizeWeekStart("2026-07-25")).toBe("2026-07-19");
    expect(normalizeWeekStart("2026-07-19")).toBe("2026-07-19");
    expect(normalizeWeekStart("2026-07-26")).toBe("2026-07-26");
  });

  it("uses America/New_York today, not UTC, for current week", () => {
    // Saturday evening ET is already Sunday in UTC — must stay on Jul 19 week.
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-26T00:30:00.000Z")); // Sat Jul 25 8:30pm EDT
    expect(currentWeekStart()).toBe("2026-07-19");
  });

  it("shifts weeks without UTC day rollback", () => {
    expect(shiftWeek("2026-07-19", 1)).toBe("2026-07-26");
    expect(shiftWeek("2026-07-26", -1)).toBe("2026-07-19");
  });
});
