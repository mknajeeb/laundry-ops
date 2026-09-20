import { normPayPeriodYmd } from "./payPeriodOptions";
import { displayStatusLabel } from "./payrollBatchStatus";

/** Batches in the dashboard pay period. Same period does not collapse rows. */
export function periodBatchesForDashboard(batches = [], payPeriodStart, payPeriodEnd) {
  const ps = normPayPeriodYmd(payPeriodStart);
  const pe = normPayPeriodYmd(payPeriodEnd);
  if (!ps || !pe) return [];
  return (batches || []).filter(
    (b) =>
      normPayPeriodYmd(b.pay_period_start) === ps && normPayPeriodYmd(b.pay_period_end) === pe,
  );
}

/**
 * Resolve Current Payroll Period selection by numeric payout_batch.id only.
 * Never first-match by (period, category).
 */
export function resolveDashboardBatch(periodBatches = [], selectedBatchId) {
  if (selectedBatchId == null || selectedBatchId === "") return null;
  return periodBatches.find((b) => String(b?.id) === String(selectedBatchId)) || null;
}

/** Chip / summary identity label — includes batch_name. */
export function formatDashboardBatchChip(batch) {
  const name = batch?.batch_name || (batch?.id != null ? `Batch ${batch.id}` : "Batch");
  const cat = batch?.worker_category_label || batch?.worker_category || "";
  const status = displayStatusLabel(batch);
  if (cat) return `${cat} · ${name} · ${status}`;
  return `${name} · ${status}`;
}

/** Default selection when period loads or selection is missing. Prefer unpaid, else first by id. */
export function defaultDashboardBatchId(periodBatches = []) {
  if (!periodBatches.length) return null;
  const unpaid = periodBatches.find((b) => b.payroll_display?.display_status !== "paid");
  return (unpaid || periodBatches[0])?.id ?? null;
}
