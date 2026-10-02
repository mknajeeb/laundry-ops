import { afterEach, describe, expect, it } from "vitest";
import { buildTimeRoleDays } from "./weeklyScheduleTimeBlocks";
import { buildTimeRoleCsvRows, buildWeeklyScheduleCsvRows } from "./weeklyScheduleExport";
import {
  allocateRoleHoursByDay,
  DEFAULT_ROLE_CATALOG,
  scheduledHoursByUserDay,
  setScheduleRoleCatalog,
  summarizeScheduleHours,
} from "./weeklyScheduleRoles";
import { buildDayViewTabs, filterResponsibilitiesByRoleView } from "./weeklyScheduleViewFilters";
import {
  defaultNewShiftEntity,
  pickDefaultEntityTab,
  shiftEntityChoicesForEmployee,
} from "./weeklyScheduleEmployerTabs";

const employeesById = {
  1: { user_id: 1, display_name: "Employee A" },
  2: { user_id: 2, display_name: "Employee B" },
  3: { user_id: 3, display_name: "Employee C" },
  4: { user_id: 4, display_name: "Employee D" },
  5: { user_id: 5, display_name: "Employee E" },
};

function shift(id, userId, start, end, role, extra = {}) {
  return {
    id,
    user_id: userId,
    day_of_week: 1,
    start_time: start,
    end_time: end,
    break_minutes: 0,
    role,
    roles: [role],
    ...extra,
  };
}

afterEach(() => setScheduleRoleCatalog(null));

describe("day filter counts", () => {
  const responsibilities = [
    { id: 1, user_id: 4, day_of_week: 3, role: "self_service" },
    { id: 2, user_id: 2, day_of_week: 1, role: "drop_off_customer" },
  ];

  it("counts daily responsibilities so a day with only untimed work is not zero", () => {
    const tabs = buildDayViewTabs([shift(1, 1, "09:00", "12:00", "fold")], { compact: true, responsibilities });
    const count = (label) => tabs.find((tab) => tab.label === label).count;
    expect(count("All")).toBe(3);
    expect(count("Mo")).toBe(2);
    expect(count("We")).toBe(1);
    expect(count("Tu")).toBe(0);
  });

  it("applies the role filter to responsibilities", () => {
    expect(filterResponsibilitiesByRoleView(responsibilities, ["self_service"]).map((r) => r.id)).toEqual([1]);
    expect(filterResponsibilitiesByRoleView(responsibilities, ["fold"])).toEqual([]);
    expect(filterResponsibilitiesByRoleView(responsibilities, [])).toHaveLength(2);
  });
});

describe("buildTimeRoleDays", () => {
  it("groups by exact time range, chronologically, then roles in catalog order", () => {
    const entries = [
      shift(1, 4, "05:00", "08:00", "fold"),
      shift(2, 1, "02:00", "05:00", "sort"),
      shift(3, 3, "02:00", "05:00", "wash"),
      shift(4, 2, "02:00", "05:00", "sort"),
      shift(5, 5, "05:00", "08:00", "fold"),
    ];
    const [day] = buildTimeRoleDays(entries, { dayIndices: [1], employeesById });
    expect(day.blocks.map((b) => `${b.start_time}-${b.end_time}`)).toEqual(["02:00-05:00", "05:00-08:00"]);
    expect(day.blocks[0].roles.map((r) => r.role)).toEqual(["wash", "sort"]);
    expect(day.blocks[0].roles[1].people.map((p) => p.name)).toEqual(["Employee A", "Employee B"]);
    expect(day.blocks[0].roles[1].count).toBe(2);
    expect(day.blocks[1].roles[0].count).toBe(2);
  });

  it("honours a reordered role catalog", () => {
    setScheduleRoleCatalog(
      DEFAULT_ROLE_CATALOG.map((r) => (r.code === "sort" ? { ...r, display_order: 1 } : r)),
    );
    const entries = [shift(1, 1, "02:00", "05:00", "wash"), shift(2, 2, "02:00", "05:00", "sort")];
    const [day] = buildTimeRoleDays(entries, { dayIndices: [1], employeesById });
    expect(day.blocks[0].roles.map((r) => r.role)).toEqual(["sort", "wash"]);
  });

  it("keeps overlapping but different ranges as separate blocks", () => {
    const entries = [shift(1, 1, "02:00", "06:00", "sort"), shift(2, 2, "03:00", "06:00", "sort")];
    const [day] = buildTimeRoleDays(entries, { dayIndices: [1], employeesById });
    expect(day.blocks).toHaveLength(2);
  });

  it("places a mid-shift role change in each assignment's own block with remarks", () => {
    const entry = shift(1, 1, "02:00", "08:00", "sort", {
      roles: ["sort", "fold"],
      assignments: [
        { role: "sort", start_time: "02:00", end_time: "05:00", full_shift: false, remarks: null },
        { role: "fold", start_time: "05:00", end_time: "08:00", full_shift: false, remarks: "Bay 2" },
      ],
    });
    const [day] = buildTimeRoleDays([entry], { dayIndices: [1], employeesById });
    expect(day.blocks.map((b) => b.key)).toEqual(["02:00|05:00", "05:00|08:00"]);
    const fold = day.blocks[1].roles[0];
    expect(fold.role).toBe("fold");
    expect(fold.people[0]).toMatchObject({ name: "Employee A", remarks: "Bay 2", fullShift: false });
  });

  it("sorts an overnight block after the earlier same-start block", () => {
    const entries = [shift(1, 1, "22:00", "06:00", "wash"), shift(2, 2, "22:00", "23:00", "wash")];
    const [day] = buildTimeRoleDays(entries, { dayIndices: [1], employeesById });
    expect(day.blocks.map((b) => b.end_time)).toEqual(["23:00", "06:00"]);
  });

  it("lists daily responsibilities separately, grouped by role", () => {
    const responsibilities = [
      { id: 7, user_id: 2, day_of_week: 1, role: "self_service", remarks: "Open" },
      { id: 8, user_id: 1, day_of_week: 1, role: "drop_off_customer", remarks: null },
      { id: 9, user_id: 3, day_of_week: 2, role: "self_service", remarks: null },
    ];
    const [day] = buildTimeRoleDays([], { dayIndices: [1], employeesById, responsibilities });
    expect(day.blocks).toEqual([]);
    expect(day.responsibilities.map((g) => g.role)).toEqual(["drop_off_customer", "self_service"]);
    expect(day.responsibilities[1].people[0]).toMatchObject({ name: "Employee B", remarks: "Open" });
  });
});

