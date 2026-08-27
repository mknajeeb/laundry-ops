import { describe, expect, it } from "vitest";
import { mergeRinseWfDashboardPayload } from "./managementRinseWfLoadModel";

describe("mergeRinseWfDashboardPayload", () => {
  it("keeps primary segments and loads weights from secondary", () => {
    const primary = {
      date_et: "2026-08-16",
      rinse: {
        segments: { wf: { total_workload: 113, completed: 80 } },
      },
      review: { deferred: true },
    };
    const secondary = {
      rinse: {
        weight_totals: { pre_lbs: 500 },
        specialty_metrics: { wf: { rejected_orders: { count: 2 } } },
      },
      review: {
        deferred: false,
        specialty_items: 4,
        missing_from_portal: 1,
        split_order_review: 2,
      },
    };
    const merged = mergeRinseWfDashboardPayload(primary, secondary);
    expect(merged.rinse.segments.wf.total_workload).toBe(113);
    expect(merged.rinse.weight_totals.pre_lbs).toBe(500);
    expect(merged.rinse.specialty_metrics.wf.rejected_orders.count).toBe(2);
    expect(merged.review.specialty_items).toBe(4);
  });

  it("returns primary-only data before secondary resolves", () => {
    const primary = {
      date_et: "2026-08-16",
      rinse: { segments: { wf: { pending: 3 } } },
      review: { deferred: true },
    };
    const merged = mergeRinseWfDashboardPayload(primary, null);
    expect(merged.rinse.segments.wf.pending).toBe(3);
    expect(merged.review.deferred).toBe(true);
  });
});
