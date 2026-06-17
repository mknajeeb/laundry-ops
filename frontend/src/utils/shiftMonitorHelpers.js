import { easternIsoDate } from "./foldingEasternDate";

/** Current calendar date in America/New_York (YYYY-MM-DD). */
export function currentEtIsoDate() {
  return easternIsoDate();
}

/**
 * Operations Mode: single ET day selected and that day is today.
 * Custom ranges (even if they include today) are Reporting Mode.
 */
export function isOperationsMode(dateStart, dateEnd) {
  const today = currentEtIsoDate();
  return Boolean(dateStart && dateEnd && dateStart === dateEnd && dateStart === today);
}

/** @deprecated Use isOperationsMode — kept for existing imports */
export function isLiveOperationalView(dateStart, dateEnd) {
  return isOperationsMode(dateStart, dateEnd);
}

export function isReportingMode(dateStart, dateEnd) {
  return !isOperationsMode(dateStart, dateEnd);
}

/** Optional report insight percentages (presentation-only; uses module rows). */
export function buildWorkloadReportStats(module) {
  const rows = module?.rows || [];
  const total = Number(module?.daily_workload_total ?? module?.total ?? 0);
  if (!total) return null;
  const completed = Number(module?.completed ?? module?.completed_today_count ?? 0);
  const rushCount = rows.filter((r) => String(r.rush_bucket || "").toUpperCase() === "RUSH").length;
  const hdCount = rows.filter(
    (r) => String(r.service_bucket || r.service_type || "").toUpperCase() === "HD",
  ).length;
  return {
    completedPct: Math.round((completed / total) * 100),
    rushPct: Math.round((rushCount / total) * 100),
    hdPct: Math.round((hdCount / total) * 100),
  };
}

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

function avServiceCardVariant(service, rush, status) {
  const base = service === "wf" ? "wf" : "hd";
  if (rush === "rush") return "rush";
  if (status === "completed") return service === "hd" ? "hd" : "wf";
  return base;
}

function avFilteredServiceCards(module, rows, rush, status) {
  const labels = { all: "Total", pending: "Pending", completed: "Completed" };
  const bucketStatus = status;
  if (rush === "all") {
    const fieldMap = {
      all: { wf: "wf_total", hd: "hd_total" },
      pending: { wf: "wf_pending", hd: "hd_pending" },
      completed: { wf: "wf_completed", hd: "hd_completed" },
    };
    const fields = fieldMap[status];
    return [
      {
        key: `wf_${status}`,
        label: `WF ${labels[status]}`,
        count: module?.[fields.wf] ?? countAtVendorBucket(rows, { rush: "all", service: "wf", status: bucketStatus }),
        bucket: { rush: "all", service: "wf", status: bucketStatus },
        clickable: true,
        variant: avServiceCardVariant("wf", rush, status),
      },
      {
        key: `hd_${status}`,
        label: `HD ${labels[status]}`,
        count: module?.[fields.hd] ?? countAtVendorBucket(rows, { rush: "all", service: "hd", status: bucketStatus }),
        bucket: { rush: "all", service: "hd", status: bucketStatus },
        clickable: true,
        variant: avServiceCardVariant("hd", rush, status),
      },
    ];
  }
  const wf = countAtVendorBucket(rows, { rush, service: "wf", status: bucketStatus });
  const hd = countAtVendorBucket(rows, { rush, service: "hd", status: bucketStatus });
  return [
    {
      key: `${rush}_wf_${status}`,
      label: `WF ${labels[status]}`,
      count: wf,
      bucket: { rush, service: "wf", status: bucketStatus },
      clickable: true,
      variant: avServiceCardVariant("wf", rush, status),
    },
    {
      key: `${rush}_hd_${status}`,
      label: `HD ${labels[status]}`,
      count: hd,
      bucket: { rush, service: "hd", status: bucketStatus },
      clickable: true,
      variant: avServiceCardVariant("hd", rush, status),
    },
  ];
}

