import { readFileSync } from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { describe, expect, it } from "vitest";

const root = path.dirname(fileURLToPath(import.meta.url));

describe("PIN Revenue & Cash / Hang Dry nav contract", () => {
  it("wires /revenue-cost/floor to RevenueCostFloorFlow", () => {
    const pageSrc = readFileSync(path.join(root, "../pages/RevenueCostFloorPage.jsx"), "utf8");
    const appSrc = readFileSync(path.join(root, "../App.jsx"), "utf8");
    expect(pageSrc).toContain("RevenueCostFloorFlow");
    expect(appSrc).toContain("/revenue-cost/floor");
    expect(appSrc).toContain("RevenueCostFloorPage");
    expect(appSrc).not.toContain("PinRevenueCashPage");
    expect(appSrc).not.toContain('path="/revenue-cash"');
  });

  it("wires /hang-dry/floor to HangDryFloorFlow via Management HD APIs", () => {
    const pageSrc = readFileSync(path.join(root, "../pages/HangDryFloorPage.jsx"), "utf8");
    const flowSrc = readFileSync(path.join(root, "HangDryFloorFlow.jsx"), "utf8");
    const appSrc = readFileSync(path.join(root, "../App.jsx"), "utf8");
    expect(pageSrc).toContain("HangDryFloorFlow");
    expect(appSrc).toContain("/hang-dry/floor");
    expect(appSrc).toContain("HangDryFloorPage");
    expect(flowSrc).toContain("getManagementRinseHd");
    expect(flowSrc).toContain("saveManagementRinseHdProduction");
    expect(flowSrc).not.toContain("ManagementHubNav");
    expect(flowSrc).not.toContain("markManagementRinseHdComplete");
  });
});
