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
    expect(appSrc).not.toContain("RevenueCostFloorFlow");
    expect(appSrc).not.toContain("HangDryFloorFlow");
    expect(flowSrc).toContain("getManagementRevenue");
    expect(flowSrc).toContain("getManagementRinseHd");
    expect(flowSrc).toContain("saveManagementRinseHdProduction");
    expect(flowSrc).toContain('{ id: "hang_dry", title: "Hang Dry" }');
    expect(flowSrc).not.toContain("getDrcMobileToday");
    expect(flowSrc).not.toContain("ManagementHubNav");
  });

  it("redirects legacy floors to /revenue-cash", () => {
    const revenuePage = readFileSync(path.join(root, "../pages/RevenueCostFloorPage.jsx"), "utf8");
    const hangDryPage = readFileSync(path.join(root, "../pages/HangDryFloorPage.jsx"), "utf8");
    const appSrc = readFileSync(path.join(root, "../App.jsx"), "utf8");
    expect(revenuePage).toContain('to="/revenue-cash"');
    expect(revenuePage).not.toContain("RevenueCostFloorFlow");
    expect(hangDryPage).toContain('to="/revenue-cash"');
    expect(hangDryPage).not.toContain("HangDryFloorFlow");
    expect(appSrc).toContain('path="/revenue-cost/floor"');
    expect(appSrc).toContain('path="/hang-dry/floor"');
    expect(appSrc).toContain('to="/revenue-cash"');
  });
});
