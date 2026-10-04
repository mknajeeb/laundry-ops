import React from "react";
import { renderToString } from "react-dom/server";
import { afterEach, describe, expect, it } from "vitest";
import WeeklyScheduleBreaksTasksView from "./WeeklyScheduleBreaksTasksView";
import WeeklyScheduleBreaksTasksPrint from "./WeeklyScheduleBreaksTasksPrint";
import WeeklyScheduleSummaryBar from "./WeeklyScheduleSummaryBar";
import WeeklyScheduleSummaryPrint from "./WeeklyScheduleSummaryPrint";
import { buildHourlyCoverage } from "./weeklyScheduleTimeBlocks";
import { buildBreaksTasksGrid, filterResponsibilitiesByTaskSelection, taskRoleOptions } from "./weeklyScheduleBreaksGrid";
import { buildBreaksTasksCsvRows } from "./weeklyScheduleExport";
import { computeWeekSummary, DEFAULT_ROLE_CATALOG, setScheduleRoleCatalog, setScheduleRoleGroups } from "./weeklyScheduleRoles";
import { summaryRoleLines, summaryTextLines, summaryTotalsMetrics } from "./weeklyScheduleSummaryLines";
import { isCodeSelected, noneSelectedIn, selectedCountIn, toggleSelectionCode } from "./weeklyScheduleViewFilters";

const employees = [
  { user_id: 1, display_name: "Ana" },
  { user_id: 2, display_name: "Ben" },
  { user_id: 3, display_name: "Cam" },
];
const byId = Object.fromEntries(employees.map((e) => [e.user_id, e]));

function shift(id, userId, day, start, end, roles, extra = {}) {
  return {
    id, user_id: userId, day_of_week: day, start_time: start, end_time: end, break_minutes: 0,
    role: roles.join(","), roles, assignments: roles.map((role) => ({ role, full_shift: true })), ...extra,
  };
}

// Ana folds Monday with a timed lunch; Ben washes Monday with a 30-minute break without a time;
// Ana sorts Tuesday with no break; Cam has only a task.
const entries = [
  shift(1, 1, 1, "09:00", "17:00", ["fold"], { break_minutes: 30, break_slots: [{ start_time: "12:00", end_time: "12:30" }] }),
  shift(2, 2, 1, "09:00", "17:00", ["wash"], { break_minutes: 30 }),
  shift(3, 1, 2, "09:00", "13:00", ["sort"]),
];
const responsibilities = [
  { id: 9, user_id: 1, day_of_week: 1, role: "lint_cleaning", remarks: "Dryers 1-12" },
  { id: 10, user_id: 3, day_of_week: 2, role: "floor_cleaning", remarks: null },
];

const catalog = DEFAULT_ROLE_CATALOG.map((role) => ({
  ...role,
  role_group: ["wash", "sort", "fold"].includes(role.code) ? "rinse_wf" : ["hd_operator", "hd_folder"].includes(role.code) ? "rinse_hd" : null,
}));
const groups = [
  { code: "rinse_wf", label: "Rinse WF", display_order: 1 },
  { code: "rinse_hd", label: "Rinse HD", display_order: 2 },
];

afterEach(() => {
  setScheduleRoleCatalog(null);
  setScheduleRoleGroups([]);
});

function grid({ roles = null, taskTypes = null, includeBreaks = true } = {}) {
  const days = buildHourlyCoverage(entries, { dayIndices: [1, 2], employeesById: byId, roles });
  const shown = roles ? entries.filter((e) => e.roles.some((r) => roles.includes(r))) : entries;
  return buildBreaksTasksGrid({
    days: includeBreaks ? days : [],
    dayIndices: [1, 2],
    shiftEntries: includeBreaks ? shown : [],
    responsibilities: filterResponsibilitiesByTaskSelection(responsibilities, taskTypes),
    employeesById: byId,
    includeBreaks,
    taskTypes,
  });
}

