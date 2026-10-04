import { afterEach, describe, expect, it } from "vitest";
import { buildHourlyCoverage } from "./weeklyScheduleTimeBlocks";
import { buildHourlyCoverageCsvRows, buildWeeklyScheduleCsvRows, formatShiftEntryText } from "./weeklyScheduleExport";
import {
  allocateRoleHoursByDay,
  computeFilteredDaySummaries,
  computeWeekSummary,
  employeeTotalsFromEntries,
  entryBreakBreakdown,
  entryBreakLines,
  scheduledHoursBreakdownByUserDay,
  setScheduleRoleCatalog,
  summarizeScheduleHours,
  validateBreakSlots,
} from "./weeklyScheduleRoles";

const employees = [
  { user_id: 1, display_name: "Employee A", default_hourly_rate: 20 },
  { user_id: 2, display_name: "Employee B", default_hourly_rate: 20 },
];
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

function slots(...pairs) {
  return pairs.map(([start_time, end_time]) => ({ start_time, end_time }));
}

function day(entries, options = {}) {
  return buildHourlyCoverage(entries, { dayIndices: [1], employeesById, ...options })[0];
}

function row(coverageDay, hour) {
  return coverageDay.hours.find((r) => r.hour === hour);
}

afterEach(() => setScheduleRoleCatalog(null));

describe("break validation", () => {
  it("accepts breaks inside a day shift and an overnight shift", () => {
    expect(validateBreakSlots("09:00", "17:00", slots(["12:00", "12:30"], ["15:00", "15:15"]))).toBeNull();
    expect(validateBreakSlots("22:00", "06:00", slots(["23:30", "00:15"], ["03:00", "03:30"]))).toBeNull();
  });

  it("rejects breaks outside the shift, including past an overnight end", () => {
    expect(validateBreakSlots("09:00", "17:00", slots(["16:45", "17:15"]))).toMatch(/within the shift/);
    expect(validateBreakSlots("09:00", "17:00", slots(["08:00", "08:30"]))).toMatch(/within the shift/);
    expect(validateBreakSlots("22:00", "06:00", slots(["05:45", "06:15"]))).toMatch(/within the shift/);
    expect(validateBreakSlots("22:00", "06:00", slots(["21:00", "21:30"]))).toMatch(/within the shift/);
  });

  it("rejects overlapping, empty, and zero-length breaks", () => {
    expect(validateBreakSlots("09:00", "17:00", slots(["12:00", "12:30"], ["12:15", "12:45"]))).toMatch(/overlaps/);
    expect(validateBreakSlots("09:00", "17:00", slots(["12:00", "12:00"]))).toMatch(/after the start/);
    expect(validateBreakSlots("09:00", "17:00", [{ start_time: "12:00", end_time: "" }])).toMatch(/required/);
  });
});

describe("break deduction", () => {
  it("keeps a duration-only break and labels it Not scheduled", () => {
    const legacy = shift(1, 1, "09:00", "17:00", "fold", { break_minutes: 30 });
    expect(entryBreakBreakdown(legacy)).toEqual({
      grossMinutes: 480,
      breakMinutes: 30,
      timedBreakMinutes: 0,
      unscheduledBreakMinutes: 30,
    });
    expect(entryBreakLines(legacy)).toEqual(["Break 30 min \u00b7 Not scheduled"]);
  });

  it("replaces a duration-only break when it gets a time instead of adding to it", () => {
    const timed = shift(1, 1, "09:00", "17:00", "fold", { break_minutes: 30, break_slots: slots(["12:00", "12:30"]) });
    expect(entryBreakBreakdown(timed)).toMatchObject({ breakMinutes: 30, timedBreakMinutes: 30, unscheduledBreakMinutes: 0 });
    const longer = shift(1, 1, "09:00", "17:00", "fold", { break_minutes: 30, break_slots: slots(["12:00", "12:45"]) });
    expect(entryBreakBreakdown(longer)).toMatchObject({ breakMinutes: 45, unscheduledBreakMinutes: 0 });
    expect(entryBreakLines(timed)).toEqual(["Break 12 PM\u201312:30 PM"]);
  });

  it("counts multiple and partial-hour breaks", () => {
    const entry = shift(1, 1, "09:00", "17:00", "fold", {
      break_minutes: 45,
      break_slots: slots(["11:50", "12:20"], ["15:00", "15:15"]),
    });
    const parts = scheduledHoursBreakdownByUserDay([entry]).get("1|1");
    expect(parts).toMatchObject({ gross: 8, break: 0.75, timedBreak: 0.75, unscheduledBreak: 0, net: 7.25 });
  });

  it("counts overlapping shifts and the same break on both once", () => {
    const a = shift(1, 1, "08:00", "14:00", "wash", { break_minutes: 30, break_slots: slots(["12:00", "12:30"]) });
    const b = shift(2, 1, "12:00", "16:00", "fold", { break_minutes: 30, break_slots: slots(["12:00", "12:30"]) });
    expect(scheduledHoursBreakdownByUserDay([a, b]).get("1|1")).toMatchObject({ gross: 8, break: 0.5, net: 7.5 });
  });

  it("handles an overnight shift with a break after midnight", () => {
    const entry = shift(1, 1, "22:00", "06:00", "sort", { break_minutes: 30, break_slots: slots(["01:00", "01:30"]) });
    expect(scheduledHoursBreakdownByUserDay([entry]).get("1|1")).toMatchObject({ gross: 8, break: 0.5, net: 7.5 });
    const coverage = day([entry]);
    expect(row(coverage, 25).breaks).toMatchObject({ count: 1, hours: 0.5 });
    expect(row(coverage, 25).cells.sort.hours).toBe(0.5);
    expect(coverage.totals.sort.hours).toBe(7.5);
  });
});

