import { describe, expect, it } from "vitest";
import {
  allTasksChecked,
  canAccessMaintenanceTaskReports,
  canManageMaintenanceTaskSettings,
  isCompletedStatus,
  mtlEmployeePageSx,
  reorderIds,
  statusLabel,
} from "./maintenanceTaskListHelpers";

describe("maintenanceTaskListHelpers", () => {
  it("labels statuses for manager summary", () => {
    expect(statusLabel("completed")).toBe("Completed");
    expect(statusLabel("submitted")).toBe("Completed");
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
