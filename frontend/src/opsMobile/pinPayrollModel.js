/**
 * Read-only payroll presentation from payout-batch list rows.
 * Employee lines and wage rates are never copied into the mobile view.
 */

const APPROVED = new Set(["ready_for_payroll", "ready_to_pay", "paid"]);
const PAYABLE = new Set(["contractor_1099", "temp", "tryout"]);

export function displayStatus(batch) {
  return batch?.payroll_display?.display_status || "draft";
}

export function displayStatusLabel(batch) {
  return batch?.payroll_display?.display_status_label || "Draft";
}

export function isApprovedBatch(batch) {
  return APPROVED.has(displayStatus(batch));
}

function money(value) {
  if (value == null || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

export function formatMoney(value) {
  const n = money(value);
  if (n == null) return "—";
  return `$${n.toFixed(2)}`;
}

/** Batch-level figures only. Line-level compensation is dropped. */
export function publicBatch(batch) {
  if (!batch || typeof batch !== "object") return null;
  const summary = batch.payroll_display?.payroll_summary || {};
  return {
    id: batch.id,
    name: batch.batch_name || "Payroll batch",
    status: displayStatus(batch),
    statusLabel: displayStatusLabel(batch),
    payPeriodStart: String(batch.pay_period_start || "").slice(0, 10),
    payPeriodEnd: String(batch.pay_period_end || "").slice(0, 10),
    category: batch.worker_category_label || batch.worker_category || "",
    categoryKey: String(batch.worker_category || "").toLowerCase(),
    employees: Number(batch.worker_count ?? summary.employee_count ?? 0),
    approvedHours: money(batch.total_approved_hours),
    grossWages: money(batch.total_gross_amount),
    payoutAmount: money(batch.total_payout_amount),
    adjustments: money(batch.total_adjustments),
    paidOn: storedDay(batch.paid_at),
    sentOn: storedDay(batch.sent_to_accountant_at),
  };
}

export function isPayableCategory(row) {
  return PAYABLE.has(String(row?.categoryKey || row?.worker_category || "").toLowerCase());
}

export function workerPaymentRows(batch) {
  return (batch?.lines || []).map((line) => {
    const recorded = String(line?.payout_details?.settlement?.payment_recorded || "").toLowerCase();
    const status = String(line?.payment_status || "").toLowerCase();
    const paid = recorded === "paid" || status === "paid";
    const amount = money(line?.total_amount ?? line?.gross_amount);
    return {
      id: line.id,
      name: line.worker_name_snapshot || line.worker_name || "Worker",
      paid,
      statusLabel: paid ? "Paid" : "Ready to Pay",
      amount,
      paidAmount: paid ? amount : 0,
      remaining: paid ? 0 : amount,
    };
  });
}

export function paymentTotals(workers) {
  let paid = 0;
  let remaining = 0;
  let paidKnown = false;
  let remainingKnown = false;
  for (const worker of workers || []) {
    if (worker.paidAmount != null) {
      paid += worker.paidAmount;
      paidKnown = true;
    }
    if (worker.remaining != null) {
      remaining += worker.remaining;
      remainingKnown = true;
    }
  }
  const round = (n) => Math.round(n * 100) / 100;
  return {
    paidAmount: paidKnown ? round(paid) : null,
    remainingAmount: remainingKnown ? round(remaining) : null,
    paidWorkers: (workers || []).filter((worker) => worker.paid).length,
    unpaidWorkers: (workers || []).filter((worker) => !worker.paid).length,
  };
}

export function approvedPublicBatches(items) {
  return (items || []).map(publicBatch).filter((row) => row && APPROVED.has(row.status));
}

export function periodKey(row) {
  if (!row?.payPeriodStart || !row?.payPeriodEnd) return "";
  return `${row.payPeriodStart}|${row.payPeriodEnd}`;
}

export function payrollPeriods(rows) {
  const seen = new Map();
  for (const row of rows || []) {
    const key = periodKey(row);
    if (!key || seen.has(key)) continue;
    seen.set(key, {
      key,
      start: row.payPeriodStart,
      end: row.payPeriodEnd,
    });
  }
  return [...seen.values()].sort((a, b) => b.start.localeCompare(a.start));
}

export function periodContaining(periods, ymd) {
  const day = String(ymd || "");
  return (periods || []).find((period) => period.start <= day && day <= period.end) || periods?.[0] || null;
}

export function batchesForPeriod(rows, period) {
  if (!period) return [];
  return (rows || []).filter((row) => periodKey(row) === period.key);
}

export function storedDay(value) {
  const match = String(value || "").match(/^(\d{4}-\d{2}-\d{2})/);
  return match ? match[1] : "";
}

/** Paid or sent date, using the calendar day stored on the batch timestamp. */
export function batchesByStoredPaidDate(rows, from, to) {
  const start = String(from || "");
  const end = String(to || "");
  return (rows || []).filter((row) => {
    const day = row.paidOn || row.sentOn;
    if (!day) return false;
    if (start && day < start) return false;
    if (end && day > end) return false;
    return true;
  });
}

export function periodsOverlapping(periods, from, to) {
  const start = String(from || "");
  const end = String(to || "");
  return (periods || []).filter((period) => {
    if (start && period.end < start) return false;
    if (end && period.start > end) return false;
    return true;
  });
}

export function summarizeBatches(rows) {
  let hours = 0;
  let gross = 0;
  let payout = 0;
  let hoursKnown = false;
  let grossKnown = false;
  let payoutKnown = false;
  for (const row of rows || []) {
    if (row.approvedHours != null) {
      hours += row.approvedHours;
      hoursKnown = true;
    }
    if (row.grossWages != null) {
      gross += row.grossWages;
      grossKnown = true;
    }
    if (row.payoutAmount != null) {
      payout += row.payoutAmount;
      payoutKnown = true;
    }
  }
  const round = (n) => Math.round(n * 100) / 100;
  return {
    batches: (rows || []).length,
    employees: (rows || []).reduce((sum, row) => sum + Number(row.employees || 0), 0),
    approvedHours: hoursKnown ? round(hours) : null,
    grossWages: grossKnown ? round(gross) : null,
    payoutAmount: payoutKnown ? round(payout) : null,
  };
}

const PAYROLL_VIEW_KEY = "pinPayrollView.v1";

export function loadPayrollView() {
  try {
    const raw = sessionStorage.getItem(PAYROLL_VIEW_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : null;
  } catch {
    return null;
  }
}

export function savePayrollView(view) {
  try {
    sessionStorage.setItem(PAYROLL_VIEW_KEY, JSON.stringify(view));
  } catch {
    /* ignore */
  }
}
