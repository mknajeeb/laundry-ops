/** Phase 2 — client-side ranking for employee productivity (Phase 1 data unchanged). */

export const PRODUCTIVITY_RANK_OPTIONS = [
  { id: "processed", label: "Credited Bags" },
  { id: "bags", label: "Completed Bags" },
  { id: "processed_hr", label: "Bags / Hour" },
  { id: "bags_hr", label: "Completed / Hour" },
  { id: "lbs", label: "Credited Lbs" },
  { id: "avg_lbs_bag", label: "Avg Lbs / Bag" },
  { id: "lbs_hr", label: "Lbs / Hour" },
];

export const PERFORMANCE_TIER_STYLES = {
  top: {
    bgcolor: "rgba(34, 197, 94, 0.08)",
    borderColor: "rgba(34, 197, 94, 0.35)",
    rankColor: "#15803d",
  },
  middle: {
    bgcolor: "transparent",
    borderColor: "transparent",
    rankColor: "text.secondary",
  },
  bottom: {
    bgcolor: "rgba(245, 158, 11, 0.1)",
    borderColor: "rgba(245, 158, 11, 0.35)",
    rankColor: "#b45309",
  },
};

export function avgLbsPerCompletedBag(emp) {
  const bags = Number(emp?.credited_bags_count ?? emp?.processed_bags_count ?? emp?.completed_bags) || 0;
  if (bags <= 0) return null;
  return (Number(emp?.total_credited_lbs ?? emp?.total_processed_lbs ?? emp?.total_completed_lbs) || 0) / bags;
}

export function fmtAvgLbsPerBag(emp) {
  const avg = avgLbsPerCompletedBag(emp);
  if (avg == null) return "—";
  return avg.toFixed(2);
}

function rankValue(emp, rankBy) {
  switch (rankBy) {
    case "processed":
      return Number(emp.credited_bags_count ?? emp.processed_bags_count) || 0;
    case "processed_hr":
      return emp.processed_bags_per_hour != null
        ? Number(emp.processed_bags_per_hour)
        : (emp.bags_per_hour != null ? Number(emp.bags_per_hour) : null);
    case "lbs":
      return Number(emp.total_credited_lbs ?? emp.total_processed_lbs ?? emp.total_completed_lbs) || 0;
    case "avg_lbs_bag":
      return avgLbsPerCompletedBag(emp);
    case "bags_hr":
      return emp.completed_bags_per_hour != null
        ? Number(emp.completed_bags_per_hour)
        : (emp.bags_per_hour != null ? Number(emp.bags_per_hour) : null);
    case "lbs_hr":
      return emp.processed_lbs_per_hour != null
        ? Number(emp.processed_lbs_per_hour)
        : (emp.lbs_per_hour != null ? Number(emp.lbs_per_hour) : null);
    case "bags":
    default:
      return Number(emp.completed_bags) || 0;
  }
}

export function employeeShowsSplitView(emp) {
  if (emp?.show_processed_completed_split === false) return false;
  const credited = Number(emp?.credited_bags_count ?? emp?.processed_bags_count) || 0;
  const completed = Number(emp?.completed_bags) || 0;
  const pending = Number(emp?.pending_completion_count) || 0;
  return pending > 0 || (credited > 0 && completed !== credited);
}

export function sectionShowsSplitView(employees = []) {
  return employees.some((emp) => employeeShowsSplitView(emp));
}

export function isMissingClockIn(emp) {
  if (Number(emp?.productive_hours) > 0) return false;
  if (emp?.productive_start_time || emp?.productive_start_time_et) return false;
  return !emp?.clock_in_time && !emp?.clock_in_time_et;
}

export function productivityStartLabel(emp) {
  if (emp?.productivity_start_source === "roster_modified") {
    return "Shift Start";
  }
  if (
    emp?.productivity_start_source === "operator_processing" ||
    emp?.productivity_start_source === "inferred_fold_start"
  ) {
    return "Folding Start";
  }
  return "Clock In";
}

export function productivityEndLabel(emp) {
  if (emp?.productivity_end_source === "roster_modified") return "Shift End";
  if (emp?.productivity_end_source === "clock_out") return "Clock Out";
  return "Last Completion";
}

