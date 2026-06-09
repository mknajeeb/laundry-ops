export const RUSH_FILTERS = [
  { id: "all", label: "All" },
  { id: "rush", label: "Rush" },
  { id: "non_rush", label: "Non-Rush" },
];

export function filterByRush(records, rushFilter) {
  if (!rushFilter || rushFilter === "all") return records || [];
  return (records || []).filter((r) => {
    if (rushFilter === "rush") return r.rush_label === "Rush";
    if (rushFilter === "non_rush") return r.rush_label === "Non-Rush";
    return true;
  });
}

export function filterRecords(records, tag, rushFilter = "all") {
  let out = records || [];
  if (tag) {
    out = out.filter((r) => (r.drilldown_tags || []).includes(tag));
  }
  return filterByRush(out, rushFilter);
}

export function sectionSplitCounts(section, rushFilter = "all") {
  if (!section || section.live === false) {
    return { total: null, wf: null, hd: null, unknown: null, unavailable: true };
  }
  const rushWf = section.rush_wf || 0;
  const rushHd = section.rush_hd || 0;
  const nonWf = section.nonrush_wf || 0;
  const nonHd = section.nonrush_hd || 0;
  const unknown = section.unknown_needs_review || 0;
  if (rushFilter === "rush") {
    return { total: rushWf + rushHd, wf: rushWf, hd: rushHd, unknown: 0 };
  }
  if (rushFilter === "non_rush") {
    return { total: nonWf + nonHd, wf: nonWf, hd: nonHd, unknown: 0 };
  }
  return { total: section.total || 0, wf: rushWf + nonWf, hd: rushHd + nonHd, unknown };
}

export function shiftMetricValue(metric, rushFilter = "all") {
  if (metric == null) return null;
  if (typeof metric === "number") return metric;
  if (typeof metric === "object" && !Array.isArray(metric)) {
    if (rushFilter === "rush") return metric.rush ?? metric.all ?? null;
    if (rushFilter === "non_rush") return metric.non_rush ?? metric.all ?? null;
    return metric.all ?? null;
  }
  return null;
}

const SHIFT_METRIC_LABELS = {
  weighed: { all: "Weighed", rush: "Rush Weighed", non_rush: "Non-Rush Weighed" },
  not_weighed: { all: "Not Weighed", rush: "Rush Not Weighed", non_rush: "Non-Rush Not Weighed" },
  issues: { all: "Issues", rush: "Rush Issues", non_rush: "Non-Rush Issues" },
  workitems: { all: "Workitems", rush: "Rush Workitems", non_rush: "Non-Rush Workitems" },
  weight_difference: { all: "Weight Difference", rush: "Rush Weight Difference", non_rush: "Non-Rush Weight Difference" },
  yet_to_fold: { all: "Yet to Fold", rush: "Rush Yet to Fold", non_rush: "Non-Rush Yet to Fold" },
};

export function shiftMetricLabel(metricKey, rushFilter = "all") {
  const labels = SHIFT_METRIC_LABELS[metricKey];
  if (!labels) return metricKey;
  if (rushFilter === "rush") return labels.rush;
  if (rushFilter === "non_rush") return labels.non_rush;
  return labels.all;
}

export function formatLastWash(entry, emptyLabel = "No wash started yet") {
  if (!entry || (!entry.at && !entry.time)) return emptyLabel;
  const when = formatEtDateTime(entry.at || entry.time);
  const due = entry.due_date || entry.date_clean ? formatEtDate(entry.due_date || entry.date_clean) : null;
  const lines = [
    when,
    [entry.customer || "—", entry.employee || entry.user || "—"].filter(Boolean).join(" · "),
    [entry.service_type, entry.rush_label || entry.computed_rush_label].filter(Boolean).join(" · "),
    due ? `Due: ${due}` : null,
  ].filter(Boolean);
  return lines.join("\n");
}

const ET_TZ = "America/New_York";

export function formatEtDateTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  return d.toLocaleString("en-US", {
    timeZone: ET_TZ,
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
    timeZoneName: "short",
  });
}

export function formatEtDate(iso) {
  if (!iso) return "—";
  const raw = String(iso).slice(0, 10);
  const [y, mo, da] = raw.split("-").map(Number);
  if (!y || !mo || !da) return String(iso);
  return new Date(y, mo - 1, da).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
}

export function formatDueDateRow(row) {
  const due = row?.due_date || row?.date_clean;
  if (!due) return "Due: —";
  return `Due: ${formatEtDate(due)}`;
}

export function formatLastActivityRow(row) {
  const t = row?.last_activity_time || row?.last_scan_time;
  if (!t) return "Last Activity: —";
  return `Last Activity: ${formatEtDateTime(t)}`;
}

export function formatRushAuditRow(row) {
  const parts = [];
  if (row?.view_date) parts.push(`View Date: ${formatEtDate(row.view_date)}`);
  if (row?.computed_rush_rule) parts.push(row.computed_rush_rule);
  else if (row?.rush_type_raw) parts.push(`Raw rush_type: ${row.rush_type_raw}`);
  return parts.join(" · ") || null;
}

export function formatShiftDateLabel(dateStart, dateEnd) {
  const fmt = (iso) => {
    if (!iso) return "";
    const [y, mo, da] = iso.split("-").map(Number);
    return new Date(y, mo - 1, da).toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  };
  if (dateStart === dateEnd) return `Showing: ${fmt(dateStart)}`;
  return `Showing: ${fmt(dateStart)} – ${fmt(dateEnd)}`;
}

export function syncStatusSubtext(section, syncName = "Ready for Vendor Sync") {
  const sync = section?.sync_status || {};
  if (sync.status === "disabled" || sync.enabled === false) {
    return sync.message || `${syncName}: disabled`;
  }
  if (sync.sync_time_unavailable) {
    return sync.message || `${syncName}: unavailable`;
  }
  const parts = [sync.message || (section?.last_refreshed_at ? `${syncName}: ${section.last_refreshed_at}` : null)];
  if (sync.stale && sync.stale_reason) parts.push(sync.stale_reason);
  return parts.filter(Boolean).join(" · ");
}

export function rinseSyncBanner(data) {
  const rinseSync = data?.rinse_sync || {};
  const av = rinseSync.at_vendor || data?.current_active_work?.sync_status || {};
  const rfv = rinseSync.ready_for_vendor || data?.ready_for_vendor?.sync_status || {};
  const lines = [];
  if (av.message) lines.push(av.message);
  else if (av.last_refreshed_at_et) lines.push(`At Vendor Sync: ${av.last_refreshed_at_et}`);
  if (rfv.enabled === false) {
    lines.push(rfv.message || "Ready for Vendor Sync: disabled");
  } else if (rfv.message) {
    lines.push(rfv.message);
  }
  const staleParts = [];
  if (av.stale && av.stale_reason) staleParts.push(av.stale_reason);
  if (rfv.stale && rfv.stale_reason) staleParts.push(rfv.stale_reason);
  return { lines, staleParts, anyStale: staleParts.length > 0 };
}