describe("scheduled hours with role assignments", () => {
  it("counts a shift once regardless of how many role ranges it holds", () => {
    const entry = shift(1, 1, "02:00", "08:00", "sort", {
      roles: ["sort", "wash"],
      hours: 6,
      assignments: [
        { role: "sort", start_time: "02:00", end_time: "05:00", full_shift: false },
        { role: "wash", start_time: "05:00", end_time: "08:00", full_shift: false },
      ],
    });
    expect(scheduledHoursByUserDay([entry]).get("1|1")).toBe(6);
    const day = allocateRoleHoursByDay([entry])[1];
    expect(day.sort).toBeCloseTo(3);
    expect(day.wash).toBeCloseTo(3);
  });

  it("de-duplicates overlapping shifts for the same employee and day", () => {
    const a = shift(1, 1, "08:00", "14:00", "fold", { hours: 5.5, break_minutes: 30 });
    const b = shift(2, 1, "12:00", "16:00", "fold", { hours: 4 });
    expect(scheduledHoursByUserDay([a, b]).get("1|1")).toBeCloseTo(7.5);
  });

  it("keeps each break for separate and touching shifts", () => {
    const morning = shift(1, 1, "06:00", "10:00", "fold", { hours: 3.75, break_minutes: 15 });
    const evening = shift(2, 1, "14:00", "20:00", "fold", { hours: 5.5, break_minutes: 30 });
    const touching = shift(3, 1, "10:00", "14:00", "fold", { hours: 3.75, break_minutes: 15, day_of_week: 2 });
    const before = shift(4, 1, "06:00", "10:00", "fold", { hours: 3.75, break_minutes: 15, day_of_week: 2 });
    const hours = scheduledHoursByUserDay([morning, evening, touching, before]);
    expect(hours.get("1|1")).toBeCloseTo(9.25);
    expect(hours.get("1|2")).toBeCloseTo(7.5);
  });

  it("handles overnight shifts", () => {
    const overnight = shift(1, 1, "22:00", "06:00", "fold", { hours: 7.5, break_minutes: 30 });
    const inside = shift(2, 1, "23:00", "03:00", "sort", { hours: 4 });
    const early = shift(3, 1, "02:00", "06:00", "fold", { hours: 4, day_of_week: 2 });
    const late = shift(4, 1, "22:00", "06:00", "fold", { hours: 7.5, break_minutes: 30, day_of_week: 2 });
    const hours = scheduledHoursByUserDay([overnight, inside, early, late]);
    expect(hours.get("1|1")).toBeCloseTo(7.5);
    expect(hours.get("1|2")).toBeCloseTo(11.5);
  });
});

