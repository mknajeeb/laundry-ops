import React from "react";
import { renderToString } from "react-dom/server";
import { describe, expect, it } from "vitest";
import WeeklyScheduleBreaksByTimeView from "./WeeklyScheduleBreaksByTimeView";
import WeeklyScheduleBreaksByTimePrint from "./WeeklyScheduleBreaksByTimePrint";
import { buildHourlyCoverage } from "./weeklyScheduleTimeBlocks";
import { buildBreaksTasksGrid, gridTasksByDay } from "./weeklyScheduleBreaksGrid";
import {
  buildBreaksByTime,
  intervalLabel,
  peakSimultaneous,
  slotHeadline,
  slotPersonDetail,
} from "./weeklyScheduleBreaksByTime";
import { buildBreaksByTimeCsvRows } from "./weeklyScheduleExport";
import { computeWeekSummary } from "./weeklyScheduleRoles";

const names = ["Amna", "Evelin", "Tarannum", "Florentina", "Gia", "Hana", "Ivy", "Jo", "Kim", "Lou"];
const byId = Object.fromEntries(names.map((name, i) => [i + 1, { user_id: i + 1, display_name: name }]));
const THU = 4;
const FRI = 5;

let nextId = 1;
function shift(userId, day, start, end, roles, slots = [], breakMinutes = null) {
  const id = nextId++;
  const minutes = breakMinutes ?? slots.reduce((sum, [a, b]) => {
    const [ah, am] = a.split(":").map(Number);
    const [bh, bm] = b.split(":").map(Number);
    return sum + ((bh * 60 + bm - (ah * 60 + am) + 1440) % 1440);
  }, 0);
  return {
    id, user_id: userId, day_of_week: day, start_time: start, end_time: end, break_minutes: minutes,
    role: roles.join(","), roles, assignments: roles.map((role) => ({ role, full_shift: true })),
    break_slots: slots.map(([a, b]) => ({ start_time: a, end_time: b })),
  };
}

// Thursday: three together 10:00–10:30; Florentina 8:45–9:15 crosses rows; Gia then Hana back to back
// (staggered); Ivy and Jo overlap 11:45–12:00; Kim has 30 minutes without a time (wash);
// Lou works overnight with a 23:45–00:15 break. Amna also has a second overlapping shift repeating
// her 10:00 break, which must not count her twice. Friday: Amna 9:00–9:30.
const entries = [
  shift(1, THU, "08:00", "16:00", ["fold"], [["10:00", "10:30"]]),
  shift(1, THU, "09:00", "13:00", ["fold"], [["10:00", "10:30"]]),
  shift(2, THU, "08:00", "16:00", ["fold"], [["10:00", "10:30"]]),
  shift(3, THU, "08:00", "16:00", ["fold"], [["10:00", "10:30"]]),
  shift(4, THU, "07:00", "15:00", ["fold"], [["08:45", "09:15"]]),
  shift(5, THU, "08:00", "16:00", ["fold"], [["11:00", "11:15"]]),
  shift(6, THU, "08:00", "16:00", ["fold"], [["11:15", "11:30"]]),
  shift(7, THU, "08:00", "16:00", ["fold"], [["11:30", "12:00"]]),
  shift(8, THU, "08:00", "16:00", ["fold"], [["11:45", "12:15"]]),
  shift(9, THU, "08:00", "16:00", ["wash"], [], 30),
  shift(10, THU, "22:00", "06:00", ["fold"], [["23:45", "00:15"]]),
  shift(1, FRI, "08:00", "16:00", ["fold"], [["09:00", "09:30"]]),
];
const responsibilities = [{ id: 50, user_id: 3, day_of_week: THU, role: "lint_cleaning", remarks: "Dryers 1-12" }];

function coverage(roles = null) {
  return buildHourlyCoverage(entries, { dayIndices: [THU, FRI], employeesById: byId, roles });
}

function byTime({ roles = null, interval = 30, includeBreaks = true } = {}) {
  return buildBreaksByTime({ days: coverage(roles), dayIndices: [THU, FRI], interval, includeBreaks });
}