describe("hourly matrix with breaks", () => {
  it("takes a partial-hour timed break out of role coverage and shows it in the break column", () => {
    const entry = shift(1, 1, "09:00", "17:00", "fold", { break_minutes: 30, break_slots: slots(["12:15", "12:45"]) });
    const coverage = day([entry]);
    expect(row(coverage, 12).cells.fold.hours).toBe(0.5);
    expect(row(coverage, 12).breaks).toMatchObject({ count: 1, hours: 0.5 });
    expect(row(coverage, 12).breaks.people[0]).toMatchObject({ name: "Employee A", rangeLabel: "12:15–12:45" });
    expect(coverage.totals.fold.hours).toBe(7.5);
    expect(coverage.breakTotal).toEqual({ count: 1, hours: 0.5 });
    expect(coverage.breakRanges[0]).toMatchObject({ roles: ["fold"], overlapsWith: [] });
    expect(allocateRoleHoursByDay([entry])[1].fold).toBe(7.5);
    expect(summarizeScheduleHours([entry], byIdMap).roles[0].hours).toBe(7.5);
  });

  it("removes the break before splitting simultaneous roles", () => {
    const entry = shift(1, 1, "08:00", "12:00", ["wash", "fold"], { break_minutes: 30, break_slots: slots(["10:00", "10:30"]) });
    const coverage = day([entry]);
    expect(row(coverage, 10).cells.wash.hours).toBe(0.25);
    expect(row(coverage, 10).cells.fold.hours).toBe(0.25);
    expect(row(coverage, 10).breaks.hours).toBe(0.5);
    expect(coverage.totals.wash.hours).toBe(1.75);
    const hours = allocateRoleHoursByDay([entry])[1];
    expect(hours.wash).toBe(1.75);
    expect(hours.fold).toBe(1.75);
  });

  it("lists duration-only breaks separately without placing them in an hour", () => {
    const legacy = shift(1, 1, "09:00", "17:00", "fold", { break_minutes: 30 });
    const coverage = day([legacy]);
    expect(coverage.hours.every((r) => r.breaks.count === 0)).toBe(true);
    expect(coverage.totals.fold.hours).toBe(8);
    expect(coverage.unscheduledBreaks).toEqual([{ userId: 1, name: "Employee A", entry: legacy, hours: 0.5 }]);
    expect(coverage.unscheduledBreakTotal).toEqual({ count: 1, hours: 0.5 });
  });

  it("marks overlapping breaks and filters breaks by the roles they pause", () => {
    const a = shift(1, 1, "09:00", "17:00", "fold", { break_minutes: 30, break_slots: slots(["12:00", "12:30"]) });
    const b = shift(2, 2, "09:00", "17:00", "wash", { break_minutes: 30, break_slots: slots(["12:15", "12:45"]) });
    const coverage = day([a, b]);
    expect(coverage.breakRanges.map((r) => [r.name, r.overlapsWith])).toEqual([
      ["Employee A", ["Employee B"]],
      ["Employee B", ["Employee A"]],
    ]);
    expect(row(coverage, 12).breaks).toMatchObject({ count: 2, hours: 1 });
    const washOnly = day([a, b], { roles: ["wash"] });
    expect(washOnly.breakRanges.map((r) => r.name)).toEqual(["Employee B"]);
    expect(row(washOnly, 12).breaks.hours).toBe(0.5);
  });
});

