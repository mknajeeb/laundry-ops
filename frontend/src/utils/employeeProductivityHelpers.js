/** Phase 2 — client-side ranking for employee productivity (Phase 1 data unchanged). */

export const PRODUCTIVITY_RANK_OPTIONS = [
  { id: "bags", label: "Completed Bags" },
  { id: "lbs", label: "Completed Lbs" },
  { id: "avg_lbs_bag", label: "Avg Lbs / Bag" },
  { id: "bags_hr", label: "Bags / Hour" },
  { id: "lbs_hr", label: "Lbs / Hour" },
];

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
      return emp.bags_per_hour != null ? Number(emp.bags_per_hour) : null;
    case "lbs_hr":
      return emp.lbs_per_hour != null ? Number(emp.lbs_per_hour) : null;
    case "bags":
    default:
      return Number(emp.completed_bags) || 0;
  }
}

export function isMissingClockIn(emp) {
  return !emp?.clock_in_time && !emp?.clock_in_time_et;
}

export function fmtProductivityRate(value, missingClockIn) {
  if (missingClockIn) return "N/A";
  if (value == null || Number.isNaN(Number(value))) return "N/A";
  return Number(value).toFixed(2);
}

/** Sort employees for ranking display; null rates sort last. Client-side only — no API reload. */
export function rankEmployees(employees, rankBy = "bags") {
  const list = [...(employees || [])];
  list.sort((a, b) => {
    const av = rankValue(a, rankBy);
    const bv = rankValue(b, rankBy);
    if (av == null && bv == null) return String(a.employee || "").localeCompare(String(b.employee || ""));
    if (av == null) return 1;
    if (bv == null) return -1;
    if (bv !== av) return bv - av;
    return String(a.employee || "").localeCompare(String(b.employee || ""));
  });
  return list.map((emp, idx) => ({ ...emp, productivity_rank: idx + 1 }));
}