function slot(model, hh, mm, dow = THU) {
  return model.rows.find((row) => !row.gap && row.start === hh * 60 + mm)?.cells[dow];
}

describe("breaks by time", () => {
  it("counts everyone on break together and names them with exact times", () => {
    const cell = slot(byTime(), 10, 0);
    expect(cell.people.map((p) => p.name)).toEqual(["Amna", "Evelin", "Tarannum"]);
    expect(cell).toMatchObject({ count: 3, peak: 3, hours: 1.5 });
    expect(slotHeadline(cell)).toBe("3 on break \u00b7 1.5 break-hours");
    expect(slotPersonDetail(cell.people[0])).toBe("10:00–10:30");
    expect(cell.people[0].breaks[0].entry.user_id).toBe(1);
  });

  it("splits a break across rows by actual overlap and keeps its daily total", () => {
    const model = byTime();
    const before = slot(model, 8, 30);
    const after = slot(model, 9, 0);
    expect(before.people[0]).toMatchObject({ name: "Florentina", minutes: 15, partial: true });
    expect(after.people[0]).toMatchObject({ name: "Florentina", minutes: 15, partial: true });
    expect(before.hours + after.hours).toBe(0.5);
    expect(slotPersonDetail(before.people[0])).toBe("8:45–9:15 \u00b7 15 min here");
  });

  it("separates everyone breaking in an interval from the most on break at once", () => {
    const model = byTime();
    const staggered = slot(model, 11, 0);
    expect(staggered).toMatchObject({ count: 2, peak: 1, hours: 0.5 });
    expect(slotHeadline(staggered)).toBe("2 take a break \u00b7 max 1 at once \u00b7 0.5 break-hours");
    const overlapping = slot(model, 11, 30);
    expect(overlapping).toMatchObject({ count: 2, peak: 2, hours: 0.75 });
    expect(slot(model, 12, 0)).toMatchObject({ count: 1, hours: 0.25 });
    expect(peakSimultaneous([[{ start: 0, end: 15 }], [{ start: 15, end: 30 }]]).peak).toBe(1);
  });

  it("places overnight breaks after midnight on the day the shift starts", () => {
    const model = byTime();
    const late = slot(model, 23, 30);
    const afterMidnight = slot(model, 24, 0);
    expect(late.people[0]).toMatchObject({ name: "Lou", minutes: 15 });
    expect(afterMidnight.people[0]).toMatchObject({ name: "Lou", minutes: 15 });
    expect(intervalLabel(24 * 60, 24 * 60 + 30)).toBe("12:00–12:30 AM (+1)");
    expect(slotPersonDetail(late.people[0])).toBe("11:45–12:15 \u00b7 15 min here");
    expect(slot(model, 0, 0)).toBeUndefined();
  });

  it("keeps breaks without a time out of every row and lists them per day", () => {
    const model = byTime();
    const thursday = model.columns.find((c) => c.dow === THU);
    expect(thursday.untimed.map((item) => item.name)).toEqual(["Kim"]);
    expect(thursday.untimedBreakHours).toBe(0.5);
    for (const row of model.rows) expect(row.cells[THU]?.people?.some((p) => p.name === "Kim") || false).toBe(false);
  });

  it("reconciles interval totals with daily, weekly, employee-grid, and week-summary break totals", () => {
    const days = coverage();
    const model = buildBreaksByTime({ days, dayIndices: [THU, FRI] });
    const grid = buildBreaksTasksGrid({ days, dayIndices: [THU, FRI], shiftEntries: entries, responsibilities, employeesById: byId });
    for (const column of model.columns) {
      const day = days.find((d) => d.dow === column.dow);
      const gridColumn = grid.columns.find((c) => c.dow === column.dow);
      expect(column.intervalHours).toBeCloseTo(column.timedBreakHours, 9);
      expect(column.timedBreakHours).toBeCloseTo(day.breakTotal.hours, 9);
      expect(column.timedBreakHours).toBeCloseTo(gridColumn.timedBreakHours, 9);
      expect(column.untimedBreakHours).toBeCloseTo(gridColumn.untimedBreakHours, 9);
    }
    // Amna's duplicate shift repeats her break; she is counted once (3 people at 10:00, 4h timed on Thursday).
    expect(model.columns[0].timedBreakHours).toBe(4);
    expect(model.columns[0].peak).toBe(3);
    expect(model.week.intervalHours).toBeCloseTo(model.week.timedBreakHours, 9);
    expect(model.week.timedBreakHours).toBe(4.5);
    const summary = computeWeekSummary({ entries, employees: Object.values(byId) });
    expect(model.week.timedBreakHours).toBeCloseTo(summary.timedBreakHours, 9);
    expect(model.week.timedBreakHours + model.week.untimedBreakHours).toBeCloseTo(summary.breakHours, 9);
  });

  it("offers 15-minute rows with the same totals", () => {
    const fine = byTime({ interval: 15 });
    expect(fine.interval).toBe(15);
    expect(slot(fine, 8, 45).people[0]).toMatchObject({ name: "Florentina", minutes: 15, partial: true });
    expect(slot(fine, 11, 0)).toMatchObject({ count: 1, peak: 1 });
    expect(slot(fine, 11, 15)).toMatchObject({ count: 1, peak: 1 });
    expect(fine.week.intervalHours).toBeCloseTo(byTime().week.intervalHours, 9);
  });

  it("collapses long runs without breaks into one gap row", () => {
    const gaps = byTime().rows.filter((row) => row.gap);
    expect(gaps.length).toBeGreaterThan(0);
    expect(gaps[0]).toMatchObject({ start: 12 * 60 + 30 });
  });

  it("follows the role filter and shows nothing when breaks are off", () => {
    const washOnly = byTime({ roles: ["wash"] });
    expect(washOnly.hasTimed).toBe(false);
    expect(washOnly.columns[0].untimed.map((i) => i.name)).toEqual(["Kim"]);
    const foldOnly = byTime({ roles: ["fold"] });
    expect(foldOnly.columns[0].untimed).toEqual([]);
    expect(slot(foldOnly, 10, 0).count).toBe(3);
    const off = byTime({ includeBreaks: false });
    expect(off.rows).toEqual([]);
    expect(off.columns.every((c) => c.timedBreakHours === 0 && c.untimed.length === 0)).toBe(true);
  });

  it("renders screen, print, and CSV from the same model", () => {
    const days = coverage();
    const model = buildBreaksByTime({ days, dayIndices: [THU, FRI] });
    const grid = buildBreaksTasksGrid({ days, dayIndices: [THU, FRI], shiftEntries: entries, responsibilities, employeesById: byId });
    const tasksByDay = gridTasksByDay(grid);
    expect(tasksByDay[THU][0]).toMatchObject({ name: "Tarannum", role: "lint_cleaning" });
    const props = { weekStart: "2026-10-04", byTime: model, grid, tasksByDay };
    const screen = renderToString(<WeeklyScheduleBreaksByTimeView {...props} canEdit />);
    const print = renderToString(<WeeklyScheduleBreaksByTimePrint {...props} />);
    for (const html of [screen, print]) {
      for (const text of [
        "3 on break \u00b7 1.5 break-hours",
        "max 1 at once",
        "Amna",
        "15 min here",
        "Peak 3 at once",
        "Not scheduled",
        "Kim \u00b7 30 min",
        "Scheduled total",
        "12:00–12:30 AM (+1)",
        "Dryers 1-12",
        "Unassigned tasks",
      ]) {
        expect(html, text).toContain(text);
      }
    }
    expect(screen).toContain("Set time");
    expect(screen).toContain('data-slot-peak="3"');
    const csv = buildBreaksByTimeCsvRows({ ...props, summaryLines: ["Totals"] }).join("\n");
    expect(csv).toContain("3 on break / 1.5 break-hours; Amna 10:00 - 10:30");
    expect(csv).toContain("Florentina 8:45 - 9:15 / 15 min here");
    expect(csv).toContain("Not scheduled (week 0.5h)");
    expect(csv).toContain("Lint");
  });
});
