import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { OPS_MOBILE } from "./tokens";
import { taskProgress } from "../utils/maintenanceTaskListHelpers";

const root = path.dirname(fileURLToPath(import.meta.url));

describe("OpsTaskCard UX contracts", () => {
  const src = readFileSync(path.join(root, "OpsTaskCard.jsx"), "utf8");

  it("renders task names prominently and uses large Complete control", () => {
    expect(src).toContain("fontWeight: 800");
    expect(src).toContain("Complete");
    expect(src).toContain("minHeight: 56");
    expect(src).toContain("minWidth: 112");
    expect(OPS_MOBILE.touchMin).toBe(56);
  });

  it("does not complete on whole-card tap (explicit onComplete only)", () => {
    // Outer card Box has no onClick; only Complete/Undo controls call handlers.
    expect(src.indexOf("onClick={() => onComplete?.()}")).toBeGreaterThan(-1);
    expect(src.indexOf("onClick={() => onUndo?.()}")).toBeGreaterThan(-1);
    expect(src).toContain("More");
    const outerBoxSlice = src.slice(0, src.indexOf("Complete"));
    expect(outerBoxSlice).not.toContain("onClick={() => onComplete");
  });

  it("progress updates after a confirmed task change", () => {
    const before = {
      items: [
        { completed: false, task_name_snapshot: "A" },
        { completed: false, task_name_snapshot: "B" },
      ],
    };
    expect(taskProgress(before)).toEqual({ done: 0, total: 2 });
    const after = {
      items: [
        { completed: true, task_name_snapshot: "A" },
        { completed: false, task_name_snapshot: "B" },
      ],
    };
    expect(taskProgress(after)).toEqual({ done: 1, total: 2 });
  });

  it("long task names wrap via CSS (no default ellipsis on title)", () => {
    expect(src).toContain("whiteSpace: \"normal\"");
    expect(src).toContain("overflowWrap: \"anywhere\"");
    expect(src).not.toMatch(/title[\s\S]{0,200}textOverflow:\s*[\"']ellipsis/);
  });
});
