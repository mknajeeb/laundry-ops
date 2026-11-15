import assert from "node:assert/strict";
import test from "node:test";
import {
  autoScrollDelta,
  entriesForPeriod,
  hourCoverage,
  movedShift,
  overlappingBreakCount,
  placePopover,
  shiftHours,
  taskRollup,
} from "./plannerModel.js";

const fold = {
  user_id: 1,
  day_of_week: 1,
  start_time: "08:00",
  end_time: "16:00",
  role: "fold",
  break_slots: [{ start_time: "12:00", end_time: "12:30", timed: true }],
};

test("week and day filters use the same entries", () => {
  const entries = [fold, { ...fold, user_id: 2, day_of_week: 2 }];
  assert.equal(entriesForPeriod(entries, { mode: "week" }).length, 2);
  assert.deepEqual(entriesForPeriod(entries, { mode: "day", day: 1 }).map((entry) => entry.user_id), [1]);
});

test("moving a shift keeps its length", () => {
  const moved = movedShift(fold, { dayOfWeek: 3, startTime: "09:00" });
  assert.equal(moved.end_time, "17:00");
  assert.equal(shiftHours(moved).gross, shiftHours(fold).gross);
});

test("a timed break leaves scheduled coverage and drops available coverage", () => {
  const noon = hourCoverage([fold, { ...fold, user_id: 2, break_slots: [] }], 12);
  assert.equal(noon.scheduled.length, 2);
  assert.deepEqual(noon.available.map((entry) => entry.user_id), [2]);
  assert.equal(shiftHours(fold).net, 7.5);
});

test("more than three timed breaks overlap", () => {
  assert.equal(overlappingBreakCount([1, 2, 3, 4].map((user_id) => ({ ...fold, user_id }))), 4);
});

test("a shared task group counts once", () => {
  const rollup = taskRollup([
    { id: 1, assignment_group_id: "g", user_id: 1, status: "completed" },
    { id: 2, assignment_group_id: "g", user_id: 2, status: "pending_approval" },
    { id: 3, user_id: 3, status: "approved" },
  ]);
  assert.equal(rollup.groups, 2);
  assert.equal(rollup.people.total, 3);
});

test("popovers stay in the viewport", () => {
  const placed = placePopover(
    { top: 700, bottom: 740, left: 900 },
    { width: 280, height: 180 },
    { width: 1000, height: 800 },
  );
  assert.ok(placed.top < 700);
  assert.ok(placed.left + 280 <= 1000);
  assert.ok(autoScrollDelta(10, { top: 0, bottom: 800 }) < 0);
  assert.equal(autoScrollDelta(400, { top: 0, bottom: 800 }), 0);
});
