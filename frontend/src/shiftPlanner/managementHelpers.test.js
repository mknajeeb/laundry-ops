import { describe, expect, it } from "vitest";
import {
  applyPersistedPlannerParams,
  buildManagementPayload,
  buildPlanningBlocks,
  buildPlanningSlotViewModel,
  buildPositionFlowDisplay,
  buildStagePositionDisplay,
  fillRestBasePeopleForRole,
  formatBlockStaffingLine,
  formatCollapsedSlotStaffLine,
  formatHybridStaffChips,
  formatManagementOutcome,
  getAdditionalForBlock,
  getBasePeopleForBlock,
  getHybridPeopleForBlock,
  indexBlockPositionsByEnd,
  intervalsOverlap,
  parseClockToSec,
  pickPersistedPlannerParams,
  setBasePeopleForBlock,
  setHybridPeopleForBlock,
  stageRemaining,
  validateManagementPlanInputs,
  validatePersistedPlannerParams,
  validateStaffingIntervals,
} from "./managementHelpers";
import { DEFAULT_MANAGEMENT_INPUTS, PERSISTED_PLANNER_PARAM_KEYS } from "./managementConstants";

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
    expect(body.avg_lbs_per_bag).toBe(20);
    expect(body.two_washer_split_pct).toBe(80);
    expect(body.two_dryer_split_pct).toBe(80);
  });

  it("validates avg weight and split percentage bounds", () => {
    expect(validateManagementPlanInputs(DEFAULT_MANAGEMENT_INPUTS).ok).toBe(true);
    expect(validateManagementPlanInputs({ ...DEFAULT_MANAGEMENT_INPUTS, avg_lbs_per_bag: 0 }).ok).toBe(false);
    expect(validateManagementPlanInputs({ ...DEFAULT_MANAGEMENT_INPUTS, two_washer_split_pct: 101 }).ok).toBe(false);
    expect(validateManagementPlanInputs({ ...DEFAULT_MANAGEMENT_INPUTS, two_dryer_split_pct: -1 }).ok).toBe(false);
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

  it("Fill rest copies only the selected role into later blocks", () => {
    const blocks = buildPlanningBlocks("9:00 AM", "12:00 PM", 60);
    let intervals = [];
    intervals = setBasePeopleForBlock(intervals, "folder", "9:00 AM", "10:00 AM", 6);
    intervals = setBasePeopleForBlock(intervals, "weigher", "9:00 AM", "10:00 AM", 1);
    intervals = setBasePeopleForBlock(intervals, "sorter", "9:00 AM", "10:00 AM", 1);
    intervals = setBasePeopleForBlock(intervals, "washer", "9:00 AM", "10:00 AM", 1);
    intervals = setBasePeopleForBlock(intervals, "dryer", "9:00 AM", "10:00 AM", 1);
    // Later blocks start empty / different.
    intervals = setBasePeopleForBlock(intervals, "folder", "10:00 AM", "11:00 AM", 2);
    intervals = setBasePeopleForBlock(intervals, "sorter", "10:00 AM", "11:00 AM", 3);

    const afterFold = fillRestBasePeopleForRole(intervals, "folder", blocks, 6);
    expect(getBasePeopleForBlock(afterFold, "folder", "9:00 AM")).toBe(6);
    expect(getBasePeopleForBlock(afterFold, "folder", "10:00 AM")).toBe(6);
    expect(getBasePeopleForBlock(afterFold, "folder", "11:00 AM")).toBe(6);
    // Other roles unchanged.
    expect(getBasePeopleForBlock(afterFold, "weigher", "9:00 AM")).toBe(1);
    expect(getBasePeopleForBlock(afterFold, "weigher", "10:00 AM")).toBe(0);
    expect(getBasePeopleForBlock(afterFold, "sorter", "10:00 AM")).toBe(3);
    expect(getBasePeopleForBlock(afterFold, "washer", "9:00 AM")).toBe(1);
    expect(getBasePeopleForBlock(afterFold, "dryer", "9:00 AM")).toBe(1);

    const afterWeigh = fillRestBasePeopleForRole(afterFold, "weigher", blocks, 1);
    expect(getBasePeopleForBlock(afterWeigh, "weigher", "9:00 AM")).toBe(1);
    expect(getBasePeopleForBlock(afterWeigh, "weigher", "10:00 AM")).toBe(1);
    expect(getBasePeopleForBlock(afterWeigh, "weigher", "11:00 AM")).toBe(1);
    expect(getBasePeopleForBlock(afterWeigh, "folder", "10:00 AM")).toBe(6);
    expect(getBasePeopleForBlock(afterWeigh, "sorter", "10:00 AM")).toBe(3);
  });

  it("Fill rest propagates zero and leaves temps / first block alone", () => {
    const blocks = buildPlanningBlocks("9:00 AM", "11:00 AM", 60);
    let intervals = [
      {
        id: "temp-sort",
        role: "sorter",
        people: 1,
        start: "9:15 AM",
        end: "9:45 AM",
        mode: "additional",
      },
    ];
    intervals = setBasePeopleForBlock(intervals, "weigher", "9:00 AM", "10:00 AM", 0);
    intervals = setBasePeopleForBlock(intervals, "weigher", "10:00 AM", "11:00 AM", 2);
    intervals = setBasePeopleForBlock(intervals, "sorter", "9:00 AM", "10:00 AM", 1);

    const next = fillRestBasePeopleForRole(intervals, "weigher", blocks, 0);
    expect(getBasePeopleForBlock(next, "weigher", "9:00 AM")).toBe(0);
    expect(getBasePeopleForBlock(next, "weigher", "10:00 AM")).toBe(0);
    expect(getBasePeopleForBlock(next, "sorter", "9:00 AM")).toBe(1);
    expect(getAdditionalForBlock(next, "sorter", "9:00 AM", "10:00 AM")).toHaveLength(1);

    // Later block remains independently editable after fill.
    const edited = setBasePeopleForBlock(next, "weigher", "10:00 AM", "11:00 AM", 4);
    expect(getBasePeopleForBlock(edited, "weigher", "9:00 AM")).toBe(0);
    expect(getBasePeopleForBlock(edited, "weigher", "10:00 AM")).toBe(4);
  });

  it("getBasePeopleForBlock reveals mid-block BASE that does not cover block start", () => {
    const intervals = [
      {
        id: "mid",
        role: "sorter",
        people: 1,
        start: "5:30 AM",
        end: "6:00 AM",
        mode: "base",
      },
      {
        id: "temp",
        role: "sorter",
        people: 2,
        start: "5:30 AM",
        end: "6:00 AM",
        mode: "additional",
      },
    ];
    // Old bug: only checked coverage at 5:00 → showed 0 while DES had 3 sorter slots.
    expect(getBasePeopleForBlock(intervals, "sorter", "5:00 AM")).toBe(0);
    expect(getBasePeopleForBlock(intervals, "sorter", "5:00 AM", "6:00 AM")).toBe(1);
    expect(getAdditionalForBlock(intervals, "sorter", "5:00 AM", "6:00 AM")).toHaveLength(1);
  });

  it("hybrid block helpers author weigh_wash without dedicated role inflation", () => {
    let hybrids = setHybridPeopleForBlock([], "weigh_wash", "9:00 AM", "10:00 AM", 1);
    expect(getHybridPeopleForBlock(hybrids, "weigh_wash", "9:00 AM", "10:00 AM")).toBe(1);
    expect(getHybridPeopleForBlock(hybrids, "wash_dry", "9:00 AM", "10:00 AM")).toBe(0);

    const body = buildManagementPayload({
      ...DEFAULT_MANAGEMENT_INPUTS,
      staffing_intervals: [
        {
          id: "s1",
          role: "sorter",
          people: 1,
          start: "9:00 AM",
          end: "10:00 AM",
          mode: "base",
        },
      ],
      hybrid_intervals: hybrids,
    });
    const kinds = body.staffing_plan.intervals.map((row) => row.hybrid || row.role);
    expect(kinds).toContain("sorter");
    expect(kinds).toContain("weigh_wash");
    expect(body.staffing_plan.intervals.filter((r) => r.hybrid === "weigh_wash")).toHaveLength(1);
    expect(body.staffing_plan.intervals.every((r) => r.role !== "weigher" || r.hybrid)).toBe(true);

    hybrids = setHybridPeopleForBlock(hybrids, "weigh_wash", "9:00 AM", "10:00 AM", 0);
    expect(getHybridPeopleForBlock(hybrids, "weigh_wash", "9:00 AM", "10:00 AM")).toBe(0);
  });

  it("indexBlockPositionsByEnd never lets next block_start overwrite prior block_end", () => {
    const rows = [
      {
        block_start: "5:00 AM",
        block_end: "6:00 AM",
        sorted_this_block: 12,
        washed_this_block: 0,
      },
      {
        block_start: "6:00 AM",
        block_end: "7:00 AM",
        sorted_this_block: 0,
        washed_this_block: 8,
      },
    ];
    const map = indexBlockPositionsByEnd(rows);
    expect(map["6:00 AM"].sorted_this_block).toBe(12);
    expect(map["6:00 AM"].washed_this_block).toBe(0);
    expect(map["7:00 AM"].washed_this_block).toBe(8);
    // Collision bug previously set map['6:00 AM'] from the second row's block_start.
    expect(map["6:00 AM"].block_end).toBe("6:00 AM");
  });

  it("stage remaining is target minus stage done and never negative", () => {
    expect(stageRemaining(50, 32)).toBe(18);
    expect(stageRemaining(50, 50)).toBe(0);
    expect(stageRemaining(50, 60)).toBe(0);
    expect(stageRemaining(50, null)).toBe(50);
  });

  it("buildStagePositionDisplay prioritizes done/remaining and Fold COMPLETE label", () => {
    const sort = buildStagePositionDisplay({
      title: "SORT",
      thisBlock: 12,
      stageTotal: 32,
      targetBags: 50,
    });
    expect(sort.done).toBe(32);
    expect(sort.remaining).toBe(18);
    expect(sort.done + sort.remaining).toBe(50);
    expect(sort.doneLabel).toBe("DONE");
    expect(sort.thisBlockLabel).toBe("+12 this slot");

    const fold = buildStagePositionDisplay({
      title: "FOLD",
      thisBlock: 10,
      stageTotal: 16,
      targetBags: 50,
      completeLabel: true,
    });
    expect(fold.done).toBe(16);
    expect(fold.remaining).toBe(34);
    expect(fold.doneLabel).toBe("COMPLETE");
  });

  it("buildPositionFlowDisplay keeps waiting separate from remaining and uses wash/dry totals", () => {
    const flow = buildPositionFlowDisplay(
      {
        weighed_this_block: 18,
        weighed_total: 34,
        sorted_this_block: 15,
        sorted_total: 31,
        washed_this_block: 14,
        washed_total: 20,
        dried_this_block: 12,
        dried_total: 17,
        folded_this_block: 10,
        folded_total: 16,
        waiting_to_sort: 3,
        waiting_to_wash: 11,
        waiting_to_dry: 4,
        waiting_to_fold: 7,
        in_wash_cycle: 2,
        in_dry_cycle: 2,
      },
      50,
    );
    expect(flow.stages.weigh).toMatchObject({ done: 34, remaining: 16, thisBlock: 18 });
    expect(flow.stages.sort).toMatchObject({ done: 31, remaining: 19, thisBlock: 15 });
    expect(flow.stages.wash).toMatchObject({
      done: 20,
      remaining: 30,
      thisBlock: 14,
      doneLabel: "DONE",
      inCycle: 2,
      inCycleLabel: "2 IN CYCLE",
    });
    expect(flow.stages.dry).toMatchObject({
      done: 17,
      remaining: 33,
      thisBlock: 12,
      doneLabel: "DONE",
      inCycle: 2,
      inCycleLabel: "2 IN CYCLE",
    });
    expect(flow.stages.fold).toMatchObject({
      done: 16,
      remaining: 34,
      thisBlock: 10,
      doneLabel: "COMPLETE",
    });
    // Waiting ≠ remaining
    expect(flow.waiting.to_wash).toBe(11);
    expect(flow.stages.sort.remaining).toBe(19);
    expect(flow.waiting.to_wash).not.toBe(flow.stages.sort.remaining);
    // Target reconciliation for every stage
    for (const stage of Object.values(flow.stages)) {
      expect(stage.done + stage.remaining).toBe(50);
    }
  });

  it("one planning slot view model combines staffing start and end POSITION", () => {
    const slots = [
      { block_start: "5:00 AM", block_end: "6:00 AM" },
      { block_start: "6:00 AM", block_end: "7:00 AM" },
    ].map((pb) =>
      buildPlanningSlotViewModel({
        blockStart: pb.block_start,
        blockEnd: pb.block_end,
        staffingIntervals: [
          {
            id: "w",
            role: "weigher",
            people: 1,
            start: "5:00 AM",
            end: "7:00 AM",
            mode: "base",
          },
          {
            id: "s",
            role: "sorter",
            people: 1,
            start: "5:00 AM",
            end: "6:00 AM",
            mode: "base",
          },
        ],
        hybridIntervals: [
          {
            id: "h",
            hybrid: "weigh_wash",
            people: 1,
            start: "6:00 AM",
            end: "7:00 AM",
            mode: "base",
          },
        ],
        positionBlock: {
          washed_this_block: 2,
          washed_total: 18,
          dried_this_block: 0,
          dried_total: 0,
          folded_this_block: 0,
          folded_total: 0,
          weighed_this_block: 0,
          weighed_total: 80,
          sorted_this_block: 0,
          sorted_total: 22,
          waiting_to_sort: 0,
          waiting_to_wash: 0,
          waiting_to_dry: 0,
          waiting_to_fold: 0,
          in_wash_cycle: 2,
          in_dry_cycle: 2,
        },
        targetBags: 100,
        staffingExpanded: false,
      }),
    );

    // 1. One slot → one combined view model (not separate staff/position cards)
    expect(slots).toHaveLength(2);
    expect(slots[0].slotLabel).toBe("5:00 AM → 6:00 AM");
    expect(slots[1].slotLabel).toBe("6:00 AM → 7:00 AM");

    // 2. Start staffing + end position in same model
    expect(slots[0].blockStart).toBe("5:00 AM");
    expect(slots[0].positionLabel).toBe("6:00 AM POSITION");
    expect(slots[0].flow).toBeTruthy();

    // 3–4. Collapsed staff line includes dedicated + compact hybrid chip
    expect(formatCollapsedSlotStaffLine(
      [
        { role: "weigher", people: 0, start: "6:00 AM", end: "7:00 AM", mode: "base" },
        { role: "sorter", people: 1, start: "6:00 AM", end: "7:00 AM", mode: "base" },
        { role: "dryer", people: 1, start: "6:00 AM", end: "7:00 AM", mode: "base" },
        { role: "folder", people: 2, start: "6:00 AM", end: "7:00 AM", mode: "base" },
      ],
      [{ hybrid: "weigh_wash", people: 1, start: "6:00 AM", end: "7:00 AM", mode: "base" }],
      "6:00 AM",
      "7:00 AM",
    )).toBe("Weigh 0 · Sort 1 · Wash 0 · Dry 1 · Fold 2 · Hybrid W/W 1");
    expect(formatHybridStaffChips(
      [{ hybrid: "weigh_wash", people: 1, start: "6:00 AM", end: "7:00 AM", mode: "base" }],
      "6:00 AM",
      "7:00 AM",
    )).toEqual(["Hybrid W/W 1"]);

    // 6–10. Position concepts + in-cycle; Dry DONE may be 0 with IN CYCLE > 0
    const seven = slots[1].flow;
    expect(seven.stages.wash.thisBlockLabel).toContain("this slot");
    expect(seven.stages.wash).toMatchObject({
      thisBlock: 2,
      done: 18,
      remaining: 82,
      inCycleLabel: "2 IN CYCLE",
    });
    expect(seven.stages.dry).toMatchObject({
      thisBlock: 0,
      done: 0,
      remaining: 100,
      inCycle: 2,
      inCycleLabel: "2 IN CYCLE",
    });
    expect(seven.stages.fold.doneLabel).toBe("COMPLETE");

    // 7. Waiting queues between stages stay distinct keys
    expect(seven.waiting).toEqual({
      to_sort: 0,
      to_wash: 0,
      to_dry: 0,
      to_fold: 0,
    });

    // 12. Multiple slots stay compact (one model each)
    expect(slots.every((s) => s.slotKey && s.staffLine && s.positionLabel)).toBe(true);
  });

  it("reads in_wash_cycle / in_dry_cycle from detail when flat keys absent", () => {
    const flow = buildPositionFlowDisplay(
      {
        washed_this_block: 2,
        washed_total: 18,
        dried_this_block: 0,
        dried_total: 0,
        weighed_this_block: 0,
        weighed_total: 80,
        sorted_this_block: 0,
        sorted_total: 22,
        folded_this_block: 0,
        folded_total: 0,
        waiting_to_sort: 0,
        waiting_to_wash: 0,
        waiting_to_dry: 0,
        waiting_to_fold: 0,
        detail: { in_wash_cycle: 2, in_dry_cycle: 2 },
      },
      100,
    );
    expect(flow.stages.wash.inCycle).toBe(2);
    expect(flow.stages.dry.inCycle).toBe(2);
    expect(flow.stages.dry.done).toBe(0);
  });

  it("pickPersistedPlannerParams excludes staffing and session-only fields", () => {
    const picked = pickPersistedPlannerParams({
      ...DEFAULT_MANAGEMENT_INPUTS,
      bag_count: 77,
      staffing_intervals: [{ id: "x" }],
      avg_lbs_per_bag: 25,
      two_washer_split_pct: 50,
    });
    expect(picked.bag_count).toBe(77);
    expect(picked.staffing_intervals).toBeUndefined();
    expect(picked.avg_lbs_per_bag).toBeUndefined();
    expect(Object.keys(picked).sort()).toEqual([...PERSISTED_PLANNER_PARAM_KEYS].sort());
  });

  it("applyPersistedPlannerParams restores saved values without touching staffing", () => {
    const staffing = [{ id: "keep", role: "sorter", people: 2, start: "9:00 AM", end: "10:00 AM", mode: "base" }];
    const next = applyPersistedPlannerParams(
      { ...DEFAULT_MANAGEMENT_INPUTS, bag_count: 10, staffing_intervals: staffing },
      { bag_count: 90, wash_cycle_min: 35 },
    );
    expect(next.bag_count).toBe(90);
    expect(next.wash_cycle_min).toBe(35);
    expect(next.staffing_intervals).toEqual(staffing);
  });

  it("validatePersistedPlannerParams rejects invalid values and accepts defaults", () => {
    expect(validatePersistedPlannerParams(DEFAULT_MANAGEMENT_INPUTS).ok).toBe(true);
    expect(validatePersistedPlannerParams({ ...DEFAULT_MANAGEMENT_INPUTS, bag_count: -1 }).ok).toBe(false);
    expect(validatePersistedPlannerParams({
      ...DEFAULT_MANAGEMENT_INPUTS,
      start_time: "3:00 PM",
      target_time: "9:00 AM",
    }).ok).toBe(false);
    expect(validatePersistedPlannerParams({
      ...DEFAULT_MANAGEMENT_INPUTS,
      planning_block_size_min: 15,
    }).ok).toBe(false);
    expect(validatePersistedPlannerParams({
      ...DEFAULT_MANAGEMENT_INPUTS,
      washer_count: 0,
    }).ok).toBe(false);
    expect(validatePersistedPlannerParams({
      ...DEFAULT_MANAGEMENT_INPUTS,
      weigh_sec_per_bag: 0,
    }).ok).toBe(false);
  });

  it("Fill rest does not mutate plan/machine/process fields when applied via payload inputs", () => {
    const blocks = buildPlanningBlocks("9:00 AM", "11:00 AM", 60);
    const inputs = {
      ...DEFAULT_MANAGEMENT_INPUTS,
      bag_count: 50,
      washer_count: 4,
      dryer_count: 4,
      weigh_sec_per_bag: 45,
      staffing_intervals: setBasePeopleForBlock([], "folder", "9:00 AM", "10:00 AM", 6),
    };
    const nextIntervals = fillRestBasePeopleForRole(inputs.staffing_intervals, "folder", blocks, 6);
    const body = buildManagementPayload({ ...inputs, staffing_intervals: nextIntervals });
    expect(body.bag_count).toBe(50);
    expect(body.washer_count).toBe(4);
    expect(body.dryer_count).toBe(4);
    expect(body.weigh_sec_per_bag).toBe(45);
    expect(body.start_time).toBe("9:00 AM");
    expect(body.target_time).toBe("3:00 PM");
  });
});
