import { describe, expect, it } from "vitest";
import {
  approvedPublicBatches,
  batchesByStoredPaidDate,
  batchesForPeriod,
  paymentTotals,
  payrollPeriods,
  periodContaining,
  publicBatch,
  summarizeBatches,
  workerPaymentRows,
} from "./pinPayrollModel";

const approved = {
  id: 9,
  batch_name: "W-2 Nov 10",
  worker_category: "w2",
  pay_period_start: "2026-11-10",
  pay_period_end: "2026-11-16",
  worker_count: 4,
  total_approved_hours: 80,
  total_gross_amount: 1600,
  total_payout_amount: 1400,
  total_adjustments: 25,
  paid_at: "2026-11-18 15:00:00",
  payroll_display: { display_status: "paid", display_status_label: "Paid" },
  lines: [{ worker_name_snapshot: "Ana", gross_amount: 400, hourly_rate: 20 }],
};

describe("payroll mobile model", () => {
  it("drops employee compensation and keeps gross wages separate from payout", () => {
    const row = publicBatch(approved);
    expect(row.lines).toBeUndefined();
    expect(row.grossWages).toBe(1600);
    expect(row.payoutAmount).toBe(1400);
    expect(row.approvedHours).toBe(80);
    expect(JSON.stringify(row)).not.toContain("hourly_rate");
    expect(JSON.stringify(row)).not.toContain("Ana");
  });

  it("keeps drafts out of the approved list and summarizes one pay period", () => {
    const rows = approvedPublicBatches([
      approved,
      {
        id: 3,
        batch_name: "Draft",
        pay_period_start: "2026-11-10",
        pay_period_end: "2026-11-16",
        total_gross_amount: 9999,
        payroll_display: { display_status: "draft", display_status_label: "Draft" },
      },
    ]);
    expect(rows).toHaveLength(1);
    const periods = payrollPeriods(rows);
    expect(periodContaining(periods, "2026-11-12").start).toBe("2026-11-10");
    const summary = summarizeBatches(batchesForPeriod(rows, periods[0]));
    expect(summary.batches).toBe(1);
    expect(summary.grossWages).toBe(1600);
    expect(summary.payoutAmount).toBe(1400);
    expect(summary.approvedHours).toBe(80);
  });

  it("tracks partial 1099 payment without exposing the hourly rate", () => {
    const workers = workerPaymentRows({
      lines: [
        { id: 1, worker_name_snapshot: "Ana", payment_status: "paid", total_amount: 500, hourly_rate: 25 },
        { id: 2, worker_name_snapshot: "Luis", payment_status: "approved_unpaid", total_amount: 300, hourly_rate: 20 },
      ],
    });
    expect(workers.map((worker) => worker.statusLabel)).toEqual(["Paid", "Ready to Pay"]);
    expect(paymentTotals(workers)).toMatchObject({ paidAmount: 500, remainingAmount: 300, unpaidWorkers: 1 });
    expect(JSON.stringify(workers)).not.toContain("hourly_rate");
  });

  it("filters by the stored paid or sent date", () => {
    const rows = approvedPublicBatches([approved]);
    expect(batchesByStoredPaidDate(rows, "2026-11-18", "2026-11-18")).toHaveLength(1);
    expect(batchesByStoredPaidDate(rows, "2026-11-19", "2026-11-19")).toHaveLength(0);
  });
});
