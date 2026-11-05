import {
  checklistSummary,
  employeeCheckSummary,
  groupChecklistSections,
  isMyChecklistItem,
  responsibilityLabel,
  splitSharedChecklist,
  visibleSectionLabel,
} from "./sharedChecklistOwnership";

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

describe("checklistSummary", () => {
  it("shows required items instead of an empty checklist", () => {
    expect(
      checklistSummary({
        activity_group_items: [
          { task_code: "washer", required: true },
          { task_code: "floor", required: true },
        ],
      }),
    ).toEqual({ required: 2, done: 0 });
  });

  it("counts an item waiting for verification as checked", () => {
    expect(
      checklistSummary({
        shared_checklist_items: [
          { task_code: "floor", required: true, status: "pending_approval", employee_checks: [] },
        ],
      }),
    ).toEqual({ required: 1, done: 1 });
  });

  it("lets an excused employee leave the remaining acknowledgment in place", () => {
    expect(
      checklistSummary({
        shared_checklist_items: [
          {
            task_code: "floor",
            required: true,
            status: "pending",
            employee_checks: [
              { user_id: 1, status: "completed" },
              { user_id: 2, status: "excused" },
            ],
          },
        ],
      }),
    ).toEqual({ required: 1, done: 1 });
  });

  it("does not treat one employee's check as the whole item", () => {
    expect(
      checklistSummary({
        shared_checklist_items: [
          {
            task_code: "washer",
            required: true,
            status: "pending",
            employee_checks: [
              { status: "completed" },
              { status: "pending" },
            ],
          },
        ],
      }),
    ).toEqual({ required: 1, done: 0 });
  });
});

describe("employeeCheckSummary", () => {
  it("keeps each assigned employee's check-off separate", () => {
    const lines = employeeCheckSummary([
      { user_id: 23, employee_name: "Tarannum", status: "completed", completed_at: "2026-11-04 09:15:00" },
      { user_id: 36, employee_name: "Amna", status: "pending" },
    ]);
    expect(lines).toEqual([
      { userId: 23, name: "Tarannum", status: "completed", done: true, completedAt: "2026-11-04 09:15:00" },
      { userId: 36, name: "Amna", status: "pending", done: false, completedAt: null },
    ]);
  });
});

describe("splitSharedChecklist", () => {
  it("puts Anyone on Team and my named items first, once each", () => {
    const split = splitSharedChecklist([team, mine, theirs], 7);
    expect(split.myItems.map((item) => item.task_code)).toEqual(["a", "b"]);
    expect(split.otherItems.map((item) => item.task_code)).toEqual(["c"]);
    expect(split.requiredDone).toBe(1);
    expect(split.requiredTotal).toBe(2);
    expect(isMyChecklistItem(team, 3)).toBe(true);
    expect(responsibilityLabel(team)).toBe("Any assigned employee");
    expect(responsibilityLabel({ responsibility_label: "Anyone on Team" })).toBe("Any assigned employee");
    expect(visibleSectionLabel("General", 1)).toBe("");
    expect(visibleSectionLabel("Section 1", 2)).toBe("");
    expect(visibleSectionLabel("Dryer Cleaning", 2)).toBe("Dryer Cleaning");
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
