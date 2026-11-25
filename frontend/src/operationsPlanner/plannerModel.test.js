import { describe, expect, it } from "vitest";
import { employeeDayTimeline, timelineRoleBreakdown } from "../components/weeklySchedule/weeklyScheduleRoles";
import { staffingFigures } from "./plannerGeometry";
import {
  autoScrollDelta,
  coverageShiftLedger,
  entriesForPeriod,
  hourCoverage,
  minutesToClock,
  movedShift,
  roleAvailability,
  roleCoverage,
  roleDayCoverage,
  staffingHours,
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
    const combinedHour = roleCoverage([combined], "wash", 9, 1);
    expect(combinedHour.scheduled).toHaveLength(1);
    expect(combinedHour.available).toHaveLength(1);
    expect(combinedHour.onBreak).toHaveLength(0);
    expect(combinedHour.slices.every((slice) => slice.onBreak === 0)).toBe(true);
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
    expect(noon.slices.map((slice) => [slice.start, slice.end, slice.scheduled, slice.available])).toEqual([
      ["12:00", "12:30", 2, 1],
      ["12:30", "13:00", 2, 2],
    ]);
  });

  it("shows who is actually available during a partial break", () => {
    const person = (user_id, break_slots = []) => ({
      user_id,
      day_of_week: 1,
      start_time: "08:00",
      end_time: "16:00",
      role: "fold",
      break_slots,
      role_assignments: [{ role: "fold", start_time: "08:00", end_time: "16:00" }],
    });
    const entries = [
      person(1, [{ start_time: "10:00", end_time: "10:30", timed: true }]),
      person(2, [{ start_time: "10:00", end_time: "10:30", timed: true }]),
      person(3),
    ];
    const hour = roleCoverage(entries, "fold", 10, 3);
    expect(hour.scheduled).toHaveLength(3);
    expect(hour.slices.map((slice) => [slice.start, slice.end, slice.scheduled, slice.available, slice.onBreak])).toEqual([
      ["10:00", "10:30", 3, 1, 2],
      ["10:30", "11:00", 3, 3, 0],
    ]);
    expect(hour.lowAvailable).toBe(1);
    expect(hour.highAvailable).toBe(3);
    const totals = roleDayCoverage(entries, "fold", 1);
    expect(totals.people).toBe(3);
    expect(totals.grossHours).toBe(24);
    expect(totals.netHours).toBe(23);
    expect(totals.untimedHours).toBe(0);
    const rows = staffingHours(entries, [], "fold", 1);
    expect(rows.find((row) => row.hour === 10)).toMatchObject({ scheduled: 3, lowAvailable: 1, highAvailable: 3 });
    expect(rows.find((row) => row.hour === 11)).toMatchObject({ scheduled: 3, lowAvailable: 3, highAvailable: 3, onBreak: 0 });
  });

  it("splits overlapping and partial breaks without removing the rest of the hour", () => {
    const person = (user_id, start, end) => ({
      user_id,
      day_of_week: 1,
      start_time: "08:00",
      end_time: "16:00",
      role: "fold",
      break_slots: [{ start_time: start, end_time: end, timed: true }],
      role_assignments: [{ role: "fold", start_time: "08:00", end_time: "16:00" }],
    });
    const partial = roleAvailability([
      person(1, "10:15", "10:45"),
      person(2),
      person(3),
    ], "fold", { day: 1, start: 10 * 60, end: 11 * 60 });
    expect(partial.map((slice) => [slice.start, slice.end, slice.available])).toEqual([
      ["10:00", "10:15", 3],
      ["10:15", "10:45", 2],
      ["10:45", "11:00", 3],
    ]);
    const overlap = roleAvailability([
      person(1, "10:00", "10:30"),
      person(2, "10:15", "10:45"),
      person(3, "11:00", "11:30"),
    ], "fold", { day: 1, start: 10 * 60, end: 11 * 60 });
    expect(overlap.map((slice) => [slice.start, slice.end, slice.scheduled, slice.available])).toEqual([
      ["10:00", "10:15", 3, 2],
      ["10:15", "10:30", 3, 1],
      ["10:30", "10:45", 3, 2],
      ["10:45", "11:00", 3, 3],
    ]);
    const doubled = roleDayCoverage([{
      user_id: 1,
      day_of_week: 1,
      start_time: "08:00",
      end_time: "16:00",
      role: "fold",
      break_minutes: 40,
      break_slots: [
        { start_time: "10:00", end_time: "10:30", timed: true },
        { start_time: "10:15", end_time: "10:40", timed: true },
      ],
      role_assignments: [{ role: "fold", start_time: "08:00", end_time: "16:00" }],
    }], "fold", 1);
    expect(doubled.timedBreakHours).toBeCloseTo(40 / 60, 4);
    expect(doubled.grossHours).toBe(8);
    expect(doubled.netHours).toBeCloseTo(8 - 40 / 60, 4);
    expect(roleAvailability([{
      user_id: 1,
      day_of_week: 1,
      start_time: "08:00",
      end_time: "16:00",
      role: "fold",
      break_slots: [
        { start_time: "10:00", end_time: "10:30", timed: true },
        { start_time: "10:15", end_time: "10:40", timed: true },
      ],
    }], "fold", { day: 1, start: 10 * 60, end: 11 * 60 }).map((slice) => [slice.start, slice.end, slice.available])).toEqual([
      ["10:00", "10:40", 0],
      ["10:40", "11:00", 1],
    ]);
  });

  it("deducts a timed break only from the role it overlaps", () => {
    const entry = {
      user_id: 4,
      day_of_week: 1,
      start_time: "05:00",
      end_time: "14:00",
      role: "wash,fold",
      break_minutes: 60,
      break_slots: [{ start_time: "07:30", end_time: "08:30", timed: true }],
      role_assignments: [
        { role: "wash", start_time: "05:00", end_time: "08:00" },
        { role: "fold", start_time: "08:00", end_time: "14:00" },
      ],
    };
    expect(roleDayCoverage([entry], "wash", 1)).toMatchObject({ people: 1, grossHours: 3, netHours: 2.5, timedBreakHours: 0.5 });
    expect(roleDayCoverage([entry], "fold", 1)).toMatchObject({ people: 1, grossHours: 6, netHours: 5.5, timedBreakHours: 0.5 });
    expect(roleAvailability([entry], "fold", { day: 1, start: 7 * 60, end: 8 * 60 })).toEqual([]);
    expect(roleAvailability([entry], "wash", { day: 1, start: 7 * 60, end: 8 * 60 }).map((slice) => [slice.start, slice.end, slice.available])).toEqual([
      ["07:00", "07:30", 1],
      ["07:30", "08:00", 0],
    ]);
    expect(roleAvailability([entry], "fold", { day: 1, start: 8 * 60, end: 9 * 60 }).map((slice) => [slice.start, slice.end, slice.available])).toEqual([
      ["08:00", "08:30", 0],
      ["08:30", "09:00", 1],
    ]);
  });

  it("keeps an untimed break off the clock and off other roles", () => {
    const single = {
      user_id: 5,
      day_of_week: 2,
      start_time: "08:00",
      end_time: "16:00",
      role: "fold",
      break_minutes: 30,
      break_slots: [{ minutes: 30 }],
      role_assignments: [{ role: "fold", start_time: "08:00", end_time: "16:00" }],
    };
    const totals = roleDayCoverage([single], "fold", 2);
    expect(totals).toMatchObject({ grossHours: 8, netHours: 7.5, untimedHours: 0.5, unallocatedUntimedHours: 0 });
    expect(roleAvailability([single], "fold", { day: 2, start: 10 * 60, end: 11 * 60 })).toEqual([
      { start: "10:00", end: "11:00", scheduled: 1, available: 1, onBreak: 0, scheduledIds: [5], availableIds: [5], onBreakIds: [] },
    ]);
    const split = {
      user_id: 6,
      day_of_week: 2,
      start_time: "05:00",
      end_time: "13:00",
      role: "wash,fold",
      break_minutes: 30,
      break_slots: null,
      role_assignments: [
        { role: "wash", start_time: "05:00", end_time: "08:00" },
        { role: "fold", start_time: "08:00", end_time: "13:00" },
      ],
    };
    expect(roleDayCoverage([split], "wash", 2).netHours).toBe(3);
    expect(roleDayCoverage([split], "fold", 2)).toMatchObject({
      grossHours: 5,
      netHours: 5,
      untimedHours: 0,
      unallocatedUntimedHours: 0.5,
      severalRoleUntimedHours: 0.5,
      openTimeUntimedHours: 0,
    });
    const openTail = roleDayCoverage([
      {
        user_id: 8,
        day_of_week: 3,
        start_time: "08:00",
        end_time: "16:30",
        role: "attendant",
        break_slots: [{ minutes: 30 }, { minutes: 30 }],
        role_assignments: [{ role: "attendant", start_time: "08:00", end_time: "16:00" }],
      },
      {
        user_id: 8,
        day_of_week: 3,
        start_time: "08:00",
        end_time: "16:00",
        role: "attendant",
        break_slots: [{ minutes: 30 }],
        role_assignments: [{ role: "attendant", start_time: "08:00", end_time: "16:00" }],
      },
    ], "attendant", 3);
    expect(openTail).toMatchObject({
      people: 1,
      grossHours: 8,
      netHours: 8,
      untimedHours: 0,
      unallocatedUntimedHours: 0.5,
      openTimeUntimedHours: 0.5,
      severalRoleUntimedHours: 0,
    });
    expect(roleAvailability([
      {
        user_id: 8,
        day_of_week: 3,
        start_time: "08:00",
        end_time: "16:30",
        role: "attendant",
        break_slots: [{ minutes: 30 }],
        role_assignments: [{ role: "attendant", start_time: "08:00", end_time: "16:00" }],
      },
    ], "attendant", { day: 3, start: 10 * 60, end: 11 * 60 })[0]).toMatchObject({ scheduled: 1, available: 1, onBreak: 0 });
    expect(roleCoverage([split], "fold", 9, null, 2).onBreak).toHaveLength(0);
    expect(roleCoverage([split], "fold", 9, null, 2).available).toHaveLength(1);
  });

  it("keeps coverage role hours on the payroll timeline", () => {
    const samples = [
      fold,
      {
        user_id: 4,
        day_of_week: 1,
        start_time: "05:00",
        end_time: "14:00",
        role: "wash,fold",
        break_minutes: 60,
        break_slots: [{ start_time: "07:30", end_time: "08:30", timed: true }],
        role_assignments: [
          { role: "wash", start_time: "05:00", end_time: "08:00" },
          { role: "fold", start_time: "08:00", end_time: "14:00" },
        ],
      },
      {
        user_id: 9,
        day_of_week: 3,
        start_time: "08:00",
        end_time: "16:00",
        role: "wash,fold",
        break_minutes: 30,
        break_slots: [{ start_time: "10:00", end_time: "10:30", timed: true }],
      },
    ];
    for (const entry of samples) {
      const segments = (entry.role_assignments || []).filter((item) => item?.role && item.start_time && item.end_time);
      const adapted = segments.length
        ? {
          ...entry,
          assignments: segments.map((item) => ({
            role: item.role,
            start_time: item.start_time,
            end_time: item.end_time,
            full_shift: false,
          })),
        }
        : entry;
      const breakdown = timelineRoleBreakdown(employeeDayTimeline([adapted]));
      for (const [role, parts] of breakdown.roles) {
        if (!role) continue;
        const coverage = roleDayCoverage([entry], role, entry.day_of_week);
        expect(coverage.grossHours).toBeCloseTo(parts.gross, 4);
        expect(coverage.netHours).toBeCloseTo(parts.net, 4);
        expect(coverage.timedBreakHours).toBeCloseTo(parts.timedBreak, 4);
        expect(coverage.untimedHours).toBeCloseTo(parts.untimedBreak, 4);
        expect(coverage.unallocatedUntimedHours).toBeCloseTo(parts.unallocatedBreak, 4);
      }
    }
  });

  it("counts one employee once when that employee's shifts overlap", () => {
    const morning = {
      user_id: 1,
      day_of_week: 1,
      start_time: "06:00",
      end_time: "14:00",
      role: "fold",
      break_slots: [{ start_time: "10:00", end_time: "10:30", timed: true }],
      role_assignments: [{ role: "fold", start_time: "06:00", end_time: "14:00" }],
    };
    const inside = {
      ...morning,
      id: 2,
      start_time: "08:00",
      end_time: "12:00",
      break_slots: [],
      role_assignments: [{ role: "fold", start_time: "08:00", end_time: "12:00" }],
    };
    const other = { ...morning, id: 3, user_id: 2, break_slots: [] };
    const slices = roleAvailability([morning, inside, other], "fold", { day: 1, start: 10 * 60, end: 11 * 60 });
    expect(slices.map((slice) => [slice.start, slice.end, slice.scheduled, slice.available, slice.scheduledIds])).toEqual([
      ["10:00", "10:30", 2, 1, [1, 2]],
      ["10:30", "11:00", 2, 2, [1, 2]],
    ]);
    expect(staffingHours([morning, inside, other], [], "fold", 1).find((row) => row.hour === 10)).toMatchObject({
      scheduled: 2,
      lowAvailable: 1,
      highAvailable: 2,
    });
    expect(roleDayCoverage([morning, inside], "fold", 1)).toMatchObject({ people: 1, grossHours: 8, netHours: 7.5 });
  });

  it("reconciles coverage with shift gross, break, and net", () => {
    const days = [
      [fold],
      [{
        user_id: 4,
        day_of_week: 1,
        start_time: "05:00",
        end_time: "14:00",
        role: "wash,fold",
        break_minutes: 60,
        break_slots: [{ start_time: "07:30", end_time: "08:30", timed: true }],
        role_assignments: [
          { role: "wash", start_time: "05:00", end_time: "08:00" },
          { role: "fold", start_time: "08:00", end_time: "14:00" },
        ],
      }],
      [{
        user_id: 9,
        day_of_week: 3,
        start_time: "08:00",
        end_time: "16:00",
        role: "wash,fold",
        break_minutes: 30,
        break_slots: [{ start_time: "10:00", end_time: "10:30", timed: true }],
      }],
      [{
        user_id: 6,
        day_of_week: 2,
        start_time: "05:00",
        end_time: "13:00",
        role: "wash,fold",
        break_minutes: 30,
        break_slots: null,
        role_assignments: [
          { role: "wash", start_time: "05:00", end_time: "08:00" },
          { role: "fold", start_time: "08:00", end_time: "13:00" },
        ],
      }],
      [
        {
          user_id: 8,
          day_of_week: 3,
          start_time: "08:00",
          end_time: "16:30",
          role: "attendant",
          break_slots: [{ minutes: 30 }, { minutes: 30 }],
          role_assignments: [{ role: "attendant", start_time: "08:00", end_time: "16:00" }],
        },
        {
          user_id: 8,
          day_of_week: 3,
          start_time: "08:00",
          end_time: "16:00",
          role: "attendant",
          break_slots: [{ minutes: 30 }],
          role_assignments: [{ role: "attendant", start_time: "08:00", end_time: "16:00" }],
        },
      ],
    ];
    for (const entries of days) {
      const day = entries[0].day_of_week;
      const figures = staffingFigures(entries);
      const ledger = coverageShiftLedger(entries, day);
      expect(ledger.shiftGross).toBeCloseTo(figures.total, 4);
      expect(ledger.roleGross).toBeCloseTo(figures.role, 4);
      expect(ledger.noRoleGross).toBeCloseTo(figures.unallocated, 4);
      expect(ledger.shiftGross - ledger.timedBreak - ledger.untimedBreak - ledger.unallocatedUntimed).toBeCloseTo(figures.net, 4);
    }
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
