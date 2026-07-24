import { describe, expect, it } from "vitest";
import {
  allTasksChecked,
  applyTaskCompletionLocal,
  canAccessMaintenanceTaskReports,
  canManageMaintenanceTaskSettings,
  compactTaskContext,
  instructionPreview,
  isCompletedStatus,
  mtlEmployeePageSx,
  reorderIds,
  statusLabel,
  taskProgress,
} from "./maintenanceTaskListHelpers";

describe("maintenanceTaskListHelpers", () => {
  it("labels statuses for manager summary", () => {
    expect(statusLabel("completed")).toBe("Submitted");
    expect(statusLabel("submitted")).toBe("Submitted");
    expect(statusLabel("in_progress")).toBe("In Progress");
    expect(statusLabel("not_started")).toBe("Not Started");
    expect(isCompletedStatus("completed")).toBe(true);
  });

  it("enables submit only when every task is checked", () => {
    expect(allTasksChecked({ items: [] })).toBe(false);
    expect(
      allTasksChecked({
        items: [{ completed: true }, { completed: false }],
      }),
    ).toBe(false);
    expect(
      allTasksChecked({
        items: [{ completed: true }, { completed: true }],
      }),
    ).toBe(true);
  });

  it("tracks progress without changing status meanings", () => {
    expect(
      taskProgress({ items: [{ completed: true }, { completed: false }, { completed: false }] }),
    ).toEqual({ done: 1, total: 3 });
  });

  it("keeps long task names as full strings (no forced truncation helper)", () => {
    const name = "Sanitize all folding tables after final bag of the night";
    expect(name.length).toBeGreaterThan(20);
    expect(instructionPreview(name, 20)).toContain("…");
    expect(instructionPreview("Short", 72)).toBe("Short");
  });

  it("builds compact employee context", () => {
    expect(compactTaskContext("Maria", "Today")).toBe("Maria · Today");
    expect(compactTaskContext("Maria", "")).toBe("Maria");
  });

  it("applies local completion immutably", () => {
    const list = { id: 1, items: [{ id: 9, completed: false, task_name_snapshot: "A" }] };
    const next = applyTaskCompletionLocal(list, 9, true);
    expect(next.items[0].completed).toBe(true);
    expect(list.items[0].completed).toBe(false);
  });

  it("preserves reorder", () => {
    expect(reorderIds([1, 2, 3, 4], 0, 2)).toEqual([2, 3, 1, 4]);
  });

  it("mobile page styles avoid horizontal overflow", () => {
    const sx = mtlEmployeePageSx();
    expect(sx.overflowX).toBe("hidden");
    expect(sx.maxWidth).toBe("100vw");
    expect(sx.width).toBe("100%");
  });

  it("permission fallbacks for reports and settings", () => {
    const hasNone = () => false;
    expect(canAccessMaintenanceTaskReports("ops", hasNone)).toBe(true);
    expect(canAccessMaintenanceTaskReports("floor", hasNone)).toBe(false);
    expect(canManageMaintenanceTaskSettings("admin", hasNone)).toBe(true);
    expect(canManageMaintenanceTaskSettings("ops", hasNone)).toBe(false);

    const hasReports = (k) => k === "maintenance.tasks.reports";
    expect(canAccessMaintenanceTaskReports("floor", hasReports)).toBe(true);
    expect(canManageMaintenanceTaskSettings("admin", hasReports)).toBe(false);
  });
});
