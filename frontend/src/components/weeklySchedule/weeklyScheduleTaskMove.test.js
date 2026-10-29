import { describe, expect, it } from "vitest";
import { isSharedAssignment, parseTaskDrag, reorderIds, taskDragPayload, unscheduledNames } from "./weeklyScheduleTaskMove";

describe("task assignment moves", () => {
  it("treats a two-person shared group as one drag", () => {
    const item = { id: 4, user_id: 1, user_ids: [1, 2], day_of_week: 1, execution_mode: "shared" };
    expect(isSharedAssignment(item)).toBe(true);
    expect(parseTaskDrag(taskDragPayload(item))).toMatchObject({ id: 4, shared: true });
  });

  it("does not mark an individual task as shared", () => {
    expect(isSharedAssignment({ id: 1, user_ids: [1, 2], execution_mode: "individual" })).toBe(false);
  });

  it("reorders a card in front of another card", () => {
    expect(reorderIds([10, 11, 12], 12, 10)).toEqual([12, 10, 11]);
  });

  it("names employees who have no shift on the target day", () => {
    const entries = [{ user_id: 1, day_of_week: 2 }];
    expect(unscheduledNames(entries, [1, 2], 2, (id) => (id === 2 ? "Yesenia" : "Francis"))).toEqual(["Yesenia"]);
  });
});
