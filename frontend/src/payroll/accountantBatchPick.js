import { normPayPeriodYmd } from "./payPeriodOptions";

const STATUS_LABELS = {
  PENDING: "Pending",
  PAYMENT_INITIATED: "Payment initiated",
  PAID: "Paid",
};

function batchEndMs(batch) {
  const end = normPayPeriodYmd(batch?.pay_period_end);
  if (!end) return 0;
  const ms = Date.parse(`${end}T12:00:00`);
  return Number.isFinite(ms) ? ms : 0;
}

function isPaymentConfirmed(batch) {
  return Boolean(
    batch?.accountant_payment_confirmed_at || batch?.payout_workflow?.accountant_payment_confirmed,
  );
}

function isPendingBatch(batch) {
  if (!batch) return false;
  if (batch.accountant_processing_status === "PENDING") return true;
  const st = String(batch.status || "");
  if (st === "sent_to_accountant") return true;
  if (st === "approved_for_payment" && !isPaymentConfirmed(batch)) return true;
  return false;
}

function isPaidBatch(batch) {
  if (!batch) return false;
  if (batch.accountant_processing_status === "PAID") return true;
  return ["paid", "closed"].includes(String(batch.status || ""));
}

/** Prefer newest pending batch, then newest paid, then newest overall. */
export function pickDefaultAccountantBatch(batches = []) {
  const sorted = [...batches].sort((a, b) => batchEndMs(b) - batchEndMs(a));
  return sorted.find(isPendingBatch) || sorted.find(isPaidBatch) || sorted[0] || null;
}

export function accountantPeriodStatusLabel(batch) {
  if (!batch) return null;
  const proc = batch.accountant_processing_status;
  if (proc && STATUS_LABELS[proc]) return STATUS_LABELS[proc];

  const st = String(batch.status || "");
  if (st === "sent_to_accountant") return STATUS_LABELS.PENDING;
  if (st === "approved_for_payment") {
    return isPaymentConfirmed(batch)
      ? STATUS_LABELS.PAYMENT_INITIATED
      : STATUS_LABELS.PENDING;
  }
  if (st === "accountant_reviewed") return STATUS_LABELS.PAYMENT_INITIATED;
  if (st === "paid" || st === "closed") return STATUS_LABELS.PAID;
  return null;
}

export function accountantPeriodStatusColor(batch) {
  const label = accountantPeriodStatusLabel(batch);
  if (label === STATUS_LABELS.PAID) return "success";
  if (label === STATUS_LABELS.PAYMENT_INITIATED) return "info";
  if (label === STATUS_LABELS.PENDING) return "warning";
  return "default";
}