function avUnknownCards(rows, rush) {
  const bucket = { rush, service: "unknown", status: "all" };
  const pendingBucket = { rush, service: "unknown", status: "pending" };
  const completedBucket = { rush, service: "unknown", status: "completed" };
  const total = countAtVendorBucket(rows, bucket);
  if (total === 0) return [];
  const slug = rush === "all" ? "all" : rush;
  return [
    {
      key: `${slug}_unknown_total`,
      label: "Review Total",
      count: total,
      bucket,
      clickable: true,
      variant: "info",
    },
    {
      key: `${slug}_unknown_pending`,
      label: "Review Pending",
      count: countAtVendorBucket(rows, pendingBucket),
      bucket: pendingBucket,
      clickable: true,
      variant: "pending",
    },
    {
      key: `${slug}_unknown_completed`,
      label: "Review Completed",
      count: countAtVendorBucket(rows, completedBucket),
      bucket: completedBucket,
      clickable: true,
      variant: "completed",
    },
  ];
}

/** Management hierarchy cards for At Vendor daily workload. */
export function buildAtVendorHierarchy(module, rushSegment = "all", options = {}) {
  const { historical = false } = options;
  const rows = module?.rows || [];
  const rush = rushSegment === "all" ? "all" : rushSegment;
  const sections = [];

  sections.push({
    key: "kpi",
    layout: "kpi",
    cards: [
      {
        key: "av_total",
        label: historical ? "Total Workload" : "Total",
        count: module?.daily_workload_total ?? module?.total,
        bucket: { rush: "all", service: "all", status: "all" },
        moduleTag: "mod_at_vendor_total",
        clickable: true,
        variant: rush === "rush" ? "rush" : "total",
        large: true,
      },
      {
        key: "av_pending",
        label: "Pending",
        count: module?.pending ?? module?.pending_count,
        bucket: { rush: "all", service: "all", status: "pending" },
        moduleTag: "mod_at_vendor_pending",
        clickable: true,
        variant: rush === "rush" ? "rush" : "pending",
        large: true,
      },
      {
        key: "av_completed_today",
        label: historical ? "Completed" : "Completed Today",
        count: module?.completed ?? module?.completed_today_count,
        bucket: { rush: "all", service: "all", status: "completed" },
        moduleTag: "mod_at_vendor_completed",
        clickable: true,
        variant: "completed",
        large: true,
      },
    ],
  });

  sections.push({
    key: "work_type",
    title: "Work Type",
    cards: avFilteredServiceCards(module, rows, rush, "all"),
  });
  sections.push({
    key: "pending_work",
    title: "Pending Work",
    cards: avFilteredServiceCards(module, rows, rush, "pending"),
  });
  sections.push({
    key: "completed_today",
    title: historical ? "Completed" : "Completed Today",
    cards: avFilteredServiceCards(module, rows, rush, "completed"),
  });

  const unknownCards = avUnknownCards(rows, rush);
  if (unknownCards.length) {
    sections.push({
      key: "unknown_review",
      title: "Needs Review",
      cards: unknownCards,
    });
  }

  return sections;
}

const PORTAL_DIRECT_SOURCE = "vendor_home_page_direct";

