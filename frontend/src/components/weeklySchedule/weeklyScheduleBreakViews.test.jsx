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
import {
  computeFilteredDaySummaries,
  computeWeekSummary,
  makeBreakSlot,
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
        <WeeklyScheduleBreaksTasksView weekStart="2026-10-04" days={days} columns={columns} responsibilities={responsibilities}
          employeesById={byId} canEdit />,
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
      "On break", "Breaks without a time", "Not scheduled", "Set time", "Tasks per employee", "Unassigned",
      "Break 12 PM", "7.5h net", "Gross 16", "Net hrs", "Dryers 1-12", "Gross 8 · Break 0.5 · Net 7.5",
    ]) {
      expect(html, text).toContain(text.replace(/&/g, "&amp;"));
    }
  });
});
