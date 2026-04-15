/**
 * Portal / CSV exports sometimes append a lone " 0" after the customer name.
 * Strip for on-screen display only (does not change stored data).
 */
export function displayCustomerName(raw) {
  return String(raw || "")
    .trim()
    .replace(/\s+0$/u, "")
    .trim();
}