describe("schedule exports", () => {
  const splitShift = shift(1, 1, "02:00", "08:00", "sort", {
    roles: ["sort", "fold"],
    hours: 6,
    assignments: [
      { role: "sort", start_time: "02:00", end_time: "05:00", full_shift: false, remarks: null },
      { role: "fold", start_time: "05:00", end_time: "08:00", full_shift: false, remarks: "Bay 2" },
    ],
  });
  const responsibilities = [{ id: 7, user_id: 2, day_of_week: 1, role: "self_service", remarks: "Open, then close" }];

  it("exports the time-and-role view with blocks, roles, people, remarks, and daily responsibilities", () => {
    const days = buildTimeRoleDays([splitShift, shift(2, 3, "02:00", "05:00", "sort")], {
      dayIndices: [1],
      employeesById,
      responsibilities,
    });
    const lines = buildTimeRoleCsvRows({ days, weekStart: "2026-06-14" });
    expect(lines).toEqual([
      "Day,Date,Time,Role,Count,Employees,Remarks",
      'Mon,Jun 15,2:00 AM - 5:00 AM,Sort,2,"Employee A, Employee C",',
      "Mon,Jun 15,5:00 AM - 8:00 AM,Fold,1,Employee A,Employee A: Bay 2",
      'Mon,Jun 15,Task,Self Service,1,Employee B,"Employee B: Open, then close"',
    ]);
  });

  it("appends employee and role hour summaries to the time-and-role export", () => {
    const days = buildTimeRoleDays([splitShift], { dayIndices: [1], employeesById });
    const summary = summarizeScheduleHours([splitShift], new Map([[1, employeesById[1]]]));
    const lines = buildTimeRoleCsvRows({ days, weekStart: "2026-06-14", hoursSummary: summary });
    expect(lines).toContain("Employee A,6");
    expect(lines).toContain("Total (1 employees),6");
    expect(lines).toContain("Sort,1,3");
    expect(lines).toContain("Total role hours,,6");
  });

  it("adds role ranges, remarks, and tasks to the employee export", () => {
    const lines = buildWeeklyScheduleCsvRows({
      employees: [employeesById[1], employeesById[2]],
      entries: [splitShift],
      dayIndices: [1],
      dayLabels: ["Mon"],
      daySummaries: [],
      responsibilities,
    });
    expect(lines[1]).toContain("[Sort 2:00 AM - 5:00 AM | Fold 5:00 AM - 8:00 AM: Bay 2]");
    expect(lines[2]).toContain("Self Service (task): Open, then close");
  });
});

describe("hours summaries above the time-and-role view", () => {
  const byId = new Map(Object.values(employeesById).map((e) => [e.user_id, e]));

  it("totals employee hours with breaks and overlap, and splits simultaneous roles evenly", () => {
    const multi = shift(1, 1, "08:00", "12:00", "wash", {
      roles: ["wash", "fold"],
      hours: 3.5,
      break_minutes: 30,
      assignments: [
        { role: "wash", full_shift: true },
        { role: "fold", full_shift: true },
      ],
    });
    const overlap = shift(2, 2, "08:00", "14:00", "sort", { hours: 6 });
    const overlap2 = shift(3, 2, "12:00", "16:00", "sort", { hours: 4 });
    const summary = summarizeScheduleHours([multi, overlap, overlap2], byId);
    expect(summary.employees).toEqual([
      { user_id: 2, name: "Employee B", hours: 8 },
      { user_id: 1, name: "Employee A", hours: 3.5 },
    ]);
    expect(summary.totalHours).toBe(11.5);
    const roles = Object.fromEntries(summary.roles.map((r) => [r.role, r]));
    expect(roles.wash).toMatchObject({ hours: 1.75, employees: 1 });
    expect(roles.fold).toMatchObject({ hours: 1.75, employees: 1 });
    expect(roles.sort.employees).toBe(1);
    expect(summary.roles.map((r) => r.role)).toEqual(["wash", "sort", "fold"]);
  });

  it("reports shift time without a role and excludes tasks", () => {
    const partial = shift(1, 1, "08:00", "12:00", "dry", {
      hours: 4,
      assignments: [{ role: "dry", start_time: "08:00", end_time: "10:00", full_shift: false }],
    });
    const legacyTask = shift(2, 3, "08:00", "10:00", "lint_cleaning", { hours: 2 });
    const summary = summarizeScheduleHours([partial, legacyTask], byId);
    expect(summary.roles.map((r) => r.role)).toEqual(["dry"]);
    expect(summary.roles[0].hours).toBe(2);
    expect(summary.unassignedHours).toBe(4);
  });
});

describe("new shift category", () => {
  it("defaults to Rinse Exclusive when the employee may hold it", () => {
    const shared = { user_id: 1, can_work_rinse: true, can_work_drop_off: true, can_work_both: true };
    const veewashOnly = { user_id: 2, business_entity: "veewash" };
    expect(shiftEntityChoicesForEmployee(shared, "veewash")).toEqual(["rinse_exclusive", "veewash"]);
    expect(defaultNewShiftEntity(shared, "veewash")).toBe("rinse_exclusive");
    expect(defaultNewShiftEntity(veewashOnly, "veewash")).toBe("veewash");
    expect(pickDefaultEntityTab({ organization_slug: "veewash" })).toBe("rinse_exclusive");
  });
});
