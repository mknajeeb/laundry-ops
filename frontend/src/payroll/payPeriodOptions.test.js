import { describe, expect, it } from "vitest";
import { buildPayrollPeriodChoices, mergePayPeriodOptions } from "./payPeriodOptions";

function accountantPeriodStatusLabel(batch) {
  if (!batch || typeof batch !== "object") return null;
  const st = batch.accountant_processing_status;
  if (st === "PENDING" || st === "PROCESSED") return st;
  if (batch.status === "sent_to_accountant") return "PENDING";
  if (
    batch.status === "accountant_reviewed" ||
    batch.status === "approved_for_payment" ||
    batch.status === "paid" ||
    batch.status === "closed"
  ) {
    return "PROCESSED";
  }
  return null;
}

describe("payPeriodOptions accountant batch status", () => {
  it("passes full batch objects to batchStatusLabel (not status string)", () => {
    const pendingBatch = {
      id: 1,
      pay_period_start: "2026-05-18",
      pay_period_end: "2026-05-24",
      status: "sent_to_accountant",
      accountant_processing_status: "PENDING",
    };
    const processedBatch = {
      id: 2,
      pay_period_start: "2026-05-11",
      pay_period_end: "2026-05-17",
      status: "accountant_reviewed",
      accountant_processing_status: "PROCESSED",
    };
    const labels = [];
    mergePayPeriodOptions([], [pendingBatch, processedBatch], (batch) => {
      labels.push(batch);
      return accountantPeriodStatusLabel(batch);
    });

    expect(labels).toHaveLength(2);
    expect(labels[0]).toMatchObject({ id: 1, status: "sent_to_accountant" });
    expect(labels[1]).toMatchObject({ id: 2, status: "accountant_reviewed" });
  });

  it("shows PENDING and PROCESSED suffixes from accountant_processing_status", () => {
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
          status: "accountant_reviewed",
          accountant_processing_status: "PROCESSED",
        },
      ],
      { batchOnly: true, batchStatusLabel: accountantPeriodStatusLabel },
    );

    const pending = options.find((o) => o.key === "2026-05-18|2026-05-24");
    const processed = options.find((o) => o.key === "2026-05-11|2026-05-17");

    expect(pending?.label).toContain("PENDING");
    expect(pending?.label).not.toContain("PROCESSED");
    expect(processed?.label).toContain("PROCESSED");
    expect(processed?.batchStatus).toBe("PROCESSED");
  });
});
