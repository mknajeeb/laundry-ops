import { describe, expect, it } from "vitest";
import {
  FINALIZE_NAV_INITIAL_COUNT,
  formatFinalizeBatchRow,
  groupFinalizeBatches,
  visibleFinalizeBatches,
} from "./finalizeBatchNav";

function batch(partial) {
  return {
    payroll_display: { display_status_label: "Ready For Payroll", display_status: "ready_for_payroll" },
    ...partial,
  };
}

describe("Finalize Payroll batch navigation", () => {
  const batches = [
    batch({
      id: 120,
      batch_name: "W2-2026-019",
      worker_category: "w2",
      pay_period_start: "2026-09-07",
      pay_period_end: "2026-09-13",
    }),
    batch({
      id: 122,
      batch_name: "W2-2026-019-EVELYN",
      worker_category: "w2",
      pay_period_start: "2026-09-07",
      pay_period_end: "2026-09-13",
    }),
    batch({
      id: 112,
      batch_name: "W2-2026-017",
      worker_category: "w2",
      pay_period_start: "2026-08-24",
      pay_period_end: "2026-08-30",
      payroll_display: { display_status_label: "Paid", display_status: "paid" },
    }),
    batch({
      id: 200,
      batch_name: "1099-2026-019",
      worker_category: "contractor_1099",
      pay_period_start: "2026-09-07",
      pay_period_end: "2026-09-13",
      payroll_display: { display_status_label: "Ready To Pay" },
    }),
    batch({
      id: 201,
      batch_name: "TEMP-2026-019",
      worker_category: "temp",
      pay_period_start: "2026-09-07",
      pay_period_end: "2026-09-13",
    }),
    batch({
      id: 202,
      batch_name: "TRYOUT-2026-001",
      worker_category: "tryout",
      pay_period_start: "2026-08-31",
      pay_period_end: "2026-09-06",
      payroll_display: { display_status_label: "Draft" },
    }),
  ];

  it("keeps same-week batches separate and orders by period end then id", () => {
    const w2 = groupFinalizeBatches(batches).find((s) => s.key === "w2");
    expect(w2.items.map((b) => b.id)).toEqual([122, 120, 112]);
    expect(w2.items.map((b) => b.batch_name)).toEqual([
      "W2-2026-019-EVELYN",
      "W2-2026-019",
      "W2-2026-017",
    ]);
    expect(formatFinalizeBatchRow(w2.items[1])).toBe(
      "Sep 7\u2013Sep 13 · W2-2026-019 · Ready For Payroll",
    );
    expect(formatFinalizeBatchRow(w2.items[2])).toContain("Paid");
  });

  it("groups 1099 alone and puts tryout under Temp without changing category", () => {
    const groups = groupFinalizeBatches(batches);
    const contractor = groups.find((s) => s.key === "contractor_1099");
    const temp = groups.find((s) => s.key === "temp");
    expect(contractor.items.map((b) => b.id)).toEqual([200]);
    expect(temp.items.map((b) => b.worker_category)).toEqual(["temp", "tryout"]);
    expect(temp.items[1].worker_category).toBe("tryout");
  });

  it("shows five newest until that category is expanded", () => {
    const items = Array.from({ length: 7 }, (_, i) =>
      batch({
        id: i + 1,
        batch_name: `W2-${i + 1}`,
        worker_category: "w2",
        pay_period_start: "2026-01-05",
        pay_period_end: `2026-0${Math.min(9, i + 1)}-11`,
      }),
    );
    const sorted = groupFinalizeBatches(items)[0].items;
    expect(visibleFinalizeBatches(sorted, false)).toHaveLength(FINALIZE_NAV_INITIAL_COUNT);
    expect(visibleFinalizeBatches(sorted, true)).toHaveLength(7);
    expect(visibleFinalizeBatches(sorted, false).map((b) => b.id)).toEqual(
      sorted.slice(0, 5).map((b) => b.id),
    );
  });

  it("selects by batch id, not by shared pay period", () => {
    const w2 = groupFinalizeBatches(batches).find((s) => s.key === "w2").items;
    const select = (id) => w2.find((b) => b.id === id);
    expect(select(120).batch_name).toBe("W2-2026-019");
    expect(select(122).batch_name).toBe("W2-2026-019-EVELYN");
    expect(select(120).id).not.toBe(select(122).id);
    const samePeriod = w2.filter((b) => b.pay_period_end === "2026-09-13");
    expect(samePeriod).toHaveLength(2);
  });
});