describe("totals reconcile across views", () => {
  const entries = [
    shift(1, 1, "08:00", "14:00", "wash", { hours: 5.5, break_minutes: 30, break_slots: slots(["11:00", "11:30"]) }),
    shift(2, 1, "12:00", "16:00", "fold"),
    shift(3, 2, "22:00", "06:00", ["sort", "fold"], { break_minutes: 45, break_slots: slots(["02:00", "02:30"]) }),
    shift(4, 2, "09:00", "13:00", "", { role: "", roles: [], assignments: [], day_of_week: 3, hours: 3.75, break_minutes: 15 }),
  ];
  const data = { entries, employees };

  it("matches net, gross, and break hours in the summary, employee totals, week summary, and day summaries", () => {
    const summary = summarizeScheduleHours(entries, byIdMap);
    // A: 8 gross − 0.5 timed. B: 8 gross − 0.5 timed − 0.25 untimed, plus 4 − 0.25 untimed.
    expect(summary.grossHours).toBe(20);
    expect(summary.breakHours).toBe(1.5);
    expect(summary.unscheduledBreakHours).toBe(0.5);
    expect(summary.totalHours).toBe(18.5);
    // Role hours are net (breaks without a time are shared into them), so role + no-role time = net hours.
    expect(summary.roleTotal + summary.unassignedHours).toBeCloseTo(summary.totalHours, 6);

    const totals = employeeTotalsFromEntries(entries, employees);
    expect(totals.get(1)).toMatchObject({ total_hours: 7.5, gross_hours: 8, break_hours: 0.5 });
    expect(totals.get(2)).toMatchObject({ total_hours: 11, gross_hours: 12, break_hours: 1, unscheduled_break_hours: 0.5 });

    const week = computeWeekSummary(data, { entries, includeExcluded: true });
    expect(week).toMatchObject({ totalHours: 18.5, grossHours: 20, breakHours: 1.5 });

    const days = computeFilteredDaySummaries(data, { entries, includeExcluded: true });
    expect(days[1]).toMatchObject({ hours: 14.75, gross_hours: 16, break_hours: 1.25 });
    expect(days[3]).toMatchObject({ hours: 3.75, gross_hours: 4, break_hours: 0.25, unscheduled_break_hours: 0.25 });

    const coverage = buildHourlyCoverage(entries, { dayIndices: [1], employeesById })[0];
    const roleHours = allocateRoleHoursByDay(entries)[1];
    for (const role of ["wash", "sort", "fold"]) expect(coverage.totals[role].net).toBeCloseTo(roleHours[role], 2);
    expect(coverage.overall.hours - coverage.overall.untimedBreak).toBeCloseTo(coverage.overall.net, 6);
    expect(coverage.overall.untimedBreak).toBeCloseTo(coverage.unscheduledBreakTotal.hours, 6);
    expect(coverage.overall.net).toBeCloseTo(days[1].hours, 6);
    const dayRoles = Object.fromEntries(days[1].roles.map((row) => [row.role, row]));
    for (const role of ["wash", "sort", "fold"]) expect(dayRoles[role].hours).toBeCloseTo(coverage.totals[role].net, 6);
  });

  it("puts break details in the exports", () => {
    expect(formatShiftEntryText(entries[0], { forExport: true, showBreaks: true })).toContain(
      "(5.5h net, Break 11 AM - 11:30 AM)",
    );
    const text = formatShiftEntryText(entries[3], { forExport: true, showBreaks: true });
    expect(text).toContain("Break 15 min / Not scheduled");
    expect(formatShiftEntryText(entries[3], { forExport: true })).not.toContain("Break");

    const withTotals = employees.map((e) => ({ ...e, ...employeeTotalsFromEntries(entries, employees).get(e.user_id) }));
    const lines = buildWeeklyScheduleCsvRows({ employees: withTotals, entries, showBreaks: true });
    expect(lines[0]).toContain("Gross Hours,Break Hours,Net Hours");
    expect(lines[1].endsWith(",8,0.5,7.5")).toBe(true);
    expect(lines.at(-1)).toContain("Gross 16 / Break 1.25 / Net 14.75");

    const days = buildHourlyCoverage(entries, { dayIndices: [1, 3], employeesById });
    const hourly = buildHourlyCoverageCsvRows({ days, weekStart: "2026-06-14", columns: ["wash", "sort", "fold"] });
    expect(hourly).toContain("Mon,Jun 15,11 AM-12 PM,On break,1,0.5,0.5,Employee A: 11-11:30");
    expect(hourly).toContain("Wed,Jun 17,Break without a time,Not scheduled,1,0.25,,Employee B: not placed in any hour");
  });
});
