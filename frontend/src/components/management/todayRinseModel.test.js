import { describe, expect, it } from "vitest";
import {
  hdHeadline,
  hdIdentityLine,
  pickRinseSegments,
  pickWfSpecialty,
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
    hd: {
      total_workload: 13,
      completed: 0,
      pending: 0,
      exceptions: { review_required: 11 },
    },
    hd_rush: {
      total_workload: 2,
      completed: 0,
      pending: 0,
      exceptions: { review_required: 2 },
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
  hd_dashboard_totals: {
    total_hd_orders: 13,
    completed: 0,
    review_required: 11,
    total_items: 0,
    hd_revenue: 0,
  },
};

describe("TODAY rinse presentation model", () => {
  it("keeps WF workload/completed/pending/review identity", () => {
    const wf = wfHeadline(rinse.segments.wf);
    expect(wf).toEqual({ workload: 97, completed: 70, pending: 1, review: 26 });
    expect(wfIdentityLine(wf)).toBe("97 = 70 Completed + 1 Pending + 26 Review");
  });

  it("keeps HD operational facts without combining WF+HD", () => {
    const hd = hdHeadline(rinse.segments.hd, rinse.hd_dashboard_totals);
    expect(hd.orders).toBe(13);
    expect(hd.completed).toBe(0);
    expect(hd.review).toBe(11);
    expect(hdIdentityLine(hd)).toBe("13 = 0 Completed + 11 Review");
  });

  it("applies rush filter to WF segment and specialty counts", () => {
    expect(pickRinseSegments(rinse, "rush").wf.total_workload).toBe(12);
    expect(pickWfSpecialty(rinse, "all").rejected_orders.count).toBe(26);
    expect(pickWfSpecialty(rinse, "rush").rejected_orders.count).toBe(4);
  });
});
