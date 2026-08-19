import { readFileSync } from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { describe, expect, it } from "vitest";

const root = path.dirname(fileURLToPath(import.meta.url));

describe("PIN Revenue / Cash nav contract", () => {
  it("wires /revenue-cash to PinRevenueCashFlow via Management APIs", () => {
    const pageSrc = readFileSync(path.join(root, "../pages/PinRevenueCashPage.jsx"), "utf8");
    const flowSrc = readFileSync(path.join(root, "PinRevenueCashFlow.jsx"), "utf8");
    const appSrc = readFileSync(path.join(root, "../App.jsx"), "utf8");
    expect(pageSrc).toContain("PinRevenueCashFlow");
    expect(appSrc).toContain('path="/revenue-cash"');
    expect(appSrc).toContain("PinRevenueCashPage");
    expect(appSrc).toContain("isPinRevenueCashRoute");
    expect(appSrc).not.toContain("HangDryFloorPage");
    expect(appSrc).not.toContain("/hang-dry/floor");
    expect(appSrc).not.toContain("RevenueCostFloorFlow");
    expect(flowSrc).toContain("getManagementRevenue");
    expect(flowSrc).toContain("getManagementRinseHd");
    expect(flowSrc).toContain("saveManagementRinseHdProduction");
    expect(flowSrc).not.toContain("getDrcMobileToday");
    expect(flowSrc).not.toContain("ManagementHubNav");
  });

  it("redirects /revenue-cost/floor to /revenue-cash", () => {
    const pageSrc = readFileSync(path.join(root, "../pages/RevenueCostFloorPage.jsx"), "utf8");
    const appSrc = readFileSync(path.join(root, "../App.jsx"), "utf8");
    expect(pageSrc).toContain('to="/revenue-cash"');
    expect(pageSrc).not.toContain("RevenueCostFloorFlow");
    expect(appSrc).toContain("/revenue-cost/floor");
    expect(appSrc).toContain('to="/revenue-cash"');
  });
});
