import { describe, expect, it } from "vitest";
import { buildPayrollPeriodChoices, mergePayPeriodOptions } from "./payPeriodOptions";
import {
  accountantPeriodStatusLabel,
} from "./accountantBatchPick";

describe("payPeriodOptions accountant batch status", () => {
  it("passes full batch objects to batchStatusLabel (not status string)", () => {
    const pendingBatch = {
      id: 1,
      pay_period_start: "2026-05-18",
      pay_period_end: "2026-05-24",
      status: "sent_to_accountant",
      accountant_processing_status: "PENDING",
    };
    const paidBatch = {
      id: 2,
      pay_period_start: "2026-05-11",
      pay_period_end: "2026-05-17",
      status: "paid",
      accountant_processing_status: "PAID",
    };
    const labels = [];
    mergePayPeriodOptions([], [pendingBatch, paidBatch], (batch) => {
      labels.push(batch);
      return accountantPeriodStatusLabel(batch);
    });

    expect(labels).toHaveLength(2);
    expect(labels[0]).toMatchObject({ id: 1, status: "sent_to_accountant" });
    expect(labels[1]).toMatchObject({ id: 2, status: "paid" });
  });

  it("shows Pending and Paid suffixes from accountant_processing_status", () => {
    const options = buildPayrollPeriodChoices(
      0,
      [
        {
          id: 1,
          pay_period_start: "2026-05-18",
          pay_period_end: "2026-05-24",
          status: "sent_to_accountant",
          accountant_processing_status: "PENDING",
        },
        {
          id: 2,
          pay_period_start: "2026-05-11",
          pay_period_end: "2026-05-17",
          status: "paid",
          accountant_processing_status: "PAID",
        },
      ],
      { batchOnly: true, batchStatusLabel: accountantPeriodStatusLabel },
    );

    const pending = options.find((o) => o.key === "2026-05-18|2026-05-24");
    const paid = options.find((o) => o.key === "2026-05-11|2026-05-17");

    expect(pending?.label).toContain("Pending");
    expect(pending?.label).not.toContain("Paid");
    expect(paid?.label).toContain("Paid");
    expect(paid?.batchStatus).toBe("Paid");
  });
});