function renderTimeWithOriginal(current, original, formatTime) {
  if (!current) return "—";
  if (original && original !== current) {
    return {
      current: formatTime(current),
      original: formatTime(original),
    };
  }
  return { current: formatTime(current), original: null };
}

export function productivityStartDisplayParts(emp, formatTime) {
  if (isMissingClockIn(emp)) return { current: "Missing clock-in", original: null };
  if (emp?.roster_times_modified) {
    return renderTimeWithOriginal(
      emp.roster_start_time_et || emp.roster_start_time || emp.productive_start_time_et || emp.productive_start_time,
      emp.roster_original_start_time_et || emp.roster_original_start_time,
      formatTime,
    );
  }
  if (
    emp?.productivity_start_source === "operator_processing" ||
    emp?.productivity_start_source === "inferred_fold_start"
  ) {
    return renderTimeWithOriginal(
      emp.productive_start_time_et || emp.productive_start_time,
      null,
      formatTime,
    );
  }
  if (!emp?.clock_in_time && !emp?.clock_in_time_et) {
    return renderTimeWithOriginal(
      emp.productive_start_time_et || emp.productive_start_time,
      null,
      formatTime,
    );
  }
  return renderTimeWithOriginal(
    emp.clock_in_time_et || emp.clock_in_time,
    null,
    formatTime,
  );
}

export function productivityEndDisplayParts(emp, formatTime) {
  if (emp?.roster_times_modified) {
    return renderTimeWithOriginal(
      emp.roster_end_time_et || emp.roster_end_time || emp.productive_end_time_et || emp.productive_end_time,
      emp.roster_original_end_time_et || emp.roster_original_end_time,
      formatTime,
    );
  }
  if (emp?.productivity_end_source === "clock_out") {
    return renderTimeWithOriginal(
      emp.clock_out_time_et || emp.productive_end_time_et || emp.productive_end_time,
      null,
      formatTime,
    );
  }
  return renderTimeWithOriginal(
    emp.last_completion_time_et || emp.last_completion_time,
    null,
    formatTime,
  );
}

export function productivityStartDisplay(emp, formatTime) {
  const parts = productivityStartDisplayParts(emp, formatTime);
  return parts.current ?? "—";
}

export function productivityEndDisplay(emp, formatTime) {
  const parts = productivityEndDisplayParts(emp, formatTime);
  return parts.current ?? "—";
}

export function fmtProductivityRate(value, missingClockIn) {
  if (missingClockIn) return "N/A";
  if (value == null || Number.isNaN(Number(value))) return "N/A";
  return Number(value).toFixed(2);
}

export function fmtSummaryNumber(value, digits = 0) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  return Number(value).toFixed(digits);
}

/** Top / middle / bottom tier for conditional row highlighting. */
export function performanceTier(rank, total, { minBags = 1 } = {}) {
  if (!total || !rank) return "middle";
  if (total === 1) return "top";
  const topCut = Math.max(1, Math.ceil(total / 3));
  const bottomCut = Math.max(topCut + 1, total - Math.ceil(total / 3) + 1);
  if (rank <= topCut) return "top";
  if (rank >= bottomCut) return "bottom";
  return "middle";
}

/** Sort employees for ranking display; null rates sort last. Client-side only — no API reload. */
export function rankEmployees(employees, rankBy = "processed") {
  const list = [...(employees || [])];
  list.sort((a, b) => {
    const aActive = Number(a?.processed_bags_count) > 0 || Number(a?.completed_bags) > 0;
    const bActive = Number(b?.processed_bags_count) > 0 || Number(b?.completed_bags) > 0;
    if (aActive !== bActive) return aActive ? -1 : 1;
    const av = rankValue(a, rankBy);
    const bv = rankValue(b, rankBy);
    if (av == null && bv == null) return String(a.employee || "").localeCompare(String(b.employee || ""));
    if (av == null) return 1;
    if (bv == null) return -1;
    if (bv !== av) return bv - av;
    return String(a.employee || "").localeCompare(String(b.employee || ""));
  });
  const activeCount = list.filter(
    (e) => Number(e?.processed_bags_count) > 0 || Number(e?.completed_bags) > 0,
  ).length;
  let rank = 0;
  return list.map((emp) => {
    const active = Number(emp?.processed_bags_count) > 0 || Number(emp?.completed_bags) > 0;
    const productivityRank = active ? ++rank : null;
    return {
      ...emp,
      productivity_rank: productivityRank,
      performance_tier: active
        ? performanceTier(productivityRank, activeCount)
        : "middle",
    };
  });
}

