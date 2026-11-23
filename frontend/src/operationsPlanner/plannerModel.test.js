import { describe, expect, it } from "vitest";
import {
  autoScrollDelta,
  entriesForPeriod,
  hourCoverage,
  minutesToClock,
  movedShift,
  roleCoverage,
  snapMinutes,
  breakAccounting,
  breakOverlapBands,
  overlappingBreakCount,
  placePopover,
  requirementFor,
  scheduleHourReconciliation,
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

  it("keeps unscheduled break minutes out of overlap and coverage", () => {
    const stored = {
      user_id: 26,
      start_time: "03:00",
      end_time: "11:30",
      role: "wash",
      break_minutes: 30,
      break_slots: null,
      role_assignments: null,
    };
    expect(shiftHours(stored)).toMatchObject({ gross: 8.5, timedBreak: 0.5, net: 8 });
    expect(overlappingBreakCount([stored, { ...stored, user_id: 19 }])).toBe(0);
    expect(hourCoverage([stored], 9).available).toHaveLength(1);
    expect(hourCoverage([stored], 9).onBreak).toHaveLength(0);
    const combined = { ...stored, role: "wash,attendant" };
    expect(roleCoverage([combined], "wash", 9, 1).scheduled).toHaveLength(0);
    expect(roleCoverage([stored], "wash", 9, 1).available).toHaveLength(1);
    const breaks = breakAccounting([stored, { ...stored, user_id: 19, break_minutes: 0 }, fold]);
    expect(breaks.unscheduledCount).toBe(1);
    expect(breaks.unscheduledHours).toBe(0.5);
    expect(breaks.timedHours).toBe(0.5);
    expect(breaks.overlapKnown).toBe(false);
    expect(requirementFor([], "wash", 1, 9)).toBeNull();
    expect(requirementFor([{ role: "wash", day_of_week: 1, start_time: "05:00", end_time: "13:00", required_headcount: 0 }], "wash", 1, 9)).toBe(0);
    expect(requirementFor([{ role: "wash", day_of_week: 1, start_time: "05:00", end_time: "13:00", required_headcount: 3 }], "wash", 2, 9)).toBeNull();
    expect(requirementFor([], "fold", 1, 12, { hourly_headcount: { 12: 2 } })).toBe(2);
    expect(roleCoverage([stored], "wash", 9, null).required).toBeNull();
    expect(roleCoverage([stored], "wash", 9, null).shortage).toBe(0);
  });

  it("warns above three overlapping timed breaks", () => {
    const crowd = [1, 2, 3, 4].map((user_id) => ({ ...fold, user_id }));
    expect(overlappingBreakCount(crowd)).toBe(4);
    const bands = breakOverlapBands([
      fold,
      { ...fold, user_id: 2 },
      { ...fold, user_id: 3, break_slots: [{ start_time: "12:00", end_time: "12:15", timed: true }] },
    ]);
    expect(bands.map((band) => [minutesToClock(band.start), minutesToClock(band.end), band.count])).toEqual([
      ["12:00", "12:15", 3],
      ["12:15", "12:30", 2],
    ]);
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

  it("snaps timeline edits and subtracts a break from role coverage", () => {
    expect(snapMinutes(12 * 60 + 7)).toBe(12 * 60);
    expect(minutesToClock(12 * 60 + 7)).toBe("12:00");
    const noon = roleCoverage(
      [fold, { ...fold, user_id: 2, role_assignments: [{ role: "fold", start_time: "08:00", end_time: "16:00" }], break_slots: [] }],
      "fold",
      12,
      2,
    );
    expect(noon.scheduled).toHaveLength(2);
    expect(noon.available).toHaveLength(1);
    expect(noon.onBreak).toHaveLength(1);
    expect(noon.shortage).toBe(1);
  });

  it("counts overlapping shifts once for worked hours and separately for shift totals", () => {
    const first = { user_id: 1, day_of_week: 1, start_time: "08:00", end_time: "16:00", break_minutes: 30, break_slots: null };
    const overlap = { ...first, start_time: "12:00", end_time: "16:00", break_minutes: 30 };
    const other = { ...first, user_id: 2, break_minutes: 0 };
    const hours = scheduleHourReconciliation([first, overlap, other]);
    expect(hours.shiftGross).toBe(20);
    expect(hours.workedGross).toBe(16);
    expect(hours.overlapHours).toBe(4);
    expect(hours.shiftBreak).toBe(1);
    expect(hours.workedBreak).toBe(0.5);
    expect(hours.workedNet).toBe(15.5);
  });

  it("keeps popovers inside the viewport and scrolls near the edges", () => {
    const placed = placePopover({ top: 700, bottom: 740, left: 900 }, { width: 280, height: 180 }, { width: 1000, height: 800 });
    expect(placed.top).toBeLessThan(700);
    expect(placed.left + 280).toBeLessThanOrEqual(1000);
    expect(autoScrollDelta(10, { top: 0, bottom: 800 })).toBeLessThan(0);
    expect(autoScrollDelta(400, { top: 0, bottom: 800 })).toBe(0);
  });
});
