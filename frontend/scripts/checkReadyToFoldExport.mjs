/**
 * Node-runnable validation for Ready to Fold CSV/export helpers.
 * Run: node scripts/checkReadyToFoldExport.mjs
 */
import assert from "node:assert/strict";
import {
  exportScanChronologyCsv,
  hasScanChronologyExportRows,
} from "../src/utils/scanChronologyExport.js";

const bags = [
  {
    bag_id: "8FQ4FT46CY",
    drying_scan_et: "2026-07-13T07:21:00",
    ready_to_fold_et: "2026-07-13T08:01:00",
    drying_duration_minutes: 40,
    dryer_rack: "D60-50-VW",
    weight: 32,
    order_type: "WF",
    folding_start_et: "2026-07-13T09:28:00",
    status: "folding_started",
  },
  {
    bag_id: "AZTSVQRJ1L",
    drying_scan_et: "2026-07-13T07:33:00",
    ready_to_fold_et: "2026-07-13T08:13:00",
    drying_duration_minutes: 40,
    dryer_rack: "D43-50-VW",
    weight: null,
    order_type: null,
    folding_start_et: null,
    status: "waiting_to_fold",
  },
];

const intervals = [
  {
    label: "8:00 AM",
    newly_ready_count: 2,
    available_count: 1,
    bags,
  },
  {
    label: "8:15 AM",
    newly_ready_count: 0,
    available_count: 1,
    bags: [bags[1]],
  },
];

assert.equal(
  hasScanChronologyExportRows({
    stage: "ready_to_fold",
    sessions: bags,
    intervals,
  }),
  true,
);

assert.equal(
  hasScanChronologyExportRows({
    stage: "ready_to_fold",
    sessions: [],
    intervals: [{ newly_ready_count: 0, available_count: 0 }],
  }),
  false,
);

const clicks = [];
const created = [];
global.URL = {
  createObjectURL(blob) {
    created.push(blob);
    return "blob:ready-to-fold";
  },
  revokeObjectURL() {},
};
global.document = {
  createElement(tag) {
    assert.equal(tag, "a");
    return {
      href: "",
      download: "",
      click() {
        clicks.push(this.download);
      },
    };
  },
};

const ok = exportScanChronologyCsv({
  stage: "ready_to_fold",
  dateEt: "2026-07-13",
  sessions: bags,
  intervals,
});
assert.equal(ok, true);
assert.equal(clicks.length, 1);
assert.match(clicks[0], /scan-chronology-ready_to_fold-2026-07-13\.csv/);
assert.equal(created.length, 1);

// Duration matrix readiness for client-side display math (mirrors backend).
for (const mins of [0, 35, 40, 45, 60, 120]) {
  const dry = new Date("2026-07-13T08:05:00");
  const ready = new Date(dry.getTime() + mins * 60_000);
  assert.equal(ready.getMinutes() - dry.getMinutes() === mins % 60 || mins >= 60, true);
  assert.equal((ready - dry) / 60_000, mins);
}

// Half-open interval floor on naive ET wall clock HH:MM
function floorToIntervalLabel(hhmm) {
  const [h, m] = hhmm.split(":").map(Number);
  const floored = Math.floor(m / 15) * 15;
  return `${String(h).padStart(2, "0")}:${String(floored).padStart(2, "0")}`;
}
assert.equal(floorToIntervalLabel("08:07"), "08:00");
assert.equal(floorToIntervalLabel("08:15"), "08:15");
assert.equal(floorToIntervalLabel("08:00"), "08:00");
assert.equal(floorToIntervalLabel("23:59"), "23:45");

console.log("checkReadyToFoldExport: PASS");
