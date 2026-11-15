import { describe, expect, it } from "vitest";
import {
  autoScrollDelta,
  entriesForPeriod,
  hourCoverage,
  movedShift,
  overlappingBreakCount,
  placePopover,
  shiftHours,
  taskRollup,
} from "./plannerModel";

const fold = {
  user_id: 1,
  day_of_week: 1,
  start_time: "08:00",
  end_time: "16:00",
  role: "fold",
  break_slots: [{ start_time: "12:00", end_time: "12:30", timed: true }],
};

describe("planner period and coverage", () => {
  it("keeps week and day filters on the same entries", () => {
    const entries = [fold, { ...fold, user_id: 2, day_of_week: 2 }];
    expect(entriesForPeriod(entries, { mode: "week" })).toHaveLength(2);
    expect(entriesForPeriod(entries, { mode: "day", day: 1 }).map((entry) => entry.user_id)).toEqual([1]);
  });

  it("does not resize a shift when it moves", () => {
    const moved = movedShift(fold, { dayOfWeek: 3, startTime: "09:00" });
    expect(moved.end_time).toBe("17:00");
    expect(moved.day_of_week).toBe(3);
    expect(shiftHours(moved).gross).toBe(shiftHours(fold).gross);
  });

  it("removes a timed break from available coverage and keeps scheduled coverage", () => {
    const noon = hourCoverage([fold, { ...fold, user_id: 2, break_slots: [] }], 12);
    expect(noon.scheduled).toHaveLength(2);
    expect(noon.available.map((entry) => entry.user_id)).toEqual([2]);
    expect(shiftHours(fold)).toMatchObject({ gross: 8, net: 7.5 });
  });

  it("warns above three overlapping timed breaks", () => {
    const crowd = [1, 2, 3, 4].map((user_id) => ({ ...fold, user_id }));
    expect(overlappingBreakCount(crowd)).toBe(4);
  });

  it("counts a shared task group once", () => {
    const rollup = taskRollup([
      { id: 1, assignment_group_id: "g", user_id: 1, status: "completed" },
      { id: 2, assignment_group_id: "g", user_id: 2, status: "pending_approval" },
      { id: 3, user_id: 3, status: "approved" },
    ]);
    expect(rollup.groups).toBe(2);
    expect(rollup.counts.total).toBe(2);
    expect(rollup.people.total).toBe(3);
  });

  it("keeps popovers inside the viewport and scrolls near the edges", () => {
    const placed = placePopover({ top: 700, bottom: 740, left: 900 }, { width: 280, height: 180 }, { width: 1000, height: 800 });
    expect(placed.top).toBeLessThan(700);
    expect(placed.left + 280).toBeLessThanOrEqual(1000);
    expect(autoScrollDelta(10, { top: 0, bottom: 800 })).toBeLessThan(0);
    expect(autoScrollDelta(400, { top: 0, bottom: 800 })).toBe(0);
  });
});
