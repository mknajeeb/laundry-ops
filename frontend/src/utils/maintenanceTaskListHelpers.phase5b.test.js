import { describe, expect, it } from "vitest";
import {
  copyWeekdayAssigneeToAll,
  formatDateLong,
  formatDateWeekdayShort,
  groupTasksByCategory,
} from "../utils/maintenanceTaskListHelpers";

describe("groupTasksByCategory", () => {
  it("groups by category_snapshot and keeps order", () => {
    const groups = groupTasksByCategory([
      { id: 1, category_snapshot: "Closing", task_name_snapshot: "A" },
      { id: 2, category_snapshot: "Opening", task_name_snapshot: "B" },
      { id: 3, category_snapshot: "Closing", task_name_snapshot: "C" },
    ]);
    expect(groups.map((g) => g.category)).toEqual(["Closing", "Opening"]);
    expect(groups[0].items.map((i) => i.id)).toEqual([1, 3]);
  });
});

describe("formatDateLong", () => {
  it("formats for submitted confirmation", () => {
    expect(formatDateLong("2026-07-24")).toContain("July");
    expect(formatDateLong("2026-07-24")).toContain("24");
  });
});

describe("formatDateWeekdayShort", () => {
  it("formats manager collapsed row date", () => {
    const s = formatDateWeekdayShort("2026-07-24");
    expect(s).toContain("Jul");
    expect(s).toContain("24");
  });
});

describe("copyWeekdayAssigneeToAll", () => {
  it("copies Monday employee to every day", () => {
    const rows = [
      { weekday: 6, label: "Sunday", employee_id: null },
      { weekday: 0, label: "Monday", employee_id: 42 },
      { weekday: 1, label: "Tuesday", employee_id: 7 },
      { weekday: 2, label: "Wednesday", employee_id: null },
      { weekday: 3, label: "Thursday", employee_id: 9 },
      { weekday: 4, label: "Friday", employee_id: null },
      { weekday: 5, label: "Saturday", employee_id: 1 },
    ];
    const next = copyWeekdayAssigneeToAll(rows, 0);
    expect(next.every((r) => r.employee_id === 42)).toBe(true);
    expect(next[1].label).toBe("Monday");
  });
});
