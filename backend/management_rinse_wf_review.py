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
from backend.rinse_veewash_workload import (
    REASON_DISAPPEARED_WITHOUT_COMPLETION,
    REASON_WF_BULK_WORKITEM_REVIEW,
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


def _wf_review_ids(headline: Mapping[str, Any] | None) -> list[str]:
    segs = (headline or {}).get("segments") or {}
    seg = segs.get("wf") or {}
    ids = list(((seg.get("bag_ids") or {}).get("review_required")) or [])
    if ids:
        return [normalize_bag_id(b) for b in ids if normalize_bag_id(b)]
    by_reason, _ = _headline_maps(headline)
    seen: set[str] = set()
    out: list[str] = []
    for ids in by_reason.values():
        if not isinstance(ids, (list, tuple)):
            continue
        for bid in ids:
            key = normalize_bag_id(bid)
            if key and key not in seen:
                seen.add(key)
                out.append(key)
    return out


def _specialty_candidate_ids(
    headline: Mapping[str, Any] | None,
    by_reason: Mapping[str, Any],
    by_bag: Mapping[str, Any],
) -> list[str]:
    """Review-required IDs plus any bag with unresolved specialty reasons.

    Completed status alone must not exclude a bag that still has unresolved
    specialty review (e.g. WF_BULK_WORKITEM_REVIEW still on the bag).
    """
    seen: set[str] = set()
    out: list[str] = []

    def _add(raw: Any) -> None:
        key = normalize_bag_id(raw)
        if key and key not in seen:
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
            "specialty and missing"
        ),
        "employee_performance_hint": {
            CATEGORY_SPECIALTY: "may_associate_with_employee_or_resource",
            CATEGORY_MISSING_PORTAL: "not_automatic_employee_quality_issue",
            CATEGORY_SPLIT_ORDER: "operational_split_contradiction_not_auto_employee_quality",
        },
    }


def build_management_review_summary(
    cursor,
    organization_id: int,
    selected_date_et: date,
) -> dict[str, Any]:
    """Compact Review category counts (no bag arrays) for the Rinse WF page."""
    from backend.rinse_veewash_shift_day import get_day_record, summary_from_day_record

    day = get_day_record(cursor, organization_id, selected_date_et)
    headline = summary_from_day_record(day) or {}
    split = split_review_categories(headline)
    return {
        "date_et": selected_date_et.isoformat(),
        "split_available": True,
        "review_required": split["counts"]["review_required"],
        "specialty_items": split["counts"][CATEGORY_SPECIALTY],
        "missing_from_portal": split["counts"][CATEGORY_MISSING_PORTAL],
        "split_order_review": split["counts"].get(CATEGORY_SPLIT_ORDER) or 0,
        "categories": {
            CATEGORY_SPECIALTY: {
                "id": CATEGORY_SPECIALTY,
                "label": "Specialty Items",
                "count": split["counts"][CATEGORY_SPECIALTY],
            },
            CATEGORY_MISSING_PORTAL: {
                "id": CATEGORY_MISSING_PORTAL,
                "label": "Missing From Portal",
                "count": split["counts"][CATEGORY_MISSING_PORTAL],
            },
            CATEGORY_SPLIT_ORDER: {
                "id": CATEGORY_SPLIT_ORDER,
                "label": "Split Order Review",
                "count": split["counts"].get(CATEGORY_SPLIT_ORDER) or 0,
            },
        },
        "reason_category_map": split["reason_category_map"],
        "precedence": split["precedence"],
        "employee_performance_hint": split["employee_performance_hint"],
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
    bag_ids = list(split.get(cat) or [])
    by_reason, by_bag = _headline_maps(headline)

    # Heal membership from day_bag rows — NEVER drop Specialty Items solely
    # because status=completed. Specialty exits only when specialty is resolved.
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
    elif cat == CATEGORY_SPLIT_ORDER and not bag_ids:
        # Live fallback when headline specialty_metrics lacks split_review yet.
        from backend.rinse_wf_canonical_split import (
            STATE_REVIEW_REQUIRED,
            evaluate_day_wf_splits,
        )

        member = _wf_review_ids(headline)
        segs = (headline or {}).get("segments") or {}
        wf_seg = segs.get("wf") or {}
        bags_map = wf_seg.get("bag_ids") or {}
        for bucket in ("completed", "pending", "review_required", "new_today", "carryover"):
            for bid in bags_map.get(bucket) or []:
                nb = normalize_bag_id(bid)
                if nb and nb not in member:
                    member.append(nb)
        if member:
            evaluations = evaluate_day_wf_splits(
                cursor, organization_id, selected_date_et, member
            )
            bag_ids = [
                bid
                for bid, ev in evaluations.items()
                if ev.get("state") == STATE_REVIEW_REQUIRED
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

    rows = (
        load_day_bags_by_ids(cursor, organization_id, selected_date_et, page_ids)
        if page_ids
        else []
    )
    by_id = {normalize_bag_id(r.get("bag_id")): r for r in rows}
    by_reason, by_bag = _headline_maps(headline)

    bulk_lines: dict = {}
    if cat == CATEGORY_SPECIALTY and page_ids:
        # One batch query for specialty quantities — not scans, not N+1.
        bulk_lines = load_bag_bulk_lines(
            cursor, organization_id, selected_date_et, page_ids
        )

    split_evals: dict[str, dict[str, Any]] = {}
    if cat == CATEGORY_SPLIT_ORDER and page_ids:
        from backend.rinse_wf_canonical_split import (
            evaluate_day_wf_splits,
            evaluation_to_jsonable,
        )

        split_evals = {
            bid: evaluation_to_jsonable(ev)
            for bid, ev in evaluate_day_wf_splits(
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
        bags_out.append(
            {
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
                "employee": (
                    sev.get("split_marker_employee")
                    or snap.get("completed_by")
                    or row.get("canonical_completion_employee")
                    or snap.get("pre_weight_employee")
                    or snap.get("post_weight_employee")
                ),
                "pre_weight_lbs": snap.get("pre_weight_lbs", row.get("pre_weight_lbs")),
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
        )

    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 1)
    return {
        "ok": True,
        "date_et": selected_date_et.isoformat(),
        "category": cat,
        "counts": split["counts"],
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
        "pre_weight_lbs": bag.get("pre_weight_lbs"),
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
            from backend.rinse_wf_canonical_split import (
                evaluate_day_wf_splits,
                evaluation_to_jsonable,
            )

            split_map = evaluate_day_wf_splits(
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
