import { describe, expect, it } from "vitest";
import {
  applyPersistedPlannerParams,
  buildManagementPayload,
  buildPlanningBlocks,
  buildPlanningSlotViewModel,
  buildPositionFlowDisplay,
  buildPositionInventoryDisplay,
  buildStagePositionDisplay,
  buildSlotStaffingNotes,
  dedicatedPeopleInSlot,
  fillRestBasePeopleForRole,
  fillRestHybridPeople,
  formatBlockStaffingLine,
  describeWorkCoverage,
  findWorkCoverageForHybrid,
  findWorkCoverageForRole,
  formatCollapsedSlotStaffLine,
  formatHybridRolesLabel,
  formatHybridStaffChips,
  formatManagementOutcome,
  formatSavedSimulationListChip,
  formatStageReconcile,
  buildSavedSimulationPayload,
  applySavedSimulationPayload,
  simulationInputsFingerprint,
  formatTempStaffChips,
  formatWaitingToSortHint,
  formatWorkCoverageDetail,
  formatWorkCoverageLine,
  getAdditionalForBlock,
  getBasePeopleForBlock,
  getHybridPeopleForBlock,
  indexBlockPositionsByEnd,
  intervalsOverlap,
  isHybridFillRestComplete,
  isRoleFillRestComplete,
  listHybridsForBlock,
  normalizeHybridRoles,
  parseClockToSec,
  pickPersistedPlannerParams,
  removeHybridInterval,
  setBasePeopleForBlock,
  setHybridPeopleForBlock,
  stageRemaining,
  upsertHybridInterval,
  validateHybridDraft,
  validateManagementPlanInputs,
  validatePersistedPlannerParams,
  validateStaffingIntervals,
} from "./managementHelpers";
import { DEFAULT_MANAGEMENT_INPUTS, PERSISTED_PLANNER_PARAM_KEYS } from "./managementConstants";

