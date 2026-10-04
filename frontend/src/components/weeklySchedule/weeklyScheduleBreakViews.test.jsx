import React from "react";
import { renderToString } from "react-dom/server";
import { describe, expect, it } from "vitest";
import WeeklyScheduleBreaksTasksView from "./WeeklyScheduleBreaksTasksView";
import WeeklyScheduleTimeRoleView from "./WeeklyScheduleTimeRoleView";
import WeeklyScheduleShiftCard from "./WeeklyScheduleShiftCard";
import WeeklyScheduleBreakFields from "./WeeklyScheduleBreakFields";
import WeeklyScheduleHoursSummary from "./WeeklyScheduleHoursSummary";
import WeeklyScheduleSummaryBar from "./WeeklyScheduleSummaryBar";
import WeeklyScheduleDayHeader from "./WeeklyScheduleDayHeader";
import WeeklyScheduleTimeRolePrint from "./WeeklyScheduleTimeRolePrint";
import WeeklySchedulePrintTable from "./WeeklySchedulePrintTable";
import { buildHourlyCoverage, coverageColumns } from "./weeklyScheduleTimeBlocks";
import { buildBreaksTasksGrid } from "./weeklyScheduleBreaksGrid";
import WeeklyScheduleEmployeeCell from "./WeeklyScheduleEmployeeCell";
import {
  computeFilteredDaySummaries,
  computeWeekSummary,
  makeBreakSlot,
  scheduleEntryKey,
  summarizeRoleSelection,
  summarizeScheduleHours,
  withDisplayedTotals,
} from "./weeklyScheduleRoles";

const employees = [
  { user_id: 1, display_name: "Ana" },
  { user_id: 2, display_name: "Ben" },
];
const byId = Object.fromEntries(employees.map((e) => [e.user_id, e]));
const entries = [
  {
    id: 1, user_id: 1, day_of_week: 1, start_time: "09:00", end_time: "17:00", hours: 7.5, break_minutes: 30,
    role: "fold", roles: ["fold"], assignments: [{ role: "fold", full_shift: true }],
    break_slots: [{ start_time: "12:00", end_time: "12:30" }],
  },
  {
    id: 2, user_id: 2, day_of_week: 1, start_time: "09:00", end_time: "17:00", hours: 7.5, break_minutes: 30,
    role: "wash", roles: ["wash"], assignments: [{ role: "wash", full_shift: true }],
  },
];
const responsibilities = [{ id: 9, user_id: 1, day_of_week: 1, role: "lint_cleaning", remarks: "Dryers 1-12" }];

