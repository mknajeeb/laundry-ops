import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");

describe("Phase 5B.1 Step 2 Revenue & Cost PIN unlock payload", () => {
  it("EmployeePinHubPage tags revenue_cost unlock and opens floor route", () => {
    const src = readFileSync(join(root, "pages/EmployeePinHubPage.jsx"), "utf8");
    expect(src).toContain('pinHubModule: "revenue_cost"');
    expect(src).toContain('navigate("/revenue-cost/floor"');
    expect(src).not.toContain('navigate("/finance/daily-revenue-cost"');
  });

  it("authAttendancePinUnlock accepts optional pinHubModule / hubToken", () => {
    const src = readFileSync(join(root, "api.js"), "utf8");
    expect(src).toContain("pin_hub_module");
    expect(src).toContain("opts.pinHubModule");
    expect(src).toContain("opts.hubToken");
  });

  it("KioskUnlockPage does not send pin_hub_module", () => {
    const src = readFileSync(join(root, "pages/KioskUnlockPage.jsx"), "utf8");
    expect(src).toContain("authAttendancePinUnlock");
    expect(src).not.toContain("pinHubModule");
    expect(src).not.toContain("pin_hub_module");
  });
});
