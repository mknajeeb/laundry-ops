export const RUSH_FILTERS = [
  { id: "all", label: "All" },
  { id: "rush", label: "Rush" },
  { id: "non_rush", label: "Non-Rush" },
];

export const SERVICE_FILTERS = [
  { id: "all", label: "All" },
  { id: "wf", label: "WF" },
  { id: "hd", label: "HD" },
];

export function matchesRushFilter(rec, rushFilter) {
  if (!rushFilter || rushFilter === "all") return true;
  const rb = rec.rush_bucket || (rec.rush_label === "Rush" ? "RUSH" : rec.rush_label === "Non-Rush" ? "NON_RUSH" : "");
  if (rushFilter === "rush") return rb === "RUSH";
  if (rushFilter === "non_rush") return rb === "NON_RUSH";
  return true;
}

export function matchesServiceFilter(rec, serviceFilter) {
  if (!serviceFilter || serviceFilter === "all") return true;
  const sb = String(rec.service_bucket || rec.service_type || "").toUpperCase();
  if (serviceFilter === "wf") return sb === "WF";
  if (serviceFilter === "hd") return sb === "HD";
  return true;
}

export function filterModuleRecords(records, { moduleTag, rushFilter = "all", serviceFilter = "all" } = {}) {
  return (records || []).filter((r) => {
    if (moduleTag && !(r.module_tags || []).includes(moduleTag)) return false;
    return matchesRushFilter(r, rushFilter) && matchesServiceFilter(r, serviceFilter);
  });
}

export function filterCardsForScope(cards, serviceFilter = "all") {
  return (cards || []).filter((card) => {
    if (serviceFilter === "hd" && card.wf_only) return false;
    if (serviceFilter === "wf" && card.hd_only) return false;
    return true;
  });
}

export function getModuleCardCount(records, card, rushFilter, serviceFilter, module) {
  if (card.informational || !card.module_tag) return card.count ?? 0;
  if (module?.mode === "summary_only" || module?.filters_enabled === false) return card.count ?? 0;
  if (card.id === "av_changed_rush" && rushFilter === "non_rush") return 0;
  if (card.id === "mon_weight" && serviceFilter === "hd") return 0;
  return filterModuleRecords(records, {
    moduleTag: card.module_tag,
    rushFilter,
    serviceFilter,
  }).length;
}

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

export function filterRfvRecords(rows, tag, rushFilter = "all") {
  let out = rows || [];
  if (tag) {
    out = out.filter((r) => (r.drilldown_tags || []).includes(tag));
  }
  return out.filter((r) => matchesRushFilter(r, rushFilter) && matchesServiceFilter(r, "all"));
}

function avRowRush(row) {
  const rb = row?.rush_bucket;
  if (rb === "RUSH") return "RUSH";
  if (rb === "NON_RUSH") return "NON_RUSH";
  return "UNKNOWN";
}

function avRowService(row) {
  const sb = String(row?.service_bucket || row?.service_type || "").toUpperCase();
  if (sb === "WF") return "WF";
  if (sb === "HD") return "HD";
  return "UNKNOWN";
}

/** Filter At Vendor daily-workload rows by rush/service/status bucket (no counting logic change). */
export function filterAtVendorBucket(rows, { rush = "all", service = "all", status = "all" } = {}) {
  return (rows || []).filter((row) => {
    if (status === "pending" && row.at_vendor_status !== "Pending") return false;
    if (status === "completed" && row.at_vendor_status !== "Completed") return false;
    const rowRush = avRowRush(row);
    const rowSvc = avRowService(row);
    if (rush === "rush" && rowRush !== "RUSH") return false;
    if (rush === "non_rush" && rowRush !== "NON_RUSH") return false;
    if (service === "wf" && rowSvc !== "WF") return false;
    if (service === "hd" && rowSvc !== "HD") return false;
    if (service === "unknown") {
      if (rush === "all") {
        return rowRush === "UNKNOWN" || rowSvc === "UNKNOWN";
      }
      if (rush === "rush" && rowRush !== "RUSH") return false;
      if (rush === "non_rush" && rowRush !== "NON_RUSH") return false;
      return rowRush === "UNKNOWN" || rowSvc === "UNKNOWN";
    }
    return true;
  });
}

export function countAtVendorBucket(rows, bucket) {
  return filterAtVendorBucket(rows, bucket).length;
}

