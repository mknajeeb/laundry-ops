import { describe, expect, it } from "vitest";
import {
  pickRinseSegments,
  pickWfSpecialty,
  pickWfWeights,
  wfHeadline,
  wfIdentityLine,
} from "./todayRinseModel";

const rinse = {
  segments: {
    wf: {
      total_workload: 97,
      completed: 70,
      pending: 1,
      exceptions: { review_required: 26 },
    },
    wf_rush: {
      total_workload: 12,
      completed: 8,
      pending: 0,
      exceptions: { review_required: 4 },
    },
  },
  specialty_metrics: {
    wf: {
      comforter_orders: { count: 0 },
      bath_mat_orders: { count: 0 },
      rejected_orders: { count: 26 },
      split_orders: { count: 75 },
    },
    wf_rush: {
      comforter_orders: { count: 0 },
      bath_mat_orders: { count: 0 },
      rejected_orders: { count: 4 },
      split_orders: { count: 9 },
    },
  },
};

describe("Rinse WF presentation model", () => {
  it("keeps WF workload/completed/pending/review identity", () => {
    const wf = wfHeadline(rinse.segments.wf);
    expect(wf).toEqual({ workload: 97, completed: 70, pending: 1, review: 26 });
    expect(wfIdentityLine(wf)).toBe("97 = 70 Completed + 1 Pending + 26 Review");
  });

  it("applies rush filter to WF segment and specialty counts", () => {
    expect(pickRinseSegments(rinse, "rush").wf.total_workload).toBe(12);
    expect(pickWfSpecialty(rinse, "all").rejected_orders.count).toBe(26);
    expect(pickWfSpecialty(rinse, "rush").rejected_orders.count).toBe(4);
  });

  it("picks PRE/POST lbs with rush filter when supported", () => {
    const withWeights = {
      ...rinse,
      weight_totals: {
        rush_filtering_supported: true,
        pre_lbs: 100,
        post_lbs: 80,
        pre_weight_lbs: 100,
        post_weight_lbs: 80,
        pre_weight_bag_count: 10,
        post_weight_bag_count: 8,
        by_rush: {
          all: {
            pre_lbs: 100,
            post_lbs: 80,
            pre_weight_lbs: 100,
            post_weight_lbs: 80,
            pre_weight_bag_count: 10,
            post_weight_bag_count: 8,
          },
          rush: {
            pre_lbs: 70,
            post_lbs: 60,
            pre_weight_lbs: 70,
            post_weight_lbs: 60,
            pre_weight_bag_count: 6,
            post_weight_bag_count: 5,
          },
          non_rush: {
            pre_lbs: 30,
            post_lbs: 20,
            pre_weight_lbs: 30,
            post_weight_lbs: 20,
            pre_weight_bag_count: 4,
            post_weight_bag_count: 3,
          },
        },
      },
    };
    expect(pickWfWeights(withWeights, "all").preLbs).toBe(100);
    expect(pickWfWeights(withWeights, "rush").postLbs).toBe(60);
    expect(pickWfWeights(withWeights, "rush").preBagCount).toBe(6);
    expect(pickWfWeights(withWeights, "rush").postBagCount).toBe(5);
  });

  it("does not fall specialty back to All under Rush", () => {
    const missingRush = {
      ...rinse,
      specialty_metrics: { wf: rinse.specialty_metrics.wf },
    };
    expect(pickWfSpecialty(missingRush, "rush")).toBeNull();
  });
});
