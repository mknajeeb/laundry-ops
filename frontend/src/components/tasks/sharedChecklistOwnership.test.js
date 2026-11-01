import { groupChecklistSections, isMyChecklistItem, splitSharedChecklist } from "./sharedChecklistOwnership";

const team = { task_code: "a", required: true, responsibility_mode: "team", status: "pending" };
const mine = {
  task_code: "b",
  required: true,
  responsibility_mode: "named",
  responsibility_user_ids: [7, 8],
  status: "completed",
};
const theirs = {
  task_code: "c",
  required: false,
  responsibility_mode: "named",
  responsibility_user_ids: [9],
  status: "pending",
};

describe("splitSharedChecklist", () => {
  it("puts Anyone on Team and my named items first, once each", () => {
    const split = splitSharedChecklist([team, mine, theirs], 7);
    expect(split.myItems.map((item) => item.task_code)).toEqual(["a", "b"]);
    expect(split.otherItems.map((item) => item.task_code)).toEqual(["c"]);
    expect(split.requiredDone).toBe(1);
    expect(split.requiredTotal).toBe(2);
    expect(isMyChecklistItem(team, 3)).toBe(true);
    expect(isMyChecklistItem(theirs, 7)).toBe(false);
  });

  it("groups items by section and counts progress", () => {
    const sections = groupChecklistSections([
      { task_code: "a", section_label: "Machines", section_order: 10, status: "completed" },
      { task_code: "b", section_label: "Machines", section_order: 10, status: "pending" },
      { task_code: "c", section_label: "Facility Cleaning", section_order: 20, status: "completed" },
    ]);
    expect(sections.map((section) => [section.label, section.done, section.total])).toEqual([
      ["Machines", 1, 2],
      ["Facility Cleaning", 1, 1],
    ]);
  });
});
