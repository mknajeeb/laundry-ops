import { afterEach, describe, expect, it } from "vitest";
import { buildHourlyCoverage, filterCoverageHours } from "./weeklyScheduleTimeBlocks";
import { buildHourlyCoverageCsvRows, buildWeeklyScheduleCsvRows } from "./weeklyScheduleExport";
import {
  computeFilteredDaySummaries,
  computeWeekSummary,
  employeeTotalsFromEntries,
  entryRoleScopeView,
  scheduleEntryKey,
  setScheduleRoleCatalog,
  summarizeRoleSelection,
  summarizeSelectedRoleHours,
  withDisplayedTotals,
} from "./weeklyScheduleRoles";
import { buildDayViewTabs, buildRoleViewTabs, filterEntriesByRoles } from "./weeklyScheduleViewFilters";

const employees = [1, 2, 3, 4, 5].map((id) => ({
  user_id: id,
  display_name: `Employee ${"ABCDE"[id - 1]}`,
  default_hourly_rate: 10,
}));
const employeesById = Object.fromEntries(employees.map((e) => [e.user_id, e]));
const byIdMap = new Map(employees.map((e) => [e.user_id, e]));

function shift(id, userId, start, end, roles, extra = {}) {
  const list = Array.isArray(roles) ? roles : [roles];
  return {
    id,
    user_id: userId,
    day_of_week: 1,
    start_time: start,
    end_time: end,
    break_minutes: 0,
    role: list.join(","),
    roles: list,
    assignments: list.map((role) => ({ role, full_shift: true })),
    ...extra,
  };
}

// A: fold all day with a timed lunch → 7.5 fold.
const a = shift(11, 1, "08:00", "16:00", "fold", { break_minutes: 30, break_slots: [{ start_time: "12:00", end_time: "12:30" }] });
// B: wash and fold at the same time → 2 wash + 2 fold.
const b = shift(21, 2, "08:00", "12:00", ["wash", "fold"]);
// C: a wash shift overlapping a separate fold shift → wash 6 + 1, fold 1 + 2.
const c1 = shift(31, 3, "06:00", "14:00", "wash");
const c2 = shift(32, 3, "12:00", "16:00", "fold");
// D: overnight sort with a break without a time → 7.5 sort.
const d = shift(41, 4, "22:00", "06:00", "sort", { break_minutes: 30 });
// E: fold then sort in one shift with a 30-minute break without a time → 1.75 each.
const e = shift(51, 5, "09:00", "13:00", ["fold", "sort"], {
  break_minutes: 30,
  assignments: [
    { role: "fold", start_time: "09:00", end_time: "11:00", full_shift: false },
    { role: "sort", start_time: "11:00", end_time: "13:00", full_shift: false },
  ],
});
const entries = [a, b, c1, c2, d, e];
const data = { entries, employees };

const rows = (summary) => Object.fromEntries(summary.roles.map((row) => [row.role, [row.employees, row.hours]]));

afterEach(() => setScheduleRoleCatalog(null));

describe("selecting one role", () => {
  it("shows only that role's employees, people, and net hours in every total", () => {
    const week = computeWeekSummary(data, { roles: ["fold"] });
    expect(week).toMatchObject({ employeesScheduled: 4, totalHours: 14.25, roleFilter: ["fold"] });
    expect(rows(week)).toEqual({ fold: [4, 14.25] });

    const day = computeFilteredDaySummaries(data, { roles: ["fold"] })[1];
    expect(day).toMatchObject({ people: 4, hours: 14.25 });
    expect(rows(day)).toEqual({ fold: [4, 14.25] });

    const totals = employeeTotalsFromEntries(entries, employees, { roles: ["fold"] });
    expect([...totals.keys()].sort()).toEqual([1, 2, 3, 5]);
    expect(totals.get(1)).toMatchObject({ total_hours: 7.5, gross_hours: 8, break_hours: 0.5, scheduled_days: 1 });
    expect(totals.get(2)).toMatchObject({ total_hours: 2, estimated_cost: 20 });
    expect(totals.get(3)).toMatchObject({ total_hours: 3 });
    expect(totals.get(5)).toMatchObject({ total_hours: 1.75, gross_hours: 2, break_hours: 0.25 });
    expect(totals.get(3).role_hours).toEqual([{ role: "fold", label: "Fold", hours: 3, days: 1 }]);

    const summary = summarizeSelectedRoleHours(entries, byIdMap, ["fold"]);
    expect(summary).toMatchObject({ totalHours: 14.25, roleTotal: 14.25, distinctEmployees: 4, unassignedHours: 0 });
  });

  it("limits the hourly matrix to that role and those employees", () => {
    const day = buildHourlyCoverage(entries, { dayIndices: [1], employeesById, roles: ["fold"] })[0];
    expect(day.columns).toEqual(["fold"]);
    // D holds no fold, so the overnight sort shift adds no rows.
    expect(day.hours.map((row) => row.hour)).toEqual([6, 7, 8, 9, 10, 11, 12, 13, 14, 15]);
    expect(day.hours[0]).toMatchObject({ gap: true, scheduled: 1 });
    expect(day.totals.fold).toEqual({ count: 4, hours: 14.5, untimedBreak: 0.25, net: 14.25 });
    expect(day.overall).toMatchObject({ count: 4, hours: 14.5, net: 14.25 });
    expect(day.hours.every((row) => Object.keys(row.cells).join() === "fold")).toBe(true);
  });
});

