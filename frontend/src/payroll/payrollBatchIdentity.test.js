import { describe, expect, it } from "vitest";
import { batchVisibleForDetails } from "./payrollBatchStatus";
import {
  formatFinalizeBatchRow,
  groupFinalizeBatches,
} from "./finalizeBatchNav";
import {
  buildPayrollPeriodChoices,
  resolveAccountantBatchById,
} from "./payPeriodOptions";
import { accountantPeriodStatusLabel } from "./accountantBatchPick";
import {
  formatDashboardBatchChip,
  periodBatchesForDashboard,
  resolveDashboardBatch,
} from "./payrollDashboardNav";

/**
 * Production Sep 7–13 fixture: two distinct W-2 payout batches in the same week,
 * plus 1099 and TEMP. Identity is numeric payout_batch.id — never period or label.
 */
function sep713Fixture() {
  return [
    {
      id: 120,
      batch_name: "W2-2026-019",
      worker_category: "w2",
      worker_category_label: "W-2",
      pay_period_start: "2026-09-07",
      pay_period_end: "2026-09-13",
      status: "sent_to_accountant",
      accountant_processing_status: "PENDING",
      payroll_display: {
        display_status: "ready_for_payroll",
        display_status_label: "Ready For Payroll",
        worker_category: "w2",
      },
    },
    {
      id: 122,
      batch_name: "W2-2026-019-EVELYN",
      worker_category: "w2",
      worker_category_label: "W-2",
      pay_period_start: "2026-09-07",
      pay_period_end: "2026-09-13",
      status: "approved_for_payment",
      accountant_processing_status: "PENDING",
      payroll_display: {
        display_status: "ready_for_payroll",
        display_status_label: "Ready For Payroll",
        worker_category: "w2",
      },
    },
    {
      id: 200,
      batch_name: "1099-2026-019",
      worker_category: "contractor_1099",
      worker_category_label: "1099",
      pay_period_start: "2026-09-07",
      pay_period_end: "2026-09-13",
      status: "approved_for_payment",
      payroll_display: {
        display_status: "ready_to_pay",
        display_status_label: "Ready To Pay",
        worker_category: "contractor_1099",
      },
    },
    {
      id: 201,
      batch_name: "TEMP-2026-019",
      worker_category: "temp",
      worker_category_label: "Temp",
      pay_period_start: "2026-09-07",
      pay_period_end: "2026-09-13",
      status: "approved_for_payment",
      payroll_display: {
        display_status: "ready_to_pay",
        display_status_label: "Ready To Pay",
        worker_category: "temp",
      },
    },
  ];
}