function avStatusCards(prefix, module, rows, rush) {
  const totalKey = rush === "rush" ? "rush_total" : "non_rush_total";
  const pendingKey = rush === "rush" ? "rush_pending" : "non_rush_pending";
  const completedKey = rush === "rush" ? "rush_completed" : "non_rush_completed";
  const bucketRush = rush;
  return [
    {
      key: `${prefix}_total`,
      label: `${prefix} Total`,
      count: module?.[totalKey],
      bucket: { rush: bucketRush, service: "all", status: "all" },
      clickable: true,
    },
    {
      key: `${prefix}_pending`,
      label: `${prefix} Pending`,
      count: module?.[pendingKey],
      bucket: { rush: bucketRush, service: "all", status: "pending" },
      clickable: true,
    },
    {
      key: `${prefix}_completed`,
      label: `${prefix} Completed`,
      count: module?.[completedKey],
      bucket: { rush: bucketRush, service: "all", status: "completed" },
      clickable: true,
    },
  ];
}

function avServiceStatusCards(prefix, rows, rush, service) {
  const bucket = { rush, service, status: "all" };
  const pendingBucket = { rush, service, status: "pending" };
  const completedBucket = { rush, service, status: "completed" };
  const total = countAtVendorBucket(rows, bucket);
  const pending = countAtVendorBucket(rows, pendingBucket);
  const completed = countAtVendorBucket(rows, completedBucket);
  if (total === 0 && pending === 0 && completed === 0) return [];
  return [
    {
      key: `${prefix}_${service}_total`,
      label: `${prefix} ${service.toUpperCase()} Total`,
      count: total,
      bucket,
      clickable: total != null,
    },
    {
      key: `${prefix}_${service}_pending`,
      label: `${prefix} ${service.toUpperCase()} Pending`,
      count: pending,
      bucket: pendingBucket,
      clickable: pending != null,
    },
    {
      key: `${prefix}_${service}_completed`,
      label: `${prefix} ${service.toUpperCase()} Completed`,
      count: completed,
      bucket: completedBucket,
      clickable: completed != null,
    },
  ];
}

function avUnknownCards(prefix, rows, rush) {
  const bucket = { rush, service: "unknown", status: "all" };
  const pendingBucket = { rush, service: "unknown", status: "pending" };
  const completedBucket = { rush, service: "unknown", status: "completed" };
  const total = countAtVendorBucket(rows, bucket);
  if (total === 0) return [];
  return [
    {
      key: `${prefix.replace(/\s+/g, "_").toLowerCase()}_unknown_total`,
      label: `${prefix} Unknown Total`,
      count: total,
      bucket,
      clickable: true,
    },
    {
      key: `${prefix.replace(/\s+/g, "_").toLowerCase()}_unknown_pending`,
      label: `${prefix} Unknown Pending`,
      count: countAtVendorBucket(rows, pendingBucket),
      bucket: pendingBucket,
      clickable: true,
    },
    {
      key: `${prefix.replace(/\s+/g, "_").toLowerCase()}_unknown_completed`,
      label: `${prefix} Unknown Completed`,
      count: countAtVendorBucket(rows, completedBucket),
      bucket: completedBucket,
      clickable: true,
    },
  ];
}

/** Management hierarchy cards for At Vendor daily workload. */
export function buildAtVendorHierarchy(module, rushSegment = "all") {
  const rows = module?.rows || [];
  const sections = [];

  sections.push({
    key: "layer1",
    title: "Daily Workload",
    cards: [
      {
        key: "av_total",
        label: "Total",
        count: module?.daily_workload_total ?? module?.total,
        bucket: { rush: "all", service: "all", status: "all" },
        moduleTag: "mod_at_vendor_total",
        clickable: true,
      },
      {
        key: "av_pending",
        label: "Pending",
        count: module?.pending ?? module?.pending_count,
        bucket: { rush: "all", service: "all", status: "pending" },
        moduleTag: "mod_at_vendor_pending",
        clickable: true,
      },
      {
        key: "av_completed_today",
        label: "Completed Today",
        count: module?.completed ?? module?.completed_today_count,
        bucket: { rush: "all", service: "all", status: "completed" },
        moduleTag: "mod_at_vendor_completed",
        clickable: true,
      },
    ],
  });

  if (rushSegment === "all") {
    const unknownCards = avUnknownCards("Unknown", rows, "all");
    sections.push({
      key: "layer2",
      title: "By urgency",
      cards: [
        ...avStatusCards("Rush", module, rows, "rush"),
        ...avStatusCards("Non-Rush", module, rows, "non_rush"),
        ...unknownCards.map((card) => ({
          ...card,
          bucket: { rush: "all", service: "unknown", status: card.bucket.status },
        })),
      ],
    });
  } else if (rushSegment === "rush") {
    sections.push({
      key: "layer2_rush",
      title: "Rush",
      cards: avStatusCards("Rush", module, rows, "rush"),
    });
    sections.push({
      key: "layer3_rush",
      title: "Rush by service",
      cards: [
        ...avServiceStatusCards("Rush", rows, "rush", "wf"),
        ...avServiceStatusCards("Rush", rows, "rush", "hd"),
        ...avUnknownCards("Rush", rows, "rush"),
      ],
    });
  } else if (rushSegment === "non_rush") {
    sections.push({
      key: "layer2_non_rush",
      title: "Non-Rush",
      cards: avStatusCards("Non-Rush", module, rows, "non_rush"),
    });
    sections.push({
      key: "layer3_non_rush",
      title: "Non-Rush by service",
      cards: [
        ...avServiceStatusCards("Non-Rush", rows, "non_rush", "wf"),
        ...avServiceStatusCards("Non-Rush", rows, "non_rush", "hd"),
        ...avUnknownCards("Non-Rush", rows, "non_rush"),
      ],
    });
  }

  return sections;
}

