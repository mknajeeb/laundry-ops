import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const root = path.dirname(fileURLToPath(import.meta.url));

describe("R&C manager weekday assignment UI contracts", () => {
  it("Cost Maintenance mounts Revenue & Cost Employee Assignments panel", () => {
    const tab = readFileSync(path.join(root, "CostMaintenanceTab.jsx"), "utf8");
    const panel = readFileSync(path.join(root, "DrcMobileWeekdayAssignmentsPanel.jsx"), "utf8");
    expect(tab).toContain("DrcMobileWeekdayAssignmentsPanel");
    expect(tab).toContain("<DrcMobileWeekdayAssignmentsPanel canEdit");
    expect(panel).toContain("Revenue & Cost Employee Assignments");
    expect(panel).toContain("Unassigned");
    expect(panel).toContain("getDrcMobileWeekdayAssignments");
    expect(panel).toContain("putDrcMobileWeekdayAssignments");
    expect(panel).toContain("Saturday");
    expect(panel).toContain("Self Service");
  });

  it("employee floor still uses API business_date, not browser today", () => {
    const flow = readFileSync(
      path.join(root, "../../opsMobile/RevenueCostFloorFlow.jsx"),
      "utf8",
    );
    expect(flow).toContain("BusinessDateHeading");
    expect(flow).toContain("payload?.business_date");
    expect(flow).not.toContain("new Date().toISOString()");
  });
});
