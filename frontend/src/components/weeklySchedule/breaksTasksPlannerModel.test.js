import { describe, expect, it } from "vitest";
import {
  BREAK_OVERLAP_CAP,
  breaksAfterEdit,
  buildEmployeeRows,
  buildTaskGroups,
  dayBreaks,
  filterTaskGroups,
  maxSimultaneous,
  overlapExceedsCap,
  peopleByState,
  taskGroupCounts,
  weekBreakSummary,
} from "./breaksTasksPlannerModel";

const employees = {
  1: { user_id: 1, display_name: "Ana" },
  2: { user_id: 2, display_name: "Ben" },
  3: { user_id: 3, display_name: "Cam" },
  4: { user_id: 4, display_name: "Dee" },
  5: { user_id: 5, display_name: "Eli" },
};

function shift(id, userId, slots, unscheduled = 0) {
  return {
    id,
    user_id: userId,
    day_of_week: 6,
    start_time: "07:00",
    end_time: "15:00",
    role: "wash",
    break_slots: slots,
    unscheduled_break_minutes: unscheduled,
  };
}

describe("break timeline overlap", () => {
  it("counts three timed breaks and ignores untimed breaks", () => {
    const entries = [
      shift(1, 1, [{ start_time: "10:00", end_time: "10:30" }]),
      shift(2, 2, [{ start_time: "10:00", end_time: "10:30" }]),
      shift(3, 3, [{ start_time: "10:15", end_time: "10:45" }]),
      shift(4, 4, [], 20),
      shift(5, 5, [], 15),
    ];
    const breaks = dayBreaks(entries, employees, 6);
    expect(breaks.timed).toHaveLength(3);
    expect(breaks.untimed.map((item) => item.name)).toEqual(["Dee", "Eli"]);
    expect(maxSimultaneous(breaks.timed)).toBe(3);
    expect(overlapExceedsCap(breaks.timed)).toBe(false);
  });

  it("requires confirmation only when a fourth employee overlaps", () => {
    const entries = [
      shift(1, 1, [{ start_time: "10:00", end_time: "10:30" }]),
      shift(2, 2, [{ start_time: "10:00", end_time: "10:30" }]),
      shift(3, 3, [{ start_time: "10:00", end_time: "10:30" }]),
      shift(4, 4, []),
    ];
    const proposed = breaksAfterEdit(entries, employees, 6, 4, [{ start_time: "10:00", end_time: "10:20" }]);
    expect(maxSimultaneous(proposed)).toBe(4);
    expect(overlapExceedsCap(proposed, BREAK_OVERLAP_CAP)).toBe(true);
    const touching = breaksAfterEdit(entries, employees, 6, 4, [{ start_time: "10:30", end_time: "11:00" }]);
    expect(maxSimultaneous(touching)).toBe(3);
  });

  it("summarizes each day's maximum overlap and untimed breaks", () => {
    const summary = weekBreakSummary(
      [shift(1, 1, [{ start_time: "10:00", end_time: "10:30" }], 10)],
      employees,
    );
    const saturday = summary.find((day) => day.day === 6);
    expect(saturday).toMatchObject({ maxOverlap: 1, untimed: 1, overCap: false });
    expect(summary.find((day) => day.day === 1)).toMatchObject({ maxOverlap: 0, untimed: 0 });
  });
});

describe("task tracker", () => {
  const responsibilities = [
    {
      id: 1,
      user_id: 1,
      day_of_week: 6,
      role: "floor_cleaning",
      assignment_group_id: "g1",
      execution_mode: "shared",
      activity_status: "completed",
      timing_label: "10:00 AM",
    },
    {
      id: 2,
      user_id: 2,
      day_of_week: 6,
      role: "floor_cleaning",
      assignment_group_id: "g1",
      execution_mode: "shared",
      activity_status: "pending_approval",
      timing_label: "10:00 AM",
    },
    {
      id: 3,
      user_id: 3,
      day_of_week: 1,
      role: "lint_cleaning",
      execution_mode: "individual",
      activity_status: null,
    },
  ];

  it("keeps one shared group and separates assignment from completion", () => {
    const groups = buildTaskGroups(responsibilities, employees);
    expect(groups).toHaveLength(2);
    const shared = groups.find((group) => group.groupId === "g1");
    expect(shared.members).toHaveLength(2);
    expect(shared.shared).toBe(true);
    const counts = taskGroupCounts(shared, Object.values(employees));
    expect(counts).toMatchObject({ assigned: 2, completed: 1, awaiting: 1, unassigned: 3 });
    expect(peopleByState(shared, "completed").map((member) => member.name)).toEqual(["Ana"]);
    expect(peopleByState(shared, "awaiting").map((member) => member.name)).toEqual(["Ben"]);
    expect(peopleByState(shared, "assigned")).toEqual([]);
  });

  it("filters by day, employee, and status without hiding the other day", () => {
    const groups = buildTaskGroups(responsibilities, employees);
    expect(filterTaskGroups(groups, { day: 6, scope: "day" })).toHaveLength(1);
    expect(filterTaskGroups(groups, { scope: "week" })).toHaveLength(2);
    expect(filterTaskGroups(groups, { scope: "week", userId: 3 })).toHaveLength(1);
    expect(filterTaskGroups(groups, { scope: "week", status: "awaiting" }).map((group) => group.groupId)).toEqual(["g1"]);
  });
});

describe("employee planner", () => {
  it("lists a person with a task and no shift, and keeps roles off the summary", () => {
    const rows = buildEmployeeRows({
      employees: [
        { user_id: 1, display_name: "Ana" },
        { user_id: 2, display_name: "Ben" },
      ],
      entries: [shift(1, 1, [{ start_time: "12:00", end_time: "12:30" }])],
      responsibilities: [
        { id: 8, user_id: 2, day_of_week: 6, role: "floor_cleaning", execution_mode: "individual" },
      ],
      day: 6,
      employeesById: employees,
    });
    expect(rows.map((row) => [row.name, row.hasShift, row.tasks.length, row.breakCount])).toEqual([
      ["Ana", true, 0, 1],
      ["Ben", false, 1, 0],
    ]);
    expect(rows[0].roles).toEqual(["wash"]);
    expect(rows[0].shiftLabel).toContain("7:00");
  });
});
