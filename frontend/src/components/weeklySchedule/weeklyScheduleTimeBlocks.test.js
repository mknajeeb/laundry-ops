import { afterEach, describe, expect, it } from "vitest";
import {
  buildHourlyCoverage,
  coverageColumns,
  filterCoverageHours,
  hourBoundaryLabel,
  hourLabel,
} from "./weeklyScheduleTimeBlocks";
import { buildHourlyCoverageCsvRows, buildWeeklyScheduleCsvRows } from "./weeklyScheduleExport";
import {
  allocateRoleHoursByDay,
  DEFAULT_ROLE_CATALOG,
  scheduledHoursByUserDay,
  setScheduleRoleCatalog,
  summarizeScheduleHours,
  summarizeSelectedRoleHours,
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

function coverageDay(entries, options = {}) {
  return buildHourlyCoverage(entries, { dayIndices: [1], employeesById, ...options })[0];
}

function cellAt(day, hour, role) {
  return day.hours.find((row) => row.hour === hour).cells[role];
}

describe("hourly coverage", () => {
  it("intersects an assignment with each hour (2:30–4:15 → 0.5, 1, 0.25)", () => {
    const day = coverageDay([shift(1, 1, "02:30", "04:15", "sort")]);
    expect(day.hours.map((row) => row.label)).toEqual(["2–3 AM", "3–4 AM", "4–5 AM"]);
    expect(day.hours.map((row) => row.cells.sort.hours)).toEqual([0.5, 1, 0.25]);
    expect(day.hours.map((row) => row.cells.sort.cumulative)).toEqual([0.5, 1.5, 1.75]);
    expect(day.hours.map((row) => row.cells.sort.count)).toEqual([1, 1, 1]);
    const [early, full, late] = day.hours.map((row) => row.cells.sort.people[0]);
    expect(early).toMatchObject({ name: "Employee A", partial: true, rangeLabel: "2:30–3" });
    expect(full.partial).toBe(false);
    expect(late).toMatchObject({ partial: true, rangeLabel: "4–4:15" });
    expect(day.hours[1].endLabel).toBe("4 AM");
  });

  it("keeps distinct headcount separate from employee-hours and cumulative totals", () => {
    const day = coverageDay([
      shift(1, 1, "02:00", "03:00", "sort"),
      shift(2, 2, "02:30", "03:00", "sort"),
      shift(3, 3, "02:00", "05:00", "wash"),
    ]);
    expect(day.columns).toEqual(["wash", "sort"]);
    expect(cellAt(day, 2, "sort")).toMatchObject({ count: 2, hours: 1.5, cumulative: 1.5 });
    expect(cellAt(day, 2, "wash")).toMatchObject({ count: 1, hours: 1 });
    expect(day.hours[0].total).toEqual({ count: 3, hours: 2.5, cumulative: 2.5 });
    expect(cellAt(day, 3, "sort")).toMatchObject({ count: 0, hours: 0, cumulative: 1.5 });
    expect(day.hours[1].total).toEqual({ count: 1, hours: 1, cumulative: 3.5 });
    expect(day.hours[2].total.cumulative).toBe(4.5);
    expect(day.totals).toEqual({
      wash: { count: 1, hours: 3, untimedBreak: 0, unallocatedBreak: 0, net: 3 },
      sort: { count: 2, hours: 1.5, untimedBreak: 0, unallocatedBreak: 0, net: 1.5 },
    });
    expect(day.overall).toEqual({ count: 3, hours: 4.5, untimedBreak: 0, unallocatedBreak: 0, net: 4.5 });
  });

  it("splits simultaneous roles evenly but counts the employee once per hour", () => {
    const multi = shift(1, 1, "08:00", "10:00", "wash", {
      roles: ["wash", "fold"],
      assignments: [
        { role: "wash", full_shift: true },
        { role: "fold", full_shift: true },
      ],
    });
    const day = coverageDay([multi]);
    expect(cellAt(day, 8, "wash")).toMatchObject({ count: 1, hours: 0.5 });
    expect(cellAt(day, 8, "fold")).toMatchObject({ count: 1, hours: 0.5 });
    expect(cellAt(day, 8, "wash").people[0].shared).toBe(true);
    expect(day.hours[0].total).toMatchObject({ count: 1, hours: 1 });
    expect(day.overall).toMatchObject({ count: 1, hours: 2, net: 2 });
  });

  it("counts overlapping shifts for the same employee once", () => {
    const day = coverageDay([shift(1, 1, "08:00", "12:00", "sort"), shift(2, 1, "10:00", "14:00", "sort")]);
    expect(cellAt(day, 10, "sort")).toMatchObject({ count: 1, hours: 1 });
    expect(day.totals.sort).toMatchObject({ count: 1, hours: 6, net: 6 });
  });

  it("keeps overnight coverage on the start day, marked +1, without double counting", () => {
    const days = buildHourlyCoverage([shift(1, 1, "22:00", "02:00", "wash")], {
      dayIndices: [1, 2],
      employeesById,
    });
    expect(days[0].hours.map((row) => row.label)).toEqual([
      "10–11 PM",
      "11 PM–12 AM",
      "12–1 AM (+1)",
      "1–2 AM (+1)",
    ]);
    expect(days[0].totals.wash.hours).toBe(4);
    expect(days[1].hours).toEqual([]);
    expect(hourBoundaryLabel(26)).toBe("2 AM (+1)");
  });

  it("keeps earlier hours in the cumulative total when a time filter hides them", () => {
    const [day] = filterCoverageHours([coverageDay([shift(1, 1, "02:30", "04:15", "sort")])], { fromHour: 3 });
    expect(day.hours.map((row) => row.hour)).toEqual([3, 4]);
    expect(day.hours[0].cells.sort.cumulative).toBe(1.5);
    expect(day.hours[0].total.cumulative).toBe(1.5);
  });

  it("shows uncovered hours between the first and last scheduled work", () => {
    const noRole = shift(3, 2, "03:00", "04:00", "", { role: "", roles: [], assignments: [] });
    const day = coverageDay([shift(1, 1, "02:00", "03:00", "sort"), noRole, shift(2, 3, "05:00", "06:00", "sort")]);
    expect(day.hours.map((row) => row.hour)).toEqual([2, 3, 4, 5]);
    expect(day.hours.map((row) => row.gap)).toEqual([false, true, true, false]);
    expect(day.hours[1].scheduled).toBe(1);
    expect(day.hours[2].scheduled).toBe(0);
  });

  it("limits columns and totals to selected roles while splitting over all roles", () => {
    const multi = shift(1, 1, "08:00", "09:00", "wash", {
      roles: ["wash", "fold"],
      assignments: [
        { role: "wash", full_shift: true },
        { role: "fold", full_shift: true },
      ],
    });
    const day = coverageDay([multi, shift(2, 2, "08:00", "09:00", "sort")], { roles: ["wash"] });
    expect(day.columns).toEqual(["wash"]);
    expect(cellAt(day, 8, "wash").hours).toBe(0.5);
    expect(day.hours[0].total).toMatchObject({ count: 1, hours: 0.5 });
    expect(coverageDay([multi], { roles: [] }).columns).toEqual([]);
  });

  it("excludes tasks from the matrix and lists the day's tasks separately", () => {
    const legacyTask = shift(1, 3, "08:00", "10:00", "lint_cleaning");
    const responsibilities = [
      { id: 7, user_id: 2, day_of_week: 1, role: "self_service", remarks: "Open" },
      { id: 8, user_id: 1, day_of_week: 1, role: "drop_off_customer", remarks: null },
      { id: 9, user_id: 3, day_of_week: 2, role: "self_service", remarks: null },
    ];
    const day = coverageDay([legacyTask], { responsibilities, roles: ["sort"] });
    expect(day.columns).toEqual([]);
    expect(day.responsibilities.map((g) => g.role)).toEqual(["drop_off_customer", "self_service"]);
    expect(day.responsibilities[1].people[0]).toMatchObject({ name: "Employee B", remarks: "Open" });
  });

  it("orders columns by the configured role catalog", () => {
    setScheduleRoleCatalog(DEFAULT_ROLE_CATALOG.map((r) => (r.code === "sort" ? { ...r, display_order: 1 } : r)));
    const day = coverageDay([shift(1, 1, "02:00", "05:00", "wash"), shift(2, 2, "02:00", "05:00", "sort")]);
    expect(day.columns).toEqual(["sort", "wash"]);
    expect(coverageColumns([day])).toEqual(["sort", "wash"]);
  });

  it("labels hour rows across noon", () => {
    expect(hourLabel(11)).toBe("11 AM–12 PM");
    expect(hourLabel(2, "-")).toBe("2-3 AM");
  });
});

describe("summaries for selected roles", () => {
  it("keeps only selected role rows and reconciles the remaining shift time", () => {
    const byId = new Map(Object.values(employeesById).map((e) => [e.user_id, e]));
    const split = shift(1, 1, "02:00", "08:00", "sort", {
      roles: ["sort", "fold"],
      hours: 6,
      assignments: [
        { role: "sort", start_time: "02:00", end_time: "05:00", full_shift: false },
        { role: "fold", start_time: "05:00", end_time: "08:00", full_shift: false },
      ],
    });
    const other = shift(2, 2, "02:00", "04:00", "wash", { hours: 2 });
    const summary = summarizeSelectedRoleHours([split, other], byId, ["sort"]);
    expect(summary.employees.map((row) => row.user_id)).toEqual([1]);
    expect(summary.roles.map((row) => [row.role, row.hours])).toEqual([["sort", 3]]);
    expect(summary.roleTotal).toBe(3);
    // Only the selected role's hours count; the fold half of the shift is not shown or moved to sort.
    expect(summary.totalHours).toBe(3);
    expect(summary.employees).toEqual([
      { user_id: 1, name: "Employee A", hours: 3, grossHours: 3, breakHours: 0, unallocatedBreakHours: 0 },
    ]);
    expect(summary.unassignedHours).toBe(0);
    expect(summarizeSelectedRoleHours([split, other], byId, null).totalHours).toBe(8);
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

  it("exports hourly coverage with people, role hours, cumulative hours, partial times, totals, and tasks", () => {
    const days = buildHourlyCoverage([shift(1, 1, "02:00", "03:00", "sort"), shift(2, 2, "02:30", "04:00", "sort")], {
      dayIndices: [1],
      employeesById,
      responsibilities,
    });
    const lines = buildHourlyCoverageCsvRows({ days, weekStart: "2026-06-14", columns: coverageColumns(days) });
    expect(lines.slice(0, 8)).toEqual([
      "Day,Date,Hour,Role,People,Role hours,Cumulative role hours,Employees and coverage",
      "Mon,Jun 15,2-3 AM,Sort,2,1.5,1.5,Employee A; Employee B: 2:30-3",
      "Mon,Jun 15,2-3 AM,All shown roles,2,1.5,1.5,",
      "Mon,Jun 15,3-4 AM,Sort,1,1,2.5,Employee B",
      "Mon,Jun 15,3-4 AM,All shown roles,1,1,2.5,",
      "Mon,Jun 15,Day total,Sort,2,2.5,,",
      "Mon,Jun 15,Day total,All shown roles,2,2.5,,",
      'Mon,Jun 15,Task,Self Service,1,,,"Employee B: Open, then close"',
    ]);
  });

  it("appends employee and role hour summaries to the hourly export", () => {
    const days = buildHourlyCoverage([splitShift], { dayIndices: [1], employeesById });
    const summary = summarizeScheduleHours([splitShift], new Map([[1, employeesById[1]]]));
    const lines = buildHourlyCoverageCsvRows({ days, weekStart: "2026-06-14", columns: coverageColumns(days), hoursSummary: summary });
    expect(lines).toContain("Mon,Jun 15,5-6 AM,Fold,1,1,1,Employee A");
    expect(lines).toContain("Employee A,6,6,0");
    expect(lines).toContain("Total (1 employees),6,6,0");
    expect(lines).toContain("Sort,1,3,Net");
    expect(lines).toContain("Total net hours,1,6,Net");
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
      { user_id: 2, name: "Employee B", hours: 8, grossHours: 8, breakHours: 0, unallocatedBreakHours: 0 },
      { user_id: 1, name: "Employee A", hours: 3.5, grossHours: 4, breakHours: 0.5, unallocatedBreakHours: 0 },
    ]);
    expect(summary.totalHours).toBe(11.5);
    expect(summary.grossHours).toBe(12);
    expect(summary.unscheduledBreakHours).toBe(0.5);
    const roles = Object.fromEntries(summary.roles.map((r) => [r.role, r]));
    // The 30-minute break has no time on a wash+fold shift, so it is not allocated to either role: both stay
    // gross of it and it is reported once as an unallocated deduction. Employee A's net hours still include it.
    expect(roles.wash).toMatchObject({ hours: 2, employees: 1, unallocatedBreakHours: 0.5 });
    expect(roles.fold).toMatchObject({ hours: 2, employees: 1, unallocatedBreakHours: 0.5 });
    expect(summary.roleUnallocatedBreakHours).toBe(0.5);
    expect(summary.roleTotal + summary.unassignedHours - summary.roleUnallocatedBreakHours).toBe(summary.totalHours);
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

describe("shifts kept without a production role", () => {
  const noRole = shift(1, 1, "09:00", "16:00", "fold", { role: "", roles: [], assignments: [], hours: 6.5, break_minutes: 30 });

  it("keeps hours, counts no role, and shows the hours as uncovered in the hourly view", () => {
    const summary = summarizeScheduleHours([noRole], new Map([[1, employeesById[1]]]));
    expect(summary.totalHours).toBe(6.5);
    expect(summary.roles).toEqual([]);
    expect(summary.unassignedHours).toBe(6.5);
    expect(summary.unscheduledBreakHours).toBe(0.5);
    const day = coverageDay([noRole]);
    expect(day.columns).toEqual([]);
    expect(day.hours).toHaveLength(7);
    expect(day.hours.every((row) => row.gap && row.scheduled === 1)).toBe(true);
  });

  it("labels the shift No role in the employee export", () => {
    const lines = buildWeeklyScheduleCsvRows({
      employees: [employeesById[1]],
      entries: [noRole],
      dayIndices: [1],
      dayLabels: ["Mon"],
      daySummaries: [],
    });
    expect(lines[1]).toContain("9:00 AM - 4:00 PM");
    expect(lines[1]).toContain("No role");
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
