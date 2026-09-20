import { describe, expect, it } from "vitest";
import { buildPayrollPeriodChoices, mergePayPeriodOptions, resolveAccountantBatchById } from "./payPeriodOptions";
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

    const pending = options.find((o) => o.batchId === 1);
    const paid = options.find((o) => o.batchId === 2);

    expect(pending?.key).toBe("batch:1");
    expect(paid?.key).toBe("batch:2");
    expect(pending?.label).toContain("Pending");
    expect(pending?.label).not.toContain("Paid");
    expect(paid?.label).toContain("Paid");
    expect(paid?.batchStatus).toBe("Paid");
  });

  const samePeriodBatches = [
    {
      id: 122,
      batch_name: "W2-2026-019-EVELYN",
      pay_period_start: "2026-09-07",
      pay_period_end: "2026-09-13",
      status: "approved_for_payment",
      accountant_processing_status: "PENDING",
    },
    {
      id: 120,
      batch_name: "W2-2026-019",
      pay_period_start: "2026-09-07",
      pay_period_end: "2026-09-13",
      status: "sent_to_accountant",
      accountant_processing_status: "PENDING",
    },
    {
      id: 112,
      batch_name: "W2-2026-017",
      pay_period_start: "2026-08-24",
      pay_period_end: "2026-08-30",
      status: "paid",
      accountant_processing_status: "PAID",
    },
  ];

  it("keeps both batches when they share a pay period", () => {
    const options = buildPayrollPeriodChoices(0, samePeriodBatches, {
      batchOnly: true,
      batchStatusLabel: accountantPeriodStatusLabel,
    });
    const week = options.filter((o) => o.start === "2026-09-07" && o.end === "2026-09-13");

    expect(week).toHaveLength(2);
    expect(week.map((o) => o.batchId)).toEqual([122, 120]);
    expect(week.map((o) => o.key)).toEqual(["batch:122", "batch:120"]);
    expect(week.map((o) => o.label)).toEqual([
      "Sep 7\u2013Sep 13 · W2-2026-019-EVELYN · Pending",
      "Sep 7\u2013Sep 13 · W2-2026-019 · Pending",
    ]);
    expect(new Set(options.map((o) => o.key)).size).toBe(options.length);
  });

  it("selects W2-2026-019 and W2-2026-019-EVELYN by batch id, not period", () => {
    const options = buildPayrollPeriodChoices(0, samePeriodBatches, {
      batchOnly: true,
      batchStatusLabel: accountantPeriodStatusLabel,
    });
    const select = (batchId) => {
      const opt = options.find((o) => o.key === `batch:${batchId}`);
      return resolveAccountantBatchById(samePeriodBatches, opt?.batchId);
    };

    expect(select(120)).toMatchObject({ id: 120, batch_name: "W2-2026-019" });
    expect(select(122)).toMatchObject({ id: 122, batch_name: "W2-2026-019-EVELYN" });
    expect(select(120)?.id).not.toBe(select(122)?.id);
    expect(resolveAccountantBatchById(samePeriodBatches, "2026-09-07|2026-09-13")).toBeNull();
    expect(resolveAccountantBatchById(samePeriodBatches, "batch:2026-09-07|2026-09-13")).toBeNull();
  });

  it("keeps a single option for a one-batch Paid period", () => {
    const options = buildPayrollPeriodChoices(0, samePeriodBatches, {
      batchOnly: true,
      batchStatusLabel: accountantPeriodStatusLabel,
    });
    const paidWeek = options.filter((o) => o.start === "2026-08-24" && o.end === "2026-08-30");

    expect(paidWeek).toHaveLength(1);
    expect(paidWeek[0]).toMatchObject({
      batchId: 112,
      key: "batch:112",
      label: "Aug 24\u2013Aug 30 · W2-2026-017 · Paid",
      batchStatus: "Paid",
    });
    expect(resolveAccountantBatchById(samePeriodBatches, paidWeek[0].batchId)?.id).toBe(112);
  });

  it("payroll period search still collapses a shared week to one row", () => {
    const collapsed = mergePayPeriodOptions(
      [],
      samePeriodBatches.filter((b) => b.pay_period_start === "2026-09-07"),
    );
    expect(collapsed).toHaveLength(1);
    expect(collapsed[0].key).toBe("2026-09-07|2026-09-13");
  });
});