/** Prefer direct Vendor Home scrape counts for the live portal snapshot panel. */
function portalSnapshotDirectFields(av) {
  const useDirect = av.portal_reported_source === PORTAL_DIRECT_SOURCE;
  return {
    useDirect,
    atVeewash: useDirect && av.portal_reported_orders_at_veewash != null
      ? av.portal_reported_orders_at_veewash
      : av.orders_at_veewash ?? av.current_portal_snapshot_total ?? av.current_live_vendor_home_total,
    yetToProcess: useDirect && av.portal_reported_orders_at_veewash_yet_to_process != null
      ? av.portal_reported_orders_at_veewash_yet_to_process
      : av.orders_at_veewash_yet_to_process ?? av.portal_snapshot_yet_to_process,
    yetToProcessReliable: useDirect && av.portal_reported_orders_at_veewash_yet_to_process != null
      ? true
      : av.orders_at_veewash_yet_to_process_reliable === true
        || av.portal_snapshot_yet_to_process_reliable === true,
    dueToday: useDirect && av.portal_reported_due_today != null
      ? av.portal_reported_due_today
      : av.due_today,
    dueTodayReliable: useDirect && av.portal_reported_due_today != null
      ? true
      : av.due_today_reliable === true,
    dueTodayYtp: useDirect && av.portal_reported_due_today_yet_to_process != null
      ? av.portal_reported_due_today_yet_to_process
      : av.due_today_yet_to_process,
    dueTodayYtpReliable: useDirect && av.portal_reported_due_today_yet_to_process != null
      ? true
      : av.due_today_yet_to_process_reliable === true,
    operationalAtVeewash: av.orders_at_veewash,
  };
}