describe("Sep 7–13 payroll batch identity fixture", () => {
  const batches = sep713Fixture();

  it("batchVisibleForDetails keeps both W-2 statuses (does not hide sent_to_accountant)", () => {
    const visible = batches.filter(batchVisibleForDetails);
    expect(visible.map((b) => b.id).sort((a, b) => a - b)).toEqual([120, 122, 200, 201]);
    expect(visible.find((b) => b.id === 120).status).toBe("sent_to_accountant");
    expect(visible.find((b) => b.id === 122).status).toBe("approved_for_payment");
  });

  it("Finalize shows both W-2 rows for the same week without dedupe", () => {
    const visible = batches.filter(batchVisibleForDetails);
    const w2 = groupFinalizeBatches(visible).find((s) => s.key === "w2");
    expect(w2.items.map((b) => b.id)).toEqual([122, 120]);
    expect(w2.items.map((b) => b.batch_name)).toEqual([
      "W2-2026-019-EVELYN",
      "W2-2026-019",
    ]);
    expect(formatFinalizeBatchRow(w2.items.find((b) => b.id === 120))).toBe(
      "Sep 7\u2013Sep 13 · W2-2026-019 · Ready For Payroll",
    );
    expect(formatFinalizeBatchRow(w2.items.find((b) => b.id === 122))).toBe(
      "Sep 7\u2013Sep 13 · W2-2026-019-EVELYN · Ready For Payroll",
    );
    const select = (id) => w2.items.find((b) => b.id === id);
    expect(select(120).id).toBe(120);
    expect(select(122).id).toBe(122);
    expect(select(120).status).toBe("sent_to_accountant");
    expect(select(122).status).toBe("approved_for_payment");
  });

  it("Accountant By Batch uses batch:<id> and distinguishes both W-2 batches", () => {
    const w2 = batches.filter((b) => b.worker_category === "w2");
    const options = buildPayrollPeriodChoices(0, w2, {
      batchOnly: true,
      batchStatusLabel: accountantPeriodStatusLabel,
    });
    expect(options).toHaveLength(2);
    expect(options.map((o) => o.key)).toEqual(["batch:122", "batch:120"]);
    expect(options.map((o) => o.batchId)).toEqual([122, 120]);
    expect(resolveAccountantBatchById(w2, 120)).toMatchObject({
      id: 120,
      batch_name: "W2-2026-019",
      status: "sent_to_accountant",
    });
    expect(resolveAccountantBatchById(w2, 122)).toMatchObject({
      id: 122,
      batch_name: "W2-2026-019-EVELYN",
      status: "approved_for_payment",
    });
    expect(resolveAccountantBatchById(w2, "batch:120")?.id).toBe(120);
    expect(resolveAccountantBatchById(w2, "2026-09-07|2026-09-13")).toBeNull();
  });

  it("Dashboard keeps same-period batches distinct and selects by numeric id", () => {
    const period = periodBatchesForDashboard(batches, "2026-09-07", "2026-09-13");
    expect(period.map((b) => b.id).sort((a, b) => a - b)).toEqual([120, 122, 200, 201]);
    expect(resolveDashboardBatch(period, 120)?.batch_name).toBe("W2-2026-019");
    expect(resolveDashboardBatch(period, 122)?.batch_name).toBe("W2-2026-019-EVELYN");
    expect(resolveDashboardBatch(period, 120)?.status).toBe("sent_to_accountant");
    expect(resolveDashboardBatch(period, 122)?.status).toBe("approved_for_payment");
    expect(formatDashboardBatchChip(period.find((b) => b.id === 120))).toContain("W2-2026-019");
    expect(formatDashboardBatchChip(period.find((b) => b.id === 122))).toContain(
      "W2-2026-019-EVELYN",
    );
    // first (period, category) match must not be identity
    const firstW2 = period.find((b) => b.worker_category === "w2");
    expect(resolveDashboardBatch(period, 122)?.id).not.toBe(firstW2.id);
  });

  it("identity stays numeric when two same-category batches have similar names", () => {
    const similar = [
      {
        id: 301,
        batch_name: "W2-2026-020",
        worker_category: "w2",
        pay_period_start: "2026-09-14",
        pay_period_end: "2026-09-20",
        status: "sent_to_accountant",
        payroll_display: {
          display_status: "ready_for_payroll",
          display_status_label: "Ready For Payroll",
        },
      },
      {
        id: 302,
        batch_name: "W2-2026-020A",
        worker_category: "w2",
        pay_period_start: "2026-09-14",
        pay_period_end: "2026-09-20",
        status: "approved_for_payment",
        payroll_display: {
          display_status: "ready_for_payroll",
          display_status_label: "Ready For Payroll",
        },
      },
    ];
    const visible = similar.filter(batchVisibleForDetails);
    const w2 = groupFinalizeBatches(visible).find((s) => s.key === "w2").items;
    expect(w2.map((b) => b.id)).toEqual([302, 301]);
    expect(w2.find((b) => b.batch_name.startsWith("W2-2026-020") && b.id === 301).id).toBe(301);
    expect(w2.find((b) => b.id === 302).batch_name).toBe("W2-2026-020A");

    const options = buildPayrollPeriodChoices(0, similar, {
      batchOnly: true,
      batchStatusLabel: accountantPeriodStatusLabel,
    });
    expect(options.map((o) => o.key)).toEqual(["batch:302", "batch:301"]);
    expect(resolveAccountantBatchById(similar, 301)?.batch_name).toBe("W2-2026-020");
    expect(resolveAccountantBatchById(similar, 302)?.batch_name).toBe("W2-2026-020A");

    const period = periodBatchesForDashboard(similar, "2026-09-14", "2026-09-20");
    expect(resolveDashboardBatch(period, 301)?.status).toBe("sent_to_accountant");
    expect(resolveDashboardBatch(period, 302)?.status).toBe("approved_for_payment");
  });

  it("does not rewrite underlying statuses for display mapping", () => {
    expect(batches.find((b) => b.id === 120).status).toBe("sent_to_accountant");
    expect(batches.find((b) => b.id === 122).status).toBe("approved_for_payment");
    expect(batches.find((b) => b.id === 120).payroll_display.display_status_label).toBe(
      "Ready For Payroll",
    );
  });
});
