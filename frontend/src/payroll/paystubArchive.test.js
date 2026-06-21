import { describe, expect, it } from "vitest";
import { recentBatchIds } from "./paystubArchive";

describe("recentBatchIds", () => {
  const batches = [
    { id: 1, pay_period_start: "2026-05-04" },
    { id: 2, pay_period_start: "2026-05-11" },
    { id: 3, pay_period_start: "2026-05-18" },
    { id: 4, pay_period_start: "2026-05-25" },
    { id: 5, pay_period_start: "2026-06-01" },
    { id: 7, pay_period_start: "2026-06-08" },
  ];

  it("returns the last N batch ids in chronological order", () => {
    expect(recentBatchIds(batches, 6)).toEqual([1, 2, 3, 4, 5, 7]);
    expect(recentBatchIds(batches, 5)).toEqual([2, 3, 4, 5, 7]);
    expect(recentBatchIds(batches, 3)).toEqual([4, 5, 7]);
  });
});
