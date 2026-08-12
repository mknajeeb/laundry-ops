import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const root = dirname(fileURLToPath(import.meta.url));
const boardSrc = readFileSync(
  join(root, "../components/shiftPlanner/ManagementPlannerBoard.jsx"),
  "utf8",
);
const helpersSrc = readFileSync(join(root, "managementHelpers.js"), "utf8");

describe("one-slot recovery board structure", () => {
  it("renders one planning-slot-card per time slot (not separate STAFFING/POSITION cards)", () => {
    expect(boardSrc).toContain('data-testid="planning-slot-card"');
    expect(boardSrc).toContain("STAFF: {staffLine}");
    expect(boardSrc).toContain("{pb.block_end} POSITION");
    expect(boardSrc).toContain("One card = one time slot");
    // Old two-card pattern removed
    expect(boardSrc).not.toContain('kind="staffing"');
    expect(boardSrc).not.toContain('kind="position"');
    expect(boardSrc).not.toContain("Block sequence: STAFFING → POSITION");
  });

  it("keeps expanded staffing controls and compact Hybrid subsection", () => {
    expect(boardSrc).toContain("data-testid=\"expanded-staffing\"");
    expect(boardSrc).toContain("data-testid=\"collapsed-staff-line\"");
    expect(boardSrc).toContain("Fill rest");
    expect(boardSrc).toContain("Temp");
    expect(boardSrc).toContain("Collapse all staffing");
    expect(boardSrc).toContain("Expand all staffing");
    expect(boardSrc).toContain("Edit Parameters");
    expect(boardSrc).toContain("Avg Bag Weight");
    expect(boardSrc).toContain("2-Washer Split");
    expect(boardSrc).toContain("2-Dryer Split");
    expect(boardSrc).toContain("Washers");
    expect(boardSrc).toContain("Dryers");
    expect(boardSrc).toContain("Target bags");
    expect(boardSrc).toContain("Start time");
    expect(boardSrc).toContain("Target finish");
    expect(boardSrc).toContain("Block size");
    expect(boardSrc).toContain("PlanningTimePicker");
    expect(boardSrc).toMatch(/>\s*Hybrid\s*</);
    expect(boardSrc).toContain("MANAGEMENT_HYBRIDS.map");
    expect(boardSrc).toContain("this 15 min");
    expect(boardSrc).toContain("total-done-");
    expect(boardSrc).toContain("this-15-");
  });

  it("keeps sticky Recalculate and auto-recalc debounce", () => {
    expect(boardSrc).toContain('data-testid="recalculate-plan"');
    expect(boardSrc).toContain("summaryStickySx");
    expect(boardSrc).toContain('position: "sticky"');
    expect(boardSrc).toContain("Recalculate");
    expect(boardSrc).toContain("recalculateNow");
    expect(boardSrc).toContain("Auto-updates as you edit");
    // Auto-recalc on input changes remains
    expect(boardSrc).toContain("setTimeout(() => {\n      runSim(inputs);\n    }, 350)");
    expect(boardSrc).toContain("}, [inputs, settingsReady]");
  });

  it("uses five-column POSITION checkpoint snapshot + 15-min timeline", () => {
    expect(boardSrc).toContain("buildPositionInventoryDisplay");
    expect(boardSrc).toContain("position-two-row");
    expect(boardSrc).toContain("position-stage-columns");
    expect(boardSrc).toContain("POSITION ·");
    expect(boardSrc).toContain("total done");
    expect(boardSrc).toContain("this 15 min");
    expect(boardSrc).toContain("15-MIN CHECKPOINTS");
    expect(boardSrc).toContain("setSelectedTimeSec");
    expect(boardSrc).toContain("position-reconciled");
    expect(boardSrc).toContain("availability-15min");
    expect(helpersSrc).toContain("columnsFromCheckpoint");
    expect(helpersSrc).toContain("waiting_next");
    expect(helpersSrc).toContain("this_15_min");
    expect(boardSrc).not.toContain("AVAILABLE TO START");
    expect(boardSrc).toContain("checkpoint-header");
    expect(boardSrc).not.toContain("QueueBridge");
    expect(boardSrc).not.toContain("WAITING TO ENTER");
    expect(boardSrc).not.toContain("Weighing Now");
    expect(boardSrc).not.toContain("Sorting Now");
    expect(boardSrc).not.toContain("Washing Now");
    expect(boardSrc).not.toContain("Drying Now");
    expect(boardSrc).not.toContain("Folding Now");
  });

  it("uses this 15 min labels and does not surface this block in UI copy", () => {
    expect(boardSrc).toContain("this 15 min");
    expect(boardSrc).not.toMatch(/this block/i);
    expect(boardSrc).not.toContain("THIS BLOCK");
  });

  it("keeps Upstream Work Coverage under staffing, separate from POSITION", () => {
    expect(boardSrc).toContain("WorkCoverageHint");
    expect(boardSrc).toContain("describeWorkCoverage");
  });

  it("keeps color segregation bands for staffing vs position", () => {
    expect(boardSrc).toContain("staffingBandSx");
    expect(boardSrc).toContain("positionBandSx");
    expect(boardSrc).toContain("slotCardSx");
    expect(boardSrc).toContain("POSITION_TEAL");
    expect(boardSrc).toContain("POSITION_AMBER");
  });
});
