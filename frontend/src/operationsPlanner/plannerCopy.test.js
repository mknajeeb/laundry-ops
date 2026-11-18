import { describe, expect, it } from "vitest";
import { copyDay, copyEmployeeDay, copyEmployeeWeek, copiedShift, copyWeekShifts } from "./plannerCopy";
import { patternCells, reviewLines, scopeDecision, staffingChanges } from "./plannerReview";
import { laborComparison } from "./plannerLabor";

const shift = {
  id: 9,
  user_id: 4,
  day_of_week: 1,
  start_time: "08:00",
  end_time: "16:00",
  role: "fold",
  break_minutes: 30,
  break_slots: [],
  role_assignments: [],
};

describe("schedule copies", () => {
  it("copies a shift onto another employee and day without task history", () => {
    const copy = copiedShift({ ...shift, tasks: [{ id: 1, status: "completed" }] }, { userId: 8, dayOfWeek: 3 });
    expect(copy.user_id).toBe(8);
    expect(copy.day_of_week).toBe(3);
    expect(copy.id).not.toBe(9);
    expect(copy.tasks).toBeUndefined();
    expect(copy.break_minutes).toBe(30);
  });

  it("copies an employee day, an employee week, a whole day, and a week of shifts", () => {
    const other = { ...shift, id: 10, user_id: 5, day_of_week: 2 };
    expect(copyEmployeeDay([shift, other], 4, 1, 4)).toHaveLength(3);
    expect(copyEmployeeWeek([shift, other], 4, 6).filter((entry) => entry.user_id === 6)).toHaveLength(1);
    expect(copyDay([shift, { ...shift, id: 11, user_id: 5 }], 1, 5).filter((entry) => entry.day_of_week === 5)).toHaveLength(2);
    expect(copyWeekShifts([shift, other])).toHaveLength(2);
  });
});

describe("save scope", () => {
  it("repeats one shift and also repeats two shifts on the same day", () => {
    const next = { ...shift, end_time: "17:00" };
    expect(scopeDecision([shift], [next]).recurring).toBe(true);
    expect(patternCells([shift], [next])[0].shift.end_time).toBe("17:00");
    const split = [shift, { ...shift, id: "draft-2", start_time: "16:00", end_time: "20:00" }];
    expect(scopeDecision([shift], split).recurring).toBe(true);
    expect(patternCells([shift], split)[0].shifts).toHaveLength(2);
  });

  it("lists the before and after shift and a new staffing interval", () => {
    const lines = reviewLines([shift], [{ ...shift, end_time: "17:00" }], [{ user_id: 4, display_name: "Ana" }]);
    expect(lines[0].kind).toBe("Change");
    expect(lines[0].employee).toBe("Ana");
    expect(lines[0].before).toMatch(/08:00–16:00/);
    expect(lines[0].after).toMatch(/17:00/);
    expect(staffingChanges([], [{ role: "fold", day_of_week: 1, start_time: "08:00", end_time: "12:00", required_headcount: 2 }])).toHaveLength(1);
  });
});

describe("shared labor hours", () => {
  it("uses the weekly schedule total for one shift and keeps assignment hours when shifts overlap", () => {
    const single = laborComparison([shift], []);
    expect(single.scheduleGross).toBe(8);
    expect(single.assignmentGross).toBe(8);
    const overlap = laborComparison([
      shift,
      { ...shift, id: 12, start_time: "12:00", end_time: "16:00", break_minutes: 0 },
    ], []);
    expect(overlap.assignmentGross).toBe(12);
    expect(overlap.uniqueGross).toBe(8);
    expect(overlap.scheduleGross).toBe(8);
  });
});
