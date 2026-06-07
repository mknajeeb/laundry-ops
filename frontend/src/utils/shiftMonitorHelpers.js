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
  if (!section) {
    return { total: 0, wf: 0, hd: 0, unknown: 0 };
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
