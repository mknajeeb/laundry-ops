/** Friendly labels for Shift Analysis Dashboard (lifecycle vs performance stages). */

export const LIFECYCLE_STATUS_LABELS = {
  ASSIGNED_NOT_SENT_TO_VENDOR: "Assigned / Not Sent",
  SENT_TO_VENDOR: "Sent to Vendor",
  PENDING_WEIGHING: "Pending Weighing",
  WEIGHED_NOT_STARTED: "Weighed / Not Started",
  SORTED_READY_FOR_WASH: "Sorted / Ready",
  IN_WASHING: "In Washing",
  IN_DRYING: "In Drying",
  FOLDED_COMPLETED: "Folded / Completed",
  SENT_TO_RINSE: "Sent to Rinse",
  UNKNOWN: "Unknown",
};

export const PERFORMANCE_STAGE_LABELS = {
  LOAD_WASHER: "Load Washer",
  LOAD_DRYER: "Load Dryer",
  WEIGHING: "Weighing",
  SORTING: "Sorting / Prep",
  WAITING_FOR_WASHER: "Waiting for Washer",
  FOLDING: "Folding",
};

export const EXCEPTION_LABELS = {
  ORDER_REJECTED_FULL: "Rejected Full Order",
  ORDER_REJECT_NO_START_CLEANING_AFTER_LIMIT: "Rejected — no wash started",
  ORDER_REJECT_NO_START_CLEANING_30_MIN: "Rejected — no wash started",
  COMPLETED_WITHOUT_FINAL_CLEAN_SCAN: "Completed without final CLEAN rack scan",
  NEEDS_REVIEW_EXTERNAL_SCAN_AFTER_CLEAN: "External scan after CLEAN",
  CHECKOUT_WITHOUT_CLEAN_RACK: "Checked out without CLEAN scan",
  SENT_TO_RINSE_WITHOUT_CLEAN_RACK: "Checked out without CLEAN scan",
};

/** Operational checkout labels — separate from lifecycle SENT_TO_RINSE. */
export const CHECKOUT_STATUS_LABELS = {
  NOT_CHECKED_OUT: "Checkout Pending",
  CHECKED_OUT: "Checked Out",
  CHECKOUT_NEEDS_REVIEW: "Checkout Needs Review",
};

export const SENT_TO_RINSE_REASON_LABELS = {
  MISSING_FROM_NEXT_PORTAL_SCRAPE: "Missing from confirmed portal scrape after completion",
  EXTERNAL_USER_SCAN_AFTER_CLEAN: "External scan after CLEAN",
};

export function sentToRinseReasonLabel(code, backendLabels = {}) {
  if (!code) return "—";
  return backendLabels[code] || SENT_TO_RINSE_REASON_LABELS[code] || code.replace(/_/g, " ");
}

export function lifecycleStatusLabel(code, backendLabels = {}) {
  if (!code) return "—";
  return backendLabels[code] || LIFECYCLE_STATUS_LABELS[code] || code.replace(/_/g, " ");
}

export function performanceStageLabel(code) {
  if (!code) return "—";
  return PERFORMANCE_STAGE_LABELS[code] || code.replace(/_/g, " ");
}

export function exceptionLabel(code) {
  if (!code) return "—";
  return EXCEPTION_LABELS[code] || code.replace(/_/g, " ");
}

export function formatExceptionList(flags, backendLabels = {}) {
  const list = Array.isArray(flags) ? flags : [];
  if (!list.length) return "—";
  return list.map((c) => backendLabels[c] || exceptionLabel(c)).join(", ");
}

export function formatOperationalFlags(flags) {
  const f = flags || {};
  const parts = [];
  if (f.has_create_issue) parts.push("Issue");
  if (f.has_create_workitem) parts.push("Workitem");
  if (f.has_create_bulk_workitem) parts.push("Bulk workitem");
  if (f.has_workitem && !f.has_create_workitem) parts.push("Workitem (other)");
  return parts.length ? parts.join(", ") : "—";
}

export function formatStageDetail(stageDetail) {
  const detail = stageDetail || {};
  const keys = Object.keys(detail);
  if (!keys.length) return "—";
  return keys
    .map((key) => {
      const label = performanceStageLabel(key);
      const val = detail[key];
      if (val && typeof val === "object") {
        const parts = [];
        if (val.start_time) parts.push(`start ${val.start_time}`);
        if (val.end_time) parts.push(`end ${val.end_time}`);
        if (val.expected_end_time) parts.push(`expected ${val.expected_end_time}`);
        return `${label}: ${parts.join(", ") || JSON.stringify(val)}`;
      }
      return `${label}: ${String(val)}`;
    })
    .join(" · ");
}
