import { describe, expect, it } from "vitest";
import { buildHourlyCoverage } from "./weeklyScheduleTimeBlocks";
import { buildBreaksTasksGrid, gridTasksByDay } from "./weeklyScheduleBreaksGrid";
import { evaluateTaskTiming, taskTimingLabel } from "./weeklyScheduleTaskTiming";

const employeesById = {
  1: { user_id: 1, display_name: "Maria Perez" },
  2: { user_id: 2, display_name: "Francis" },
  3: { user_id: 3, display_name: "Yesenia" },
};

function shift(id, userId, start, end, extra = {}) {
  return {
    id,
    user_id: userId,
    day_of_week: 1,
    start_time: start,
    end_time: end,
    break_minutes: 0,
    role: "fold",
    roles: ["fold"],
    assignments: [{ role: "fold", full_shift: true }],
    ...extra,
  };
}

describe("task timing", () => {
  it("labels all six options and hides Anytime", () => {
    expect(taskTimingLabel({ timing_mode: "anytime" })).toBe("");
    expect(taskTimingLabel({ timing_mode: "specific_time", start_time: "08:00" })).toBe("8:00 AM");
    expect(taskTimingLabel({ timing_mode: "upon_entry" })).toBe("Upon Entry");
    expect(taskTimingLabel({ timing_mode: "before_break" })).toBe("Before Break");
    expect(taskTimingLabel({ timing_mode: "after_break" })).toBe("After Break");
    expect(taskTimingLabel({ timing_mode: "before_exit" })).toBe("Before Exit");
  });

  it("blocks a specific time outside a shift or during a break, and warns when a break is missing", () => {
    const maria = {
      name: "Maria Perez",
      shifts: [{ start_time: "08:00", end_time: "16:00", break_slots: [{ start_time: "12:00", end_time: "12:30" }] }],
    };
    const francis = { name: "Francis", shifts: [{ start_time: "10:00", end_time: "18:00", break_slots: [] }] };
    expect(evaluateTaskTiming({ timingMode: "specific_time", startTime: "08:00", members: [maria, francis] }).errors).toEqual([
      "Francis is not scheduled at 8:00 AM",
    ]);
    expect(evaluateTaskTiming({ timingMode: "specific_time", startTime: "12:15", members: [maria] }).errors[0]).toMatch(/scheduled break/);
    const beforeBreak = evaluateTaskTiming({ timingMode: "before_break", members: [maria, francis] });
    expect(beforeBreak.errors).toEqual([]);
    expect(beforeBreak.warnings.join(" ")).toMatch(/Francis has no scheduled break/);
    expect(beforeBreak.warnings.join(" ")).not.toMatch(/Maria Perez has no scheduled break/);
  });

  it("keeps relative timing attached to the current shift", () => {
    const early = evaluateTaskTiming({
      timingMode: "upon_entry",
      members: [
        { name: "Maria Perez", shifts: [{ start_time: "08:00", end_time: "16:00", break_slots: [] }] },
        { name: "Francis", shifts: [{ start_time: "09:00", end_time: "17:00", break_slots: [] }] },
      ],
    });
    expect(early.warnings.join(" ")).toMatch(/Upon Entry differs/);
    const moved = evaluateTaskTiming({
      timingMode: "upon_entry",
      members: [
        { name: "Maria Perez", shifts: [{ start_time: "07:00", end_time: "15:00", break_slots: [] }] },
        { name: "Francis", shifts: [{ start_time: "07:00", end_time: "15:00", break_slots: [] }] },
      ],
    });
    expect(moved.warnings).toEqual([]);
  });
});

describe("task assignment display", () => {
  it("shows one group assignment with both names and the timing, and a separate group of the same task", () => {
    const entries = [shift(1, 1, "08:00", "16:00"), shift(2, 2, "08:00", "16:00"), shift(3, 3, "08:00", "16:00", { break_slots: [{ start_time: "12:00", end_time: "12:30" }], break_minutes: 30 })];
    const responsibilities = [
      { id: 1, user_id: 1, user_ids: [1, 2], assignment_group_id: "g1", execution_mode: "shared", day_of_week: 1, role: "floor_cleaning", timing_mode: "specific_time", start_time: "08:00" },
      { id: 2, user_id: 2, user_ids: [1, 2], assignment_group_id: "g1", execution_mode: "shared", day_of_week: 1, role: "floor_cleaning", timing_mode: "specific_time", start_time: "08:00" },
      { id: 3, user_id: 3, user_ids: [3], day_of_week: 1, role: "floor_cleaning", timing_mode: "before_break", remarks: "Front" },
      { id: 4, user_id: 3, user_ids: [3], day_of_week: 1, role: "lint_cleaning", timing_mode: "upon_entry" },
    ];
    const days = buildHourlyCoverage(entries, { dayIndices: [1], employeesById, responsibilities });
    const shared = days[0].responsibilities.find((group) => group.namesLabel === "Francis + Maria Perez");
    expect(shared.executionLabel).toBe("Shared");
    expect(days[0].responsibilities.map((group) => `${group.label} · ${group.namesLabel}${group.timingLabel ? ` · ${group.timingLabel}` : ""}`)).toEqual([
      "Lint Cleaning · Yesenia · Upon Entry",
      "Floor Cleaning · Francis + Maria Perez · 8:00 AM",
      "Floor Cleaning · Yesenia · Before Break",
    ]);
    const grid = buildBreaksTasksGrid({ days, dayIndices: [1], shiftEntries: entries, responsibilities, employeesById });
    expect(grid.columns[0].taskCount).toBe(3);
    const maria = grid.rows.find((row) => row.name === "Maria Perez");
    expect(maria.cells[1].tasks[0].namesLabel).toBe("Francis + Maria Perez");
    expect(maria.cells[1].tasks[0].timingLabel).toBe("8:00 AM");
    expect(maria.taskCount).toBe(1);
    const tasks = gridTasksByDay(grid)[1].map((task) => `${task.label} · ${task.name}${task.timingLabel ? ` · ${task.timingLabel}` : ""}`);
    expect(tasks).toContain("Floor Cleaning · Francis + Maria Perez · 8:00 AM");
    expect(tasks.filter((line) => line.startsWith("Floor Cleaning")).length).toBe(2);
    expect(grid.rows.find((row) => row.name === "Yesenia").cells[1].tasks.map((task) => task.timingLabel)).toEqual([
      "Upon Entry",
      "Before Break",
    ]);
  });
});
