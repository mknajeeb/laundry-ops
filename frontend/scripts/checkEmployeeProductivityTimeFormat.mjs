#!/usr/bin/env node
/**
 * Regression: Employee Productivity must use friendly ET (Jun 17, 5:21 AM ET),
 * not formatIsoEtWall / raw SQL-style timestamps in source.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  formatFriendlyEtWall,
  formatFriendlyScanTime,
} from "../src/utils/rinseTimeFormat.js";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const PRODUCTIVITY_FILES = [
  "src/components/shift/EmployeeProductivityDashboard.jsx",
  "src/components/shift/EmployeeProductivityDrilldown.jsx",
];

let failed = false;

for (const rel of PRODUCTIVITY_FILES) {
  const abs = path.join(root, rel);
  const content = fs.readFileSync(abs, "utf8");
  if (content.includes("formatIsoEtWall")) {
    console.error(`FAIL: ${rel} still imports or uses formatIsoEtWall`);
    failed = true;
  }
  if (!content.includes("formatFriendlyEtWall")) {
    console.error(`FAIL: ${rel} must use formatFriendlyEtWall`);
    failed = true;
  }
}

const drilldown = fs.readFileSync(
  path.join(root, "src/components/shift/EmployeeProductivityDrilldown.jsx"),
  "utf8",
);
if (!drilldown.includes("friendlyTimeDisplay")) {
  console.error("FAIL: EmployeeProductivityDrilldown must pass friendlyTimeDisplay to ShiftBagRecordRow");
  failed = true;
}

const samples = [
  ["2026-06-17 05:21:00 ET", "Jun 17, 5:21 AM ET"],
  ["2026-06-17 05:21:00", "Jun 17, 5:21 AM ET"],
  ["2026-06-17T05:21:00-04:00", "Jun 17, 5:21 AM ET"],
];

for (const [input, expected] of samples) {
  const out = formatFriendlyEtWall(input);
  if (out !== expected) {
    console.error(`FAIL: formatFriendlyEtWall(${JSON.stringify(input)}) => ${JSON.stringify(out)}, expected ${JSON.stringify(expected)}`);
    failed = true;
  }
}

const scanOut = formatFriendlyScanTime({ scanned_at_parsed: "2026-06-17T05:21:00-04:00" });
if (scanOut !== "Jun 17, 5:21 AM ET") {
  console.error(`FAIL: formatFriendlyScanTime => ${JSON.stringify(scanOut)}`);
  failed = true;
}

if (failed) {
  process.exit(1);
}

console.log("OK: Employee Productivity time format regression checks passed");
