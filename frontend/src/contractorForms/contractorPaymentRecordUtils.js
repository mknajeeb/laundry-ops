/** Map saved payment summary rows ↔ editable invoice form state. */

import { emptyPaymentRecord, splitSupervisorFields } from "./ContractorInvoicePaymentPrint";

function numStr(v) {
  if (v == null || v === "") return "";
  const n = Number(v);
  return Number.isFinite(n) ? String(v) : "";
}

export function savedPaymentRowToRecord(row, prefill = null) {
  const snap = row?.form_snapshot_json && typeof row.form_snapshot_json === "object"
    ? row.form_snapshot_json
    : {};
  const ctype = row?.contractor_type || snap.contractor_type || "regular";
  const base = emptyPaymentRecord(prefill || snap, ctype);
  const supervisor = splitSupervisorFields(
    snap.company_supervisor_name || prefill?.company_supervisor_name,
  );
  return {
    ...base,
    ...snap,
    contractor_type: ctype,
    worker_name: row?.worker_name_snapshot || snap.worker_name || base.worker_name,
    worker_phone: row?.worker_phone_snapshot || snap.worker_phone || base.worker_phone,
    worker_email: row?.worker_email_snapshot || snap.worker_email || base.worker_email,
    work_period_start: row?.pay_period_start || snap.work_period_start || "",
    work_period_end: row?.pay_period_end || snap.work_period_end || "",
    work_performed: row?.work_performed || snap.work_performed || "",
    approved_hours: numStr(row?.approved_service_hours ?? snap.approved_hours),
    service_rate: numStr(row?.service_rate ?? snap.service_rate),
    health_safety_credit_hours: numStr(
      row?.health_safety_credit_hours ?? snap.health_safety_credit_hours,
    ),
    adjustment_amount: numStr(row?.adjustments ?? snap.adjustment_amount),
    service_amount: Number(row?.service_amount ?? snap.service_amount) || 0,
    health_safety_credit_amount:
      Number(row?.health_safety_credit_amount ?? snap.health_safety_credit_amount) || 0,
    total_amount_due: Number(row?.total_amount_due ?? row?.total_payment ?? snap.total_amount_due) || 0,
    amount_paid: numStr(row?.amount_paid ?? snap.amount_paid),
    payment_method: row?.payment_method || snap.payment_method || "",
    payment_reference: row?.payment_reference || snap.payment_reference || "",
    payment_date: row?.payment_date || snap.payment_date || base.payment_date,
    invoice_date: row?.invoice_date || snap.invoice_date || base.invoice_date,
    issued_by_entity: snap.issued_by_entity || "veewash",
    issue_from_name: snap.issue_from_name || "",
    issue_from_address: snap.issue_from_address || "",
    company_supervisor_name:
      snap.company_supervisor_name || supervisor.company_supervisor_name || "",
    company_supervisor_title:
      snap.company_supervisor_title || supervisor.company_supervisor_title || "",
    total_paid_ytd_prior: numStr(snap.total_paid_ytd_prior ?? "0"),
    notes: row?.notes || snap.notes || "",
    print_include_payment_reference: snap.print_include_payment_reference !== false,
    amount_paid_manual: Boolean(snap.amount_paid_manual),
  };
}
