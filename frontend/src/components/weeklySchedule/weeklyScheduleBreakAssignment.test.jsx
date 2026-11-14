import React from "react";
import { renderToString } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { BreakAssignmentPanel } from "./AssignTasksDialog";
import {
  breakSummary,
  breakTargets,
  suggestedBreakSlot,
  unscheduledAssignmentPairs,
} from "./weeklyScheduleBreakAssignment";

const ana = { user_id: 1, display_name: "Ana" };
const ben = { user_id: 2, display_name: "Ben" };
const entries = [
  {
    id: 10,
    user_id: 1,
    day_of_week: 1,
    start_time: "09:00",
    end_time: "17:00",
    break_slots: [{ start_time: "12:00", end_time: "12:30" }],
    unscheduled_break_minutes: 0,
  },
  {
    id: 11,
    user_id: 2,
    day_of_week: 1,
    start_time: "09:00",
    end_time: "17:00",
    break_slots: [],
    unscheduled_break_minutes: 0,
  },
];

describe("break and task assignment selection", () => {
  it("lists who is not scheduled without treating a shift as missing", () => {
    expect(unscheduledAssignmentPairs(entries, [ana, ben], [1, 2])).toEqual([
      { userId: 1, day: 2, name: "Ana" },
      { userId: 2, day: 2, name: "Ben" },
    ]);
  });

  it("describes an existing break and leaves a shift with no break empty", () => {
    expect(breakSummary(entries[0])).toMatchObject({ hasBreak: true, totalMinutes: 30, timedMinutes: 30 });
    expect(breakSummary(entries[1]).hasBreak).toBe(false);
    expect(breakSummary({ break_slots: [], unscheduled_break_minutes: 20 })).toMatchObject({
      hasBreak: true,
      unscheduled: 20,
      totalMinutes: 20,
    });
  });

  it("keeps each employee and date separate, including a date with no shift", () => {
    const targets = breakTargets({ people: [ana, ben], days: [1, 2], entries });
    expect(targets.map((target) => [target.name, target.day, target.shifts.length])).toEqual([
      ["Ana", 1, 1],
      ["Ana", 2, 0],
      ["Ben", 1, 1],
      ["Ben", 2, 0],
    ]);
    const suggestion = suggestedBreakSlot(entries[1]);
    expect(suggestion.start_time < suggestion.end_time).toBe(true);
  });

  it("shows the current break, add, and the shift requirement on their own rows", () => {
    const html = renderToString(
      <BreakAssignmentPanel
        people={[ana, ben]}
        days={[1, 2]}
        entries={entries}
        weekStart="2026-10-05"
        onSaveBreak={async () => false}
      />,
    );
    expect(html).toContain("Edit");
    expect(html).toContain("Remove");
    expect(html).toContain("Add Break");
    expect(html).toContain("A scheduled break needs a shift. This employee is not scheduled on this date.");
    expect(html.match(/data-break-target=/g)).toHaveLength(4);
  });
});
