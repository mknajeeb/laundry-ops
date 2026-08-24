"""Management Rinse WF — Review list + one-bag detail (summary first).

Categories (mutually exclusive for Specialty vs Missing; Split Order Review is
a separate canonical-split queue):

  missing_from_portal
      DISAPPEARED_WITHOUT_COMPLETION
      (and not also specialty-bulk when both present — specialty wins)

  specialty_items
      WF_BULK_WORKITEM_REVIEW and all other WF review reasons
      (operational specialty / quality / weight / manager-sent, etc.)

  split_order_review
      Canonical split REVIEW_REQUIRED (marker/load contradiction). Independent
      of DISAPPEARED_WITHOUT_COMPLETION and specialty queues.

Precedence when a bag has both DISAPPEARED and specialty-bulk:
  → specialty_items (manager must resolve specialty workitems)

List path: day-bag summaries + optional bulk lines for specialty qty.
Detail path: build_drilldown(include_details=True) for ONE bag — scans on demand.
Weights come from the canonical current-cycle resolver (via drilldown detail).
"""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping

from backend.rinse_bag_completion import normalize_bag_id
from backend.rinse_current_cycle_weight import authoritative_evidence_pre_lbs
from backend.rinse_veewash_workload import (
    REASON_DISAPPEARED_WITHOUT_COMPLETION,
    REASON_WF_BULK_WORKITEM_REVIEW,
)

def _canonical_review_weights(
    cursor,
    organization_id: int,
    selected_date_et: date,
    bag_ids: list[str],
) -> dict[str, dict[str, Any]]:
    """Batch PRE/POST from the shared current-cycle resolver (never day_bag snap)."""
    ids = [normalize_bag_id(b) for b in bag_ids if normalize_bag_id(b)]
    if not ids:
        return {}
    from backend.rinse_veewash_review import load_bag_weight_map

    return load_bag_weight_map(
        cursor,
        organization_id,
        ids,
        selected_date_et=selected_date_et,
    )


def _merge_review_weight_fields(
    bag: dict[str, Any],
    weights: dict[str, Any] | None,
) -> None:
    """Overlay authoritative PRE/POST; PRE stays null when no PRE evidence."""
    evidence_pre = authoritative_evidence_pre_lbs(weights or {})
    bag["evidence_pre_weight_lbs"] = evidence_pre
    bag["pre_weight_lbs"] = evidence_pre
    if not weights:
        return
    bag["pre_weight_event_id"] = weights.get("pre_weight_event_id")
    post = weights.get("post_weight_lbs")
    if post is not None or weights.get("post_weight_event_exists"):
        bag["post_weight_lbs"] = post
        bag["post_weight_value"] = weights.get("post_weight_value", post)
        bag["post_weight_event_exists"] = weights.get("post_weight_event_exists")
    bag["pre_weight_at"] = weights.get("pre_weight_at")
    bag["post_weight_at"] = weights.get("post_weight_at")
    bag["completion_employee"] = bag.get("completion_employee") or weights.get(
        "post_weight_employee"
    )


CATEGORY_SPECIALTY = "specialty_items"
CATEGORY_MISSING_PORTAL = "missing_from_portal"
CATEGORY_SPLIT_ORDER = "split_order_review"

# Explicit reason → category. Anything else in Review Required → specialty_items.
MISSING_FROM_PORTAL_REASONS = frozenset(
    {
        REASON_DISAPPEARED_WITHOUT_COMPLETION,
    }
)

SPECIALTY_ITEMS_REASONS = frozenset(
    {
        REASON_WF_BULK_WORKITEM_REVIEW,
        "WF_ZERO_OR_MISSING_POST_WEIGHT",
        "WF_ZERO_OR_MISSING_WEIGHT",
        "COMPLETED_WITHOUT_RECOGNIZED_ENTRY",
        "SERVICE_CLASSIFICATION_MISMATCH",
        "MANAGER_SENT_FOR_REVIEW",
        "COMPLETION_DETAILS_MISSING",
        "MISSING_PRE_EVIDENCE",
        "SCAN_CHRONOLOGY_STALE",
    }
)

REASON_CATEGORY_MAP: dict[str, str] = {
    **{code: CATEGORY_MISSING_PORTAL for code in MISSING_FROM_PORTAL_REASONS},
    **{code: CATEGORY_SPECIALTY for code in SPECIALTY_ITEMS_REASONS},
    "SPLIT_MARKED_BUT_SECOND_WASHER_NOT_FOUND": CATEGORY_SPLIT_ORDER,
    "MULTIPLE_WASHERS_WITHOUT_SPLIT_MARKER": CATEGORY_SPLIT_ORDER,
    "SPLIT_EVIDENCE_INCOMPLETE_AT_DISAPPEARANCE": CATEGORY_SPLIT_ORDER,
}


def _split_eval_as_of_day(
    cursor,
    organization_id: int,
    selected_date_et: date,
    bag_ids: list[str] | tuple[str, ...],
    *,
    slim_events: bool = False,
):
    """Evaluate splits with scan evidence truncated to end of selected_date_et ET.

    Manager decisions are always for ``shift_date_et = selected_date_et`` only.
    Prefer persisted headline ``specialty_metrics.split_review`` when present;
    this live path is the as-of-day fallback for historical / closed days.
    """
    from backend.rinse_wf_canonical_split import evaluate_day_wf_splits

    return evaluate_day_wf_splits(
        cursor,
        organization_id,
        selected_date_et,
        bag_ids,
        slim_events=slim_events,
        truncate_to_selected_day=True,
    )


