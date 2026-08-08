import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const root = dirname(fileURLToPath(import.meta.url));
const boardSrc = readFileSync(
  join(root, "../components/shiftPlanner/ManagementPlannerBoard.jsx"),
  "utf8",
);

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
    expect(boardSrc).toContain("Fill rest");
    expect(boardSrc).toContain("Temp");
    expect(boardSrc).toContain("Collapse all staffing");
    expect(boardSrc).toContain("Expand all staffing");
    expect(boardSrc).toContain("Edit Parameters");
    expect(boardSrc).toContain("Avg Bag Weight");
    expect(boardSrc).toContain("2-Washer Split");
    expect(boardSrc).toContain("2-Dryer Split");
    expect(boardSrc).toMatch(/Hybrid\s*\n/);
    expect(boardSrc).toContain("MANAGEMENT_HYBRIDS.map");
    expect(boardSrc).toContain("THIS SLOT");
    expect(boardSrc).toContain("inCycleLabel");
  });
});
