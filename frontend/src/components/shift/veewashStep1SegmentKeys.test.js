/**
 * Segment-key resolution for Step-1 WF/HD × Rush filters.
 * Presentation only — maps UI filters onto API `summary.segments` keys.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { resolveStep1SegmentKeys } from "./veewashStep1SegmentKeys.js";

test("resolveStep1SegmentKeys covers service × rush combinations", () => {
  assert.deepEqual(resolveStep1SegmentKeys("all", "all"), {
    wf: "wf",
    hd: "hd",
    total: "all",
  });
  assert.deepEqual(resolveStep1SegmentKeys("all", "rush"), {
    wf: "wf_rush",
    hd: "hd_rush",
    total: "rush",
  });
  assert.deepEqual(resolveStep1SegmentKeys("all", "non_rush"), {
    wf: "wf_non_rush",
    hd: "hd_non_rush",
    total: "non_rush",
  });
  assert.deepEqual(resolveStep1SegmentKeys("wf", "all"), {
    wf: "wf",
    hd: null,
    total: "wf",
  });
  assert.deepEqual(resolveStep1SegmentKeys("wf", "rush"), {
    wf: "wf_rush",
    hd: null,
    total: "wf_rush",
  });
  assert.deepEqual(resolveStep1SegmentKeys("hd", "non_rush"), {
    wf: null,
    hd: "hd_non_rush",
    total: "hd_non_rush",
  });
});
