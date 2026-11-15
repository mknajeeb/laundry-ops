import { describe, expect, it } from "vitest";
import { buildOperationsPrintHtml, dayBreakDetail, describeRoleHourDisplay, roleTimelineFromCoverage, shiftRoleSegments, taskStatusRollup } from "./operationsPlannerModel";

describe("operations planner model", () => {
  it("counts a shared group once and keeps awaiting verification out of approved", () => {
    const rollup = taskStatusRollup(
      [
        { id: 1, user_id: 1, day_of_week: 1, role: "floor_cleaning", activity_status: "completed", assignment_group_id: "g1", execution_mode: "shared" },
        { id: 2, user_id: 2, day_of_week: 1, role: "floor_cleaning", activity_status: "pending_approval", assignment_group_id: "g1", execution_mode: "shared" },
        { id: 3, user_id: 3, day_of_week: 1, role: "washer_cleaning", activity_status: "approved" },
      ],
      { 1: { display_name: "Ana" }, 2: { display_name: "Ben" }, 3: { display_name: "Cam" } },
    );
    expect(rollup.byGroup.total).toBe(2);
    expect(rollup.byGroup.shared).toBe(1);
    expect(rollup.byGroup.awaiting).toBe(1);
    expect(rollup.byGroup.verified).toBe(1);
    expect(rollup.people.total).toBe(3);
    expect(rollup.people.awaiting).toBe(1);
    expect(rollup.people.completed).toBe(1);
    expect(rollup.people.verified).toBe(1);
  });

  it("keeps untimed breaks out of the overlap count and names the hot window", () => {
    const detail = dayBreakDetail(
      [
        { id: 1, user_id: 1, day_of_week: 1, break_slots: [{ start_time: "12:00", end_time: "12:30" }] },
        { id: 2, user_id: 2, day_of_week: 1, break_slots: [{ start_time: "12:00", end_time: "12:20" }] },
        { id: 3, user_id: 3, day_of_week: 1, break_slots: [{ start_time: "12:10", end_time: "12:40" }] },
        { id: 4, user_id: 4, day_of_week: 1, break_slots: [{ start_time: "12:00", end_time: "12:15" }] },
        { id: 5, user_id: 5, day_of_week: 1, unscheduled_break_minutes: 30 },
      ],
      {},
      1,
    );
    expect(detail.timed).toHaveLength(4);
    expect(detail.untimed).toHaveLength(1);
    expect(detail.maxOverlap).toBe(4);
    expect(detail.hot.length).toBeGreaterThan(0);
    expect(detail.hot[0].count).toBeGreaterThan(3);
  });

  it("splits a shift into the assigned role ranges", () => {
    const segments = shiftRoleSegments({
      id: 1,
      user_id: 1,
      day_of_week: 1,
      start_time: "07:00",
      end_time: "15:00",
      break_minutes: 30,
      break_slots: [{ start_time: "12:00", end_time: "12:30" }],
      assignments: [
        { role: "wash", full_shift: false, start_time: "07:00", end_time: "11:00" },
        { role: "fold", full_shift: false, start_time: "11:00", end_time: "15:00" },
      ],
    });
    expect(segments.map((segment) => segment.role)).toEqual(["wash", "fold"]);
    expect(segments[0].start).toBe("07:00");
    expect(segments[0].end).toBe("11:00");
    expect(segments[1].start).toBe("11:00");
    expect(segments[1].gross).toBeGreaterThan(segments[1].net);
  });

  it("prints the current planner scope with role hours and task states", () => {
    const html = buildOperationsPrintHtml({
      weekLabel: "Nov 9 – Nov 15",
      lens: "tasks",
      mode: "week",
      dayLabel: "Mon",
      employees: [{ user_id: 1, display_name: "Amna" }],
      dayColumns: [1],
      entriesByCell: {},
      responsibilitiesByCell: {
        "1:1": [{ id: 1, user_id: 1, day_of_week: 1, role: "floor_cleaning", activity_status: "pending_approval", assignment_group_id: "g", execution_mode: "shared" }],
      },
      weekSummary: { employeesScheduled: 1, grossHours: 8, totalHours: 7.5, roles: [{ role: "wash", label: "Wash", employees: 1, hours: 4 }] },
    });
    expect(html).toContain("weekly hours");
    expect(html).toContain("awaiting");
    expect(html).toContain("Shared");
    expect(html).not.toContain("Export Excel");
  });

  it("rounds each role on its own and leaves the week net rounded once", () => {
    const rows = [
      { role: "wash", hours: 115.16666666666667 },
      { role: "sort", hours: 85.16666666666666 },
      { role: "dry", hours: 83.16666666666666 },
      { role: "fold", hours: 98.16666666666666 },
      { role: "hd_operator", hours: 101.75 },
    ];
    const weekNet = rows.reduce((sum, row) => sum + row.hours, 0);
    const display = describeRoleHourDisplay(rows, weekNet);
    expect(display.sourceAgrees).toBe(true);
    expect(display.shown).toEqual([115.2, 85.2, 83.2, 98.2, 101.8]);
    expect(display.shown[0]).toBe(115.2);
    expect(display.weekShown).toBe(483.4);
    expect(display.shownSum).toBeCloseTo(483.6, 5);
    expect(display.displayGap).toBeCloseTo(0.2, 5);
    expect(describeRoleHourDisplay([{ hours: 8 }], 4).shown).toEqual([8]);
  });

  it("keeps hourly staffing and break overlays on the coverage timeline", () => {
    const timeline = roleTimelineFromCoverage({
      hours: [
        {
          hour: 7,
          label: "7–8 AM",
          cells: { wash: { hours: 2, count: 2, people: [{ name: "Amna", rangeLabel: "7:00–8:00 AM", hours: 1 }, { name: "Luis", rangeLabel: "7:00–8:00 AM", hours: 1 }] } },
          breaks: { people: [] },
        },
        {
          hour: 12,
          label: "12–1 PM",
          cells: { wash: { hours: 1, count: 1, people: [{ name: "Luis", rangeLabel: "12:00–1:00 PM", hours: 1 }] } },
          breaks: { people: [{ name: "Amna", roles: ["fold"], rangeLabel: "12:00–12:30 PM", hours: 0.5 }, { name: "Luis", roles: ["wash"], rangeLabel: "12:00–12:30 PM", hours: 0.5 }] },
        },
      ],
      columns: ["wash"],
      totals: { wash: { count: 2, hours: 27.5, net: 27.2 } },
    });
    expect(timeline.roles[0].gross).toBe(27.5);
    expect(timeline.roles[0].net).toBe(27.2);
    expect(timeline.roles[0].slices[0].scheduledCount).toBe(2);
    expect(timeline.roles[0].slices[0].availableCount).toBe(2);
    expect(timeline.roles[0].slices[0].breakCount).toBe(0);
    expect(timeline.roles[0].slices[1].scheduledPeople.map((person) => person.name)).toEqual(["Luis"]);
    expect(timeline.roles[0].slices[1].breakPeople.map((person) => person.name)).toEqual(["Luis"]);
    expect(timeline.roles[0].slices[1].availableCount).toBe(0);
    expect(timeline.roles[0].slices[1].grossHours).toBe(1.5);
    expect(timeline.roles[0].slices[1].netHours).toBe(1);
    expect(timeline.roles[0].slices[1].people[0].range).toBe("12:00–1:00 PM");
  });
});
