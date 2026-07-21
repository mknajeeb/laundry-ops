/**
 * Category-aware helpers for the Payroll → By Employee document-history screen.
 *
 * Reuses the existing backend document-state per line (`row.document`) so there is
 * a single source of truth for whether a W-2 paystub or a temp/1099 vendor receipt
 * is available. No payroll amounts, taxes, or dates are computed here.
 *
 *   W-2            → official paystub
 *   Temp / 1099    → vendor receipt (finalized receipts use the stored snapshot)
 */

import {
  filterPayrollTimelineUsers,
  mapAccountantDocumentUserOption,
} from "./accountantDocumentUsers";

export const DOC_HISTORY_CATEGORY_OPTIONS = [
  { value: "all", label: "All categories" },
  { value: "w2", label: "W-2" },
  { value: "temp", label: "Temp" },
  { value: "contractor_1099", label: "1099" },
];

const VENDOR_RECEIPT_CATEGORIES = new Set(["temp", "contractor_1099"]);

export function isVendorReceiptCategory(category) {
  return VENDOR_RECEIPT_CATEGORIES.has(String(category || ""));
}

export function rowWorkerCategory(row) {
  return String(row?.worker_category || "");
}

/** Document a row produces: 'receipt' for temp/1099, otherwise 'paystub' (W-2). */
export function rowDocumentKind(row) {
  return isVendorReceiptCategory(rowWorkerCategory(row)) ? "receipt" : "paystub";
}

export function isRowFinalized(row) {
  if (!row || typeof row !== "object") return false;
  if (row.payout_details_finalized != null) return Boolean(row.payout_details_finalized);
  return Boolean(row.payout_details_finalized_at);
}

/**
 * What actions a row may offer, driven entirely by the backend document-state.
 *
 *   { kind, final, preview }
 *
 * - final=true  → the finalized document can be previewed / printed / downloaded.
 * - preview=true (with final=false) → only a pre-finalization preview is allowed
 *   (temp/1099 where the workflow permits it). Never a final download.
 *
 * A W-2 row never exposes a receipt; a temp/1099 row never exposes a paystub.
 */
export function rowDocumentActions(row) {
  const kind = rowDocumentKind(row);
  const doc = (row && row.document) || {};
  if (kind === "receipt") {
    if (doc.vendor_receipt_available === true) {
      return { kind, final: true, preview: true };
    }
    if (doc.vendor_receipt_preview_available === true) {
      return { kind, final: false, preview: true };
    }
    return { kind, final: false, preview: false };
  }
  // W-2 paystub — final only (matches existing history behavior; no pending preview).
  if (doc.paystub_available === true) {
    return { kind, final: true, preview: true };
  }
  return { kind, final: false, preview: false };
}

/** Tax withheld only applies to W-2 paystubs; receipts show a not-applicable dash. */
export function taxWithheldApplies(row) {
  return rowDocumentKind(row) !== "receipt";
}

function effectiveKind(category, rows) {
  if (category === "w2") return "paystub";
  if (isVendorReceiptCategory(category)) return "receipt";
  const kinds = new Set((rows || []).map(rowDocumentKind));
  if (kinds.size === 1) return kinds.has("receipt") ? "receipt" : "paystub";
  return "mixed";
}

/** Final-column header: Paystub (W-2), Receipt (temp/1099), or Document (mixed). */
export function documentColumnLabel(category, rows) {
  const k = effectiveKind(category, rows);
  if (k === "receipt") return "Receipt";
  if (k === "paystub") return "Paystub";
  return "Document";
}

/** Bulk action label: Download All Paystubs / Receipts / Documents. */
export function downloadAllLabel(category, rows) {
  const k = effectiveKind(category, rows);
  if (k === "receipt") return "Download All Receipts";
  if (k === "paystub") return "Download All Paystubs";
  return "Download All Documents";
}

/** Money column header: "Amount paid" when only contractor receipts are shown. */
export function netColumnLabel(rows) {
  const list = rows || [];
  if (list.length && list.every((r) => rowDocumentKind(r) === "receipt")) {
    return "Amount paid";
  }
  return "Net paid";
}

/**
 * Bulk-download plan across the visible rows. Only finalized documents are
 * included; pending/unfinalized rows are skipped (never a final download).
 * Each entry keeps the correct document kind so both paystubs and receipts are
 * included for mixed results — temp/1099 records are never silently omitted.
 */
export function bulkDownloadPlan(rows) {
  const plan = [];
  for (const row of rows || []) {
    const avail = rowDocumentActions(row);
    if (!avail.final) continue;
    plan.push({
      kind: avail.kind,
      batchId: row.batch_id,
      lineId: row.id,
      workerName: row.worker_name_snapshot || "",
      payPeriodStart: row.pay_period_start || "",
      payPeriodEnd: row.pay_period_end || "",
    });
  }
  return plan;
}

/** Filename suffix identifying the document type for bulk/individual downloads. */
export function documentDownloadSuffix(kind) {
  return kind === "receipt" ? "Receipt" : "Paystub";
}

/** Payroll workers eligible for the selected category ("all" unions every lane). */
export function workersForCategory(users, category) {
  const list = users || [];
  if (category === "all") {
    const seen = new Set();
    const out = [];
    for (const cat of ["w2", "temp", "contractor_1099"]) {
      for (const u of filterPayrollTimelineUsers(list, cat)) {
        const id = u.id ?? u.user_id;
        if (id == null || seen.has(id)) continue;
        seen.add(id);
        out.push(u);
      }
    }
    return out;
  }
  return filterPayrollTimelineUsers(list, category);
}

/** Worker options ({id,label}) for the employee/worker dropdown by category. */
export function workerOptionsForCategory(users, category) {
  return workersForCategory(users, category).map(mapAccountantDocumentUserOption);
}
