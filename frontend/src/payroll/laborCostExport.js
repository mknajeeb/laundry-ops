/** Display and CSV helpers for Labor Cost Analysis. Totals are calculated on the server. */

function finiteNumber(value) {
  if (value == null || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

export function formatMoney(value) {
  const n = finiteNumber(value);
  if (n == null) return "—";
  return n.toLocaleString("en-US", { style: "currency", currency: "USD" });
}

export function formatRate(value) {
  const n = finiteNumber(value);
  if (n == null) return "—";
  return `$${n.toFixed(2)}/hr`;
}

export function formatHours(value) {
  const n = finiteNumber(value);
  if (n == null) return "—";
  return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function formatPercent(value) {
  const n = finiteNumber(value);
  if (n == null) return "—";
  return `${n.toFixed(2)}%`;
}

export function formatImpact(value) {
  const n = finiteNumber(value);
  if (n == null) return "—";
  if (n > 0.004) return `+$${n.toFixed(2)}`;
  if (n < -0.004) return `-$${Math.abs(n).toFixed(2)}`;
  return "$0.00";
}

export function formatSignedMoney(value) {
  const n = finiteNumber(value);
  if (n == null) return "—";
  const body = formatMoney(Math.abs(n));
  if (n > 0.004) return `+${body}`;
  if (n < -0.004) return `-${body}`;
  return body;
}

export function formatComparisonChange(row) {
  if (!row) return "N/A";
  if (row.change_kind === "percentage_points") {
    if (row.difference == null) return "N/A";
    const n = Number(row.difference);
    const sign = n > 0 ? "+" : "";
    return `${sign}${n.toFixed(2)} percentage points`;
  }
  if (row.percent_change == null) return "N/A";
  const n = Number(row.percent_change);
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(2)}%`;
}

export function formatDifference(row) {
  if (!row || row.difference == null) return "—";
  if (row.unit === "percentage_points") return formatComparisonChange(row);
  if (row.unit === "hours") {
    const n = Number(row.difference);
    const sign = n > 0 ? "+" : "";
    return `${sign}${formatHours(n)}`;
  }
  if (row.unit === "money") return formatSignedMoney(row.difference);
  return formatImpact(row.difference);
}

export const LABOR_COLUMNS = [
  { key: "employee_name", label: "Employee", optional: false, numeric: false },
  { key: "classification_label", label: "Classification", optional: false, numeric: false },
  { key: "regular_hours", label: "Regular Hours", optional: true, numeric: true, format: "hours" },
  { key: "ot_hours", label: "OT Hours", optional: true, numeric: true, format: "hours" },
  { key: "payable_hours", label: "Total Hours", optional: false, numeric: true, format: "hours" },
  { key: "ot_percent", label: "OT %", optional: false, numeric: true, format: "percent" },
  { key: "base_wage", label: "Base Wage", optional: true, numeric: true, format: "rate" },
  { key: "employee_rate_without_ot", label: "Employee Rate — No OT", optional: true, numeric: true, format: "rate" },
  { key: "employee_effective_rate", label: "Employee Rate — With OT", optional: false, numeric: true, format: "rate" },
  { key: "employee_ot_impact_per_hour", label: "Employee OT Impact/hr", optional: true, numeric: true, format: "impact" },
  { key: "employer_rate_without_ot", label: "Employer Rate — No OT", optional: true, numeric: true, format: "rate" },
  { key: "employer_effective_rate", label: "Employer Rate — With OT", optional: false, numeric: true, format: "rate" },
  { key: "employer_ot_impact_per_hour", label: "Employer OT Impact/hr", optional: false, numeric: true, format: "impact" },
  { key: "ot_premium", label: "OT Premium ($)", optional: false, numeric: true, format: "money" },
  { key: "ot_wages", label: "Total OT Wages ($)", optional: true, numeric: true, format: "money" },
  { key: "employer_ot_premium", label: "Employer OT Premium ($)", optional: true, numeric: true, format: "money" },
  { key: "employer_burden_percent", label: "Employer Burden %", optional: true, numeric: true, format: "percent" },
  { key: "total_employer_cost", label: "Total Employer Cost", optional: false, numeric: true, format: "money" },
  { key: "target_delta_per_hour", label: "vs Target", optional: false, numeric: true, format: "impact" },
];

export const CHART_METRICS = [
  { key: "employer_effective_rate", label: "Average Employer Effective Rate", kind: "rate", target: true },
  { key: "employee_effective_rate", label: "Average Employee Effective Rate", kind: "rate" },
  { key: "employer_rate_without_ot", label: "Employer Rate Without OT Premium", kind: "rate" },
  { key: "ot_hours", label: "OT Hours", kind: "hours" },
  { key: "ot_percent", label: "OT %", kind: "percent" },
  { key: "ot_premium", label: "OT Premium ($)", kind: "money" },
  { key: "employer_ot_premium", label: "Employer OT Premium ($)", kind: "money" },
  { key: "employer_ot_impact_per_hour", label: "Employer OT Impact/hr", kind: "rate" },
  { key: "total_employer_cost", label: "Total Employer Payroll Cost", kind: "money" },
];

function csvCell(value) {
  const text = value == null ? "" : String(value);
  if (/[",\n]/.test(text)) return `"${text.replace(/"/g, '""')}"`;
  return text;
}

export function laborCostCsv(employees) {
  const header = LABOR_COLUMNS.map((col) => csvCell(col.label)).join(",");
  const lines = (employees || []).map((emp) =>
    LABOR_COLUMNS.map((col) => csvCell(emp?.[col.key] ?? "")).join(","),
  );
  return [header, ...lines].join("\n");
}

export function formatColumnValue(column, row) {
  const value = row?.[column.key];
  if (column.format === "hours") return formatHours(value);
  if (column.format === "percent") return formatPercent(value);
  if (column.format === "rate") return formatRate(value);
  if (column.format === "impact") return formatImpact(value);
  if (column.format === "money") return formatMoney(value);
  return value || "—";
}