def category_for_reason_codes(codes: list[str] | tuple[str, ...] | None) -> str:
    """Deterministic single category for a bag's reason codes (no double-count)."""
    normalized = [str(c) for c in (codes or []) if c]
    code_set = set(normalized)
    has_specialty_bulk = REASON_WF_BULK_WORKITEM_REVIEW in code_set
    has_missing = bool(code_set & MISSING_FROM_PORTAL_REASONS)
    # Specialty bulk wins over disappeared when both apply.
    if has_specialty_bulk:
        return CATEGORY_SPECIALTY
    if has_missing and not (code_set & SPECIALTY_ITEMS_REASONS):
        return CATEGORY_MISSING_PORTAL
    if has_missing and not has_specialty_bulk:
        # Disappeared plus other non-bulk operational reasons → missing portal
        # only when no specialty-items reason besides disappeared.
        other = code_set - MISSING_FROM_PORTAL_REASONS
        if not other:
            return CATEGORY_MISSING_PORTAL
    if code_set & SPECIALTY_ITEMS_REASONS:
        return CATEGORY_SPECIALTY
    if has_missing:
        return CATEGORY_MISSING_PORTAL
    # Unknown review code → specialty working queue (not employee portal blame).
    return CATEGORY_SPECIALTY


def specialty_review_is_unresolved(
    codes: list[str] | tuple[str, ...] | None,
    *,
    bulk_cleared: bool | None = None,
) -> bool:
    """True when Specialty Items review is still open.

    Independent of day-bag ``completed`` / ``pending`` status.
    A bag leaves active Specialty Review only when specialty itself is resolved
    (reason codes cleared / bulk cleared) — never merely because status=completed.
    """
    normalized = [str(c) for c in (codes or []) if c]
    if bulk_cleared is True:
        normalized = [
            c for c in normalized if c != REASON_WF_BULK_WORKITEM_REVIEW
        ]
    if not normalized:
        return False
    return category_for_reason_codes(normalized) == CATEGORY_SPECIALTY


def specialty_review_is_resolved(
    codes: list[str] | tuple[str, ...] | None,
    *,
    bulk_cleared: bool | None = None,
) -> bool:
    """Inverse of ``specialty_review_is_unresolved`` (canonical specialty exit)."""
    return not specialty_review_is_unresolved(codes, bulk_cleared=bulk_cleared)


def _headline_maps(headline: Mapping[str, Any] | None) -> tuple[dict, dict]:
    hl = headline or {}
    by_reason = hl.get("review_by_reason") if isinstance(hl.get("review_by_reason"), dict) else {}
    by_bag = (
        hl.get("review_reasons_by_bag")
        if isinstance(hl.get("review_reasons_by_bag"), dict)
        else {}
    )
    return dict(by_reason), dict(by_bag)


def _bag_codes(by_bag: Mapping[str, Any], by_reason: Mapping[str, Any], bag_id: str) -> list[str]:
    bid = normalize_bag_id(bag_id)
    raw = by_bag.get(bid) or by_bag.get(str(bag_id)) or []
    if isinstance(raw, (list, tuple)) and raw:
        return [str(c) for c in raw if c]
    codes: list[str] = []
    for code, ids in by_reason.items():
        if isinstance(ids, (list, tuple)) and (
            bid in ids or str(bag_id) in ids or bag_id in ids
        ):
            codes.append(str(code))
    return codes


_WF_MEMBERSHIP_BAG_ID_BUCKETS = (
    "review_required",
    "pending",
    "completed",
    "new_today",
    "carryover",
    "disappeared_without_completion",
    "missing_workload_entry_scan",
    "completed_awaiting_workload_assignment",
)


def _wf_membership_ids(headline: Mapping[str, Any] | None) -> set[str]:
    """Canonical WF day membership from segments.wf bag_ids (all status buckets).

    Used to keep Management Rinse WF review queues service-isolated. HD bags that
    only appear in org-wide review_by_reason must never enter WF review surfaces.
    """
    segs = (headline or {}).get("segments") or {}
    bags_map = ((segs.get("wf") or {}).get("bag_ids") or {})
    if not isinstance(bags_map, dict):
        return set()
    out: set[str] = set()
    for bucket in _WF_MEMBERSHIP_BAG_ID_BUCKETS:
        for raw in bags_map.get(bucket) or []:
            key = normalize_bag_id(raw)
            if key:
                out.add(key)
    # Also accept any other bag_ids lists under wf (forward-compatible).
    for vals in bags_map.values():
        if not isinstance(vals, (list, tuple)):
            continue
        for raw in vals:
            key = normalize_bag_id(raw)
            if key:
                out.add(key)
    return out


def _service_is_wf(row: Mapping[str, Any] | None) -> bool:
    """True when a day-bag row is WF.

    Blank service does not prove non-WF (legacy rows); only an explicit non-WF
    service_type excludes a bag from WF review surfaces.
    """
    svc = str((row or {}).get("service_type") or "").strip().upper()
    if not svc:
        return True
    return svc == "WF"


def _wf_review_ids(headline: Mapping[str, Any] | None) -> list[str]:
    """WF Review Required IDs only — never admit HD via org-wide reason maps.

    Source of truth: ``segments.wf.bag_ids.review_required``.

    When that list is empty, return empty — do **not** fall back to org-wide
    ``review_by_reason`` / ``review_reasons_by_bag``. Those maps include HD bags
    (e.g. DISAPPEARED_WITHOUT_COMPLETION) and leaked them into WF Missing From
    Portal. Specialty Items for completed-but-unresolved WF bags still come from
    ``_specialty_candidate_ids`` via WF membership ∩ specialty reasons.
    """
    segs = (headline or {}).get("segments") or {}
    seg = segs.get("wf") or {}
    ids = list(((seg.get("bag_ids") or {}).get("review_required")) or [])
    return [normalize_bag_id(b) for b in ids if normalize_bag_id(b)]