describe("selecting several roles", () => {
  it("counts an employee holding both selected roles once overall and once per role", () => {
    const week = computeWeekSummary(data, { roles: ["wash", "fold"] });
    expect(rows(week)).toEqual({ wash: [2, 9], fold: [4, 14.25] });
    expect(week).toMatchObject({ employeesScheduled: 4, totalHours: 23.25 });
    const totals = employeeTotalsFromEntries(entries, employees, { roles: ["wash", "fold"] });
    expect(totals.get(2)).toMatchObject({ total_hours: 4 });
    expect(totals.get(3)).toMatchObject({ total_hours: 10 });
    expect(totals.has(4)).toBe(false);
  });
});

describe("hiding a simultaneous role", () => {
  it("keeps the split computed over every role instead of moving the hidden share", () => {
    expect(rows(computeWeekSummary({ entries: [b], employees }, { roles: ["fold"] }))).toEqual({ fold: [1, 2] });
    // Overlapping separate shifts: the wash shift still takes its half of 12–2.
    expect(rows(computeWeekSummary({ entries: [c1, c2], employees }, { roles: ["fold"] }))).toEqual({ fold: [1, 3] });
    const day = buildHourlyCoverage([b, c1, c2], { dayIndices: [1], employeesById, roles: ["fold"] })[0];
    expect(day.hours.find((row) => row.hour === 12).cells.fold).toMatchObject({ count: 1, hours: 0.5 });
    expect(day.totals.fold.net).toBe(5);
  });
});

describe("breaks under a role selection", () => {
  it("removes timed breaks and shares breaks without a time across the person's roles", () => {
    const sortOnly = computeWeekSummary(data, { roles: ["sort"] });
    // D: 8 − 0.5 untimed; E: 2 sort − 0.25 share of its 30-minute untimed break.
    expect(rows(sortOnly)).toEqual({ sort: [2, 9.25] });
    expect(sortOnly).toMatchObject({ grossHours: 10, breakHours: 0.75, unscheduledBreakHours: 0.75 });
    const all = computeWeekSummary(data);
    const roleSum = all.roles.reduce((sum, row) => sum + row.hours, 0);
    expect(roleSum).toBeCloseTo(all.totalHours, 6);
  });
});

describe("overnight shifts", () => {
  it("keeps the overnight role on its start day with +1 hours and net totals", () => {
    const day = buildHourlyCoverage(entries, { dayIndices: [1], employeesById, roles: ["sort"] })[0];
    expect(day.hours.at(-1).label).toBe("5–6 AM (+1)");
    expect(day.totals.sort).toEqual({ count: 2, hours: 10, untimedBreak: 0.75, net: 9.25 });
    expect(computeFilteredDaySummaries(data, { roles: ["sort"] })[2].people).toBe(0);
  });
});

describe("cumulative totals with filtered roles", () => {
  it("count only the selected roles and keep earlier hours of the day", () => {
    const [day] = filterCoverageHours(
      buildHourlyCoverage(entries, { dayIndices: [1], employeesById, roles: ["fold"] }),
      { fromHour: 12 },
    );
    expect(day.hours[0].hour).toBe(12);
    // Through 12 PM: A 4 + B 2 + E 2 = 8; 12–1 PM adds A 0.5 + C 0.5.
    expect(day.hours[0].cells.fold.cumulative).toBe(9);
    expect(day.hours[0].total.cumulative).toBe(9);
  });
});

