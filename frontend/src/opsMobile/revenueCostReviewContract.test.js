import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const root = path.dirname(fileURLToPath(import.meta.url));

describe("Phase 5E review-pass UI contracts", () => {
  it("employee floor shows returned reason and pending-review submitted label", () => {
    const src = readFileSync(path.join(root, "RevenueCostFloorFlow.jsx"), "utf8");
    expect(src).toContain("Submitted (pending review)");
    expect(src).toContain("Returned for correction");
    expect(src).toContain("sectionIsReturned");
  });

  it("employee floor does not mount manager Daily Entry editors", () => {
    const src = readFileSync(path.join(root, "RevenueCostFloorFlow.jsx"), "utf8");
    expect(src).not.toContain("saveDailyRevenueEntry");
    expect(src).not.toContain("DailyEntryTab");
    expect(src).not.toContain("DashboardTab");
    expect(src).not.toContain("RevenueMaintenanceTab");
    expect(src).not.toContain("CostMaintenanceTab");
  });
});
