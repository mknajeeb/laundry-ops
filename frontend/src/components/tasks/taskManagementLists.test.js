import { describe, expect, it } from "vitest";
import {
  checklistSections,
  groupActivitiesByCategory,
  visibleCatalogRows,
} from "./taskManagementLists";

describe("task management lists", () => {
  const tasks = [
    { code: "lint_cleaning", name: "Dryer Lint Cleaning", active: 1 },
    { code: "custom_smoke", name: "Dryer Lint Cleaning", active: 0 },
  ];

  it("hides inactive rows until the operator asks for them", () => {
    expect(visibleCatalogRows(tasks).map((row) => row.code)).toEqual(["lint_cleaning"]);
    expect(visibleCatalogRows(tasks, { showInactive: true }).map((row) => row.code)).toEqual([
      "lint_cleaning",
      "custom_smoke",
    ]);
  });

  it("groups activity checklists by category and section without rewriting codes", () => {
    const groups = [
      {
        id: 2,
        name: "Floor & Washer",
        category_code: "intra_day",
        role_code: "agroup_floor_washer",
        items: [
          { task_code: "floor_cleaning", section_label: "Facility", required: true },
          { task_code: "washer_residue", section_label: "Machines", required: false },
        ],
      },
      { id: 9, name: "Old group", category_code: "intra_day", active: false, role_code: "agroup_old" },
    ];
    const visible = groupActivitiesByCategory(visibleCatalogRows(groups), [
      { code: "intra_day", name: "Intra-Day" },
    ]);
    expect(visible).toHaveLength(1);
    expect(visible[0].groups.map((group) => group.role_code)).toEqual(["agroup_floor_washer"]);
    expect(checklistSections(visible[0].groups[0].items).map((section) => section.label)).toEqual([
      "Facility",
      "Machines",
    ]);
  });
});
