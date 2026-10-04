import {
  formatHours,
  formatRoleHoursValue,
  formatUnallocatedBreak,
  groupRoleCodes,
  UNALLOCATED_BREAK_NOTE,
} from "./weeklyScheduleRoles";

export function peopleText(count) {
  const n = Number(count || 0);
  return `${n} ${n === 1 ? "person" : "people"}`;
}

/** "8 people · 42.5 hours" — distinct employees and net hours for one role ("… 43 gross hours" while unresolved). */
export function roleSummaryValue(row, daysOnly = false) {
  if (daysOnly) return peopleText(row.employees);
  const hours = Math.round(Number(row.hours || 0) * 100) / 100;
  return `${peopleText(row.employees)} · ${formatRoleHoursValue(hours, row.unallocatedBreakHours)} ${hours === 1 ? "hour" : "hours"}`;
}

/**
 * First summary line: employees, gross, break, and net hours. While a break without a time on a
 * multi-role shift cannot be allocated to the selected roles, the total is labeled gross of it.
 */
export function summaryTotalsMetrics(summary, { showBreaks = true, compact = false } = {}) {
  if (!summary) return [];
  const daysOnly = summary.daysOnly === true;
  const filtered = Array.isArray(summary.roleFilter);
  const pending = !daysOnly && Number(summary.unallocatedBreakHours || 0) > 0.0001;
  const metrics = [
    {
      key: "people",
      label: filtered ? "Selected roles" : compact ? "Employees" : "Employees Scheduled",
      value: filtered ? peopleText(summary.employeesScheduled) : String(summary.employeesScheduled ?? 0),
    },
  ];
  if (daysOnly) {
    metrics.push({ key: "days", label: compact ? "Days" : "Total Days", value: String(summary.totalDays ?? 0) });
    return metrics;
  }
  if (showBreaks) {
    metrics.push(
      { key: "gross", label: compact ? "Gross hrs" : "Gross Hours", value: formatHours(summary.grossHours) },
      {
        key: "break",
        label: compact ? "Break hrs" : "Break Hours",
        value:
          Number(summary.unscheduledBreakHours || 0) > 0
            ? `${formatHours(summary.breakHours)} (${formatHours(summary.unscheduledBreakHours)} not scheduled)`
            : formatHours(summary.breakHours),
      },
    );
  }
  metrics.push({
    key: "net",
    label: pending
      ? "Hours (gross of unallocated break)"
      : showBreaks
        ? compact
          ? "Net hrs"
          : "Net Hours"
        : compact
          ? "Hours"
          : "Total Hours",
    value: formatHours(summary.totalHours),
  });
  return metrics;
}

/** One line per role category (Rinse WF, Rinse HD, Drop Off, …) with every role in it. */
export function summaryRoleLines(summary) {
  if (!summary) return [];
  const daysOnly = summary.daysOnly === true;
  const byRole = new Map((summary.roles || []).map((row) => [row.role, row]));
  return groupRoleCodes([...byRole.keys()]).map((group) => ({
    code: group.code,
    label: group.label,
    items: group.roles.map((role) => {
      const row = byRole.get(role);
      return { role, label: row.label, value: roleSummaryValue(row, daysOnly) };
    }),
  }));
}

/** Unallocated break line for role filters ("" when there is none). */
export function summaryUnallocatedText(summary, { showBreaks = true } = {}) {
  if (!summary || summary.daysOnly) return "";
  const hours = Number(summary.roleUnallocatedBreakHours || 0);
  if (hours <= 0.0001) return "";
  return showBreaks ? `${formatUnallocatedBreak(hours)} · ${UNALLOCATED_BREAK_NOTE}` : UNALLOCATED_BREAK_NOTE;
}

/** "No roles selected" / "No roles selected in this view" when nothing shown is selected. */
export function noRolesSelectedText(selection) {
  return Array.isArray(selection) && selection.length ? "No roles selected in this view" : "No roles selected";
}

/** Plain-text summary lines for print and CSV: totals, then one line per role category. */
export function summaryTextLines(summary, { showBreaks = true, showCost = false, estimatedCostText = "" } = {}) {
  if (!summary) return [];
  const totals = summaryTotalsMetrics(summary, { showBreaks, compact: true }).map((m) => `${m.label}: ${m.value}`);
  if (showCost && estimatedCostText) totals.push(`Estimated labor cost: ${estimatedCostText}`);
  const lines = [totals.join(" | ")];
  for (const line of summaryRoleLines(summary)) {
    lines.push(`${line.label}: ${line.items.map((item) => `${item.label} ${item.value}`).join(" | ")}`);
  }
  const unallocated = summaryUnallocatedText(summary, { showBreaks });
  if (unallocated) lines.push(`Unallocated break: ${unallocated}`);
  return lines;
}