export function buildExecutiveSummaryCards(summary = {}, scopeLabel = "") {
  const splitView = Number(summary.total_pending_completion) > 0
    || Number(summary.total_bags_credited) !== Number(summary.total_bags_completed);
  const cards = [
    {
      key: "employees_active",
      label: "Total Employees Active",
      value: fmtSummaryNumber(summary.total_employees_active, 0),
      variant: "default",
    },
    {
      key: "bags_credited",
      label: splitView ? "Credited Workload Bags" : "Credited Bags",
      value: fmtSummaryNumber(summary.total_bags_credited ?? summary.total_bags_processed, 0),
      variant: "wf",
    },
  ];
  if (splitView) {
    cards.push(
      {
        key: "bags_completed",
        label: "Credited Completed",
        value: fmtSummaryNumber(summary.total_bags_completed, 0),
        variant: "snapshot",
      },
      {
        key: "pending_completion",
        label: "Credited Pending",
        value: fmtSummaryNumber(summary.total_pending_completion, 0),
        variant: "hd",
      },
    );
  }
  if (Number(summary.total_unassigned_bags) > 0) {
    cards.push({
      key: "unassigned",
      label: "Unassigned Bags",
      value: fmtSummaryNumber(summary.total_unassigned_bags, 0),
      variant: "hd",
    });
  }
  cards.push(
    {
      key: "avg_bags_hr",
      label: "Avg Bags / Hour",
      value: fmtSummaryNumber(summary.average_bags_per_hour ?? summary.average_processed_bags_per_hour, 2),
      variant: "default",
    },
    {
      key: "avg_lbs_hr",
      label: "Avg Lbs / Hour",
      value: fmtSummaryNumber(summary.average_pounds_per_hour ?? summary.average_processed_pounds_per_hour, 2),
      variant: "default",
      sub: scopeLabel ? `Scope: ${scopeLabel}` : undefined,
    },
  );
  return cards;
}

export function fmtLaborValue(value, { currency = false, digits = 2 } = {}) {
  if (value == null || Number.isNaN(Number(value))) return "No Data";
  const num = Number(value);
  if (currency) return `$${num.toFixed(digits)}`;
  return num.toFixed(digits);
}

export function buildLaborKpiCards(laborSummary) {
  const kpis = laborSummary?.kpis || {};
  const available = Boolean(laborSummary?.available);
  const fmt = (val, opts = {}) => (available ? fmtLaborValue(val, opts) : "N/A");
  return [
    {
      key: "total_labor_hours",
      label: "Total Labor Hours",
      value: fmt(kpis.total_labor_hours),
      variant: "total",
    },
    {
      key: "folder_hours",
      label: "Folder Hours",
      value: fmt(kpis.folder_hours),
      variant: "wf",
    },
    {
      key: "operator_hours",
      label: "Operator Hours",
      value: fmt(kpis.operator_hours),
      variant: "hd",
    },
    {
      key: "total_labor_cost",
      label: "Total Labor Cost",
      value: fmt(kpis.total_labor_cost, { currency: true }),
      variant: "completed",
    },
  ];
}

export function buildLaborCostKpiCards(laborSummary) {
  const kpis = laborSummary?.kpis || {};
  const available = Boolean(laborSummary?.available);
  const fmt = (val) => (available ? fmtLaborValue(val, { currency: true, digits: 2 }) : "N/A");
  return [
    {
      key: "cost_per_bag",
      label: "Cost Per Bag",
      value: fmt(kpis.cost_per_bag),
      variant: "snapshot",
    },
    {
      key: "cost_per_pound",
      label: "Cost Per Pound",
      value: fmt(kpis.cost_per_pound),
      variant: "snapshot",
    },
  ];
}
