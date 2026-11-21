/**
 * Scan Chronology is the recorded scan/event list.
 * A saved session is optional context and does not decide whether a scan
 * exists, who it belongs to, or whether it is valid.
 */

export const SCAN_STAGES = [
  { id: "weighing", labelKey: "pinMgmt.stage.weighing" },
  { id: "sorting", labelKey: "pinMgmt.stage.sorting" },
  { id: "washing", labelKey: "pinMgmt.stage.washing" },
  { id: "drying", labelKey: "pinMgmt.stage.drying" },
  { id: "folder", labelKey: "pinMgmt.stage.folding" },
  { id: "user_activity", labelKey: "pinMgmt.stage.activity" },
];

export const ACTIVITY_TYPES = [
  { id: "all", labelKey: "pinMgmt.allActivities" },
  { id: "weighing", labelKey: "pinMgmt.stage.weighing" },
  { id: "sorting", labelKey: "pinMgmt.stage.sorting" },
  { id: "washing", labelKey: "pinMgmt.stage.washing" },
  { id: "drying", labelKey: "pinMgmt.stage.drying" },
  { id: "folder", labelKey: "pinMgmt.stage.folding" },
  { id: "post_processing_weight", labelKey: "pinMgmt.stage.weight" },
];

export function formatDurationSeconds(seconds) {
  const s = Number(seconds);
  if (!Number.isFinite(s)) return "—";
  if (s <= 0) return "0m";
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

export function serviceTypesParam(wf, hd) {
  if (wf && hd) return "";
  if (wf) return "WF";
  if (hd) return "HD";
  return "none";
}

export function scanTime(row, stage) {
  if (!row) return null;
  if (stage === "washing") return row.wash_time_et || row.timestamp_et || null;
  if (stage === "drying") return row.dry_time_et || row.timestamp_et || null;
  if (stage === "sorting") return row.sort_time_et || row.time_et || row.start_et || null;
  return row.time_et || row.start_et || row.sort_time_et || null;
}

export function scanMachine(row, stage) {
  if (!row) return "";
  if (stage === "washing") return row.washer_rack || "";
  if (stage === "drying") return row.dryer_rack || "";
  return row.machine_or_rack || row.start_rack || "";
}

export function scanRows(data) {
  return Array.isArray(data?.sessions) ? data.sessions : [];
}

export function scanEmployee(row) {
  const name = String(row?.employee || "").trim();
  if (!name || name.toLowerCase() === "unknown") return "";
  return name;
}

/** Optional session context. Null when no session was recorded. */
export function recordedSessionContext(data) {
  const local = data?.local_sessions?.summary;
  const count = Number(local?.total_sessions || 0);
  if (!count) return null;
  return { sessions: count, hours: local?.total_hours ?? 0 };
}

export function chronologyMetrics(stage, data) {
  const summary = data?.summary || {};
  const rows = scanRows(data);
  const metrics = [];
  if (stage === "user_activity") {
    return [
      { labelKey: "pinMgmt.activeEmployees", value: summary.active_employees ?? 0 },
      { labelKey: "pinMgmt.activities", value: summary.total_activities ?? 0 },
      { labelKey: "pinMgmt.stage.weighing", value: summary.weighing_count ?? 0 },
      { labelKey: "pinMgmt.stage.sorting", value: summary.sorting_sessions ?? 0 },
      { labelKey: "pinMgmt.stage.washing", value: summary.washer_loads ?? 0 },
      { labelKey: "pinMgmt.stage.drying", value: summary.dryer_loads ?? 0 },
      { labelKey: "pinMgmt.stage.folding", value: summary.folder_sessions ?? 0 },
    ];
  }
  const named = rows.filter((row) => scanEmployee(row)).length;
  metrics.push(
    { labelKey: "pinMgmt.scans", value: rows.length },
    { labelKey: "pinMgmt.withEmployee", value: named },
  );
  if (stage === "washing") {
    metrics.push(
      { labelKey: "pinMgmt.washerLoads", value: summary.total_sessions ?? 0 },
      {
        labelKey: "pinMgmt.uniqueBags",
        value: summary.unique_bags_washed ?? summary.unique_bag_ids ?? "—",
      },
      { labelKey: "pinMgmt.washersUsed", value: summary.unique_machines_used ?? "—" },
    );
  } else if (stage === "drying") {
    metrics.push(
      { labelKey: "pinMgmt.dryingScans", value: summary.total_sessions ?? 0 },
      { labelKey: "pinMgmt.dryersUsed", value: summary.unique_machines_used ?? "—" },
      { labelKey: "pinMgmt.mostUsedDryer", value: summary.most_used_machine || "—" },
    );
  } else if (stage === "folder") {
    metrics.push(
      { labelKey: "pinMgmt.foldingSessions", value: summary.total_sessions ?? 0 },
      { labelKey: "pinMgmt.complete", value: summary.complete_sessions ?? 0 },
      { labelKey: "pinMgmt.incomplete", value: summary.incomplete_sessions ?? 0 },
      { labelKey: "pinMgmt.foldingTime", value: formatDurationSeconds(summary.total_stage_seconds) },
    );
  } else if (summary.total_stage_seconds != null) {
    metrics.push({
      labelKey: "pinMgmt.stageTime",
      value: formatDurationSeconds(summary.total_stage_seconds),
    });
  }
  return metrics;
}

export function userActivityRows(data) {
  const groups = Array.isArray(data?.employee_groups) ? data.employee_groups : [];
  const rows = [];
  for (const group of groups) {
    for (const activity of group?.activities || []) {
      rows.push({
        ...activity,
        employee: activity?.employee || group?.employee || "",
      });
    }
  }
  rows.sort((a, b) => String(b.time_et || "").localeCompare(String(a.time_et || "")));
  return rows;
}

export function scanDetailLines(row, stage) {
  if (!row) return [];
  const lines = [];
  const push = (labelKey, value) => {
    if (value == null || value === "") return;
    lines.push({ labelKey, value });
  };
  push("pinMgmt.employee", row.employee);
  push("pinMgmt.bag", row.bag_id);
  push("pinMgmt.machine", scanMachine(row, stage));
  push("pinMgmt.weight", row.weight_lbs != null && row.weight_lbs !== "" ? `${row.weight_lbs} lbs` : "");
  push("pinMgmt.start", row.start_et);
  push("pinMgmt.end", row.end_et);
  if (row.duration_seconds != null) push("pinMgmt.duration", formatDurationSeconds(row.duration_seconds));
  if (row.gap_until_next_seconds != null) {
    push("pinMgmt.gap", formatDurationSeconds(row.gap_until_next_seconds));
  }
  push("pinMgmt.status", folderStatusLabel(row.status));
  push("pinMgmt.source", row.source);
  return lines;
}

export function folderStatusLabel(status) {
  if (status === "complete") return "pinMgmt.complete";
  if (status === "incomplete_open") return "pinMgmt.openSession";
  if (status === "incomplete_missing_start") return "pinMgmt.missingStart";
  return status || "";
}

const SCAN_VIEW_KEY = "pinScanView.v1";

export function loadScanView() {
  try {
    const raw = sessionStorage.getItem(SCAN_VIEW_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : null;
  } catch {
    return null;
  }
}

export function saveScanView(view) {
  try {
    sessionStorage.setItem(SCAN_VIEW_KEY, JSON.stringify(view));
  } catch {
    /* ignore */
  }
}
