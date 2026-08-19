import { readFileSync } from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { describe, expect, it } from "vitest";

const root = path.dirname(fileURLToPath(import.meta.url));

describe("PIN Revenue / Cash unlock contract", () => {
  it("hub unlocks revenue_cost into /revenue-cash", () => {
    const src = readFileSync(path.join(root, "../pages/EmployeePinHubPage.jsx"), "utf8");
    expect(src).toContain('pinHubModule: "revenue_cost"');
    expect(src).toContain('navigate("/revenue-cash"');
    expect(src).not.toContain('navigate("/revenue-cost/floor"');
    expect(src).not.toContain('pinHubModule: "hang_dry"');
    expect(src).not.toContain("/hang-dry/floor");
  });
});
