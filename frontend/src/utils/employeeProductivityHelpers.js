/** Phase 2 — client-side ranking for employee productivity (Phase 1 data unchanged). */

export const PRODUCTIVITY_RANK_OPTIONS = [
  { id: "bags", label: "Completed Bags" },
  { id: "bags_hr", label: "Bags / Hour" },
  { id: "lbs", label: "Completed Lbs" },
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
  const bags = Number(emp?.completed_bags) || 0;
  if (bags <= 0) return null;
  return (Number(emp?.total_completed_lbs) || 0) / bags;
}

export function fmtAvgLbsPerBag(emp) {
  const avg = avgLbsPerCompletedBag(emp);
  if (avg == null) return "—";
  return avg.toFixed(2);
}

function rankValue(emp, rankBy) {
  switch (rankBy) {
    case "lbs":
      return Number(emp.total_completed_lbs) || 0;
    case "avg_lbs_bag":
      return avgLbsPerCompletedBag(emp);
    case "bags_hr":
      return emp.completed_bags_per_hour != null
        ? Number(emp.completed_bags_per_hour)
        : (emp.bags_per_hour != null ? Number(emp.bags_per_hour) : null);
    case "lbs_hr":
      return emp.completed_lbs_per_hour != null
        ? Number(emp.completed_lbs_per_hour)
        : (emp.lbs_per_hour != null ? Number(emp.lbs_per_hour) : null);
    case "bags":
    default:
      return Number(emp.completed_bags) || 0;
  }
}

export function employeeShowsSplitView() {
  return false;
}

export function sectionShowsSplitView() {
  return false;
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

/** Resolve lbs from a credited bag record (matches drilldown fallback chain). */
export function resolveBagWeightLbs(bag) {
  if (!bag || typeof bag !== "object") return null;
  if (bag.weight_lbs != null) return Number(bag.weight_lbs);
  if (bag.completed_lbs != null) return Number(bag.completed_lbs);
  if (bag.processed_lbs != null) return Number(bag.processed_lbs);
  if (bag.credited_lbs != null) return Number(bag.credited_lbs);
  if (bag.post_clean_weight != null) return Number(bag.post_clean_weight);
  if (bag.weight != null) return Number(bag.weight);
  if (bag.weight_num != null) return Number(bag.weight_num);
  if (bag.weight_lbs != null) return Number(bag.weight_lbs);
  return null;
}

/** Employee total lbs — prefer API total, else sum bag-level fallbacks. */
export function employeeDisplayLbs(emp) {
  const apiTotal = emp?.total_completed_lbs;
  if (apiTotal != null && Number(apiTotal) > 0) return Number(apiTotal);
  const bags = emp?.bags;
  if (!Array.isArray(bags) || !bags.length) return Number(apiTotal) || 0;
  let sum = 0;
  let hasWeight = false;
  for (const bag of bags) {
    const lbs = resolveBagWeightLbs(bag);
    if (lbs != null && !Number.isNaN(lbs)) {
      sum += lbs;
      hasWeight = true;
    }
  }
  return hasWeight ? Math.round(sum * 100) / 100 : Number(apiTotal) || 0;
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
export function rankEmployees(employees, rankBy = "bags") {
  const list = [...(employees || [])];
  list.sort((a, b) => {
    const aActive = Number(a?.completed_bags) > 0;
    const bActive = Number(b?.completed_bags) > 0;
    if (aActive !== bActive) return aActive ? -1 : 1;
    const av = rankValue(a, rankBy);
    const bv = rankValue(b, rankBy);
    if (av == null && bv == null) return String(a.employee || "").localeCompare(String(b.employee || ""));
    if (av == null) return 1;
    if (bv == null) return -1;
    if (bv !== av) return bv - av;
    return String(a.employee || "").localeCompare(String(b.employee || ""));
  });
  const activeCount = list.filter((e) => Number(e?.completed_bags) > 0).length;
  let rank = 0;
  return list.map((emp) => {
    const active = Number(emp?.completed_bags) > 0;
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
  const cards = [
    {
      key: "employees_active",
      label: "Total Employees Active",
      value: fmtSummaryNumber(summary.total_employees_active, 0),
      variant: "default",
    },
    {
      key: "bags_completed",
      label: "Completed Bags",
      value: fmtSummaryNumber(summary.total_bags_completed ?? summary.total_bags_credited, 0),
      variant: "wf",
    },
  ];
  if (Number(summary.total_unassigned_bags) > 0) {
    cards.push({
      key: "unassigned",
      label: "Unassigned Completed",
      value: fmtSummaryNumber(summary.total_unassigned_bags, 0),
      variant: "hd",
    });
  }
  cards.push(
    {
      key: "completed_lbs",
      label: "Completed Lbs",
      value: fmtSummaryNumber(summary.total_pounds_completed ?? summary.total_credited_lbs, 1),
      variant: "snapshot",
    },
    {
      key: "avg_bags_hr",
      label: "Avg Bags / Hour",
      value: fmtSummaryNumber(summary.average_completed_bags_per_hour ?? summary.average_bags_per_hour, 2),
      variant: "default",
    },
    {
      key: "avg_lbs_hr",
      label: "Avg Lbs / Hour",
      value: fmtSummaryNumber(summary.average_completed_pounds_per_hour ?? summary.average_pounds_per_hour, 2),
      variant: "default",
      sub: summary.missing_weight_warning
        || (scopeLabel ? `Scope: ${scopeLabel}` : undefined),
      warning: Boolean(summary.missing_weight_warning),
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
