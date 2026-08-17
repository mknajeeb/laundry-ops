import { resolveStep1SegmentKeys } from "../shift/veewashStep1SegmentKeys";

function asInt(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

/** Review category scalars for the active rush chip (backend by_rush; no local formulas). */
export function pickReviewSummary(review, rushFilter = "all") {
  if (!review || typeof review !== "object") return null;
  const by = review.by_rush;
  if (rushFilter === "rush" && by?.rush) {
    return { ...review, ...by.rush };
  }
  if ((rushFilter === "non_rush" || rushFilter === "non-rush") && by?.non_rush) {
    return { ...review, ...by.non_rush };
  }
  if (by?.all) {
    return { ...review, ...by.all };
  }
  return review;
}

export function pickRinseSegments(rinse, rushFilter = "all") {
  const keys = resolveStep1SegmentKeys("wf", rushFilter);
  const segments = rinse?.segments || {};
  return {
    wfKey: keys.wf,
    hdKey: keys.hd,
    wf: segments[keys.wf] || null,
    hd: segments[keys.hd] || null,
  };
}

export function pickWfSpecialty(rinse, rushFilter = "all") {
  const spec = rinse?.specialty_metrics || {};
  // Do not silently fall back to All when a rush scope pack is missing.
  if (rushFilter === "rush") return spec.wf_rush || null;
  if (rushFilter === "non_rush") return spec.wf_non_rush || null;
  return spec.wf || spec.all || null;
}

/** Item quantity for a specialty pack row (COMFORTERS / BATH MATS cards). */
export function specialtyItemQty(row) {
  if (!row || typeof row !== "object") return 0;
  const raw = row.item_qty ?? row.total_quantity;
  const n = Number(raw);
  return Number.isFinite(n) ? n : 0;
}

/** Order count for a specialty pack row (subtitle / distinct from item qty). */
export function specialtyOrderCount(row) {
  if (!row || typeof row !== "object") return 0;
  return asInt(row.order_count ?? row.count);
}

export function wfHeadline(seg) {
  const review = asInt(seg?.exceptions?.review_required ?? seg?.exceptions?.total);
  const completed = asInt(seg?.completed);
  const pending = asInt(seg?.pending);
  const workload = asInt(
    seg?.total_workload ??
      seg?.active_workload ??
      completed + pending + review,
  );
  return { workload, completed, pending, review };
}

export function hdHeadline(seg, hdTotals) {
  const review = asInt(
    hdTotals?.review_required ?? seg?.exceptions?.review_required ?? seg?.exceptions?.total,
  );
  const completed = asInt(hdTotals?.completed ?? seg?.completed);
  const orders = asInt(
    hdTotals?.total_hd_orders ??
      seg?.total_workload ??
      seg?.active_workload ??
      completed + review,
  );
  const items = asInt(hdTotals?.total_items);
  const revenue = hdTotals?.hd_revenue ?? hdTotals?.total_revenue ?? 0;
  return { orders, completed, review, items, revenue };
}

export function pickWfWeights(rinse, rushFilter = "all") {
  const totals = rinse?.weight_totals || {};
  const byRush = totals.by_rush || {};
  const key = rushFilter === "rush" || rushFilter === "non_rush" ? rushFilter : "all";
  const scoped = byRush[key] || byRush.all || {};
  return {
    preLbs: scoped.pre_weight_lbs ?? scoped.pre_lbs ?? totals.pre_weight_lbs ?? totals.pre_lbs ?? null,
    postLbs:
      scoped.post_weight_lbs ?? scoped.post_lbs ?? totals.post_weight_lbs ?? totals.post_lbs ?? null,
    preBagCount: asInt(
      scoped.pre_weight_bag_count ?? totals.pre_weight_bag_count ?? 0,
    ),
    postBagCount: asInt(
      scoped.post_weight_bag_count ?? totals.post_weight_bag_count ?? 0,
    ),
    rushFilteringSupported: Boolean(totals.rush_filtering_supported),
    source: totals.source || null,
  };
}

export function pickWfSupplies(rinse, topLevelSupplies) {
  // Prefer the dedicated async supplies payload when the page provides it.
  if (topLevelSupplies != null) return topLevelSupplies;
  return rinse?.supplies || null;
}

export function wfIdentityLine({ workload, completed, pending, review }) {
  return `${workload} = ${completed} Completed + ${pending} Pending + ${review} Review`;
}

export function hdIdentityLine({ orders, completed, review }) {
  return `${orders} = ${completed} Completed + ${review} Review`;
}
