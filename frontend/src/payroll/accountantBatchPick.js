import { normPayPeriodYmd } from "./payPeriodOptions";

function batchEndMs(batch) {
  const end = normPayPeriodYmd(batch?.pay_period_end);
  if (!end) return 0;
  const ms = Date.parse(`${end}T12:00:00`);
  return Number.isFinite(ms) ? ms : 0;
}

function isPendingBatch(batch) {
  if (!batch) return false;
  if (batch.status === "sent_to_accountant") return true;
  if (batch.accountant_processing_status === "PENDING") return true;
  if (batch.payroll_display?.display_status === "ready_for_payroll") return true;
  return false;
}

function isProcessedBatch(batch) {
  if (!batch) return false;
  if (batch.accountant_processing_status === "PROCESSED") return true;
  return ["accountant_reviewed", "approved_for_payment", "paid", "closed"].includes(
    String(batch.status || ""),
  );
}

/** Prefer newest pending batch, then newest processed, then newest overall. */
export function pickDefaultAccountantBatch(batches = []) {
  const sorted = [...batches].sort((a, b) => batchEndMs(b) - batchEndMs(a));
  return (
    sorted.find(isPendingBatch) ||
    sorted.find(isProcessedBatch) ||
    sorted[0] ||
    null
  );
}

export function accountantPeriodStatusLabel(batch) {
  if (!batch) return null;
  if (isPendingBatch(batch)) return "PENDING";
  if (isProcessedBatch(batch)) return "PROCESSED";
  return null;
}
