/** Download helpers for payroll paystub PDF documents. */

import { downloadHtmlDocumentPdf } from "../contractorForms/contractorPrint";

export function paystubDownloadFilename(
  workerName,
  payPeriodStart,
  payPeriodEnd,
  { suffix = "Paystub" } = {},
) {
  const name = String(workerName || "Employee")
    .replace(/[<>:"/\\|?*\x00-\x1f]/g, "")
    .trim()
    .replace(/\s+/g, " ");
  const start = String(payPeriodStart || "").slice(0, 10);
  const end = String(payPeriodEnd || "").slice(0, 10);
  const period =
    start && end ? `${start} to ${end}` : start || end || "pay-period";
  const label = String(suffix || "").trim();
  const base = label ? `${name} ${period} ${label}` : `${name} ${period}`;
  return `${base}.pdf`;
}

export function paystubBatchDownloadFilename(
  batchName,
  payPeriodStart,
  payPeriodEnd,
  { suffix = "All Paystubs" } = {},
) {
  const batch = String(batchName || "Payroll")
    .replace(/[<>:"/\\|?*\x00-\x1f]/g, "")
    .trim()
    .replace(/\s+/g, " ");
  const start = String(payPeriodStart || "").slice(0, 10);
  const end = String(payPeriodEnd || "").slice(0, 10);
  const period =
    start && end ? `${start} to ${end}` : start || end || "pay-period";
  const label = String(suffix || "").trim();
  return `${batch} ${period} ${label}.pdf`;
}

export function paystubArchiveDownloadFilename({
  workerName,
  payPeriodStart,
  payPeriodEnd,
  workerCategoryLabel,
} = {}) {
  const start = String(payPeriodStart || "").slice(0, 10);
  const end = String(payPeriodEnd || "").slice(0, 10);
  const period =
    start && end ? `${start} to ${end}` : start || end || "all-periods";
  if (workerName) {
    const name = String(workerName)
      .replace(/[<>:"/\\|?*\x00-\x1f]/g, "")
      .trim()
      .replace(/\s+/g, " ");
    return `${name} Paystubs ${period}.pdf`;
  }
  const cat = String(workerCategoryLabel || "Employee")
    .replace(/[<>:"/\\|?*\x00-\x1f]/g, "")
    .trim();
  return `${cat} Paystub Archive ${period}.pdf`;
}

export async function downloadPdfFromFetch(fetchFn, filename, options = {}) {
  const res = await fetchFn();
  const html = typeof res?.data === "string" ? res.data : String(res?.data ?? "");
  const ok = await downloadHtmlDocumentPdf(html, {
    pageSize: options.pageSize || "letter portrait",
    filename,
  });
  if (!ok) {
    throw new Error("Paystub PDF generation failed");
  }
}
