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
    expect(panel).toContain("section_label");
    expect(panel).toContain("DAY_ORDER");
  });

  it("PIN Revenue / Cash uses Management APIs, not DRC mobile today/draft/submit", () => {
    const flow = readFileSync(path.join(root, "../../opsMobile/PinRevenueCashFlow.jsx"), "utf8");
    expect(flow).toContain("getManagementRevenue");
    expect(flow).toContain("getManagementRinseHd");
    expect(flow).not.toContain("getDrcMobileToday");
    expect(flow).not.toContain("submitDrcMobileAll");
  });
});
