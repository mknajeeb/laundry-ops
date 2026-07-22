/** Grouping helpers for Payroll Reports (Monthly Payroll Paid, PDF, on-screen). */

/**
 * Group report rows the same way the PDF does for Monthly Payroll Paid:
 * by Official Pay Date, then by payroll period within each pay date.
 * @param {Array<object>} rows
 * @returns {Array<{ payDate: string, period: string, heading: string, rows: object[] }>}
 */
export function groupMonthlyPaidRows(rows) {
  const byPay = new Map();
  for (const row of rows || []) {
    const payDate =
      row?.pay_date || row?.official_pay_date || row?.pay_date_display || "Pay Date Missing";
    const period =
      row?.payroll_period ||
      [row?.pay_period_start, row?.pay_period_end].filter(Boolean).join(" – ") ||
      "Unknown period";
    if (!byPay.has(payDate)) byPay.set(payDate, new Map());
    const byPeriod = byPay.get(payDate);
    if (!byPeriod.has(period)) byPeriod.set(period, []);
    byPeriod.get(period).push(row);
  }
  const groups = [];
  for (const payDate of [...byPay.keys()].sort()) {
    const byPeriod = byPay.get(payDate);
    for (const period of [...byPeriod.keys()].sort()) {
      groups.push({
        payDate,
        period,
        heading: `Pay Date: ${payDate} · Payroll Period: ${period}`,
        rows: byPeriod.get(period),
      });
    }
  }
  return groups;
}

/** Distinct Official Pay Dates in the filtered rows (sorted). */
export function distinctPayDates(rows) {
  return [
    ...new Set(
      (rows || [])
        .map((r) => r?.pay_date || r?.official_pay_date || "")
        .filter(Boolean),
    ),
  ].sort();
}
