import { describe, expect, it } from "vitest";
import {
  allocateRoleHoursByDay,
  computeFilteredDaySummaries,
  computeWeekSummary,
  formatEmployeeWeeklySummary,
  formatRoleHoursLabel,
  parseEntryRoles,
  ROLE_ORDER,
  WEEKLY_SCHEDULE_ROLES,
  withDisplayedTotals,
} from "./weeklyScheduleRoles";
import { filterEntriesByRoleView } from "./weeklyScheduleViewFilters";
import { filterEntriesByEmployerTab } from "./weeklyScheduleEmployerTabs";
import { buildWeeklyScheduleCsvRows, formatDayRoleTotalsText } from "./weeklyScheduleExport";

function entry(partial) {
  return {
    user_id: 1,
    day_of_week: 0,
    role: "fold",
    roles: undefined,
    start_time: "08:00",
    end_time: "16:00",
    break_minutes: 0,
    hours: 8,
    ...partial,
  };
}

describe("weekly schedule PT roles", () => {
  it("defines PT Sorter, PT Washer, and PT Folder as independent roles", () => {
    const values = WEEKLY_SCHEDULE_ROLES.map((role) => role.value);
    expect(values).toContain("pt_sorter");
    expect(values).toContain("pt_washer");
    expect(values).toContain("pt_folder");
    expect(ROLE_ORDER).toContain("pt_sorter");
    expect(parseEntryRoles({ role: "pt_washer" })).toEqual(["pt_washer"]);
    expect(parseEntryRoles({ role: "pt_sorter,pt_folder" })).toEqual(["pt_sorter", "pt_folder"]);
    expect(parseEntryRoles({ role: "pt_wash" })).toEqual(["pt_washer"]);
  });
});

describe("formatRoleHoursLabel", () => {
  it("formats whole and partial hours", () => {
    expect(formatRoleHoursLabel(7)).toBe("7h");
    expect(formatRoleHoursLabel(7.5)).toBe("7.5h");
    expect(formatRoleHoursLabel(0.5)).toBe("0.5h");
  });
});

describe("allocateRoleHoursByDay", () => {
  it("uses segment times for split-role shifts, not full-day duration", () => {
    const hours = allocateRoleHoursByDay([
      entry({ role: "wash", start_time: "06:45", end_time: "07:15", hours: 0.5 }),
      entry({ role: "fold", start_time: "08:00", end_time: "15:00", hours: 7 }),
    ]);
    expect(hours[0].wash).toBe(0.5);
    expect(hours[0].fold).toBe(7);
    expect(hours[0].sort).toBe(0);
  });

  it("sums multiple segments of the same role for one employee", () => {
    const hours = allocateRoleHoursByDay([
      entry({ role: "sort", start_time: "06:00", end_time: "08:00", hours: 2 }),
      entry({ role: "sort", start_time: "12:00", end_time: "14:00", hours: 2 }),
    ]);
    expect(hours[0].sort).toBe(4);
  });

  it("splits multi-role tagged segments evenly and keeps PT separate", () => {
    const hours = allocateRoleHoursByDay([
      entry({ role: "sort,wash", start_time: "08:00", end_time: "12:00", hours: 4 }),
      entry({ role: "pt_washer", start_time: "13:00", end_time: "17:00", hours: 4 }),
    ]);
    expect(hours[0].sort).toBe(2);
    expect(hours[0].wash).toBe(2);
    expect(hours[0].pt_washer).toBe(4);
  });

  it("does not double-count overlapping same-role segments", () => {
    const hours = allocateRoleHoursByDay([
      entry({ role: "wash", start_time: "08:00", end_time: "12:00", hours: 4 }),
      entry({ role: "wash", start_time: "10:00", end_time: "14:00", hours: 4 }),
    ]);
    expect(hours[0].wash).toBe(6);
  });

  it("supports overnight segments", () => {
    const hours = allocateRoleHoursByDay([
      entry({ role: "fold", start_time: "22:00", end_time: "02:00", hours: 4 }),
    ]);
    expect(hours[0].fold).toBe(4);
  });
});

describe("day and week summaries with filters", () => {
  const data = {
    employees: [
      { user_id: 1, excluded: false, estimated_cost: 0 },
      { user_id: 2, excluded: false, estimated_cost: 0 },
    ],
    entries: [
      entry({ user_id: 1, role: "wash", start_time: "06:45", end_time: "07:15", hours: 0.5 }),
      entry({ user_id: 1, role: "fold", start_time: "08:00", end_time: "15:00", hours: 7 }),
      entry({ user_id: 2, role: "pt_sorter", start_time: "09:00", end_time: "13:00", hours: 4 }),
      entry({ user_id: 2, day_of_week: 1, role: "sort", start_time: "08:00", end_time: "12:00", hours: 4 }),
    ],
  };

  it("computes day role counts and hours including PT roles", () => {
    const days = computeFilteredDaySummaries(data);
    expect(days[0].wash).toBe(1);
    expect(days[0].wash_hours).toBe(0.5);
    expect(days[0].fold).toBe(1);
    expect(days[0].fold_hours).toBe(7);
    expect(days[0].pt_sorter).toBe(1);
    expect(days[0].pt_sorter_hours).toBe(4);
    expect(days[0].sort).toBe(0);
  });

  it("updates totals when role filter is applied", () => {
    const filtered = filterEntriesByRoleView(data.entries, ["pt_sorter"]);
    const days = computeFilteredDaySummaries(data, { entries: filtered });
    expect(days[0].pt_sorter).toBe(1);
    expect(days[0].pt_sorter_hours).toBe(4);
    expect(days[0].wash).toBe(0);
    expect(days[0].wash_hours).toBe(0);
    expect(days[0].fold_hours).toBe(0);
  });

  it("keeps mapped-user views from double-counting via userIds", () => {
    const days = computeFilteredDaySummaries(data, { userIds: [1] });
    expect(days[0].people).toBe(1);
    expect(days[0].wash_hours).toBe(0.5);
    expect(days[0].pt_sorter).toBe(0);

    const week = computeWeekSummary(data, { userIds: [1] });
    expect(week.washCount).toBe(1);
    expect(week.washHours).toBe(0.5);
    expect(week.ptSorterCount).toBe(0);
    expect(week.foldHours).toBe(7);
  });

  it("includes PT counts and hours in week summary", () => {
    const week = computeWeekSummary(data);
    expect(week.ptSorterCount).toBe(1);
    expect(week.ptSorterHours).toBe(4);
    expect(week.ptWasherCount).toBe(0);
    expect(week.washHours).toBe(0.5);
    expect(week.sortHours).toBe(4);
  });
});