describe("breaks & tasks grid", () => {
  it("puts days in columns and employees in rows with breaks, untimed breaks, and tasks", () => {
    const g = grid();
    expect(g.columns.map((c) => c.dow)).toEqual([1, 2]);
    const monday = g.columns[0];
    expect(monday.timedBreakHours).toBe(0.5);
    expect(monday.untimedBreakHours).toBe(0.5);
    expect(monday.breakHours).toBe(1);
    expect(monday.taskCount).toBe(1);
    expect(g.rows.map((r) => r.name)).toEqual(["Ana", "Ben", "Cam"]);
    const [ana, ben, cam] = g.rows;
    expect(ana.cells[1].timed).toHaveLength(1);
    expect(ana.cells[1].tasks[0]).toMatchObject({ role: "lint_cleaning", remarks: "Dryers 1-12" });
    expect(ana.cells[2]).toMatchObject({ hasShift: true, timed: [], untimed: [], tasks: [] });
    expect(ben.cells[1].untimed[0]).toMatchObject({ hours: 0.5, unallocated: false, allocatedRole: "wash" });
    expect(cam.cells[2].tasks[0].role).toBe("floor_cleaning");
    expect(monday.unassignedTasks).not.toContain("lint_cleaning");
    expect(monday.unassignedTasks).toContain("floor_cleaning");
  });

  it("keeps tasks when timed roles are unchecked and follows the task filter instead", () => {
    const g = grid({ roles: [], includeBreaks: false });
    expect(g.columns.every((c) => c.breakHours === 0)).toBe(true);
    expect(g.rows.map((r) => r.name)).toEqual(["Ana", "Cam"]);
    expect(g.rows.flatMap((r) => Object.values(r.cells).flatMap((c) => c.tasks.map((t) => t.role)))).toEqual([
      "lint_cleaning",
      "floor_cleaning",
    ]);
    const lintOnly = grid({ roles: ["fold"], taskTypes: ["lint_cleaning"] });
    expect(lintOnly.rows.map((r) => r.name)).toEqual(["Ana"]);
    expect(lintOnly.columns[1].unassignedTasks).toEqual(["lint_cleaning"]);
    expect(taskRoleOptions(responsibilities)).toEqual(expect.arrayContaining(["lint_cleaning", "floor_cleaning"]));
  });

  it("renders the grid, print, and CSV with day totals, Not scheduled, instructions, and unassigned tasks", () => {
    const g = grid();
    const html = [
      renderToString(
        <WeeklyScheduleBreaksTasksView weekStart="2026-10-04" grid={g} canEdit taskOptions={["lint_cleaning"]} onTaskSelectionChange={() => {}} />,
      ),
      renderToString(<WeeklyScheduleBreaksTasksPrint grid={g} weekStart="2026-10-04" />),
    ].join("\n");
    for (const text of ["Breaks 1h · 0.5h not scheduled", "1 task", "Not scheduled", "Set time", "Dryers 1-12", "Unassigned tasks", "No break planned", "TASKS"]) {
      expect(html, text).toContain(text);
    }
    expect(html).not.toContain("Tasks per employee");
    const csv = buildBreaksTasksCsvRows({ grid: g, weekStart: "2026-10-04", summaryLines: ["Employees: 3"] }).join("\n");
    expect(csv).toContain("Employees: 3");
    expect(csv).toContain("Breaks 1h / 0.5h not scheduled; 1 task");
    expect(csv).toContain("Lint Cleaning: Dryers 1-12");
    expect(csv).toContain("Not scheduled 30 min");
    expect(csv).toContain("Unassigned tasks");
  });

  it("shows a select-all prompt instead of zero breaks when no roles are selected", () => {
    const g = grid({ roles: [], includeBreaks: false });
    const html = renderToString(
      <WeeklyScheduleBreaksTasksView weekStart="2026-10-04" grid={g} noRolesSelected onSelectAllRoles={() => {}} />,
    );
    expect(html).toContain("No roles selected");
    expect(html).toContain("Select all");
    expect(html).toContain("Dryers 1-12");
    expect(html).not.toContain("No planned breaks");
    expect(html).not.toContain("No breaks");
  });
});

describe("compact summary", () => {
  it("puts totals on the first line and one line per role category", () => {
    setScheduleRoleCatalog(catalog);
    setScheduleRoleGroups(groups);
    const summary = computeWeekSummary({ entries, employees }, { entries });
    expect(summaryTotalsMetrics(summary, { compact: true }).map((m) => m.label)).toEqual([
      "Employees", "Gross hrs", "Break hrs", "Net hrs",
    ]);
    const lines = summaryRoleLines(summary);
    expect(lines.map((l) => l.label)).toEqual(["Rinse WF"]);
    expect(lines[0].items.map((i) => i.label)).toEqual(["Wash", "Sort", "Fold"]);
    expect(lines[0].items.find((i) => i.role === "fold").value).toBe("1 person · 7.5 hours");
    const html = renderToString(<WeeklyScheduleSummaryBar summary={summary} compact />);
    expect(html).toContain('data-summary-line="totals"');
    expect(html).toContain('data-summary-line="rinse_wf"');
    expect(html).toContain("Rinse WF");
    const text = summaryTextLines(summary);
    expect(text[0]).toContain("Net hrs: 19");
    expect(text[1]).toMatch(/^Rinse WF: Wash 1 person · 7.5 hours \| Sort 1 person · 4 hours \| Fold 1 person · 7.5 hours$/);
    expect(renderToString(<WeeklyScheduleSummaryPrint summary={summary} />)).toContain("Rinse WF: Wash");
  });

  it("keeps the gross label and the unallocated break line for a multi-role shift", () => {
    const multi = shift(4, 1, 3, "08:00", "16:00", ["wash", "fold"], { break_minutes: 30 });
    const summary = computeWeekSummary({ entries: [multi], employees }, { entries: [multi], roles: ["fold"] });
    const html = renderToString(<WeeklyScheduleSummaryBar summary={summary} compact />);
    expect(html).toContain("1 person · 4 gross hours");
    expect(html).toContain("Unallocated break");
    expect(html).toContain("Hours (gross of unallocated break)");
  });

  it("replaces zero totals with the select-all prompt", () => {
    const summary = computeWeekSummary({ entries, employees }, { entries, roles: [] });
    const html = renderToString(<WeeklyScheduleSummaryBar summary={summary} compact noRolesSelected onSelectAllRoles={() => {}} />);
    expect(html).toContain("No roles selected—");
    expect(html).toContain("Select all");
    expect(html).not.toContain("Net hrs");
  });
});

describe("role selection", () => {
  const universe = ["wash", "sort", "fold", "attendant"];
  it("starts with every role selected and toggles in place", () => {
    expect(isCodeSelected(null, "fold")).toBe(true);
    expect(selectedCountIn(null, ["wash", "fold"])).toBe(2);
    const withoutFold = toggleSelectionCode(null, "fold", universe);
    expect(withoutFold).toEqual(["wash", "sort", "attendant"]);
    expect(toggleSelectionCode(withoutFold, "fold", universe)).toBeNull();
  });

  it("keeps choices from another tab and detects when nothing shown is selected", () => {
    const attendantOnly = ["attendant"];
    expect(noneSelectedIn(attendantOnly, ["wash", "sort", "fold"])).toBe(true);
    expect(noneSelectedIn([], ["wash"])).toBe(true);
    expect(noneSelectedIn(null, ["wash"])).toBe(false);
    expect(toggleSelectionCode(attendantOnly, "fold", universe)).toEqual(["attendant", "fold"]);
  });
});
