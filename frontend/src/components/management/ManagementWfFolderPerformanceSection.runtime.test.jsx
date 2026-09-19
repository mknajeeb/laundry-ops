/**
 * Guard: every perf* helper call in this file must be imported.
 * Catches the 76f2a690 production crash (perfKpiStripSx used but not imported).
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  FOLDER_PERFORMANCE_REFRESH_MS,
  shouldPollFolderPerformance,
} from "./performance/folderPerformanceRefresh";

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

  it("polls only the current business day on Today", () => {
    expect(FOLDER_PERFORMANCE_REFRESH_MS).toBe(60000);
    expect(
      shouldPollFolderPerformance({
        compare: "today",
        dateEt: "2026-09-19",
        todayYmd: "2026-09-19",
      })
    ).toBe(true);
    expect(
      shouldPollFolderPerformance({
        compare: "today",
        dateEt: "2026-09-18",
        todayYmd: "2026-09-19",
      })
    ).toBe(false);
    expect(
      shouldPollFolderPerformance({
        compare: "7d",
        dateEt: "2026-09-19",
        todayYmd: "2026-09-19",
      })
    ).toBe(false);
    expect(
      shouldPollFolderPerformance({
        compare: "last_n",
        dateEt: "2026-09-19",
        todayYmd: "2026-09-19",
      })
    ).toBe(false);
    expect(
      shouldPollFolderPerformance({
        compare: "same_weekday_last_week",
        dateEt: "2026-09-19",
        todayYmd: "2026-09-19",
      })
    ).toBe(false);
  });

  it("wires the 60-second refresh to unmount cleanup and an in-flight guard", () => {
    const src = readFileSync(srcPath, "utf8");
    expect(src).toMatch(/shouldPollFolderPerformance/);
    expect(src).toMatch(/FOLDER_PERFORMANCE_REFRESH_MS/);
    expect(src).toMatch(/load\(\{\s*silent:\s*true/);
    expect(src).toMatch(/window\.clearInterval/);
    expect(src).toMatch(/loadInFlight/);
  });
});
