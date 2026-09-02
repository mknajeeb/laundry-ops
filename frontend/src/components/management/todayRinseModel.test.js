import { describe, expect, it } from "vitest";
import {
  pickCurrentWorkload,
  pickRinseSegments,
  pickSelectedDateCompleted,
  pickWfSpecialty,
  pickWfWeights,
  wfHeadline,
} from "./todayRinseModel";

const rinse = {
  current_workload: {
    open: 3,
    pending: 2,
    review: 1,
    date_independent: true,
    items: [{ bag_id: "AAA", order_instance_id: 1 }],
  },
  selected_date_completed: {
    date_et: "2026-09-02",
    completed: 112,
    items: [],
  },
  segments: {
    wf: {
      total_workload: 3,
      completed: 112,
      pending: 3,
      current_open: 3,
      exceptions: { review_required: 1 },
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
  it("keeps Current Workload separate from selected-date Completed", () => {
    const wf = wfHeadline(rinse.segments.wf);
    expect(wf).toEqual({
      completed: 112,
      pending: 3,
      review: 1,
      currentOpen: 3,
      dayClosed: false,
    });
    const cw = pickCurrentWorkload(rinse, rinse.segments.wf);
    expect(cw.open).toBe(3);
    expect(cw.review).toBe(1);
    expect(cw.dateIndependent).toBe(true);
    const sc = pickSelectedDateCompleted(rinse, rinse.segments.wf);
    expect(sc.completed).toBe(112);
    expect(sc.dateEt).toBe("2026-09-02");
  });

  it("prefers current_open overlay for pending across selected dates", () => {
    const seg = {
      total_workload: 3,
      completed: 124,
      pending: 0,
      current_open: 3,
      exceptions: { review_required: 0 },
    };
    const wf = wfHeadline(seg);
    expect(wf.pending).toBe(3);
    expect(wf.currentOpen).toBe(3);
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
            pre_lbs: 40,
            post_lbs: 30,
            pre_weight_lbs: 40,
            post_weight_lbs: 30,
            pre_weight_bag_count: 4,
            post_weight_bag_count: 3,
          },
        },
      },
    };
    expect(pickWfWeights(withWeights, "rush").preLbs).toBe(40);
    expect(pickWfWeights(withWeights, "all").postBagCount).toBe(8);
  });
});