describe("people are distinct employees, not assignment counts", () => {
  const multi = [
    shift(1, 1, "08:00", "10:00", "fold"),
    shift(2, 1, "11:00", "13:00", "fold"),
    shift(3, 1, "14:00", "16:00", "fold"),
    shift(4, 1, "08:00", "12:00", "fold", { day_of_week: 2 }),
    shift(5, 2, "08:00", "12:00", "fold"),
  ];

  it("counts one person with several fold shifts once in every summary and chip", () => {
    const week = computeWeekSummary({ entries: multi, employees });
    expect(rows(week)).toEqual({ fold: [2, 14] });
    expect(computeFilteredDaySummaries({ entries: multi, employees })[1].roles[0]).toMatchObject({ employees: 2, hours: 10 });
    expect(buildRoleViewTabs(multi).find((tab) => tab.value === "fold").count).toBe(2);
    expect(buildRoleViewTabs(multi)[0].count).toBe(2);
    expect(buildDayViewTabs(multi).find((tab) => tab.value === "1").count).toBe(2);
  });

  it("keeps tasks out of role hours", () => {
    const withTask = shift(6, 3, "08:00", "10:00", ["fold", "lint_cleaning"]);
    expect(rows(computeWeekSummary({ entries: [withTask], employees }))).toEqual({ fold: [1, 2] });
  });
});

describe("role-scoped shifts, print, and export", () => {
  const { entryScopes } = summarizeRoleSelection(entries, { roles: ["fold"] });

  it("gives each shown shift only its selected-role segments and hours", () => {
    expect(entryScopes.has(scheduleEntryKey(c1))).toBe(false);
    const view = entryRoleScopeView(c2, ["fold"], entryScopes.get(scheduleEntryKey(c2)));
    expect(view).toMatchObject({ roles: ["fold"], hours: 3, breaks: [] });
    expect(view.segments.map((s) => s.label)).toEqual(["12:00 PM \u2013 4:00 PM"]);
    const bView = entryRoleScopeView(b, ["fold"], entryScopes.get(scheduleEntryKey(b)));
    expect(bView).toMatchObject({ roles: ["fold"], hours: 2 });
    const aView = entryRoleScopeView(a, ["fold"], entryScopes.get(scheduleEntryKey(a)));
    expect(aView.breaks).toEqual(["Break 12:00 PM \u2013 12:30 PM"]);
    const eView = entryRoleScopeView(e, ["fold"], entryScopes.get(scheduleEntryKey(e)));
    expect(eView.segments.map((s) => s.label)).toEqual(["9:00 AM \u2013 11:00 AM"]);
    expect(eView.hours).toBe(1.75);
  });

  it("exports only the selected role's segments, row totals, and day totals", () => {
    const shown = filterEntriesByRoles(entries, ["fold"]);
    const people = withDisplayedTotals(employees, entries, { roles: ["fold"] }).filter((row) => row.total_hours > 0);
    const lines = buildWeeklyScheduleCsvRows({
      employees: people,
      entries: shown,
      dayIndices: [1],
      dayLabels: ["Mon"],
      showBreaks: true,
      roleFilter: ["fold"],
      entryScopes,
      daySummaries: computeFilteredDaySummaries(data, { roles: ["fold"] }),
    });
    const bRow = lines.find((line) => line.startsWith("Employee B"));
    expect(bRow).toBe("Employee B,Fold,8:00 AM - 12:00 PM (2h) Fold,2,0,2");
    const cRow = lines.find((line) => line.startsWith("Employee C"));
    expect(cRow).toBe("Employee C,Fold,12:00 PM - 4:00 PM (3h) Fold,3,0,3");
    expect(lines.find((line) => line.startsWith("Day Role Totals"))).toContain("Fold: 4 people / 14.25 hours");
    expect(lines.join("\n")).not.toContain("Wash");
  });

  it("puts net role hours beside the hourly coverage in the hourly export", () => {
    const days = buildHourlyCoverage(entries, { dayIndices: [1], employeesById, roles: ["fold"] });
    const csv = buildHourlyCoverageCsvRows({ days, weekStart: "2026-06-14", columns: ["fold"] });
    expect(csv).toContain("Mon,Jun 15,Day total,Fold,4,14.5,,Net 14.25h after 0.25h break without a time");
  });
});
