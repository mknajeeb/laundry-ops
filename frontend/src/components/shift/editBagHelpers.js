/**
 * Pure helpers for unified Edit Bag draft + drawer cache merge.
 */

export function parseWeightInput(raw) {
  const s = String(raw ?? "").trim();
  if (!s) return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

export function validateEditBagDraft({
  reason,
  noChargeable,
  noChargeReason,
  lines,
  isHd,
}) {
  if (!String(reason || "").trim()) return "Correction reason is required";
  if (noChargeable) {
    if ((lines || []).some((l) => Number(l.quantity) > 0)) {
      return "No Chargeable Bulk Items cannot coexist with positive quantities";
    }
    if (!String(noChargeReason || "").trim()) {
      return "No-charge reason is required";
    }
  }
  if (!isHd) {
    for (const l of lines || []) {
      const q = Number(l.quantity);
      if (!Number.isInteger(q) || q < 0) {
        return "Bulk quantities must be zero or positive integers";
      }
    }
  }
  return "";
}

export function buildEditBagPayloadDraft({
  draft,
  lines,
  isHd,
}) {
  return {
    service_type: String(draft.service_type || "WF").toUpperCase(),
    rush_flag: draft.rush_flag,
    entry_at: draft.entry_at || null,
    rack: draft.service_type === "HD" ? null : draft.rack,
    pre_weight_lbs: parseWeightInput(draft.pre_weight_lbs),
    post_weight_lbs: parseWeightInput(draft.post_weight_lbs),
    completion_at: draft.completion_at || null,
    completed_by: draft.completed_by || null,
    completion_employee: draft.completed_by || null,
    no_chargeable: Boolean(draft.no_chargeable),
    no_charge_reason: draft.no_chargeable ? draft.no_charge_reason : null,
    bulk_items:
      isHd || draft.no_chargeable
        ? []
        : (lines || [])
            .filter((l) => Number(l.quantity) > 0)
            .map((l) => ({ workitem_id: l.workitem_id, quantity: l.quantity })),
  };
}

/**
 * Merge a list-row (include_details=false) with prior detail / cache.
 * Prevents empty bulk_workitems from hiding persisted lines (42EN4J3VRB bug).
 */
export function mergeBagListRow({
  listBag,
  previousBag,
  cachedDetail,
  editingBagId,
  skipCacheMerge = false,
}) {
  if (!listBag?.bag_id) return listBag;
  const bagId = listBag.bag_id;

  if (editingBagId && bagId === editingBagId && previousBag) {
    return { ...listBag, ...previousBag, bag_id: bagId };
  }

  if (previousBag?._detailsLoaded) {
    return {
      ...listBag,
      ...previousBag,
      dashboard_status: listBag.dashboard_status ?? previousBag.dashboard_status,
      outcome: listBag.outcome ?? previousBag.outcome,
      reason_codes: listBag.reason_codes?.length
        ? listBag.reason_codes
        : previousBag.reason_codes,
      bulk_workitems: previousBag.bulk_workitems,
      scans: previousBag.scans,
      corrections: previousBag.corrections,
      _detailsLoaded: true,
    };
  }

  if (skipCacheMerge) return listBag;
  if (!cachedDetail) return listBag;

  return {
    ...listBag,
    ...cachedDetail,
    scans: cachedDetail.scans || [],
    corrections: cachedDetail.corrections || [],
    bulk_workitems:
      Array.isArray(cachedDetail.bulk_workitems) && cachedDetail.bulk_workitems.length
        ? cachedDetail.bulk_workitems
        : listBag.bulk_workitems,
    _detailsLoaded: true,
  };
}