describe("managementHelpers", () => {
  it("custom hybrid upsert/edit/delete and rejects fewer than two roles", () => {
    expect(normalizeHybridRoles(["folder", "sorter", "sorter"])).toEqual(["sorter", "folder"]);
    expect(formatHybridRolesLabel(["washer", "dryer"])).toBe("Wash+Dry");
    expect(validateHybridDraft({ roles: ["washer"], people: 1, start: "9:00 AM", end: "10:00 AM" }).ok).toBe(false);

    let hybrids = upsertHybridInterval([], {
      id: "h1",
      roles: ["sorter", "folder"],
      people: 1,
      start: "9:00 AM",
      end: "10:00 AM",
      mode: "base",
    });
    expect(listHybridsForBlock(hybrids, "9:00 AM", "10:00 AM")).toHaveLength(1);
    expect(formatCollapsedSlotStaffLine(
      [],
      hybrids,
      "9:00 AM",
      "10:00 AM",
    )).toContain("Hybrid: Sort+Fold 1");

    hybrids = upsertHybridInterval(hybrids, {
      id: "h1",
      roles: ["washer", "dryer"],
      people: 2,
      start: "9:30 AM",
      end: "10:00 AM",
      mode: "additional",
    });
    expect(hybrids[0].roles).toEqual(["washer", "dryer"]);
    expect(hybrids[0].people).toBe(2);
    expect(hybrids[0].mode).toBe("additional");

    const body = buildManagementPayload({
      ...DEFAULT_MANAGEMENT_INPUTS,
      hybrid_intervals: hybrids,
    });
    expect(body.staffing_plan.intervals[0]).toMatchObject({
      roles: ["washer", "dryer"],
      people: 2,
      mode: "additional",
    });

    hybrids = removeHybridInterval(hybrids, "h1");
    expect(hybrids).toHaveLength(0);
  });

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
    expect(stalled.statusLabel).toMatch(/Cannot finish — needs Wash/i);

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

  it("Fill rest from first slot fills uncovered later blocks without overwriting explicit later BASE", () => {
    const blocks = buildPlanningBlocks("9:00 AM", "12:00 PM", 60);
    let intervals = [];
    intervals = setBasePeopleForBlock(intervals, "folder", "9:00 AM", "10:00 AM", 6);
    intervals = setBasePeopleForBlock(intervals, "weigher", "9:00 AM", "10:00 AM", 1);
    intervals = setBasePeopleForBlock(intervals, "sorter", "9:00 AM", "10:00 AM", 1);
    intervals = setBasePeopleForBlock(intervals, "washer", "9:00 AM", "10:00 AM", 1);
    intervals = setBasePeopleForBlock(intervals, "dryer", "9:00 AM", "10:00 AM", 1);
    // Explicit later BASE must be preserved.
    intervals = setBasePeopleForBlock(intervals, "folder", "10:00 AM", "11:00 AM", 2);
    intervals = setBasePeopleForBlock(intervals, "sorter", "10:00 AM", "11:00 AM", 3);

    const afterFold = fillRestBasePeopleForRole(intervals, "folder", blocks, 6, "9:00 AM");
    expect(getBasePeopleForBlock(afterFold, "folder", "9:00 AM")).toBe(6);
    expect(getBasePeopleForBlock(afterFold, "folder", "10:00 AM")).toBe(2); // preserved
    expect(getBasePeopleForBlock(afterFold, "folder", "11:00 AM")).toBe(6); // filled gap
    expect(getBasePeopleForBlock(afterFold, "weigher", "9:00 AM")).toBe(1);
    expect(getBasePeopleForBlock(afterFold, "weigher", "10:00 AM")).toBe(0);
    expect(getBasePeopleForBlock(afterFold, "sorter", "10:00 AM")).toBe(3);

    const afterWeigh = fillRestBasePeopleForRole(afterFold, "weigher", blocks, 1, "9:00 AM");
    expect(getBasePeopleForBlock(afterWeigh, "weigher", "9:00 AM")).toBe(1);
    expect(getBasePeopleForBlock(afterWeigh, "weigher", "10:00 AM")).toBe(1);
    expect(getBasePeopleForBlock(afterWeigh, "weigher", "11:00 AM")).toBe(1);
    expect(getBasePeopleForBlock(afterWeigh, "folder", "10:00 AM")).toBe(2);
    expect(getBasePeopleForBlock(afterWeigh, "sorter", "10:00 AM")).toBe(3);
    expect(isRoleFillRestComplete(afterWeigh, "weigher", "9:00 AM", blocks)).toBe(true);
  });

  it("Fill rest from middle and last-normal slots; preserves TEMP; no duplicate overlaps", () => {
    const blocks = buildPlanningBlocks("9:00 AM", "12:00 PM", 60);
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
    intervals = setBasePeopleForBlock(intervals, "weigher", "10:00 AM", "11:00 AM", 1);
    intervals = setBasePeopleForBlock(intervals, "sorter", "9:00 AM", "10:00 AM", 1);

    const fromMiddle = fillRestBasePeopleForRole(intervals, "weigher", blocks, 1, "10:00 AM");
    expect(getBasePeopleForBlock(fromMiddle, "weigher", "9:00 AM")).toBe(0); // earlier untouched
    expect(getBasePeopleForBlock(fromMiddle, "weigher", "10:00 AM")).toBe(1);
    expect(getBasePeopleForBlock(fromMiddle, "weigher", "11:00 AM")).toBe(1);
    expect(getAdditionalForBlock(fromMiddle, "sorter", "9:00 AM", "10:00 AM")).toHaveLength(1);

    // Idempotent: second fill does not duplicate overlapping BASE.
    const again = fillRestBasePeopleForRole(fromMiddle, "weigher", blocks, 1, "10:00 AM");
    const weighBase = again.filter(
      (r) => r.role === "weigher" && String(r.mode || "base") !== "additional",
    );
    expect(weighBase).toHaveLength(1);
    expect(weighBase[0].start).toBe("10:00 AM");
    expect(weighBase[0].end).toBe("12:00 PM");

    const fromLastNormal = setBasePeopleForBlock([], "dryer", "11:00 AM", "12:00 PM", 2);
    const dryFilled = fillRestBasePeopleForRole(fromLastNormal, "dryer", blocks, 2, "11:00 AM");
    expect(getBasePeopleForBlock(dryFilled, "dryer", "11:00 AM")).toBe(2);
    expect(isRoleFillRestComplete(dryFilled, "dryer", "11:00 AM", blocks)).toBe(true);
  });

  it("Fill rest works for 30/45/60-min blocks and partial final slot", () => {
    for (const size of [30, 45, 60]) {
      const blocks = buildPlanningBlocks("9:00 AM", "10:15 AM", size);
      expect(blocks.length).toBeGreaterThan(1);
      let intervals = setBasePeopleForBlock(
        [],
        "washer",
        blocks[0].block_start,
        blocks[0].block_end,
        1,
      );
      intervals = fillRestBasePeopleForRole(
        intervals,
        "washer",
        blocks,
        1,
        blocks[0].block_start,
      );
      expect(isRoleFillRestComplete(intervals, "washer", blocks[0].block_start, blocks)).toBe(true);
      const last = blocks[blocks.length - 1];
      expect(getBasePeopleForBlock(intervals, "washer", last.block_start, last.block_end)).toBe(1);
    }
  });

  it("custom hybrid Fill rest extends role set through uncovered horizon", () => {
    const blocks = buildPlanningBlocks("9:00 AM", "12:00 PM", 60);
    let hybrids = upsertHybridInterval([], {
      id: "h1",
      roles: ["washer", "dryer"],
      people: 1,
      start: "9:00 AM",
      end: "10:00 AM",
      mode: "base",
    });
    // Explicit later hybrid preserved
    hybrids = upsertHybridInterval(hybrids, {
      id: "h2",
      roles: ["washer", "dryer"],
      people: 2,
      start: "10:00 AM",
      end: "11:00 AM",
      mode: "base",
    });
    hybrids = fillRestHybridPeople(hybrids, ["washer", "dryer"], blocks, 1, "9:00 AM");
    expect(getHybridPeopleForBlock(hybrids, ["washer", "dryer"], "9:00 AM", "10:00 AM")).toBe(1);
    expect(getHybridPeopleForBlock(hybrids, ["washer", "dryer"], "10:00 AM", "11:00 AM")).toBe(2);
    expect(getHybridPeopleForBlock(hybrids, ["washer", "dryer"], "11:00 AM", "12:00 PM")).toBe(1);
    expect(isHybridFillRestComplete(hybrids, ["washer", "dryer"], "9:00 AM", blocks)).toBe(true);

    // TEMP hybrid preserved; fill still covers base gaps
    hybrids = upsertHybridInterval([], {
      id: "ht",
      roles: ["sorter", "folder"],
      people: 1,
      start: "9:30 AM",
      end: "10:00 AM",
      mode: "additional",
    });
    hybrids = fillRestHybridPeople(hybrids, ["sorter", "folder"], blocks, 1, "9:00 AM");
    expect(hybrids.some((r) => r.id === "ht" && r.mode === "additional")).toBe(true);
    expect(isHybridFillRestComplete(hybrids, ["sorter", "folder"], "9:00 AM", blocks)).toBe(true);
  });

  it("Fill rest with zero people is a no-op and leaves temps alone", () => {
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

    const next = fillRestBasePeopleForRole(intervals, "weigher", blocks, 0, "9:00 AM");
    expect(getBasePeopleForBlock(next, "weigher", "9:00 AM")).toBe(0);
    expect(getBasePeopleForBlock(next, "weigher", "10:00 AM")).toBe(2); // preserved
    expect(getBasePeopleForBlock(next, "sorter", "9:00 AM")).toBe(1);
    expect(getAdditionalForBlock(next, "sorter", "9:00 AM", "10:00 AM")).toHaveLength(1);
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
    const hybridRows = body.staffing_plan.intervals.filter((r) => r.roles || r.hybrid || r.mode === "hybrid");
    expect(body.staffing_plan.intervals.some((r) => r.role === "sorter")).toBe(true);
    expect(hybridRows).toHaveLength(1);
    expect(hybridRows[0].roles).toEqual(["weigher", "washer"]);
    expect(hybridRows[0].mode).toBe("hybrid");
    expect(body.staffing_plan.intervals.every((r) => r.role !== "weigher")).toBe(true);

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

  it("buildPositionInventoryDisplay uses checkpoint snapshot with four concepts", () => {
    const view = buildPositionInventoryDisplay(
      {
        target_bags: 100,
        weighed_total: 80,
        sorted_total: 22,
        washed_total: 4,
        dried_total: 0,
        folded_total: 0,
        reconciliation: { exclusive_state_sum: 100, ok: true },
        availability_checkpoints: [
          {
            time: "5:15 AM",
            time_sec: 100,
            stages: {
              weigh: { id: "weigh", title: "WEIGH", this_15_min: 20, total_done: 20, waiting_next: 14, waiting_next_label: "Sort", in_process: 1, is_terminal: false },
              sort: { id: "sort", title: "SORT", this_15_min: 4, total_done: 4, waiting_next: 2, waiting_next_label: "Wash", in_process: 1, is_terminal: false },
              wash: { id: "wash", title: "WASH", this_15_min: 0, total_done: 0, waiting_next: 0, waiting_next_label: "Dry", in_process: 2, in_labor: 1, in_cycle: 1, is_terminal: false },
              dry: { id: "dry", title: "DRY", this_15_min: 0, total_done: 0, waiting_next: 0, waiting_next_label: "Fold", in_process: 0, is_terminal: false },
              fold: { id: "fold", title: "FOLD", this_15_min: 0, total_done: 0, waiting_next: 0, waiting_next_label: null, in_process: 0, is_terminal: true },
            },
                        reconciliation: { exclusive_state_sum: 100, ok: true },
          },
          {
            time: "6:00 AM",
            time_sec: 200,
            stages: {
              weigh: { id: "weigh", title: "WEIGH", this_15_min: 20, total_done: 80, waiting_next: 58, waiting_next_label: "Sort", in_process: 0, is_terminal: false },
              sort: { id: "sort", title: "SORT", this_15_min: 6, total_done: 22, waiting_next: 13, waiting_next_label: "Wash", in_process: 1, is_terminal: false },
              wash: { id: "wash", title: "WASH", this_15_min: 4, total_done: 4, waiting_next: 1, waiting_next_label: "Dry", in_process: 5, in_labor: 0, in_cycle: 5, is_terminal: false },
              dry: { id: "dry", title: "DRY", this_15_min: 0, total_done: 0, waiting_next: 0, waiting_next_label: "Fold", in_process: 3, in_labor: 0, in_cycle: 3, is_terminal: false },
              fold: { id: "fold", title: "FOLD", this_15_min: 0, total_done: 0, waiting_next: 0, waiting_next_label: null, in_process: 0, is_terminal: true, terminal_completed: 0 },
            },
            reconciliation: { exclusive_state_sum: 100, ok: true },
          },
        ],
      },
      100,
    );
    // Defaults to last checkpoint.
    expect(view.selectedTime).toBe("6:00 AM");
    expect(view.columns.map((c) => [c.id, c.totalDone, c.this15, c.waitingNext, c.inProcess])).toEqual([
      ["weigh", 80, 20, 58, 0],
      ["sort", 22, 6, 13, 1],
      ["wash", 4, 4, 1, 5],
      ["dry", 0, 0, 0, 3],
      ["fold", 0, 0, 0, 0],
    ]);
    expect(view.columns.find((c) => c.id === "wash").waitingNextText).toBe("1 AVAILABLE FOR DRY");
    expect(view.columns.find((c) => c.id === "fold").isTerminal).toBe(true);
    expect(view.columns.find((c) => c.id === "dry").waitingNextText).toBe("0 AVAILABLE FOR FOLD");
    expect(view.checkpoints).toHaveLength(2);

    const at515 = buildPositionInventoryDisplay(
      {
        target_bags: 100,
        availability_checkpoints: view.checkpoints.map((c) => c.raw),
        reconciliation: { exclusive_state_sum: 100, ok: true },
      },
      100,
      { selectedTimeSec: 100 },
    );
    expect(at515.selectedTime).toBe("5:15 AM");
    expect(at515.columns.find((c) => c.id === "weigh").totalDone).toBe(20);
    expect(at515.columns.find((c) => c.id === "wash").inProcess).toBe(2);
  });

  it("buildPositionInventoryDisplay wash/dry in-process includes cycle", () => {
    const view = buildPositionInventoryDisplay(
      {
        washed_total: 10,
        waiting_to_dry: 3,
        in_transfer_labor: 1,
        in_dry_labor: 1,
        in_dry_cycle: 3,
        dried_total: 2,
        in_wash_labor: 1,
        in_wash_cycle: 5,
        waiting_to_wash: 0,
        sorted_total: 8,
        not_yet_weighed: 0,
        waiting_to_sort: 0,
        in_sort_labor: 0,
        waiting_to_fold: 0,
        in_fold_labor: 0,
        folded_total: 0,
        completed: 0,
        weighed_total: 8,
      },
      12,
    );
    expect(view.columns.find((c) => c.id === "wash").inProcess).toBe(6);
    expect(view.columns.find((c) => c.id === "dry").inProcess).toBe(4);
    expect(view.inventory.find((r) => r.id === "washing_now").detail).toBe("1 loading · 5 in machine");
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
    expect(flow.inventory.progress).toHaveLength(5);
    expect(flow.inventory.reconcileLabel).toMatch(/^Position reconciled: \d+ \/ 50$/);
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
    )).toBe("Weigh 0 · Sort 1 · Wash 0 · Dry 1 · Fold 2 · Hybrid: Weigh+Wash 1");
    expect(formatHybridStaffChips(
      [{ hybrid: "weigh_wash", people: 1, start: "6:00 AM", end: "7:00 AM", mode: "base" }],
      "6:00 AM",
      "7:00 AM",
    )).toEqual(["Weigh+Wash 1"]);

    // Collapsed TEMP staffing remains visible
    expect(formatCollapsedSlotStaffLine(
      [
        { role: "weigher", people: 1, start: "5:00 AM", end: "6:00 AM", mode: "base" },
        { role: "sorter", people: 0, start: "5:00 AM", end: "6:00 AM", mode: "base" },
        {
          id: "temp-sort",
          role: "sorter",
          people: 2,
          start: "5:30 AM",
          end: "6:00 AM",
          mode: "additional",
        },
      ],
      [],
      "5:00 AM",
      "6:00 AM",
    )).toContain("Sort 0 (+2 5:30 AM–6:00 AM)");
    expect(formatTempStaffChips(
      [{
        id: "temp-sort",
        role: "sorter",
        people: 2,
        start: "5:30 AM",
        end: "6:00 AM",
        mode: "additional",
      }],
      "5:00 AM",
      "6:00 AM",
    )).toEqual(["Sort +2 5:30 AM–6:00 AM"]);

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
    const nextIntervals = fillRestBasePeopleForRole(
      inputs.staffing_intervals,
      "folder",
      blocks,
      6,
      blocks[0].block_start,
    );
    const body = buildManagementPayload({ ...inputs, staffing_intervals: nextIntervals });
    expect(body.bag_count).toBe(50);
    expect(body.washer_count).toBe(4);
    expect(body.dryer_count).toBe(4);
    expect(body.weigh_sec_per_bag).toBe(45);
    expect(body.start_time).toBe("9:00 AM");
    expect(body.target_time).toBe("3:00 PM");
  });

  it("dedicatedPeopleInSlot includes temp/additional dryers", () => {
    const intervals = [
      { role: "dryer", people: 0, start: "6:00 AM", end: "7:00 AM", mode: "base" },
      { role: "dryer", people: 1, start: "6:00 AM", end: "7:00 AM", mode: "additional" },
    ];
    expect(dedicatedPeopleInSlot(intervals, "dryer", "6:00 AM", "7:00 AM")).toBe(1);
  });

  it("buildSlotStaffingNotes warns Dry with no Wash capacity; info for hybrid", () => {
    const dryOnly = buildSlotStaffingNotes(
      [
        { role: "dryer", people: 1, start: "6:00 AM", end: "7:00 AM", mode: "additional" },
      ],
      [],
      "6:00 AM",
      "7:00 AM",
    );
    expect(dryOnly.some((n) => n.tone === "warning" && /no Wash labor/i.test(n.text))).toBe(true);

    const hybridWwPlusDry = buildSlotStaffingNotes(
      [{ role: "dryer", people: 1, start: "6:00 AM", end: "7:00 AM", mode: "additional" }],
      [{ hybrid: "weigh_wash", people: 1, start: "6:00 AM", end: "7:00 AM", mode: "base" }],
      "6:00 AM",
      "7:00 AM",
    );
    expect(hybridWwPlusDry.some((n) => /no Wash labor/i.test(n.text))).toBe(false);
    expect(hybridWwPlusDry.some((n) => n.tone === "info" && /one person/i.test(n.text))).toBe(true);

    const foldNoDry = buildSlotStaffingNotes(
      [{ role: "folder", people: 2, start: "6:00 AM", end: "7:00 AM", mode: "base" }],
      [],
      "6:00 AM",
      "7:00 AM",
    );
    expect(foldNoDry.some((n) => n.tone === "warning" && /no Dry labor/i.test(n.text))).toBe(true);
  });

  it("waiting != remaining and waiting-to-enter tooltip stays concise", () => {
    const flow = buildPositionFlowDisplay(
      {
        weighed_this_block: 80,
        weighed_total: 80,
        sorted_this_block: 11,
        sorted_total: 11,
        washed_this_block: 0,
        washed_total: 0,
        dried_this_block: 0,
        dried_total: 0,
        folded_this_block: 0,
        folded_total: 0,
        waiting_to_sort: 69,
        waiting_to_wash: 11,
        waiting_to_dry: 0,
        waiting_to_fold: 0,
      },
      100,
    );
    expect(flow.stages.weigh).toMatchObject({ done: 80, remaining: 20 });
    expect(flow.stages.sort).toMatchObject({ done: 11, remaining: 89 });
    expect(flow.waiting.to_sort).toBe(69);
    expect(flow.waiting.to_sort).not.toBe(flow.stages.sort.remaining);
    expect(flow.hints.to_sort).toBe(
      "80 bags have completed Weigh and 11 have completed Sort, leaving 69 currently waiting to enter Sort.",
    );
    expect(formatWaitingToSortHint(80, 11, 69)).toBe(flow.hints.to_sort);
    expect(flow.stages.wash.waitingToEnterLabel).toBe("11 WAITING TO ENTER");
    expect(flow.hints.to_wash).toMatch(/entered Wash/i);
    expect(buildPositionFlowDisplay({
      weighed_total: 12,
      sorted_total: 12,
      washed_total: 7,
      dried_total: 0,
      folded_total: 0,
      waiting_to_sort: 0,
      waiting_to_wash: 0,
      waiting_to_dry: 0,
      waiting_to_fold: 0,
      detail: { in_wash_cycle: 5 },
    }, 100).hints.to_wash).toMatch(/0 waiting to enter Wash/i);
  });

  it("WASH/DRY reconcile upstream DONE using backend counts only", () => {
    const flow = buildPositionFlowDisplay(
      {
        weighed_total: 100,
        sorted_total: 12,
        washed_total: 7,
        dried_total: 0,
        folded_total: 0,
        weighed_this_block: 0,
        sorted_this_block: 1,
        washed_this_block: 7,
        dried_this_block: 0,
        folded_this_block: 0,
        waiting_to_sort: 0,
        waiting_to_wash: 0,
        waiting_to_dry: 2,
        waiting_to_fold: 0,
        detail: { in_wash_cycle: 5, in_dry_cycle: 5, in_wash_labor: 0, in_dry_labor: 0 },
      },
      100,
    );
    expect(flow.stages.wash).toMatchObject({
      done: 7,
      inCycle: 5,
      inCycleLabel: "5 IN CYCLE",
      waitingToEnter: 0,
      waitingToEnterLabel: "0 WAITING TO ENTER",
    });
    expect(flow.stages.dry).toMatchObject({
      done: 0,
      inCycle: 5,
      waitingToEnter: 2,
      waitingToEnterLabel: "2 WAITING TO ENTER",
    });
    expect(flow.reconcile.sortToWash).toMatchObject({
      upstreamDone: 12,
      waitingToEnter: 0,
      inCycle: 5,
      stageDone: 7,
      accounted: 12,
      matches: true,
    });
    expect(flow.reconcile.sortToWash.text).toBe(
      "12 Sort DONE = 0 waiting to enter + 5 in cycle + 7 Wash DONE",
    );
    expect(flow.reconcile.washToDry).toMatchObject({
      upstreamDone: 7,
      waitingToEnter: 2,
      inCycle: 5,
      stageDone: 0,
      accounted: 7,
      matches: true,
    });
    expect(flow.reconcile.washToDry.text).toBe(
      "7 Wash DONE = 2 waiting to enter + 5 in cycle + 0 Dry DONE",
    );
    // Formatter is presentation-only over provided backend numbers.
    expect(formatStageReconcile({
      upstreamDone: 12,
      waitingToEnter: 0,
      inCycle: 5,
      stageDone: 7,
      upstreamLabel: "Sort",
      stageLabel: "Wash",
    }).matches).toBe(true);
  });

  it("DRY DONE 0 with IN CYCLE > 0 uses API in_dry_cycle only", () => {
    const flow = buildPositionFlowDisplay(
      {
        weighed_total: 100,
        sorted_total: 100,
        washed_total: 4,
        dried_total: 0,
        folded_total: 0,
        weighed_this_block: 0,
        sorted_this_block: 0,
        washed_this_block: 2,
        dried_this_block: 0,
        folded_this_block: 0,
        waiting_to_sort: 0,
        waiting_to_wash: 0,
        waiting_to_dry: 2,
        waiting_to_fold: 0,
        detail: { in_wash_cycle: 2, in_dry_cycle: 2 },
      },
      100,
    );
    expect(flow.stages.dry).toMatchObject({
      thisBlock: 0,
      done: 0,
      remaining: 100,
      inCycle: 2,
      inCycleLabel: "2 IN CYCLE",
      thisBlockLabel: "0 this slot",
    });
    expect(flow.stages.wash.inCycleLabel).toBe("2 IN CYCLE");
  });

  it("formats manager-facing labor-use from API work_coverage only", () => {
    const full = describeWorkCoverage({
      role: "washer",
      mode: "base",
      eligible_bags: 6,
      available_work_min: 24,
      staff_min: 60,
      used_min: 60,
      idle_min: 0,
      idle_no_eligible_work_min: 0,
      unused_fit_min: 0,
      status: "fully_utilized",
    });
    expect(full.lines.join("\n")).toBe("WASH — Labor used: 60 / 60 min");
    expect(full.lines.join("\n")).not.toContain("bags");
    expect(full.lines.join("\n")).not.toContain("395");
    expect(full.lines.join("\n")).not.toMatch(/utilized/i);

    const mostly = describeWorkCoverage({
      role: "sorter",
      mode: "base",
      staff_min: 120,
      used_min: 110,
      idle_min: 10,
      idle_no_eligible_work_min: 2.25,
      unused_fit_min: 7.75,
      available_work_min: 395,
      eligible_bags: 79,
      status: "partial_upstream_short",
    });
    expect(mostly.lines.join("\n")).toBe([
      "SORT — Labor used: 110 / 120 min",
      "2.25 min waiting for bags",
      "7.75 min remaining — too short to start another sort",
    ].join("\n"));
    expect(mostly.lines.join("\n")).not.toContain("395");

    const endOnly = describeWorkCoverage({
      role: "sorter",
      mode: "base",
      staff_min: 60,
      used_min: 55,
      idle_min: 5,
      idle_no_eligible_work_min: 0,
      unused_fit_min: 5,
      status: "work_not_fit",
    });
    expect(endOnly.lines.join("\n")).toBe([
      "SORT — Labor used: 55 / 60 min",
      "5 min remaining — too short to start another sort",
    ].join("\n"));

    const tempDry = describeWorkCoverage({
      role: "dryer",
      mode: "additional",
      people: 1,
      start: "6:45 AM",
      end: "7:00 AM",
      staff_min: 15,
      used_min: 12,
      idle_min: 3,
      idle_no_eligible_work_min: 0,
      unused_fit_min: 3,
      available_work_min: 42,
      status: "work_not_fit",
    });
    expect(tempDry.lines.join("\n")).toBe([
      "DRY TEMP 6:45 AM–7:00 AM — Labor used: 12 / 15 min",
      "3 min remaining — insufficient time for next required load",
    ].join("\n"));

    const starved = describeWorkCoverage({
      role: "dryer",
      mode: "base",
      staff_min: 60,
      used_min: 18,
      idle_min: 42,
      idle_no_eligible_work_min: 42,
      unused_fit_min: 0,
      available_work_min: 6,
      status: "idle_waiting_for_work",
    });
    expect(starved.lines.join("\n")).toBe([
      "DRY — Labor used: 18 / 60 min",
      "42 min waiting for washed bags",
    ].join("\n"));

    const hybrid = describeWorkCoverage({
      hybrid: "wash_dry",
      roles: ["washer", "dryer"],
      mode: "base",
      staff_min: 60,
      used_min: 60,
      idle_min: 0,
      status: "fully_utilized",
      role_allocation_min: { washer: 36, dryer: 24, idle: 0 },
    });
    expect(hybrid.lines[0]).toContain("HYBRID");
    expect(hybrid.lines[1]).toBe("60 of 60 min productive · 100% utilized");
    expect(hybrid.lines.join("\n")).toContain("Wash 36m");
    expect(hybrid.lines.join("\n")).toContain("Dry 24m");

    const detail = formatWorkCoverageDetail({
      eligible_bags: 79,
      eligible_bags_at_start: 0,
      eligible_bags_became: 79,
      available_work_min: 395,
      staff_min: 120,
      used_min: 110,
      idle_min: 10,
      idle_no_eligible_work_min: 2.25,
      unused_fit_min: 7.75,
      machine_blocked_min: 0,
      physical_loads_available: 79,
      status: "partial_upstream_short",
    });
    expect(detail).toContain("worked");
    expect(detail).toContain("waiting");
    expect(detail).toContain("remaining too short");
    expect(detail).not.toContain("productive");
  });

  it("matches work_coverage rows to role/TEMP within a slot", () => {
    const rows = [
      {
        role: "dryer",
        hybrid: null,
        mode: "additional",
        start: "6:45 AM",
        end: "7:00 AM",
        start_sec: parseClockToSec("6:45 AM"),
        end_sec: parseClockToSec("7:00 AM"),
        eligible_bags: 14,
        available_work_min: 42,
        staff_min: 15,
        used_min: 15,
        idle_min: 0,
        status: "fully_utilized",
      },
      {
        role: "washer",
        hybrid: null,
        mode: "base",
        start: "6:00 AM",
        end: "7:00 AM",
        start_sec: parseClockToSec("6:00 AM"),
        end_sec: parseClockToSec("7:00 AM"),
        eligible_bags: 20,
        available_work_min: 90,
        staff_min: 60,
        used_min: 60,
        idle_min: 0,
        status: "fully_utilized",
      },
    ];
    const dryTemp = findWorkCoverageForRole(rows, "dryer", "6:00 AM", "7:00 AM", { mode: "additional" });
    expect(dryTemp).toHaveLength(1);
    expect(dryTemp[0].used_min).toBe(15);
    const washBase = findWorkCoverageForRole(rows, "washer", "6:00 AM", "7:00 AM", { mode: "base" });
    expect(washBase).toHaveLength(1);
    expect(findWorkCoverageForHybrid(rows, "wash_dry", "6:00 AM", "7:00 AM")).toHaveLength(0);
  });

  it("saved simulation payload keeps custom hybrids and fill-rest intervals", () => {
    const inputs = {
      ...DEFAULT_MANAGEMENT_INPUTS,
      bag_count: 100,
      staffing_intervals: [
        { id: "a", role: "sorter", people: 2, start: "9:00 AM", end: "4:00 PM", mode: "base" },
      ],
      hybrid_intervals: [
        {
          id: "h1",
          roles: ["sorter", "folder"],
          people: 1,
          start: "10:00 AM",
          end: "2:00 PM",
          mode: "base",
        },
      ],
    };
    const payload = buildSavedSimulationPayload(inputs);
    expect(payload.payload_version).toBe("mgmt_sim_v1");
    expect(payload.hybrid_intervals[0].roles).toEqual(["sorter", "folder"]);
    expect(payload.staffing_intervals[0].end).toBe("4:00 PM");
    expect(payload.block_positions).toBeUndefined();

    const restored = applySavedSimulationPayload(DEFAULT_MANAGEMENT_INPUTS, payload);
    expect(restored.bag_count).toBe(100);
    expect(restored.hybrid_intervals[0].roles).toEqual(["sorter", "folder"]);
    expect(simulationInputsFingerprint(restored)).toBe(simulationInputsFingerprint(inputs));

    expect(
      formatSavedSimulationListChip({
        completed_by_target: 100,
        target_bags: 100,
        projected_finish: "2:35 PM",
        productive_hours: 18.4,
      }),
    ).toMatch(/100\/100 · 2:35 PM · 18\.4 productive hrs/);
  });
});