describe("break and task views", () => {
  it("renders every view without throwing", () => {
    const days = buildHourlyCoverage(entries, { dayIndices: [1], employeesById: byId, responsibilities });
    const columns = coverageColumns(days);
    const summary = summarizeScheduleHours(entries, new Map(employees.map((e) => [e.user_id, e])));
    const html = [
      renderToString(
        <WeeklyScheduleBreaksTasksView
          weekStart="2026-10-04"
          grid={buildBreaksTasksGrid({ days, dayIndices: [1], shiftEntries: entries, responsibilities, employeesById: byId })}
          canEdit
        />,
      ),
      renderToString(<WeeklyScheduleTimeRoleView weekStart="2026-10-04" days={days} columns={columns} showNames canEdit />),
      renderToString(<WeeklyScheduleShiftCard entry={entries[0]} employee={employees[0]} />),
      renderToString(<WeeklyScheduleShiftCard entry={entries[1]} employee={employees[1]} />),
      renderToString(
        <WeeklyScheduleBreakFields startTime="09:00" endTime="17:00" slots={[makeBreakSlot({ start_time: "12:00", end_time: "12:30" })]}
          onSlotsChange={() => {}} unscheduledMinutes={15} onUnscheduledChange={() => {}} />,
      ),
      renderToString(<WeeklyScheduleHoursSummary summary={summary} />),
      renderToString(<WeeklyScheduleSummaryBar summary={computeWeekSummary({ entries, employees }, { entries })} compact />),
      renderToString(<WeeklyScheduleDayHeader dayLabel="Mon" summary={computeFilteredDaySummaries({ entries, employees }, { entries })[1]} compact />),
      renderToString(<WeeklyScheduleTimeRolePrint days={days} weekStart="2026-10-04" columns={columns} showNames hoursSummary={summary} />),
      renderToString(
        <WeeklySchedulePrintTable employees={withDisplayedTotals(employees, entries)} entries={entries} dayLabels={["Mon"]} dayIndices={[1]}
          daySummaries={computeFilteredDaySummaries({ entries, employees }, { entries })} showBreaks />,
      ),
    ].join("\n");
    for (const text of [
      "On break", "Breaks without a time", "Not scheduled", "Set time", "Unassigned tasks",
      "Break 12 PM", "7.5h net", "Gross 16", "Net hrs", "Dryers 1-12", "Gross 8 · Break 0.5 · Net 7.5",
    ]) {
      expect(html, text).toContain(text.replace(/&/g, "&amp;"));
    }
  });

  it("renders role-scoped summaries, chips, and cards for a role selection", () => {
    const roles = ["fold"];
    const { entryScopes } = summarizeRoleSelection(entries, { roles });
    const [ana] = withDisplayedTotals(employees, entries, { roles });
    const html = [
      renderToString(<WeeklyScheduleSummaryBar summary={computeWeekSummary({ entries, employees }, { entries, roles })} compact />),
      renderToString(
        <WeeklyScheduleDayHeader dayLabel="Mon" summary={computeFilteredDaySummaries({ entries, employees }, { entries, roles })[1]} compact />,
      ),
      renderToString(<WeeklyScheduleEmployeeCell employee={ana} />),
      renderToString(
        <WeeklyScheduleShiftCard entry={entries[0]} employee={employees[0]} roleFilter={roles} roleScope={entryScopes.get(scheduleEntryKey(entries[0]))} />,
      ),
    ].join("\n");
    for (const text of ["Selected roles", "1 person", "Fold", "1 person · 7.5 hours", "Fold: 1 person · 7.5 hrs", "Fold · 7.5 hrs", "7.5h net Fold"]) {
      expect(html, text).toContain(text);
    }
    expect(html).not.toContain("Wash");
  });

  it("labels role hours gross and shows the unallocated break when a multi-role shift's break has no time", () => {
    const multi = {
      id: 3, user_id: 1, day_of_week: 1, start_time: "08:00", end_time: "16:00", hours: 7.5, break_minutes: 30,
      role: "wash,fold", roles: ["wash", "fold"],
      assignments: [{ role: "wash", full_shift: true }, { role: "fold", full_shift: true }],
    };
    const list = [multi];
    const roles = ["fold"];
    const days = buildHourlyCoverage(list, { dayIndices: [1], employeesById: byId, roles });
    const summary = summarizeScheduleHours(list, new Map(employees.map((e) => [e.user_id, e])));
    const { entryScopes } = summarizeRoleSelection(list, { roles });
    const html = [
      renderToString(<WeeklyScheduleTimeRoleView weekStart="2026-10-04" days={days} columns={["fold"]} showNames />),
      renderToString(<WeeklyScheduleHoursSummary summary={summary} />),
      renderToString(<WeeklyScheduleSummaryBar summary={computeWeekSummary({ entries: list, employees }, { entries: list, roles })} />),
      renderToString(
        <WeeklyScheduleDayHeader dayLabel="Mon" summary={computeFilteredDaySummaries({ entries: list, employees }, { entries: list, roles })[1]} />,
      ),
      renderToString(<WeeklyScheduleShiftCard entry={multi} employee={employees[0]} />),
      renderToString(
        <WeeklyScheduleShiftCard entry={multi} employee={employees[0]} roleFilter={roles} roleScope={entryScopes.get(scheduleEntryKey(multi))} />,
      ),
      renderToString(<WeeklyScheduleTimeRolePrint days={days} weekStart="2026-10-04" columns={["fold"]} hoursSummary={summary} />),
    ].join("\n");
    for (const text of [
      "Hourly figures are gross of",
      "4h gross",
      "not allocated to a role",
      "Net hours by role unresolved until the break is scheduled",
      "Breaks without a time not allocated to a role",
      "1 person · 4 gross hours",
      "4h gross Fold",
      "7.5h net · 8h gross",
    ]) {
      expect(html, text).toContain(text);
    }
    expect(html).not.toContain("4h net Fold");
  });
});