function rfvTotalCard(label, count, drilldownTag, key) {
  return {
    key: key || drilldownTag,
    label,
    count,
    drilldownTag,
    clickable: count != null,
  };
}

/** Management hierarchy cards for Ready for Vendor (totals only). */
export function buildRfvHierarchy(rfv, rushSegment = "all") {
  if (!rfv?.live) {
    return [{
      key: "unavailable",
      cards: [{
        key: "rfv_total",
        label: "RFV Total",
        count: rfv?.total ?? "—",
        drilldownTag: "ready_for_vendor",
        clickable: false,
      }],
    }];
  }

  const sections = [];

  if (rushSegment === "all") {
    sections.push({
      key: "layer1",
      title: "Queue",
      cards: [rfvTotalCard("RFV Total", rfv.total, "ready_for_vendor", "rfv_total")],
    });
    sections.push({
      key: "layer2",
      title: "By urgency",
      cards: [
        rfvTotalCard("Rush Total", rfv.rush_total, "rfv_rush", "rfv_rush_total"),
        rfvTotalCard("Non-Rush Total", rfv.nonrush_total, "rfv_non_rush", "rfv_non_rush_total"),
        ...(rfv.unknown_needs_review
          ? [rfvTotalCard("Unknown Review Total", rfv.unknown_needs_review, "rfv_unknown_needs_review", "rfv_unknown")]
          : []),
      ],
    });
  } else if (rushSegment === "rush") {
    sections.push({
      key: "layer2_rush",
      title: "Rush",
      cards: [rfvTotalCard("Rush Total", rfv.rush_total, "rfv_rush", "rfv_rush_total")],
    });
    const layer3 = [
      rfvTotalCard("Rush WF Total", rfv.rush_wf, "rfv_rush_wf", "rfv_rush_wf"),
      rfvTotalCard("Rush HD Total", rfv.rush_hd, "rfv_rush_hd", "rfv_rush_hd"),
    ].filter((c) => c.count > 0);
    if (layer3.length) {
      sections.push({ key: "layer3_rush", title: "Rush by service", cards: layer3 });
    }
  } else if (rushSegment === "non_rush") {
    sections.push({
      key: "layer2_non_rush",
      title: "Non-Rush",
      cards: [rfvTotalCard("Non-Rush Total", rfv.nonrush_total, "rfv_non_rush", "rfv_non_rush_total")],
    });
    const layer3 = [
      rfvTotalCard("Non-Rush WF Total", rfv.nonrush_wf, "rfv_nonrush_wf", "rfv_nonrush_wf"),
      rfvTotalCard("Non-Rush HD Total", rfv.nonrush_hd, "rfv_nonrush_hd", "rfv_nonrush_hd"),
    ].filter((c) => c.count > 0);
    if (layer3.length) {
      sections.push({ key: "layer3_non_rush", title: "Non-Rush by service", cards: layer3 });
    }
  }

  return sections;
}

export function filterAtVendorDrilldown(module, drilldown) {
  if (drilldown?.moduleTag === "completed_before_day_start_still_present") {
    return module?.completed_before_day_start_still_present_rows || [];
  }
  if (drilldown?.moduleTag === "mod_at_vendor_changed_rush") {
    return filterModuleRecords(module?.rows || [], { moduleTag: "mod_at_vendor_changed_rush" });
  }
  if (drilldown?.bucket) {
    return filterAtVendorBucket(module?.rows || [], drilldown.bucket);
  }
  if (drilldown?.moduleTag) {
    return filterModuleRecords(module?.rows || [], {
      moduleTag: drilldown.moduleTag,
      rushFilter: drilldown.rushFilter || "all",
      serviceFilter: drilldown.serviceFilter || "all",
    });
  }
  return module?.rows || [];
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
  const t = row?.last_activity_time_et || row?.last_activity_time || row?.last_scan_time;
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

export function formatRecordReason(row) {
  return (
    row?.baseline_inclusion_reason
    || row?.vendor_home_bucket_reason
    || row?.scan_dts_bucket_reason
    || row?.snapshot_bucket_reason
    || row?.wip_bucket_reason
    || row?.due_today_bucket_reason
    || null
  );
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
