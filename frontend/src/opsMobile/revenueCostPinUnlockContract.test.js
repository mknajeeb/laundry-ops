import { readFileSync } from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { describe, expect, it } from "vitest";

const root = path.dirname(fileURLToPath(import.meta.url));

describe("PIN Revenue & Cash unlock contract", () => {
  it("hub unlocks revenue_cost into /revenue-cost/floor", () => {
    const src = readFileSync(path.join(root, "../pages/EmployeePinHubPage.jsx"), "utf8");
    expect(src).toContain('pinHubModule: "revenue_cost"');
    expect(src).toContain('navigate("/revenue-cost/floor"');
    expect(src).not.toContain('navigate("/revenue-cash"');
  });

  it("hub unlocks hang_dry into /hang-dry/floor", () => {
    const src = readFileSync(path.join(root, "../pages/EmployeePinHubPage.jsx"), "utf8");
    expect(src).toContain('pinHubModule: "hang_dry"');
    expect(src).toContain('navigate("/hang-dry/floor"');
  });
});
