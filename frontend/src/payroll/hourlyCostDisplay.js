/** Display helpers for employer hourly-cost reporting. Calculation stays on the server. */

function finiteNumber(value) {
  if (value == null || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

export function formatHourlyCost(value) {
  const n = finiteNumber(value);
  if (n == null) return "—";
  return `$${n.toFixed(2)}`;
}

export function formatHourlyRate(value) {
  const n = finiteNumber(value);
  if (n == null) return "—";
  return `$${n.toFixed(2)}/hr`;
}

export function formatOtImpact(value) {
  const n = finiteNumber(value);
  if (n == null) return "—";
  if (n > 0.004) return `+$${n.toFixed(2)}`;
  if (n < -0.004) return `-$${Math.abs(n).toFixed(2)}`;
  return "$0.00";
}

export function formatBurdenPercent(value) {
  const n = finiteNumber(value);
  if (n == null) return "—";
  return `${n.toFixed(2)}%`;
}

export function formatOtImpactPercent(value) {
  const n = finiteNumber(value);
  if (n == null) return "—";
  const sign = n > 0.004 ? "+" : "";
  return `${sign}${n.toFixed(1)}%`;
}

export function targetComparisonText(analysis) {
  if (!analysis || analysis.target_status === "unavailable" || analysis.target_delta_per_hour == null) {
    return "";
  }
  const target = formatHourlyRate(analysis.labor_cost_target ?? 19);
  const delta = Number(analysis.target_delta_per_hour);
  if (analysis.target_status === "above") {
    return `Above target +$${Math.abs(delta).toFixed(2)}/hr vs ${target}`;
  }
  if (Math.abs(delta) <= 0.005) {
    return `At target ${target}`;
  }
  return `Below target -$${Math.abs(delta).toFixed(2)}/hr vs ${target}`;
}

export function hourlyTargetColor(analysis) {
  if (!analysis || analysis.effective_cost_per_hour == null) return "text.primary";
  if (analysis.target_status === "above") return "error.main";
  if (analysis.target_status === "at_or_below") return "success.main";
  return "text.primary";
}

export function burdenCaption(analysis) {
  if (!analysis) return "";
  return analysis.burden_label || "";
}

/** Sentence under the burden figure. Configured percents are not called historical. */
export function burdenEstimateNote(analysis) {
  if (!analysis) return "";
  const status = analysis.burden_status;
  const method = analysis.method;
  if (status === "configured" || method === "configured_burden") {
    return "Configured employer burden for this classification. Not a finalized expense.";
  }
  if (status === "mixed") {
    return "Employer burden mixes configured rates and historical estimates. Not a finalized expense.";
  }
  if (status === "estimated" || method === "historical_burden") {
    return "Estimated from prior finalized payroll. Not a finalized expense.";
  }
  return "";
}

export function hourlyCostTooltipLines(analysis) {
  if (!analysis) return [];
  const lines = [
    `Gross earnings: ${formatHourlyCost(analysis.gross_pay)}`,
    `Total employer cost: ${formatHourlyCost(analysis.total_employer_cost)}`,
    `Additional employer expenses: ${formatHourlyCost(analysis.employer_expenses)}`,
    `Burden: ${formatBurdenPercent(analysis.burden_percent)} ${burdenCaption(analysis)}`.trim(),
  ];
  const sources = Array.isArray(analysis.burden_sources) ? analysis.burden_sources : [];
  if (sources.length) {
    const labels = sources.map((src) => {
      const start = src.pay_period_start || "";
      const end = src.pay_period_end || "";
      return `${start}–${end} (${formatBurdenPercent(src.burden_percent)})`;
    });
    lines.push(`Source payrolls: ${labels.join("; ")}`);
  }
  if (Array.isArray(analysis.included_expenses) && analysis.included_expenses.length) {
    lines.push(`Employer expenses: ${analysis.included_expenses.join(", ")}`);
  }
  lines.push(`Payable hours: ${Number(analysis.payable_hours || 0).toFixed(2)}`);
  lines.push(`Overtime premium: ${formatHourlyCost(analysis.ot_premium)}`);
  if (analysis.formula) lines.push(analysis.formula);
  const target = targetComparisonText(analysis);
  if (target) lines.push(target);
  const note = burdenEstimateNote(analysis);
  if (note) lines.push(note);
  return lines;
}
