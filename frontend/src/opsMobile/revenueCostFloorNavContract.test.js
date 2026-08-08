import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const root = path.dirname(fileURLToPath(import.meta.url));

describe("Phase 5E Revenue & Cost floor nav contracts", () => {
  it("uses dedicated floor page/flow — not manager DailyRevenueCostPage", () => {
    const pageSrc = readFileSync(path.join(root, "../pages/RevenueCostFloorPage.jsx"), "utf8");
    const flowSrc = readFileSync(path.join(root, "RevenueCostFloorFlow.jsx"), "utf8");
    expect(pageSrc).toContain("RevenueCostFloorFlow");
    expect(pageSrc).not.toContain("DailyRevenueCostPage");
    expect(flowSrc).not.toContain("DailyEntryTab");
    expect(flowSrc).not.toContain("DashboardTab");
  });

  it("Back/Done clear washpro session; Lock clears pin hub", () => {
    const pageSrc = readFileSync(path.join(root, "../pages/RevenueCostFloorPage.jsx"), "utf8");
    expect(pageSrc).toContain("clearPinHubSession");
    expect(pageSrc).toContain("authLogout");
    expect(pageSrc).toContain("onBack={returnToPinMenu}");
    expect(pageSrc).toContain("onDone={returnToPinMenu}");
    expect(pageSrc).toContain("onLock={lockToPinEntry}");
  });

  it("App routes pin-hub revenue-cost floor separately from manager finance", () => {
    const appSrc = readFileSync(path.join(root, "../App.jsx"), "utf8");
    expect(appSrc).toContain("/revenue-cost/floor");
    expect(appSrc).toContain("RevenueCostFloorPage");
    expect(appSrc).toContain("isRevenueCostFloorRoute");
  });
});