describe("employee totals follow the shifts on screen", () => {
  // Week of 2026-10-04: three Rinse Exclusive weekday shifts and a Saturday Rinse shift that
  // overlaps a WashPro shift, plus a WashPro Friday shift (the Rinse tab hides WashPro shifts).
  const shift = (day, start, end, affiliation, hours) =>
    entry({ user_id: 64, day_of_week: day, start_time: start, end_time: end, break_minutes: 30, hours, employer_affiliation: affiliation });
  const entries = [
    shift(1, "08:00", "16:00", "rinse_exclusive", 7.5),
    shift(2, "08:00", "16:00", "rinse_exclusive", 7.5),
    shift(3, "08:00", "16:00", "rinse_exclusive", 7.5),
    shift(5, "05:00", "13:00", "washpro", 7.5),
    shift(6, "05:00", "13:00", "washpro", 7.5),
    shift(6, "05:00", "13:30", "rinse_exclusive", 8),
  ];
  const employee = {
    user_id: 64,
    display_name: "Maria Rivera",
    default_hourly_rate: 15,
    total_hours: 38,
    scheduled_days: 5,
    estimated_cost: 570,
  };
  const rinseEntries = filterEntriesByEmployerTab(entries, "rinse_exclusive", [employee], "veewash");

  it("replaces whole-week payload totals with the filtered shifts", () => {
    expect(rinseEntries).toHaveLength(4);
    const [row] = withDisplayedTotals([employee], rinseEntries);
    expect(row).toMatchObject({ total_hours: 30.5, scheduled_days: 4, estimated_cost: 457.5 });
    expect(formatEmployeeWeeklySummary(row)).toBe("30.5 hrs • 4 days");
    const [all] = withDisplayedTotals([employee], entries);
    expect(all).toMatchObject({ total_hours: 38, scheduled_days: 5 });
  });

  it("keeps the week summary, day totals, and export on the same shifts", () => {
    const data = { employees: [employee], entries };
    const week = computeWeekSummary(data, { entries: rinseEntries });
    expect(week).toMatchObject({ totalHours: 30.5, totalDays: 4, estimatedCost: 457.5, foldCount: 4 });
    const days = computeFilteredDaySummaries(data, { entries: rinseEntries });
    expect(days.map((d) => d.hours)).toEqual([0, 7.5, 7.5, 7.5, 0, 0, 8]);
    const lines = buildWeeklyScheduleCsvRows({
      employees: withDisplayedTotals([employee], rinseEntries),
      entries: rinseEntries,
    });
    expect(lines[1].endsWith(",30.5")).toBe(true);
  });

  it("counts two shifts on one day as one scheduled day", () => {
    const week = computeWeekSummary({ employees: [employee], entries }, { entries });
    expect(week.totalDays).toBe(5);
    expect(week.totalHours).toBe(38);
  });
});

describe("excel export role hours and PT roles", () => {
  it("includes PT roles and day role-hour totals", () => {
    const entries = [
      entry({ user_id: 1, role: "pt_washer", start_time: "08:00", end_time: "14:00", hours: 6 }),
      entry({ user_id: 1, role: "pt_sorter", start_time: "14:00", end_time: "18:00", hours: 4 }),
      entry({ user_id: 1, role: "pt_folder", day_of_week: 1, start_time: "08:00", end_time: "20:00", hours: 12 }),
    ];
    const employees = [{ user_id: 1, display_name: "Alex", total_hours: 22, scheduled_days: 2 }];
    const lines = buildWeeklyScheduleCsvRows({ employees, entries });
    const body = lines.join("\n");
    expect(body).toContain("PT Washer");
    expect(body).toContain("PT Sorter");
    expect(body).toContain("PT Folder");
    expect(body).toContain("Day Role Totals");
    expect(body).toContain("PT Wash 1 / 6h");
    expect(body).toContain("PT Sort 1 / 4h");
    expect(body).toContain("PT Fold 1 / 12h");
    expect(formatDayRoleTotalsText(computeFilteredDaySummaries({ entries, employees })[0])).toContain("PT Wash 1 / 6h");
  });
});
