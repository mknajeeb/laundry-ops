import { describe, expect, it } from "vitest";
import {
  buildPayrollPeriodChoices,
  formatAccountantByBatchOptionLabel,
  mergePayPeriodOptions,
  resolveAccountantBatchById,
} from "./payPeriodOptions";
import { accountantPeriodStatusLabel } from "./accountantBatchPick";
import { formatWeekRangeLabel } from "../utils/businessTime";
import { displayStatusLabel } from "./payrollBatchStatus";

describe("payPeriodOptions accountant batch status", () => {
  it("does not call batchStatusLabel when building period (non-batch) options", () => {
    const pendingBatch = {
      id: 1,
      pay_period_start: "2026-05-18",
      pay_period_end: "2026-05-24",
      status: "sent_to_accountant",
      accountant_processing_status: "PENDING",
      payroll_display: { display_status_label: "Pending" },
    };
    const paidBatch = {
      id: 2,
      pay_period_start: "2026-05-11",
      pay_period_end: "2026-05-17",
      status: "paid",
      accountant_processing_status: "PAID",
      payroll_display: { display_status_label: "Paid" },
    };
    let calls = 0;
    const options = mergePayPeriodOptions([], [pendingBatch, paidBatch], () => {
      calls += 1;
      return "SHOULD_NOT_APPEAR";
    });

    expect(calls).toBe(0);
    expect(options).toHaveLength(2);
    for (const o of options) {
      expect(o.label).toBe(formatWeekRangeLabel(o.start, o.end));
      expect(o.label).not.toMatch(/Paid|Pending|Draft|SHOULD_NOT_APPEAR/i);
      expect(o.batchStatus).toBeNull();
    }
  });

  it("shows Pending and Paid suffixes on batch-only options from accountant_processing_status", () => {
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

  it("payroll period search collapses a shared week to one row without Paid/Pending", () => {
    const collapsed = mergePayPeriodOptions(
      [],
      samePeriodBatches.filter((b) => b.pay_period_start === "2026-09-07"),
      accountantPeriodStatusLabel,
    );
    expect(collapsed).toHaveLength(1);
    expect(collapsed[0].key).toBe("2026-09-07|2026-09-13");
    expect(collapsed[0].label).toBe(formatWeekRangeLabel("2026-09-07", "2026-09-13"));
    expect(collapsed[0].label).not.toMatch(/Paid|Pending|Draft/i);
  });
});

describe("pay-period label is not a batch payment status", () => {
  /** Sep 14–20 production-shaped week: 3 Draft + 1 Paid */
  const sep14Week = [
    {
      id: 132,
      batch_name: "W2-2026-020",
      pay_period_start: "2026-09-14",
      pay_period_end: "2026-09-20",
      status: "draft",
      payroll_display: { display_status: "draft", display_status_label: "Draft" },
    },
    {
      id: 133,
      batch_name: "1099-2026-020",
      pay_period_start: "2026-09-14",
      pay_period_end: "2026-09-20",
      status: "draft",
      payroll_display: { display_status: "draft", display_status_label: "Draft" },
    },
    {
      id: 134,
      batch_name: "TEMP-2026-020",
      pay_period_start: "2026-09-14",
      pay_period_end: "2026-09-20",
      status: "draft",
      payroll_display: { display_status: "draft", display_status_label: "Draft" },
    },
    {
      id: 127,
      batch_name: "1099-2026-020-MINA",
      pay_period_start: "2026-09-14",
      pay_period_end: "2026-09-20",
      status: "paid",
      accountant_processing_status: "PAID",
      payroll_display: { display_status: "paid", display_status_label: "Paid" },
    },
  ];

  it("period dropdown shows only the week range — never · Paid from the MINA batch", () => {
    const periodOptions = mergePayPeriodOptions([], sep14Week, accountantPeriodStatusLabel);
    expect(periodOptions).toHaveLength(1);
    const period = periodOptions[0];
    expect(period.key).toBe("2026-09-14|2026-09-20");
    expect(period.label).toBe(formatWeekRangeLabel("2026-09-14", "2026-09-20"));
    expect(period.label).toMatch(/Sep 14/);
    expect(period.label).toMatch(/Sep 20/);
    expect(period.label).not.toContain("Paid");
    expect(period.label).not.toContain("Pending");
    expect(period.label).not.toContain("Draft");
    expect(period.label).not.toContain("·");
  });

  it("individual batches retain Draft / Paid statuses", () => {
    expect(displayStatusLabel(sep14Week[0])).toMatch(/Draft/i);
    expect(displayStatusLabel(sep14Week[1])).toMatch(/Draft/i);
    expect(displayStatusLabel(sep14Week[2])).toMatch(/Draft/i);
    expect(displayStatusLabel(sep14Week[3])).toMatch(/Paid/i);

    const batchOptions = buildPayrollPeriodChoices(0, sep14Week, {
      batchOnly: true,
      batchStatusLabel: (b) => displayStatusLabel(b),
    });
    expect(batchOptions).toHaveLength(4);
    const byName = Object.fromEntries(batchOptions.map((o) => [o.batchName, o.label]));
    expect(byName["W2-2026-020"]).toContain("Draft");
    expect(byName["1099-2026-020"]).toContain("Draft");
    expect(byName["TEMP-2026-020"]).toContain("Draft");
    expect(byName["1099-2026-020-MINA"]).toContain("Paid");
    // Batch labels still include name + status; period collapse does not.
    expect(formatAccountantByBatchOptionLabel(sep14Week[3], "Paid")).toContain("Paid");
  });

  it("may append Available in Analysis as the only week-level suffix", () => {
    const withAvail = mergePayPeriodOptions([], sep14Week, null, {
      analysisAvailableKeys: new Set(["2026-09-14|2026-09-20"]),
    });
    expect(withAvail[0].label).toBe(
      `${formatWeekRangeLabel("2026-09-14", "2026-09-20")} · Available in Analysis`,
    );
    expect(withAvail[0].label).not.toMatch(/Paid|Pending|Draft/i);
  });
});