def _specialty_candidate_ids(
    headline: Mapping[str, Any] | None,
    by_reason: Mapping[str, Any],
    by_bag: Mapping[str, Any],
) -> list[str]:
    """Review-required IDs plus any WF bag with unresolved specialty reasons.

    Completed status alone must not exclude a bag that still has unresolved
    specialty review (e.g. WF_BULK_WORKITEM_REVIEW still on the bag).

    HD bags in org-wide reason maps are excluded — Specialty Items is WF-only.
    """
    segs = (headline or {}).get("segments") or {}
    enforce_wf = "wf" in segs
    wf_members = _wf_membership_ids(headline) if enforce_wf else set()
    seen: set[str] = set()
    out: list[str] = []

    def _add(raw: Any) -> None:
        key = normalize_bag_id(raw)
        if not key or key in seen:
            return
        if enforce_wf and key not in wf_members:
            return
        seen.add(key)
        out.append(key)

    for bid in _wf_review_ids(headline):
        _add(bid)
    for bid, codes in (by_bag or {}).items():
        if specialty_review_is_unresolved(codes if isinstance(codes, (list, tuple)) else []):
            _add(bid)
    for code, ids in (by_reason or {}).items():
        if category_for_reason_codes([str(code)]) != CATEGORY_SPECIALTY:
            continue
        if not isinstance(ids, (list, tuple)):
            continue
        for bid in ids:
            _add(bid)
    return out


