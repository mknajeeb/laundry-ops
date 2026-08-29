import { describe, expect, it } from "vitest";
import {
  ENTITY_TAB,
  addableEmployeesForEntityTab,
  filterEmployeesByEntityTab,
} from "./weeklyScheduleEmployerTabs";

const employees = [
  {
    user_id: 1,
    display_name: "Shared Empty",
    business_entity: "shared",
    can_work_rinse: true,
    can_work_drop_off: true,
    can_work_both: true,
  },
  {
    user_id: 2,
    display_name: "VeeWash Scheduled",
    business_entity: "veewash",
    can_work_rinse: false,
    can_work_drop_off: true,
    can_work_both: false,
  },
  {
    user_id: 3,
    display_name: "None Worker",
    business_entity: "none",
    can_work_rinse: false,
    can_work_drop_off: false,
    can_work_both: false,
  },
];

const entries = [{ user_id: 2, employer_affiliation: "veewash", day_of_week: 1 }];

describe("weeklyScheduleEmployerTabs visibility", () => {
  it("excludes affiliation none from entity tabs", () => {
    const visible = filterEmployeesByEntityTab(
      employees,
      ENTITY_TAB.VEEWASH,
      entries,
      "veewash",
    );
    expect(visible.map((e) => e.user_id)).toEqual([2]);
  });

  it("does not show shared worker with zero shifts as empty row", () => {
    const visible = filterEmployeesByEntityTab(
      employees,
      ENTITY_TAB.VEEWASH,
      entries,
      "veewash",
    );
    expect(visible.some((e) => e.user_id === 1)).toBe(false);
  });

  it("puts zero-shift affiliated workers in addable selector", () => {
    const addable = addableEmployeesForEntityTab(
      employees,
      ENTITY_TAB.VEEWASH,
      entries,
      "veewash",
    );
    expect(addable.map((e) => e.user_id)).toEqual([1]);
    expect(addable.some((e) => e.user_id === 3)).toBe(false);
  });
});
