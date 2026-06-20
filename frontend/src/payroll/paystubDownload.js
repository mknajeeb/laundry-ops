/** Download helpers for payroll paystub HTML documents. */

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
  return `${base}.html`;
}

export async function downloadHtmlContent(html, filename) {
  const blob = new Blob([html], { type: "text/html;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export async function downloadHtmlFromFetch(fetchFn, filename) {
  const res = await fetchFn();
  const html = typeof res?.data === "string" ? res.data : String(res?.data ?? "");
  await downloadHtmlContent(html, filename);
}
