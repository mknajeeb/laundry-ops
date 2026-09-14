/**
 * Guard: every perf* helper call in this file must be imported.
 * Catches the 76f2a690 production crash (perfKpiStripSx used but not imported).
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const srcPath = join(here, "ManagementWfFolderPerformanceSection.jsx");

describe("ManagementWfFolderPerformanceSection import integrity", () => {
  it("imports every perf* style helper it invokes", () => {
    const src = readFileSync(srcPath, "utf8");
    const used = [...src.matchAll(/\b(perf[A-Za-z0-9_]+)\s*\(/g)].map((m) => m[1]);
    expect(used.length).toBeGreaterThan(0);
    expect(used).toContain("perfKpiStripSx");

    const importMatch = src.match(
      /import\s*\{([\s\S]*?)\}\s*from\s*["']\.\/performance\/performanceTokens["']/
    );
    expect(importMatch).toBeTruthy();
    const imported = new Set(
      importMatch[1]
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean)
    );
    const missing = [...new Set(used)].filter((name) => !imported.has(name));
    expect(missing).toEqual([]);
  });

  it("does not reference undefined WF_SORT_OPTIONS / WfEmployeeRankCard leftovers", () => {
    const src = readFileSync(srcPath, "utf8");
    expect(src).not.toMatch(/\bWF_SORT_OPTIONS\b/);
    expect(src).not.toMatch(/\bWfEmployeeRankCard\b/);
    expect(src).toMatch(/\bWfEmployeeDayRow\b/);
    expect(src).toMatch(/\bSORT_OPTIONS\b/);
  });
});
