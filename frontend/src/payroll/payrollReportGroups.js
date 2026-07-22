/** Grouping helpers for Payroll Reports (Monthly Payroll Paid, PDF, on-screen). */

/**
 * Group report rows: Payroll Period → Official Pay Date → employee rows.
 * Matches backend payroll_report_analytics.group_rows_by_period_then_pay_date.
 * @param {Array<object>} rows
 * @returns {Array<{
 *   period: string,
 *   payDate?: string,
 *   heading: string,
 *   rows: object[],
 *   payDates?: Array<{ payDate: string, heading: string, rows: object[] }>
 * }>}
 */
export function groupMonthlyPaidRows(rows) {
  const byPeriod = new Map();
  for (const row of rows || []) {
    const period =
      row?.payroll_period ||
      [row?.pay_period_start, row?.pay_period_end].filter(Boolean).join(" – ") ||
      "Unknown period";
    const payDate =
      row?.pay_date || row?.official_pay_date || row?.pay_date_display || "Pay Date Missing";
    if (!byPeriod.has(period)) byPeriod.set(period, new Map());
    const byPay = byPeriod.get(period);
    if (!byPay.has(payDate)) byPay.set(payDate, []);
    byPay.get(payDate).push(row);
  }

  const groups = [];
  for (const period of [...byPeriod.keys()].sort()) {
    const byPay = byPeriod.get(period);
    const payDates = [];
    const flatRows = [];
    for (const payDate of [...byPay.keys()].sort()) {
      const sectionRows = [...byPay.get(payDate)].sort((a, b) =>
        String(a?.employee_name || "").localeCompare(String(b?.employee_name || "")),
      );
      payDates.push({
        payDate,
        heading: `Pay Date: ${payDate}`,
        rows: sectionRows,
      });
      flatRows.push(...sectionRows);
    }
    groups.push({
      period,
      payDate: payDates[0]?.payDate,
      heading: `Payroll Period: ${period}`,
      rows: flatRows,
      payDates,
    });
  }
  return groups;
}

/** Flatten nested period→pay-date groups into table sections (one per pay date). */
export function flattenMonthlyPaidSections(groups) {
  const sections = [];
  for (const g of groups || []) {
    for (const pd of g.payDates || []) {
      sections.push({
        period: g.period,
        payDate: pd.payDate,
        heading: `${g.heading}`,
        payDateHeading: pd.heading,
        rows: pd.rows,
      });
    }
  }
  return sections;
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

/** Distinct payroll periods in the filtered rows (sorted). */
export function distinctPayrollPeriods(rows) {
  return [
    ...new Set(
      (rows || [])
        .map(
          (r) =>
            r?.payroll_period ||
            [r?.pay_period_start, r?.pay_period_end].filter(Boolean).join(" – "),
        )
        .filter(Boolean),
    ),
  ].sort();
}