def split_review_categories(
    headline: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Partition into Specialty Items vs Missing From Portal (+ split review ids).

    Specialty Items = unresolved specialty-review orders (not \"completed\").
    A completed bag with unresolved specialty review remains in Specialty Items.
    A completed bag with resolved specialty review does not.

    Split Order Review comes from specialty_metrics.split_review (canonical
    evaluator) and is independent of Specialty / Missing queues.
    """
    by_reason, by_bag = _headline_maps(headline)
    review_ids = _wf_review_ids(headline)
    review_set = set(review_ids)
    candidates = _specialty_candidate_ids(headline, by_reason, by_bag)
    specialty: list[str] = []
    missing: list[str] = []
    for bid in candidates:
        codes = _bag_codes(by_bag, by_reason, bid)
        if specialty_review_is_unresolved(codes):
            specialty.append(bid)
            continue
        # Missing-from-portal only while still in the Review Required population.
        if bid in review_set and category_for_reason_codes(codes) == CATEGORY_MISSING_PORTAL:
            missing.append(bid)

    split_ids: list[str] = []
    root = (headline or {}).get("specialty_metrics") or {}
    wf_pack = root.get("wf") or root.get("all") or {}
    for key in ("split_review",):
        pack = wf_pack.get(key) if isinstance(wf_pack, dict) else None
        if isinstance(pack, dict):
            for bid in pack.get("order_ids") or []:
                nb = normalize_bag_id(bid)
                if nb and nb not in split_ids:
                    split_ids.append(nb)
            for order in pack.get("orders") or []:
                if isinstance(order, Mapping):
                    nb = normalize_bag_id(order.get("bag_id"))
                    if nb and nb not in split_ids:
                        split_ids.append(nb)

    return {
        CATEGORY_SPECIALTY: specialty,
        CATEGORY_MISSING_PORTAL: missing,
        CATEGORY_SPLIT_ORDER: split_ids,
        "counts": {
            CATEGORY_SPECIALTY: len(specialty),
            CATEGORY_MISSING_PORTAL: len(missing),
            CATEGORY_SPLIT_ORDER: len(split_ids),
            "review_required": len(review_ids),
        },
        "reason_category_map": dict(REASON_CATEGORY_MAP),
        "precedence": (
            "Specialty Items = unresolved specialty review (independent of completed); "
            "WF_BULK_WORKITEM_REVIEW → specialty_items; "
            "DISAPPEARED_WITHOUT_COMPLETION alone → missing_from_portal; "
            "canonical split REVIEW_REQUIRED → split_order_review (separate); "
            "resolved specialty leaves specialty_items; no double-count between "
            "specialty and missing; "
            "WF review queues intersect segments.wf membership only — HD review "
            "reasons never enter WF Missing/Specialty via review_by_reason fallback"
        ),
        "employee_performance_hint": {
            CATEGORY_SPECIALTY: "may_associate_with_employee_or_resource",
            CATEGORY_MISSING_PORTAL: "not_automatic_employee_quality_issue",
            CATEGORY_SPLIT_ORDER: "operational_split_contradiction_not_auto_employee_quality",
        },
    }


def specialty_review_membership_ids(
    headline: Mapping[str, Any] | None,
) -> list[str]:
    """Canonical unresolved Specialty Review bag IDs (summary + drawer share this)."""
    return list(split_review_categories(headline).get(CATEGORY_SPECIALTY) or [])


def review_category_count_payload(
    headline: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Scalar Review counts from the same membership as the Specialty drawer list.

    Never invent specialty_items from day-level review_required_count (that total
    includes HD and bags without specialty reason codes).
    """
    split = split_review_categories(headline)
    counts = split["counts"]
    return {
        "split_available": True,
        "review_required": int(counts.get("review_required") or 0),
        "specialty_items": int(counts.get(CATEGORY_SPECIALTY) or 0),
        "missing_from_portal": int(counts.get(CATEGORY_MISSING_PORTAL) or 0),
        "split_order_review": int(counts.get(CATEGORY_SPLIT_ORDER) or 0),
        "reason_category_map": split["reason_category_map"],
        "precedence": split["precedence"],
        "employee_performance_hint": split["employee_performance_hint"],
        "_membership": {
            CATEGORY_SPECIALTY: list(split.get(CATEGORY_SPECIALTY) or []),
            CATEGORY_MISSING_PORTAL: list(split.get(CATEGORY_MISSING_PORTAL) or []),
            CATEGORY_SPLIT_ORDER: list(split.get(CATEGORY_SPLIT_ORDER) or []),
        },
    }


def _bag_is_rush(row: Mapping[str, Any] | None) -> bool:
    snap = (row or {}).get("bag_snapshot") or {}
    flag = str(
        snap.get("rush_flag") or (row or {}).get("rush_status") or ""
    ).strip().upper()
    return flag in ("RUSH", "1", "TRUE", "YES")


def enrich_review_counts_by_rush(
    cursor,
    organization_id: int,
    selected_date_et: date,
    headline: Mapping[str, Any] | None,
    base: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Attach by_rush scalars using the same membership + day-bag rush flags as the list."""
    from backend.rinse_veewash_shift_day import load_day_bags_by_ids

    out = dict(base or {})
    membership = dict(out.pop("_membership", None) or {})
    if not membership:
        membership = dict(
            (review_category_count_payload(headline).get("_membership") or {})
        )
    specialty = list(membership.get(CATEGORY_SPECIALTY) or [])
    missing = list(membership.get(CATEGORY_MISSING_PORTAL) or [])
    split_ids = list(membership.get(CATEGORY_SPLIT_ORDER) or [])
    all_ids = list(dict.fromkeys([*specialty, *missing, *split_ids]))
    rush_ids: set[str] = set()
    non_rush_ids: set[str] = set()
    if all_ids:
        rows = load_day_bags_by_ids(
            cursor, organization_id, selected_date_et, all_ids, status_only=False
        )
        for row in rows:
            bid = normalize_bag_id(row.get("bag_id"))
            if not bid:
                continue
            if _bag_is_rush(row):
                rush_ids.add(bid)
            else:
                non_rush_ids.add(bid)

    def _pack(want: set[str] | None) -> dict[str, int]:
        if want is None:
            return {
                "specialty_items": len(specialty),
                "missing_from_portal": len(missing),
                "split_order_review": len(split_ids),
                "review_required": int(out.get("review_required") or 0),
            }
        spec_n = sum(1 for b in specialty if b in want)
        miss_n = sum(1 for b in missing if b in want)
        split_n = sum(1 for b in split_ids if b in want)
        return {
            "specialty_items": spec_n,
            "missing_from_portal": miss_n,
            "split_order_review": split_n,
            "review_required": spec_n + miss_n,
        }

    out["by_rush"] = {
        "all": _pack(None),
        "rush": _pack(rush_ids),
        "non_rush": _pack(non_rush_ids),
    }
    return out


def build_management_review_summary(
    cursor,
    organization_id: int,
    selected_date_et: date,
) -> dict[str, Any]:
    """Compact Review category counts (no bag arrays) for the Rinse WF page."""
    from backend.rinse_veewash_shift_day import get_day_record, summary_from_day_record

    day = get_day_record(cursor, organization_id, selected_date_et)
    headline = summary_from_day_record(day) or {}
    base = review_category_count_payload(headline)
    membership = base.pop("_membership", {})
    enriched = enrich_review_counts_by_rush(
        cursor, organization_id, selected_date_et, headline, {**base, "_membership": membership}
    )
    return {
        "date_et": selected_date_et.isoformat(),
        **{k: enriched[k] for k in (
            "split_available",
            "review_required",
            "specialty_items",
            "missing_from_portal",
            "split_order_review",
            "reason_category_map",
            "precedence",
            "employee_performance_hint",
            "by_rush",
        ) if k in enriched},
        "categories": {
            CATEGORY_SPECIALTY: {
                "id": CATEGORY_SPECIALTY,
                "label": "Specialty Items",
                "count": enriched["specialty_items"],
            },
            CATEGORY_MISSING_PORTAL: {
                "id": CATEGORY_MISSING_PORTAL,
                "label": "Missing From Portal",
                "count": enriched["missing_from_portal"],
            },
            CATEGORY_SPLIT_ORDER: {
                "id": CATEGORY_SPLIT_ORDER,
                "label": "Split Order Review",
                "count": enriched["split_order_review"],
            },
        },
    }


def _specialty_qty_from_lines(lines: list | None) -> dict[str, Any]:
    comforter_qty = 0.0
    bath_qty = 0.0
    other: list[dict[str, Any]] = []
    for line in lines or []:
        if not isinstance(line, Mapping):
            continue
        name = str(
            line.get("workitem_name_snapshot") or line.get("workitem_name") or ""
        ).strip()
        try:
            q = float(line.get("quantity") or 0)
        except (TypeError, ValueError):
            q = 0.0
        lower = name.lower()
        if "comfort" in lower:
            comforter_qty += q
        elif "bath" in lower:
            bath_qty += q
        elif name:
            other.append({"name": name, "quantity": q})
    return {
        "comforter_quantity": comforter_qty if comforter_qty else 0,
        "bath_mat_quantity": bath_qty if bath_qty else 0,
        "other_specialty_lines": other,
        "specialty_quantity": comforter_qty
        if comforter_qty
        else (bath_qty if bath_qty else None),
        "specialty_item_class": (
            "comforter"
            if comforter_qty
            else ("bath_mat" if bath_qty else None)
        ),
    }


def _short_reason(codes: list[str], category: str) -> str:
    if category == CATEGORY_MISSING_PORTAL:
        return "Missing from portal"
    if category == CATEGORY_SPLIT_ORDER:
        if "SPLIT_MARKED_BUT_SECOND_WASHER_NOT_FOUND" in codes:
            return "Split marked · second washer not found"
        if "MULTIPLE_WASHERS_WITHOUT_SPLIT_MARKER" in codes:
            return "Multiple washers · no split marker"
        if "SPLIT_EVIDENCE_INCOMPLETE_AT_DISAPPEARANCE" in codes:
            return "Split evidence incomplete at disappearance"
        return "Split order review"
    if REASON_WF_BULK_WORKITEM_REVIEW in codes:
        return "Specialty review"
    if codes:
        return str(codes[0]).replace("_", " ").title()
    return "Specialty review"


def review_drawer_section_flags(codes: list[str] | tuple[str, ...] | None) -> dict[str, bool]:
    """Which compact drawer action sections apply (multi-reason bags can have both)."""
    code_set = {str(c) for c in (codes or []) if c}
    return {
        "has_specialty_bulk": REASON_WF_BULK_WORKITEM_REVIEW in code_set,
        "has_missing_portal": bool(code_set & MISSING_FROM_PORTAL_REASONS),
    }


def _short_specialty_summary(qty_info: Mapping[str, Any]) -> str | None:
    c = qty_info.get("comforter_quantity") or 0
    b = qty_info.get("bath_mat_quantity") or 0
    parts = []
    if c:
        parts.append(f"{int(c) if float(c) == int(c) else c} Comforter{'s' if c != 1 else ''}")
    if b:
        parts.append(f"{int(b) if float(b) == int(b) else b} Bath Mat{'s' if b != 1 else ''}")
    for line in qty_info.get("other_specialty_lines") or []:
        q = line.get("quantity") or 0
        n = line.get("name") or "Item"
        parts.append(f"{int(q) if float(q) == int(q) else q} {n}")
    return " · ".join(parts) if parts else None


def build_management_review_list(
    cursor,
    organization_id: int,
    selected_date_et: date,
    *,
    category: str,
    rush_filter: str = "all",
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    """Lightweight Review list for one category — no scans / chronology."""
    import time

    from backend.rinse_bulk_workitems import load_bag_bulk_lines
    from backend.rinse_veewash_shift_day import (
        get_day_record,
        load_day_bags_by_ids,
        summary_from_day_record,
    )

    t0 = time.perf_counter()
    cat = str(category or "").strip().lower()
    if cat not in (CATEGORY_SPECIALTY, CATEGORY_MISSING_PORTAL, CATEGORY_SPLIT_ORDER):
        return {
            "ok": False,
            "error": "invalid_category",
            "message": (
                "category must be specialty_items, missing_from_portal, "
                "or split_order_review"
            ),
        }

    day = get_day_record(cursor, organization_id, selected_date_et)
    headline = summary_from_day_record(day) or {}
    split = split_review_categories(headline)
    if cat == CATEGORY_SPECIALTY:
        bag_ids = specialty_review_membership_ids(headline)
    else:
        bag_ids = list(split.get(cat) or [])
    by_reason, by_bag = _headline_maps(headline)

    # Post-reset / stale-headline defense: discover unresolved specialty from day bags
    # when headline review_reasons_by_bag was not yet synced from persisted codes.
    if cat == CATEGORY_SPECIALTY and not bag_ids:
        from backend.rinse_veewash_shift_day import load_day_bags

        discovered: list[str] = []
        for row in load_day_bags(cursor, organization_id, selected_date_et) or []:
            if not _service_is_wf(row):
                continue
            bid = normalize_bag_id(row.get("bag_id"))
            if not bid:
                continue
            codes = list(row.get("review_reason_codes") or [])
            if specialty_review_is_unresolved(codes):
                discovered.append(bid)
        bag_ids = discovered

    # Heal membership from day_bag rows — NEVER drop Specialty Items solely
    # because status=completed. Specialty exits only when specialty is resolved.
    # Always drop non-WF day-bag rows (service isolation defense in depth).
    if bag_ids and cat != CATEGORY_SPLIT_ORDER:
        # Need review_reason_codes for specialty resolution (not status_only).
        status_rows = load_day_bags_by_ids(
            cursor, organization_id, selected_date_et, bag_ids, status_only=False
        )
        by_status = {
            normalize_bag_id(r.get("bag_id")): r for r in status_rows
        }
        still: set[str] = set()
        for bid in bag_ids:
            row = by_status.get(bid) or {}
            if row and not _service_is_wf(row):
                # Explicit HD (or other non-WF) day-bag must not appear on WF queues.
                continue
            status = str(row.get("effective_status") or "").strip().lower()
            codes = list(row.get("review_reason_codes") or []) or _bag_codes(
                by_bag, by_reason, bid
            )
            if cat == CATEGORY_SPECIALTY:
                if specialty_review_is_unresolved(codes):
                    still.add(bid)
                continue
            # Missing From Portal: still requires review_required day-bag status.
            if status == "review_required":
                still.add(bid)
        bag_ids = [b for b in bag_ids if b in still]
    elif cat == CATEGORY_SPLIT_ORDER:
        # Prefer persisted specialty_metrics.split_review, then as-of-day filter.
        # Live fallback when pack empty. Never let D+1 scans create day-D review.
        from backend.rinse_wf_canonical_split import STATE_REVIEW_REQUIRED

        if not bag_ids:
            member = _wf_review_ids(headline)
            segs = (headline or {}).get("segments") or {}
            wf_seg = segs.get("wf") or {}
            bags_map = wf_seg.get("bag_ids") or {}
            for bucket in (
                "completed",
                "pending",
                "review_required",
                "carried_forward",
                "new_today",
                "carryover",
            ):
                for bid in bags_map.get(bucket) or []:
                    nb = normalize_bag_id(bid)
                    if nb and nb not in member:
                        member.append(nb)
            bag_ids = list(member)
        if bag_ids:
            evaluations = _split_eval_as_of_day(
                cursor, organization_id, selected_date_et, bag_ids
            )
            bag_ids = [
                bid
                for bid in bag_ids
                if (evaluations.get(bid) or {}).get("state") == STATE_REVIEW_REQUIRED
            ]

    rush = str(rush_filter or "all").strip().lower()
    if rush in ("rush", "non_rush", "non-rush"):
        want_rush = rush in ("rush",)
        filtered: list[str] = []
        if bag_ids:
            rows = load_day_bags_by_ids(
                cursor, organization_id, selected_date_et, bag_ids, status_only=False
            )
            by_id = {normalize_bag_id(r.get("bag_id")): r for r in rows}
            for bid in bag_ids:
                row = by_id.get(bid) or {}
                snap = row.get("bag_snapshot") or {}
                flag = str(
                    snap.get("rush_flag") or row.get("rush_status") or ""
                ).upper()
                is_rush = flag in ("RUSH", "1", "TRUE", "YES")
                if is_rush == want_rush:
                    filtered.append(bid)
        bag_ids = filtered

    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or 50), 100))
    total = len(bag_ids)
    start = (page - 1) * page_size
    page_ids = bag_ids[start : start + page_size]

    # Counts for the active category+rush scope must match drawer total.
    scoped_counts = dict(split["counts"])
    scoped_counts[cat] = total

    rows = (
        load_day_bags_by_ids(cursor, organization_id, selected_date_et, page_ids)
        if page_ids
        else []
    )
    by_id = {normalize_bag_id(r.get("bag_id")): r for r in rows}
    by_reason, by_bag = _headline_maps(headline)

    bulk_lines: dict = {}
    weight_map = _canonical_review_weights(
        cursor, organization_id, selected_date_et, page_ids
    )
    if cat == CATEGORY_SPECIALTY and page_ids:
        # One batch query for specialty quantities — not scans, not N+1.
        bulk_lines = load_bag_bulk_lines(
            cursor, organization_id, selected_date_et, page_ids
        )

    split_evals: dict[str, dict[str, Any]] = {}
    if cat == CATEGORY_SPLIT_ORDER and page_ids:
        from backend.rinse_wf_canonical_split import evaluation_to_jsonable

        split_evals = {
            bid: evaluation_to_jsonable(ev)
            for bid, ev in _split_eval_as_of_day(
                cursor, organization_id, selected_date_et, page_ids
            ).items()
        }
        # Prefer live evaluation order when headline pack was empty.
        if not bag_ids:
            bag_ids = list(split_evals.keys())

    # Enrich from headline split_review orders when available.
    split_order_meta: dict[str, dict[str, Any]] = {}
    root = (headline or {}).get("specialty_metrics") or {}
    for svc in ("wf", "all"):
        pack = (root.get(svc) or {}).get("split_review") or {}
        for order in pack.get("orders") or []:
            if isinstance(order, Mapping):
                nb = normalize_bag_id(order.get("bag_id"))
                if nb:
                    split_order_meta[nb] = dict(order)

    bags_out: list[dict[str, Any]] = []
    for bid in page_ids:
        row = by_id.get(bid) or {}
        snap = dict(row.get("bag_snapshot") or {})
        codes = list(
            row.get("review_reason_codes")
            or _bag_codes(by_bag, by_reason, bid)
            or snap.get("reason_codes")
            or []
        )
        codes = [str(c) for c in codes if c]
        qty_info = _specialty_qty_from_lines(bulk_lines.get(bid) or snap.get("bulk_workitems"))
        sev = split_evals.get(bid) or {}
        smeta = split_order_meta.get(bid) or {}
        if cat == CATEGORY_SPLIT_ORDER:
            reason = sev.get("review_reason") or smeta.get("review_reason")
            if reason and reason not in codes:
                codes = [str(reason)] + codes
        flags = review_drawer_section_flags(codes)
        completion_employee = (
            snap.get("completed_by") or row.get("canonical_completion_employee")
        )
        completion_at = (
            snap.get("completion_at") or row.get("canonical_completion_timestamp")
        )
        bag_row = {
                "bag_id": bid,
                "customer_name": snap.get("customer_name")
                or row.get("customer_name")
                or smeta.get("customer_name"),
                "service_type": snap.get("service_type") or row.get("service_type"),
                "rush_flag": snap.get("rush_flag")
                or row.get("rush_status")
                or smeta.get("rush"),
                "category": cat,
                "reason_codes": codes,
                "short_reason": _short_reason(codes, cat),
                "specialty_summary": _short_specialty_summary(qty_info),
                "comforter_quantity": qty_info.get("comforter_quantity") or 0,
                "bath_mat_quantity": qty_info.get("bath_mat_quantity") or 0,
                "specialty_quantity": qty_info.get("specialty_quantity"),
                "specialty_item_class": qty_info.get("specialty_item_class"),
                "has_specialty_bulk": flags["has_specialty_bulk"],
                "has_missing_portal": flags["has_missing_portal"],
                "employee": (
                    sev.get("split_marker_employee")
                    or snap.get("completed_by")
                    or row.get("canonical_completion_employee")
                    or snap.get("pre_weight_employee")
                    or snap.get("post_weight_employee")
                ),
                "completion_employee": completion_employee,
                "completion_at": completion_at,
                "completed_by": completion_employee,
                "pre_weight_lbs": None,
                "evidence_pre_weight_lbs": None,
                "pre_weight_at": snap.get("pre_weight_at"),
                "post_weight_lbs": snap.get("post_weight_lbs", row.get("post_weight_lbs")),
                "post_weight_at": snap.get("post_weight_at"),
                "relevant_time": (
                    sev.get("close_event_at")
                    or sev.get("split_marker_at")
                    or snap.get("pre_weight_at")
                    or snap.get("completion_at")
                    or row.get("canonical_completion_timestamp")
                    or row.get("workload_entry_timestamp")
                ),
                "dashboard_status": snap.get("outcome") or row.get("effective_status"),
                "manager_edit_version": int(row.get("manager_edit_version") or 0),
                "updated_at": row.get("updated_at"),
                "day_bag_updated_at": row.get("updated_at"),
                "employee_performance_eligible": cat == CATEGORY_SPECIALTY,
                "split_marker_present": sev.get("split_marker_present")
                if sev
                else smeta.get("split_marker_present"),
                "washer_load_count": sev.get("washer_load_count")
                if sev
                else smeta.get("washer_load_count"),
                "washer_racks": sev.get("washer_racks")
                if sev
                else smeta.get("washer_racks"),
                "close_event_purpose": sev.get("close_event_purpose")
                if sev
                else smeta.get("close_event_purpose"),
                "split_state": sev.get("state") if sev else smeta.get("split_state"),
                "review_reason": sev.get("review_reason")
                if sev
                else smeta.get("review_reason"),
                "canonical_split": sev.get("canonical_split")
                if sev
                else smeta.get("canonical_split"),
        }
        _merge_review_weight_fields(bag_row, weight_map.get(bid))
        bags_out.append(bag_row)

    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 1)
    return {
        "ok": True,
        "date_et": selected_date_et.isoformat(),
        "category": cat,
        "counts": scoped_counts,
        "counts_all": split["counts"],
        "bags": bags_out,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_more": start + page_size < total,
        },
        "reason_category_map": split["reason_category_map"],
        "precedence": split["precedence"],
        "_meta": {
            "include_details": False,
            "scans_loaded": False,
            "action_metadata": False,
            "elapsed_ms": elapsed_ms,
            "source": "day_bags_light+optional_bulk_lines",
        },
    }


def build_management_review_detail(
    cursor,
    organization_id: int,
    selected_date_et: date,
    bag_id: str,
    *,
    include_scans: bool = False,
) -> dict[str, Any]:
    """Review modal core for ONE bag.

    Default ``include_scans=False`` so the modal can open on order / weights /
    specialty / actions without waiting on full scan chronology. Call
    ``build_management_review_scans`` (or pass include_scans=True) for scans.

    Weights: canonical load_bag_weight_map / current-cycle resolver via
    build_drilldown(include_details=True). No independent PRE/POST classifier.
    """
    import time

    from backend.rinse_veewash_step1_api import build_drilldown

    t0 = time.perf_counter()
    bid = normalize_bag_id(bag_id)
    if not bid:
        return {"ok": False, "error": "bag_id_required"}

    # bag_id forces a single-bag page regardless of metric membership — one
    # drilldown only (no review→completed→active_workload cascade).
    out = build_drilldown(
        cursor,
        organization_id,
        selected_date_et=selected_date_et,
        metric="review_required",
        service="wf",
        rush="all",
        bag_id=bid,
        page=1,
        page_size=1,
        include_details=True,
        include_scans=bool(include_scans),
        include_audits=False,
    )
    bags = list(out.get("bags") or [])
    if not bags:
        return {"ok": False, "error": "bag_not_found", "bag_id": bid}

    bag = dict(bags[0])
    codes = [str(c) for c in (bag.get("reason_codes") or []) if c]
    category = category_for_reason_codes(codes)
    qty_info = _specialty_qty_from_lines(bag.get("bulk_workitems"))
    bag.update(
        {
            "comforter_quantity": qty_info.get("comforter_quantity") or 0,
            "bath_mat_quantity": qty_info.get("bath_mat_quantity") or 0,
            "other_specialty_lines": qty_info.get("other_specialty_lines") or [],
            "specialty_quantity": qty_info.get("specialty_quantity")
            if qty_info.get("specialty_quantity") is not None
            else bag.get("specialty_quantity"),
            "specialty_item_class": qty_info.get("specialty_item_class")
            or bag.get("specialty_item_class"),
        }
    )
    # Explicit PRE/POST from canonical resolver fields already on bag — never alias.
    bag["weights"] = {
        "pre_weight_lbs": bag.get("evidence_pre_weight_lbs"),
        "pre_weight_at": bag.get("pre_weight_at"),
        "pre_weight_employee": bag.get("pre_weight_employee"),
        "post_weight_lbs": bag.get("post_weight_lbs"),
        "post_weight_value": bag.get("post_weight_value"),
        "post_weight_at": bag.get("post_weight_at"),
        "post_weight_employee": bag.get("post_weight_employee"),
        "post_weight_event_exists": bag.get("post_weight_event_exists"),
        "source": "canonical_current_cycle_weight_resolver",
    }
    bag["review_category"] = category
    bag["review_category_label"] = (
        "Missing From Portal"
        if category == CATEGORY_MISSING_PORTAL
        else (
            "Split Order Review"
            if category == CATEGORY_SPLIT_ORDER
            else "Specialty Items"
        )
    )
    # Canonical split evaluation only when this bag is (or may be) split review.
    needs_split = category == CATEGORY_SPLIT_ORDER or any(
        str(c).startswith("SPLIT_") or str(c) == "MULTIPLE_WASHERS_WITHOUT_SPLIT_MARKER"
        for c in codes
    )
    if needs_split:
        try:
            from backend.rinse_wf_canonical_split import evaluation_to_jsonable

            split_map = _split_eval_as_of_day(
                cursor, organization_id, selected_date_et, [bid]
            )
            sev = split_map.get(bid)
            if sev:
                bag["canonical_split_evaluation"] = evaluation_to_jsonable(sev)
                bag["split_marker_present"] = sev.get("split_marker_present")
                bag["washer_load_count"] = sev.get("washer_load_count")
                bag["washer_racks"] = sev.get("washer_racks")
                bag["split_state"] = sev.get("state")
                bag["canonical_split"] = sev.get("canonical_split")
                bag["review_reason"] = sev.get("review_reason")
                bag["close_event_purpose"] = sev.get("close_event_purpose")
                bag["close_event_at"] = (
                    sev.get("close_event_at").isoformat(sep=" ")
                    if hasattr(sev.get("close_event_at"), "isoformat")
                    else sev.get("close_event_at")
                )
                if sev.get("state") == "REVIEW_REQUIRED":
                    bag["review_category"] = CATEGORY_SPLIT_ORDER
                    bag["review_category_label"] = "Split Order Review"
                    category = CATEGORY_SPLIT_ORDER
        except Exception:
            pass
    bag["employee_performance_eligible"] = category == CATEGORY_SPECIALTY
    bag["evidence_pre_weight_lbs"] = authoritative_evidence_pre_lbs(bag)
    bag["pre_weight_lbs"] = bag["evidence_pre_weight_lbs"]
    bag["short_reason"] = _short_reason(
        list(bag.get("reason_codes") or codes), category
    )
    # Manager edit lock is ready — Review modal always loads full detail row.
    bag["_detailsLoaded"] = True

    portal_evidence = None
    if category == CATEGORY_MISSING_PORTAL:
        portal_evidence = {
            "portal_status": bag.get("portal_status"),
            "last_seen_at": bag.get("last_seen_at"),
            "reason_codes": list(bag.get("reason_codes") or codes),
            "explanation": (
                "Processing evidence exists, but the bag disappeared from portal "
                "presence without a recognized completion event."
            ),
        }

    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 1)
    return {
        "ok": True,
        "date_et": selected_date_et.isoformat(),
        "bag": bag,
        "portal_evidence": portal_evidence,
        "active_bulk_workitems": out.get("active_bulk_workitems") or [],
        "_meta": {
            "include_details": True,
            "scans_loaded": bool(include_scans),
            "audits_loaded": False,
            "elapsed_ms": elapsed_ms,
            "weight_source": "canonical_current_cycle_weight_resolver",
            "independent_pre_post_classifier": False,
            "source": "build_drilldown_include_details_core",
            "drilldown_timing_ms": out.get("timing_ms"),
        },
    }


def build_management_review_scans(
    cursor,
    organization_id: int,
    bag_id: str,
) -> dict[str, Any]:
    """Async scan chronology for ONE Review bag — does not reload core detail."""
    import time

    from backend.rinse_veewash_step1_api import load_scans_for_bags

    t0 = time.perf_counter()
    bid = normalize_bag_id(bag_id)
    if not bid:
        return {"ok": False, "error": "bag_id_required"}
    scans_map = load_scans_for_bags(cursor, organization_id, [bid])
    scans = list(scans_map.get(bid) or [])
    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 1)
    return {
        "ok": True,
        "bag_id": bid,
        "scans": scans,
        "_meta": {
            "scans_loaded": True,
            "elapsed_ms": elapsed_ms,
            "scan_count": len(scans),
            "source": "load_scans_for_bags",
        },
    }


def build_management_review_action(
    cursor,
    organization_id: int,
    selected_date_et: date,
    bag_id: str,
) -> dict[str, Any]:
    """Expand-only drawer action metadata for ONE bag.

    Lock version, weights, completion, bulk lines, and catalog — no scans,
    chronology, photos, or full drilldown payload.
    """
    import time

    from backend.rinse_bulk_workitems import (
        list_workitems,
        load_bag_bulk_lines,
        load_bulk_resolutions,
    )
    from backend.rinse_veewash_shift_day import load_day_bags_by_ids

    t0 = time.perf_counter()
    bid = normalize_bag_id(bag_id)
    if not bid:
        return {"ok": False, "error": "bag_id_required"}

    rows = load_day_bags_by_ids(cursor, organization_id, selected_date_et, [bid])
    if not rows:
        return {"ok": False, "error": "bag_not_found", "bag_id": bid}

    row = rows[0]
    snap = dict(row.get("bag_snapshot") or {})
    codes = [str(c) for c in (row.get("review_reason_codes") or snap.get("reason_codes") or []) if c]
    flags = review_drawer_section_flags(codes)
    category = category_for_reason_codes(codes)

    bulk_lines = load_bag_bulk_lines(
        cursor, organization_id, selected_date_et, [bid]
    ).get(bid) or []
    bulk_res = load_bulk_resolutions(
        cursor, organization_id, selected_date_et, [bid]
    ).get(bid)
    need_catalog = bool(flags["has_specialty_bulk"] or bulk_lines or bulk_res)
    catalog: list[dict[str, Any]] = []
    if need_catalog:
        catalog = list_workitems(cursor, organization_id, active_only=True)

    qty_info = _specialty_qty_from_lines(bulk_lines)
    completion_employee = snap.get("completed_by") or row.get("canonical_completion_employee")
    completion_at = snap.get("completion_at") or row.get("canonical_completion_timestamp")
    weight_map = _canonical_review_weights(cursor, organization_id, selected_date_et, [bid])
    weights = weight_map.get(bid) or {}

    bag = {
        "bag_id": bid,
        "customer_name": snap.get("customer_name") or row.get("customer_name"),
        "service_type": snap.get("service_type") or row.get("service_type") or "WF",
        "rush_flag": snap.get("rush_flag") or row.get("rush_status"),
        "reason_codes": codes,
        "short_reason": _short_reason(codes, category),
        "dashboard_status": snap.get("outcome") or row.get("effective_status"),
        "pre_weight_lbs": None,
        "post_weight_lbs": snap.get("post_weight_lbs", row.get("post_weight_lbs")),
        "post_weight_value": snap.get("post_weight_lbs", row.get("post_weight_lbs")),
        "pre_weight_at": snap.get("pre_weight_at"),
        "post_weight_at": snap.get("post_weight_at"),
        "completion_employee": completion_employee,
        "completion_at": completion_at,
        "completed_by": completion_employee,
        "canonical_completion_timestamp": completion_at,
        "canonical_completion_employee": completion_employee,
        "manager_edit_version": int(row.get("manager_edit_version") or 0),
        "updated_at": row.get("updated_at"),
        "day_bag_updated_at": row.get("updated_at"),
        "comforter_quantity": qty_info.get("comforter_quantity") or 0,
        "bath_mat_quantity": qty_info.get("bath_mat_quantity") or 0,
        "bulk_workitems": bulk_lines,
        "bulk_resolution": bulk_res,
        "has_specialty_bulk": flags["has_specialty_bulk"],
        "has_missing_portal": flags["has_missing_portal"],
        "review_category": category,
        "_detailsLoaded": True,
        "_actionMetaOnly": True,
    }
    _merge_review_weight_fields(bag, weights)
    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 1)
    return {
        "ok": True,
        "date_et": selected_date_et.isoformat(),
        "bag": bag,
        "active_bulk_workitems": catalog,
        "_meta": {
            "include_details": False,
            "scans_loaded": False,
            "action_metadata": True,
            "elapsed_ms": elapsed_ms,
            "source": "day_bag+optional_bulk_catalog",
        },
    }
