import { describe, expect, it } from "vitest";
import { reconcileChecklistAssignment, rosterReleaseNote } from "./checklistAssignment";

const items = [
  { task_code: "lint", task_name: "Dryer lint", responsibility_mode: "team", user_ids: [], dirty: false },
  { task_code: "trap", task_name: "Lint trap", responsibility_mode: "named", user_ids: [5], dirty: false },
  { task_code: "floor", task_name: "Floor", responsibility_mode: "named", user_ids: [5, 8], dirty: false },
];

describe("reconcileChecklistAssignment", () => {
  it("leaves the default and a named employee who is still assigned", () => {
    const { items: next, released } = reconcileChecklistAssignment(items, [5, 8]);
    expect(released).toEqual([]);
    expect(next).toEqual(items);
  });

  it("returns an item to any assigned employee when its only named person is removed", () => {
    const { items: next, released } = reconcileChecklistAssignment(items, [8]);
    const trap = next.find((item) => item.task_code === "trap");
    const floor = next.find((item) => item.task_code === "floor");
    expect(trap).toMatchObject({ responsibility_mode: "team", user_ids: [], dirty: true });
    expect(floor).toMatchObject({ responsibility_mode: "named", user_ids: [8], dirty: true });
    expect(next.find((item) => item.task_code === "lint").responsibility_mode).toBe("team");
    expect(released.map((row) => row.task_name)).toEqual(["Lint trap", "Floor"]);
  });

  it("does not name someone who is not on this task", () => {
    const { items: next } = reconcileChecklistAssignment(
      [{ task_code: "lint", task_name: "Dryer lint", responsibility_mode: "named", user_ids: [99] }],
      [5, 8],
    );
    expect(next[0]).toMatchObject({ responsibility_mode: "team", user_ids: [] });
  });
});

describe("rosterReleaseNote", () => {
  it("says the item is any assigned employee again", () => {
    const note = rosterReleaseNote(
      [{ task_name: "Lint trap", removed_user_ids: [5], kept_user_ids: [], mode: "team" }],
      (id) => (id === 5 ? "Maria Rivera" : ""),
    );
    expect(note).toBe("Maria Rivera was removed. Lint trap is any assigned employee again.");
  });
});
