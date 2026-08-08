import { describe, expect, it } from "vitest";
import {
  buildManagementPayload,
  buildPlanningBlocks,
  formatBlockStaffingLine,
  formatManagementOutcome,
  getBasePeopleForBlock,
  intervalsOverlap,
  parseClockToSec,
  setBasePeopleForBlock,
  validateStaffingIntervals,
} from "./managementHelpers";
import { DEFAULT_MANAGEMENT_INPUTS } from "./managementConstants";

describe("managementHelpers", () => {
  it("builds payload with management_mode, process params, and end_time=target", () => {
    const body = buildManagementPayload(DEFAULT_MANAGEMENT_INPUTS);
    expect(body.management_mode).toBe(true);
    expect(body.engine).toBe("bag_des_v2");
    expect(body.staffing_plan.intervals).toEqual([]);
    expect(body.employees).toBeUndefined();
    expect(body.end_time).toBe(body.target_time);
    expect(body.weigh_sec_per_bag).toBe(45);
    expect(body.sort_min_per_bag).toBe(5);
    expect(body.fold_rate_mode).toBe("minutes_per_bag");
  });

  it("preserves exact staffing times in payload", () => {
    const body = buildManagementPayload({
      ...DEFAULT_MANAGEMENT_INPUTS,
      staffing_intervals: [
        {
          id: "1",
          role: "sorter",
          people: 1,
          start: "9:15 AM",
          end: "9:45 AM",
          mode: "additional",
        },
      ],
    });
    expect(body.staffing_plan.intervals[0]).toMatchObject({
      role: "sorter",
      start: "9:15 AM",
      end: "9:45 AM",
      mode: "additional",
    });
  });

  it("rejects overlapping BASE for same role", () => {
    const v = validateStaffingIntervals(
      [
        { id: "a", role: "sorter", people: 1, start: "9:00 AM", end: "10:00 AM", mode: "base" },
        { id: "b", role: "sorter", people: 1, start: "9:30 AM", end: "10:30 AM", mode: "base" },
      ],
      { startTime: "9:00 AM", endTime: "3:00 PM" },
    );
    expect(v.ok).toBe(false);
    expect(v.errors[0].message).toMatch(/Sort base staffing already covers/i);
  });

  it("allows adjacent BASE and overlapping ADDITIONAL", () => {
    const v = validateStaffingIntervals(
      [
        { id: "a", role: "sorter", people: 1, start: "9:00 AM", end: "10:00 AM", mode: "base" },
        { id: "b", role: "sorter", people: 1, start: "10:00 AM", end: "11:00 AM", mode: "base" },
        { id: "c", role: "sorter", people: 1, start: "9:15 AM", end: "9:45 AM", mode: "additional" },
        { id: "d", role: "sorter", people: 1, start: "9:30 AM", end: "10:15 AM", mode: "additional" },
      ],
      { startTime: "9:00 AM", endTime: "3:00 PM" },
    );
    expect(v.ok).toBe(true);
  });

  it("rejects fractional people and out of bounds", () => {
    expect(
      validateStaffingIntervals(
        [{ id: "a", role: "washer", people: 1.5, start: "9:00 AM", end: "10:00 AM", mode: "base" }],
        { startTime: "9:00 AM", endTime: "3:00 PM" },
      ).ok,
    ).toBe(false);
    expect(
      validateStaffingIntervals(
        [{ id: "a", role: "washer", people: 1, start: "8:00 AM", end: "10:00 AM", mode: "base" }],
        { startTime: "9:00 AM", endTime: "3:00 PM" },
      ).ok,
    ).toBe(false);
  });

  it("formats stalled and finishes-late outcomes", () => {
    const stalled = formatManagementOutcome({
      management_outcome: {
        completion_status: "stalled",
        first_blocking_role: "washer",
        completed_by_target: 0,
        target_bags: 20,
      },
      staffing_deficits: [
        { role: "washer", reason: "NO_STAFF_AVAILABLE", blocked_bags: 20 },
      ],
      summary: {},
    });
    expect(stalled.statusLabel).toMatch(/Stalled at Wash/i);

    const late = formatManagementOutcome({
      inputs: { target_time: "12:00 PM" },
      management_outcome: {
        completion_status: "incomplete_by_target",
        projected_finish: "12:36 PM",
        completed_by_target: 40,
        target_bags: 50,
      },
      summary: { final_completion_time: "12:36 PM" },
    });
    expect(late.title).toMatch(/36 min late/);
  });

  it("formats block staffing with additional window", () => {
    const line = formatBlockStaffingLine({
      roles: {
        weigher: { people_at_block_start: 1, peak_people: 1, additional: [] },
        sorter: {
          people_at_block_start: 1,
          peak_people: 2,
          additional: [{ people: 1, start: "9:15 AM", end: "9:45 AM" }],
        },
        washer: { people_at_block_start: 1, peak_people: 1, additional: [] },
        dryer: { people_at_block_start: 1, peak_people: 1, additional: [] },
        folder: { people_at_block_start: 2, peak_people: 2, additional: [] },
      },
    });
    expect(line).toContain("Sort 1 (+1 9:15 AM–9:45 AM)");
    expect(line).toContain("Fold 2");
  });

  it("parses clocks and half-open overlaps", () => {
    expect(parseClockToSec("9:15 AM")).toBe(9 * 3600 + 15 * 60);
    expect(intervalsOverlap(0, 60, 60, 120)).toBe(false);
    expect(intervalsOverlap(0, 60, 30, 90)).toBe(true);
  });

  it("builds planning blocks from start to target", () => {
    const blocks = buildPlanningBlocks("9:00 AM", "12:00 PM", 60);
    expect(blocks).toHaveLength(3);
    expect(blocks[0]).toMatchObject({ block_start: "9:00 AM", block_end: "10:00 AM" });
    expect(blocks[2]).toMatchObject({ block_start: "11:00 AM", block_end: "12:00 PM" });
  });

  it("sets base for one block without wiping adjacent coverage", () => {
    const start = [
      { id: "a", role: "sorter", people: 1, start: "9:00 AM", end: "12:00 PM", mode: "base" },
    ];
    const next = setBasePeopleForBlock(start, "sorter", "10:00 AM", "11:00 AM", 2);
    expect(getBasePeopleForBlock(next, "sorter", "9:00 AM")).toBe(1);
    expect(getBasePeopleForBlock(next, "sorter", "10:00 AM")).toBe(2);
    expect(getBasePeopleForBlock(next, "sorter", "11:00 AM")).toBe(1);
  });
});
