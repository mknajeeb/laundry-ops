/**
 * Client-side CSV export for Scan Chronology tabs.
 * Exports the currently loaded/filtered table rows for the active stage.
 */

function csvCell(value) {
  const text = value == null ? "" : String(value);
  if (/[",\n\r]/.test(text)) {
    return `"${text.replace(/"/g, '""')}"`;
  }
  return text;
}

function downloadCsv(filename, headers, rows) {
  const lines = [headers.map(csvCell).join(",")];
  for (const row of rows) {
    lines.push(row.map(csvCell).join(","));
  }
  const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function formatExportDateTime(iso) {
  if (!iso) return "";
  return String(iso);
}

function formatExportDuration(seconds) {
  if (seconds == null || seconds === "") return "";
  const s = Number(seconds);
  if (!Number.isFinite(s)) return "";
  return String(s);
}

function slugStage(stage) {
  return String(stage || "scan").replace(/[^a-z0-9_-]+/gi, "_").toLowerCase();
}

function buildDurationRows(sessions) {
  const headers = [
    "#",
    "Bag ID",
    "Employee",
    "Start (ET)",
    "End (ET)",
    "Duration (seconds)",
    "Next start (ET)",
    "Gap (seconds)",
    "Confidence",
    "Source",
  ];
  const rows = sessions.map((row) => [
    row.index ?? "",
    row.bag_id ?? "",
    row.employee ?? "",
    formatExportDateTime(row.start_et),
    formatExportDateTime(row.end_et),
    formatExportDuration(row.duration_seconds),
    formatExportDateTime(row.next_start_et),
    formatExportDuration(row.gap_until_next_seconds),
    row.confidence ?? "",
    row.source ?? "",
  ]);
  return { headers, rows };
}

function buildEventRows(sessions, { rackKey }) {
  const headers = ["#", "Bag ID", "Employee", "Time (ET)", "Machine/Rack", "Event", "Confidence"];
  const rows = sessions.map((row) => [
    row.index ?? "",
    row.bag_id ?? "",
    row.employee ?? "",
    formatExportDateTime(row.timestamp_et),
    row[rackKey] ?? "",
    row.event_purpose ?? "",
    row.confidence ?? "",
  ]);
  return { headers, rows };
}

function buildUtilRows(sessions) {
  const headers = ["#", "Time (ET)", "Machine", "Employee", "Bag ID"];
  const rows = sessions.map((row) => [
    row.index ?? "",
    formatExportDateTime(row.timestamp_et),
    row.machine ?? "",
    row.employee ?? "",
    row.bag_id ?? "",
  ]);
  return { headers, rows };
}

function buildCoverageRows(coverageRows) {
  const headers = [
    "Bag ID",
    "Order ID",
    "Customer",
    "Service",
    "Processed/Completed (ET)",
    "Weighing",
    "Sorting",
    "Washing",
    "Drying",
    "Exception Notes",
  ];
  const rows = coverageRows.map((row) => [
    row.bag_id ?? "",
    row.order_id ?? "",
    row.customer ?? "",
    row.service_type ?? "",
    formatExportDateTime(row.processed_completed_et),
    row.weighing_status ?? "",
    row.sorting_status ?? "",
    row.washing_status ?? "",
    row.drying_status ?? "",
    (row.exception_notes || []).join("; "),
  ]);
  return { headers, rows };
}

function buildUserActivityRows(employeeGroups) {
  const headers = [
    "Employee",
    "Time (ET)",
    "Activity",
    "Activity Type",
    "Bag ID",
    "Machine/Rack",
    "Duration (seconds)",
    "Source",
    "Confidence",
  ];
  const rows = [];
  for (const group of employeeGroups) {
    const employee = group.employee || "";
    for (const row of group.activities || []) {
      rows.push([
        employee,
        formatExportDateTime(row.time_et),
        row.activity_label || row.activity_type || "",
        row.activity_type ?? "",
        row.bag_id ?? "",
        row.machine_or_rack ?? "",
        formatExportDuration(row.duration_seconds),
        row.source ?? "",
        row.confidence ?? "",
      ]);
    }
  }
  return { headers, rows };
}

function buildReadyToFoldIntervalRows(intervals) {
  const headers = ["Time", "New Bags Ready", "Cumulative Bags Ready"];
  const rows = (intervals || []).map((interval) => [
    interval.label ?? "",
    interval.newly_ready_count ?? 0,
    interval.cumulative_ready_count ?? interval.available_count ?? 0,
  ]);
  return { headers, rows };
}

function buildReadyToFoldBagRows(sessions) {
  const headers = [
    "Bag ID",
    "Drying Scan (ET)",
    "Ready to Fold (ET)",
    "Drying Duration (minutes)",
    "Dryer",
    "Weight",
    "Order Type",
  ];
  const rows = (sessions || []).map((row) => [
    row.bag_id ?? "",
    formatExportDateTime(row.drying_scan_et),
    formatExportDateTime(row.ready_to_fold_et),
    row.drying_duration_minutes ?? "",
    row.dryer_rack ?? "",
    row.weight ?? "",
    row.order_type || row.service_type || "",
  ]);
  return { headers, rows };
}

/**
 * Export the active Scan Chronology tab as CSV.
 * @returns {boolean} true if a file was downloaded
 */
export function exportScanChronologyCsv({
  stage,
  dateEt,
  sessions = [],
  coverageRows = [],
  employeeGroups = [],
  intervals = [],
}) {
  const stageId = String(stage || "").toLowerCase();
  let payload;

  if (stageId === "user_activity") {
    payload = buildUserActivityRows(employeeGroups);
  } else if (stageId === "coverage_audit") {
    payload = buildCoverageRows(coverageRows);
  } else if (stageId === "ready_to_fold") {
    // Prefer bag-level detail when available; otherwise interval summary.
    payload = sessions.length
      ? buildReadyToFoldBagRows(sessions)
      : buildReadyToFoldIntervalRows(intervals);
  } else if (stageId === "washer_utilization" || stageId === "dryer_utilization") {
    payload = buildUtilRows(sessions);
  } else if (stageId === "washing" || stageId === "drying") {
    payload = buildEventRows(sessions, {
      rackKey: stageId === "washing" ? "washer_rack" : "dryer_rack",
    });
  } else {
    // weighing, sorting, and any future duration-style stages
    payload = buildDurationRows(sessions);
  }

  if (!payload.rows.length) return false;

  const filename = `scan-chronology-${slugStage(stageId)}-${dateEt || "export"}.csv`;
  downloadCsv(filename, payload.headers, payload.rows);
  return true;
}

export function hasScanChronologyExportRows({
  stage,
  sessions = [],
  coverageRows = [],
  employeeGroups = [],
  intervals = [],
}) {
  const stageId = String(stage || "").toLowerCase();
  if (stageId === "user_activity") {
    return employeeGroups.some((g) => (g.activities || []).length > 0);
  }
  if (stageId === "coverage_audit") {
    return coverageRows.length > 0;
  }
  if (stageId === "ready_to_fold") {
    return (
      sessions.length > 0 ||
      intervals.some(
        (interval) => (interval.newly_ready_count || 0) > 0 || (interval.available_count || 0) > 0,
      )
    );
  }
  return sessions.length > 0;
}