/** Current portal snapshot cards (live Vendor Home counts — not daily workload). */
export function buildAtVendorPortalSnapshot(module) {
  const av = module || {};
  const direct = portalSnapshotDirectFields(av);
  const snapshotTotal = direct.atVeewash;
  const snapshotReliable = direct.useDirect || av.orders_at_veewash_reliable !== false;

  const ytpReliable = direct.yetToProcessReliable;
  const ytp = direct.yetToProcess;

  const operationalNote = (
    direct.useDirect
    && direct.operationalAtVeewash != null
    && snapshotTotal != null
    && direct.operationalAtVeewash !== snapshotTotal
  )
    ? `Operational filter: ${direct.operationalAtVeewash}`
    : undefined;

  const cards = [
    {
      key: "av_portal_snapshot_total",
      label: "Currently at VeeWash",
      count: snapshotTotal,
      sub: direct.useDirect ? "Vendor Home" : operationalNote,
      clickable: snapshotTotal != null,
      portalFilter: "portal_at_veewash",
      variant: "snapshot",
    },
  ];

  if (ytpReliable && ytp != null) {
    cards.push({
      key: "av_portal_yet_to_process",
      label: "Yet to process",
      count: ytp,
      sub: direct.useDirect ? "Vendor Home" : undefined,
      clickable: true,
      portalFilter: "portal_yet_to_process",
      variant: "snapshot",
    });
  } else if (snapshotTotal > 0 && !ytpReliable) {
    cards.push({
      key: "av_portal_ytp_unavailable",
      label: "Yet to process",
      count: null,
      sub: "Pending count unavailable — run Vendor Home sync for direct counts",
      clickable: false,
      variant: "info",
    });
  }

  if (direct.dueTodayReliable && direct.dueToday != null) {
    cards.push({
      key: "av_portal_due_today",
      label: "Due Today",
      count: direct.dueToday,
      sub: direct.useDirect ? "Vendor Home" : undefined,
      clickable: true,
      portalFilter: "portal_due_today",
      variant: "snapshot",
    });
  }
  if (direct.dueTodayYtpReliable && direct.dueTodayYtp != null) {
    cards.push({
      key: "av_portal_due_today_ytp",
      label: "Due Today Yet to Process",
      count: direct.dueTodayYtp,
      sub: direct.useDirect ? "Vendor Home" : undefined,
      clickable: true,
      portalFilter: "portal_due_today_ytp",
      variant: "snapshot",
    });
  }

  if (av.scan_only_arrivals_blocked_count > 0) {
    cards.push({
      key: "av_scan_only_blocked",
      label: "Scan-only blocked",
      count: av.scan_only_arrivals_blocked_count,
      clickable: false,
      variant: "info",
    });
  }
  if (av.bags_gone_from_portal_but_in_workload_count > 0) {
    cards.push({
      key: "av_gone_but_counted",
      label: "Left portal — still in workload",
      count: av.bags_gone_from_portal_but_in_workload_count,
      sub: "Dashboard-derived · not from Vendor Home",
      clickable: true,
      portalFilter: "portal_gone_but_counted",
      variant: "info",
    });
  }
  return [{
    key: "portal_snapshot",
    layout: "snapshot",
    meta: {
      scrapeAt: av.portal_snapshot_scrape_at || null,
      reconciliation: av.portal_snapshot_presence_reconciliation || null,
      sources: {
        atVeewash: av.orders_at_veewash_source,
        yetToProcess: av.orders_at_veewash_yet_to_process_source,
        dueToday: av.due_today_source,
        dueTodayYtp: av.due_today_yet_to_process_source,
      },
      reliable: {
        atVeewash: av.orders_at_veewash_reliable !== false,
        yetToProcess: av.orders_at_veewash_yet_to_process_reliable === true,
        dueToday: av.due_today_reliable === true,
        dueTodayYtp: av.due_today_yet_to_process_reliable === true,
      },
    },
    cards: cards.map((c) => ({
      variant: c.variant || "snapshot",
      compact: true,
      ...c,
    })),
  }];
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

function isPortalDueToday(row, referenceDateEt) {
  if (!referenceDateEt) return false;
  const ref = String(referenceDateEt).slice(0, 10);
  const edd = row?.estimated_delivery_date || row?.date_clean;
  return edd ? String(edd).slice(0, 10) === ref : false;
}

/** Drilldown rows for Current Portal Snapshot cards (live presence first). */
export function filterAtVendorPortalDrilldown(module, drilldown, { referenceDateEt } = {}) {
  const portalRows = module?.portal_snapshot_drilldown_rows;
  const fallbackRows = module?.rows || [];
  const rows = (portalRows?.length ? portalRows : fallbackRows);

  switch (drilldown?.portalFilter) {
    case "portal_at_veewash":
      return portalRows?.length
        ? portalRows
        : fallbackRows.filter((r) => r.currently_on_vendor_home === true);
    case "portal_yet_to_process":
      return rows.filter((r) => r.portal_yet_to_process === true);
    case "portal_due_today":
      return rows.filter((r) => isPortalDueToday(r, referenceDateEt));
    case "portal_due_today_ytp":
      return rows.filter((r) => r.portal_yet_to_process === true && isPortalDueToday(r, referenceDateEt));
    case "portal_gone_but_counted":
      return fallbackRows.filter((r) => r.left_vendor_home_but_counted === true);
    default:
      return [];
  }
}

export function filterAtVendorDrilldown(module, drilldown, options = {}) {
  if (drilldown?.portalFilter) {
    return filterAtVendorPortalDrilldown(module, drilldown, options);
  }
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

/** Primary EDD field for drilldown rows (presence EDD preferred over date_clean). */
export function getRowEddIso(row) {
  return (
    row?.estimated_delivery_date
    || row?.estimated_delivery_date_et
    || row?.due_date
    || row?.date_clean
    || null
  );
}

function parseCalendarDateOnly(iso) {
  if (!iso) return null;
  const raw = String(iso).slice(0, 10);
  const [y, mo, da] = raw.split("-").map(Number);
  if (!y || !mo || !da) return null;
  return new Date(y, mo - 1, da);
}

/** Due status vs selected ET calendar date. */
export function computeDueStatus(referenceDateIso, eddIso) {
  const ref = parseCalendarDateOnly(referenceDateIso);
  const edd = parseCalendarDateOnly(eddIso);
  if (!ref || !edd) {
    return {
      bucket: "unknown",
      sortOrder: 99,
      label: "EDD unavailable",
      colorKey: "neutral",
      daysOffset: null,
      eddIso: eddIso || null,
    };
  }
  const daysOffset = Math.round((edd.getTime() - ref.getTime()) / 86400000);
  if (daysOffset < 0) {
    const lateDays = Math.abs(daysOffset);
    return {
      bucket: "late",
      sortOrder: 0,
      label: lateDays === 1 ? "1 Day Late" : `${lateDays} Days Late`,
      colorKey: "late",
      daysOffset,
      eddIso,
    };
  }
  if (daysOffset === 0) {
    return {
      bucket: "due_today",
      sortOrder: 1,
      label: "Due Today",
      colorKey: "due_today",
      daysOffset,
      eddIso,
    };
  }
  if (daysOffset === 1) {
    return {
      bucket: "due_tomorrow",
      sortOrder: 2,
      label: "Due Tomorrow",
      colorKey: "due_tomorrow",
      daysOffset,
      eddIso,
    };
  }
  return {
    bucket: "future",
    sortOrder: 3,
    label: `Due in ${daysOffset} Days`,
    colorKey: "future",
    daysOffset,
    eddIso,
  };
}

export const DUE_STATUS_COLORS = {
  late: "error.main",
  due_today: "warning.dark",
  due_tomorrow: "info.main",
  future: "text.secondary",
  neutral: "text.disabled",
};

export function formatEddDisplay(iso) {
  if (!iso) return "—";
  const raw = String(iso).slice(0, 10);
  const [y, mo, da] = raw.split("-").map(Number);
  if (!y || !mo || !da) return formatEtDate(iso);
  return new Date(y, mo - 1, da).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export function sortDrilldownRowsByDue(rows, referenceDateIso) {
  const list = [...(rows || [])];
  list.sort((a, b) => {
    const sa = computeDueStatus(referenceDateIso, getRowEddIso(a));
    const sb = computeDueStatus(referenceDateIso, getRowEddIso(b));
    if (sa.sortOrder !== sb.sortOrder) return sa.sortOrder - sb.sortOrder;
    const ea = parseCalendarDateOnly(sa.eddIso);
    const eb = parseCalendarDateOnly(sb.eddIso);
    if (ea && eb && ea.getTime() !== eb.getTime()) return ea - eb;
    return String(a.bag_id || "").localeCompare(String(b.bag_id || ""));
  });
  return list;
}

export function summarizeDrilldownEdd(rows, referenceDateIso) {
  let missing = 0;
  const sources = {};
  for (const row of rows || []) {
    const edd = getRowEddIso(row);
    if (!edd) {
      missing += 1;
      continue;
    }
    const src = row?.delivery_source
      || (row?.estimated_delivery_date ? "estimated_delivery_date" : "date_clean");
    sources[src] = (sources[src] || 0) + 1;
  }
  return { missing, sources, total: (rows || []).length };
}

export function formatDueDateRow(row) {
  const due = getRowEddIso(row);
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

export function isWfBag(row) {
  return String(row?.service_type || row?.service_bucket || "").toUpperCase() === "WF";
}

/** Normalize pre/post/delta weight from At Vendor or pipeline record shapes. */
export function getBagWeightParts(row) {
  const wd = row?.weight_difference || {};
  const pre = row?.pre_clean_weight ?? wd.first_weight_lbs ?? null;
  const post = row?.post_clean_weight ?? wd.second_weight_lbs ?? row?.completed_lbs ?? null;
  let delta = row?.clean_weight_delta ?? wd.difference_lbs ?? null;
  if (delta == null && pre != null && post != null) {
    const p = Number(pre);
    const q = Number(post);
    if (Number.isFinite(p) && Number.isFinite(q)) {
      delta = Math.round((q - p) * 10) / 10;
    }
  }
  const isWf = isWfBag(row);
  const hasAny = pre != null || post != null || delta != null;
  return { pre, post, delta, isWf, hasAny };
}

export function shouldShowBagWeightSummary(row) {
  const { isWf, hasAny } = getBagWeightParts(row);
  if (hasAny) return true;
  if (!isWf) return false;
  const status = String(row?.at_vendor_status || row?.facility_status || "").toLowerCase();
  return status === "completed";
}
