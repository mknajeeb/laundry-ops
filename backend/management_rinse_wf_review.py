"""Management Rinse WF — Review list + one-bag detail (summary first).

Categories (mutually exclusive for Specialty vs Missing; Split Order Review is
a separate canonical-split queue):

  missing_from_portal
      DISAPPEARED_WITHOUT_COMPLETION
      (and not also specialty-bulk when both present — specialty wins)

  specialty_items
      Explicit specialty reasons (e.g. WF_BULK_WORKITEM_REVIEW) while bulk
      specialty remains unresolved (bulk_cleared=false).

  split_order_review
      Canonical split REVIEW_REQUIRED (marker/load contradiction). Independent
      of DISAPPEARED_WITHOUT_COMPLETION and specialty queues.

  manual_review
      WF bag with ``effective_status=review_required`` that does not belong in
      Specialty / Missing / Split — e.g. manager send-back of an operationally
      completed bag (post-completion portal reasons are not Missing From Portal).

  review_required (list category)
      Union of all actionable Review drawer IDs — full queue for the headline tap.

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
from backend.rinse_employee_productivity_sessions import (
    resolve_customer_name,
    resolve_customer_names_for_bags,
)
from backend.rinse_veewash_workload import (
    REASON_DISAPPEARED_WITHOUT_COMPLETION,
    REASON_SERVICE_CLASSIFICATION_MISMATCH,
    REASON_WF_BULK_WORKITEM_REVIEW,
    REASON_WF_ZERO_OR_MISSING_POST_WEIGHT,
)
from backend.rinse_wf_service_cycle import REVIEW_MISSING_FROM_PORTAL

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
CATEGORY_MANUAL_REVIEW = "manual_review"
CATEGORY_UNKNOWN = "unknown_review"
CATEGORY_REVIEW_ALL = "review_required"

REVIEW_DRAWER_CATEGORIES = frozenset(
    {
        CATEGORY_SPECIALTY,
        CATEGORY_MISSING_PORTAL,
        CATEGORY_SPLIT_ORDER,
        CATEGORY_MANUAL_REVIEW,
        CATEGORY_UNKNOWN,
        CATEGORY_REVIEW_ALL,
    }
)

REVIEW_CUSTOMER_UNAVAILABLE = "Customer unavailable"

# Explicit missing-from-portal codes only — never fall back to Specialty.
MISSING_FROM_PORTAL_REASONS = frozenset(
    {
        REASON_DISAPPEARED_WITHOUT_COMPLETION,
        REVIEW_MISSING_FROM_PORTAL,
    }
)

SPECIALTY_ITEMS_REASONS = frozenset(
    {
        REASON_WF_BULK_WORKITEM_REVIEW,
        REASON_WF_ZERO_OR_MISSING_POST_WEIGHT,
        "WF_ZERO_OR_MISSING_WEIGHT",
        "COMPLETED_WITHOUT_RECOGNIZED_ENTRY",
        REASON_SERVICE_CLASSIFICATION_MISMATCH,
        "MANAGER_SENT_FOR_REVIEW",
        "COMPLETION_DETAILS_MISSING",
        "MISSING_PRE_EVIDENCE",
        "SCAN_CHRONOLOGY_STALE",
    }
)

SPECIALTY_ONLY_ZERO_POST_CLEARABLE_REASONS = frozenset(
    {
        REASON_SERVICE_CLASSIFICATION_MISMATCH,
        REASON_WF_ZERO_OR_MISSING_POST_WEIGHT,
        "WF_ZERO_OR_MISSING_WEIGHT",
    }
)

_PORTAL_ZERO_EPS = 0.051


def post_weight_is_recorded(
    post_weight_lbs: Any,
    *,
    weight_info: Mapping[str, Any] | None = None,
) -> bool:
    """True when POST is present as a numeric value (0.0 is valid, None is not)."""
    if weight_info and weight_info.get("post_weight_event_exists"):
        if weight_info.get("post_weight_value") is not None:
            return True
        if weight_info.get("post_weight_lbs") is not None:
            return True
    return post_weight_lbs is not None


def wf_specialty_only_zero_post_valid(
    *,
    bulk_lines: list | None = None,
    bulk_resolution: Mapping[str, Any] | None = None,
    post_weight_lbs: Any = None,
    weight_info: Mapping[str, Any] | None = None,
) -> bool:
    """POST=0 is valid when chargeable specialty qty is resolved and explains zero WF pounds."""
    from backend.rinse_bulk_workitems import bag_bulk_review_cleared
    from backend.rinse_settled_bulk_only_weight import chargeable_bulk_qty

    lines = list(bulk_lines or [])
    post = post_weight_lbs
    info = dict(weight_info or {})
    if info.get("post_weight_event_exists"):
        if info.get("post_weight_value") is not None:
            post = info.get("post_weight_value")
        elif info.get("post_weight_lbs") is not None:
            post = info.get("post_weight_lbs")
    if not post_weight_is_recorded(post, weight_info=info):
        return False
    if float(post) > _PORTAL_ZERO_EPS:
        return False
    if chargeable_bulk_qty(lines) <= 0:
        return False
    return bool(bag_bulk_review_cleared(bulk_resolution, lines))


def strip_specialty_only_resolved_reasons(
    codes: list[str] | tuple[str, ...] | None,
    *,
    bulk_lines: list | None = None,
    bulk_resolution: Mapping[str, Any] | None = None,
    post_weight_lbs: Any = None,
    weight_info: Mapping[str, Any] | None = None,
    bulk_cleared: bool | None = None,
) -> list[str]:
    """Remove bulk/specialty-only reasons satisfied by resolved specialty + valid zero POST."""
    out = [str(c) for c in (codes or []) if c]
    if bulk_cleared is True:
        out = [c for c in out if c != REASON_WF_BULK_WORKITEM_REVIEW]
    if wf_specialty_only_zero_post_valid(
        bulk_lines=bulk_lines,
        bulk_resolution=bulk_resolution,
        post_weight_lbs=post_weight_lbs,
        weight_info=weight_info,
    ):
        out = [c for c in out if c not in SPECIALTY_ONLY_ZERO_POST_CLEARABLE_REASONS]
    return out

SPLIT_ORDER_REASONS = frozenset(
    {
        "SPLIT_MARKED_BUT_SECOND_WASHER_NOT_FOUND",
        "MULTIPLE_WASHERS_WITHOUT_SPLIT_MARKER",
        "SPLIT_EVIDENCE_INCOMPLETE_AT_DISAPPEARANCE",
    }
)

REASON_CATEGORY_MAP: dict[str, str] = {
    **{code: CATEGORY_MISSING_PORTAL for code in MISSING_FROM_PORTAL_REASONS},
    **{code: CATEGORY_SPECIALTY for code in SPECIALTY_ITEMS_REASONS},
    **{code: CATEGORY_SPLIT_ORDER for code in SPLIT_ORDER_REASONS},
}


def review_customer_display_name(*candidates: Any) -> str:
    return resolve_customer_name(*candidates) or REVIEW_CUSTOMER_UNAVAILABLE


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


def category_for_reason_codes(
    codes: list[str] | tuple[str, ...] | None,
) -> str | None:
    """Deterministic single category for a bag's reason codes (no double-count).

    Returns ``None`` for unrecognized codes — never silently map to Specialty.
    """
    normalized = [str(c) for c in (codes or []) if c]
    if not normalized:
        return None
    code_set = set(normalized)
    has_specialty_bulk = REASON_WF_BULK_WORKITEM_REVIEW in code_set
    has_missing = bool(code_set & MISSING_FROM_PORTAL_REASONS)
    if has_specialty_bulk:
        return CATEGORY_SPECIALTY
    if has_missing and not (code_set & SPECIALTY_ITEMS_REASONS):
        return CATEGORY_MISSING_PORTAL
    if has_missing and not has_specialty_bulk:
        other = code_set - MISSING_FROM_PORTAL_REASONS
        if not other:
            return CATEGORY_MISSING_PORTAL
    if code_set & SPECIALTY_ITEMS_REASONS:
        return CATEGORY_SPECIALTY
    if code_set & SPLIT_ORDER_REASONS:
        return CATEGORY_SPLIT_ORDER
    if has_missing:
        return CATEGORY_MISSING_PORTAL
    return None


def _has_valid_wf_completion(
    row: Mapping[str, Any] | None,
    *,
    weights: Mapping[str, Any] | None = None,
    in_completed_bucket: bool = False,
    bulk_lines: list | None = None,
    bulk_resolution: Mapping[str, Any] | None = None,
) -> bool:
    """True when canonical completion evidence exists (POST + completion time)."""
    snap = (row or {}).get("bag_snapshot") or {}
    if not isinstance(snap, dict):
        snap = {}
    comp = (row or {}).get("canonical_completion_timestamp") or snap.get("completion_at")
    post = None
    if weights:
        post = weights.get("post_weight_lbs")
        if post is None and weights.get("post_weight_event_exists"):
            post = weights.get("post_weight_value")
    if post is None:
        post = (row or {}).get("post_weight_lbs") or snap.get("post_weight_lbs")
    status = str((row or {}).get("effective_status") or "").strip().lower()
    if not post_weight_is_recorded(post, weight_info=weights):
        return False
    if comp is not None:
        return True
    if wf_specialty_only_zero_post_valid(
        bulk_lines=bulk_lines,
        bulk_resolution=bulk_resolution,
        post_weight_lbs=post,
        weight_info=weights,
    ):
        return True
    return status == "completed" or in_completed_bucket


def missing_portal_review_is_eligible(
    codes: list[str] | tuple[str, ...] | None,
    *,
    row: Mapping[str, Any] | None = None,
    weights: Mapping[str, Any] | None = None,
    in_completed_bucket: bool = False,
) -> bool:
    """Missing From Portal only for unexpected disappearance — not post-completion departure."""
    normalized = [str(c) for c in (codes or []) if c]
    if not normalized:
        return False
    if category_for_reason_codes(normalized) != CATEGORY_MISSING_PORTAL:
        return False
    if _has_valid_wf_completion(
        row, weights=weights, in_completed_bucket=in_completed_bucket
    ):
        return False
    return True


def specialty_review_is_unresolved(
    codes: list[str] | tuple[str, ...] | None,
    *,
    bulk_cleared: bool | None = None,
    bulk_lines: list | None = None,
    bulk_resolution: Mapping[str, Any] | None = None,
    post_weight_lbs: Any = None,
    weight_info: Mapping[str, Any] | None = None,
) -> bool:
    """True when Specialty Items review is still open.

    Independent of day-bag ``completed`` / ``pending`` status.
    A bag leaves active Specialty Review only when specialty itself is resolved
    (reason codes cleared / bulk cleared) — never merely because status=completed.
    """
    normalized = strip_specialty_only_resolved_reasons(
        codes,
        bulk_lines=bulk_lines,
        bulk_resolution=bulk_resolution,
        post_weight_lbs=post_weight_lbs,
        weight_info=weight_info,
        bulk_cleared=bulk_cleared,
    )
    if not normalized:
        return False
    explicit = [
        c
        for c in normalized
        if c in SPECIALTY_ITEMS_REASONS or c == REASON_WF_BULK_WORKITEM_REVIEW
    ]
    if not explicit:
        return False
    return category_for_reason_codes(explicit) == CATEGORY_SPECIALTY


def specialty_review_is_resolved(
    codes: list[str] | tuple[str, ...] | None,
    *,
    bulk_cleared: bool | None = None,
    bulk_lines: list | None = None,
    bulk_resolution: Mapping[str, Any] | None = None,
    post_weight_lbs: Any = None,
    weight_info: Mapping[str, Any] | None = None,
) -> bool:
    """Inverse of ``specialty_review_is_unresolved`` (canonical specialty exit)."""
    return not specialty_review_is_unresolved(
        codes,
        bulk_cleared=bulk_cleared,
        bulk_lines=bulk_lines,
        bulk_resolution=bulk_resolution,
        post_weight_lbs=post_weight_lbs,
        weight_info=weight_info,
    )


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


def _resolve_bag_review_codes(
    bag_id: str,
    row: Mapping[str, Any] | None,
    fresh_reasons: Mapping[str, Any] | None,
    headline: Mapping[str, Any] | None,
) -> list[str]:
    """Single code-resolution path for canonical membership and drawer lists."""
    bid = normalize_bag_id(bag_id)
    day_codes = list((row or {}).get("review_reason_codes") or [])
    fresh = list(
        (fresh_reasons or {}).get(bid)
        or (fresh_reasons or {}).get(str(bag_id))
        or []
    )
    if fresh or day_codes:
        return list(dict.fromkeys([*(str(c) for c in fresh if c), *(str(c) for c in day_codes if c)]))
    by_reason, by_bag = _headline_maps(headline)
    return _bag_codes(by_bag, by_reason, bid)


def _filter_wf_service_bag_ids(
    bag_ids: list[str] | tuple[str, ...],
    rows_by_id: Mapping[str, Mapping[str, Any] | None],
) -> list[str]:
    """Drop non-WF day-bag rows; keep IDs with no row (membership-only)."""
    out: list[str] = []
    for raw in bag_ids or []:
        bid = normalize_bag_id(raw)
        if not bid:
            continue
        row = rows_by_id.get(bid)
        if row and not _service_is_wf(row):
            continue
        out.append(bid)
    return out


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


def _bag_is_wf_review_required(
    row: Mapping[str, Any] | None,
    headline: Mapping[str, Any] | None,
    bag_id: str,
) -> bool:
    """True when bag is in active WF Review Required membership."""
    bid = normalize_bag_id(bag_id)
    if not bid:
        return False
    if bid in set(_wf_review_ids(headline)):
        return True
    if row is not None and not _service_is_wf(row):
        return False
    return str((row or {}).get("effective_status") or "").strip().lower() == "review_required"


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


def _wf_completed_bucket(headline: Mapping[str, Any] | None) -> set[str]:
    wf = ((headline or {}).get("segments") or {}).get("wf") or {}
    bags_map = wf.get("bag_ids") or {}
    return {
        normalize_bag_id(b)
        for b in (bags_map.get("completed") or [])
        if normalize_bag_id(b)
    }


def _split_review_ids_from_headline(headline: Mapping[str, Any] | None) -> list[str]:
    split_ids: list[str] = []
    root = (headline or {}).get("specialty_metrics") or {}
    wf_pack = root.get("wf") or root.get("all") or {}
    pack = wf_pack.get("split_review") if isinstance(wf_pack, dict) else None
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
    return split_ids


def _membership_result_payload(
    specialty: list[str],
    missing: list[str],
    split_ids: list[str],
    *,
    manual: list[str] | None = None,
    unknown: list[str] | None = None,
) -> dict[str, Any]:
    manual = list(manual or [])
    unknown = list(unknown or [])
    all_review = (
        set(specialty)
        | set(missing)
        | set(split_ids)
        | set(manual)
        | set(unknown)
    )
    return {
        CATEGORY_SPECIALTY: list(specialty),
        CATEGORY_MISSING_PORTAL: list(missing),
        CATEGORY_SPLIT_ORDER: list(split_ids),
        CATEGORY_MANUAL_REVIEW: list(manual),
        CATEGORY_UNKNOWN: list(unknown),
        "counts": {
            CATEGORY_SPECIALTY: len(specialty),
            CATEGORY_MISSING_PORTAL: len(missing),
            CATEGORY_SPLIT_ORDER: len(split_ids),
            CATEGORY_MANUAL_REVIEW: len(manual),
            CATEGORY_UNKNOWN: len(unknown),
            "review_required": len(all_review),
        },
        "reason_category_map": dict(REASON_CATEGORY_MAP),
        "precedence": (
            "Split Order Review = canonical split REVIEW_REQUIRED only; "
            "Specialty Items = explicit unresolved specialty/bulk (bulk_cleared=false); "
            "Missing From Portal = DISAPPEARED_WITHOUT_COMPLETION or "
            "MISSING_FROM_PORTAL_AFTER_FULL_TRAVERSAL before valid completion; "
            "post-completion portal departure is not Missing From Portal — use manual_review; "
            "manual_review = WF review_required not in Specialty/Missing/Split; "
            "unknown codes are logged — never silently Specialty"
        ),
        "employee_performance_hint": {
            CATEGORY_SPECIALTY: "may_associate_with_employee_or_resource",
            CATEGORY_MISSING_PORTAL: "not_automatic_employee_quality_issue",
            CATEGORY_SPLIT_ORDER: "operational_split_contradiction_not_auto_employee_quality",
        },
    }


def compute_canonical_wf_review_membership(
    cursor,
    organization_id: int,
    selected_date_et: date,
    *,
    headline: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Authoritative WF Review membership from fresh evidence + day-bag rows."""
    from backend.rinse_bulk_workitems import (
        bag_bulk_review_cleared,
        load_bag_bulk_lines,
        load_bulk_resolutions,
        load_bulk_workitem_scan_map,
    )
    from backend.rinse_hd_day_metrics import attach_specialty_metrics_to_summary
    from backend.rinse_veewash_shift_day import get_day_record, load_day_bags, summary_from_day_record
    from backend.rinse_veewash_workload import (
        build_step1_headline_summary,
        build_veewash_daily_workload_from_membership,
        get_step1_activation_date,
    )
    from backend.rinse_wf_canonical_split import STATE_REVIEW_REQUIRED

    if headline is None:
        day = get_day_record(cursor, organization_id, selected_date_et) or {}
        headline = summary_from_day_record(day) or {}

    wf_rows = [
        r for r in (load_day_bags(cursor, organization_id, selected_date_et) or []) if _service_is_wf(r)
    ]
    bag_ids = sorted(
        {
            normalize_bag_id(r.get("bag_id"))
            for r in wf_rows
            if normalize_bag_id(r.get("bag_id"))
        }
    )
    by_id = {
        normalize_bag_id(r.get("bag_id")): r
        for r in wf_rows
        if normalize_bag_id(r.get("bag_id"))
    }

    _, headline_by_bag = _headline_maps(headline)
    fresh_reasons = dict(headline_by_bag) if headline_by_bag else {}
    if not fresh_reasons:
        wl = build_veewash_daily_workload_from_membership(
            cursor, organization_id, selected_date_et=selected_date_et
        )
        activation = get_step1_activation_date(cursor, organization_id) or selected_date_et
        summary = build_step1_headline_summary(
            wl, selected_date_et=selected_date_et, activation_date=activation
        )
        summary = attach_specialty_metrics_to_summary(
            cursor, organization_id, selected_date_et, summary
        )
        fresh_reasons = summary.get("review_reasons_by_bag") or {}

    headline_split = _split_review_ids_from_headline(headline)
    split_candidates: set[str] = set(headline_split)
    membership_candidates: set[str] = set(_wf_review_ids(headline))
    for bid in bag_ids:
        row = by_id.get(bid) or {}
        codes = _resolve_bag_review_codes(bid, row, fresh_reasons, headline)
        if codes:
            membership_candidates.add(bid)
        if str(row.get("effective_status") or "").strip().lower() == "review_required":
            membership_candidates.add(bid)
        if any(str(c) in SPLIT_ORDER_REASONS for c in codes):
            split_candidates.add(bid)
    split_candidates_list = sorted(split_candidates)
    split_eval = (
        _split_eval_as_of_day(
            cursor, organization_id, selected_date_et, split_candidates_list
        )
        if split_candidates_list
        else {}
    )
    split_ids = sorted(
        {
            bid
            for bid in split_candidates_list
            if (split_eval.get(bid) or {}).get("state") == STATE_REVIEW_REQUIRED
        }
    )
    membership_candidates |= set(split_ids)
    candidate_ids = sorted(membership_candidates)

    bulk_lines = (
        load_bag_bulk_lines(cursor, organization_id, selected_date_et, candidate_ids)
        if candidate_ids
        else {}
    )
    bulk_res = (
        load_bulk_resolutions(cursor, organization_id, selected_date_et, candidate_ids)
        if candidate_ids
        else {}
    )
    bulk_scans = (
        load_bulk_workitem_scan_map(
            cursor, organization_id, candidate_ids, selected_date_et=selected_date_et
        )
        if candidate_ids
        else {}
    )
    weights = (
        _canonical_review_weights(cursor, organization_id, selected_date_et, candidate_ids)
        if candidate_ids
        else {}
    )
    completed_bucket = _wf_completed_bucket(headline)

    specialty: list[str] = []
    missing: list[str] = []
    manual: list[str] = []
    unknown: list[str] = []
    excluded: list[str] = []
    disposition: dict[str, str | None] = {}
    codes_by_bag: dict[str, list[str]] = {}
    split_set = set(split_ids)

    for bid in candidate_ids:
        if bid in split_set:
            disposition[bid] = CATEGORY_SPLIT_ORDER
            continue
        row = by_id.get(bid) or {}
        codes = _resolve_bag_review_codes(bid, row, fresh_reasons, headline)
        codes_by_bag[bid] = codes
        lines = list(bulk_lines.get(bid) or [])
        scan = bulk_scans.get(bid)
        has_bulk = bool(
            lines or bulk_res.get(bid) or (scan and int(scan.get("count") or 0) > 0)
        )
        cleared = bag_bulk_review_cleared(bulk_res.get(bid), lines) if has_bulk else None
        w = weights.get(bid) or {}
        in_completed = bid in completed_bucket
        post = w.get("post_weight_lbs")
        if post is None:
            post = row.get("post_weight_lbs")

        if specialty_review_is_unresolved(
            codes,
            bulk_cleared=cleared,
            bulk_lines=lines,
            bulk_resolution=bulk_res.get(bid),
            post_weight_lbs=post,
            weight_info=w,
        ):
            specialty.append(bid)
            disposition[bid] = CATEGORY_SPECIALTY
            continue
        if missing_portal_review_is_eligible(
            codes,
            row=row,
            weights=w,
            in_completed_bucket=in_completed,
        ):
            missing.append(bid)
            disposition[bid] = CATEGORY_MISSING_PORTAL
            continue
        if _bag_is_wf_review_required(row, headline, bid):
            if codes and category_for_reason_codes(codes) is None:
                unknown.append(bid)
                disposition[bid] = CATEGORY_UNKNOWN
            else:
                manual.append(bid)
                disposition[bid] = CATEGORY_MANUAL_REVIEW
            continue
        if codes:
            cat = category_for_reason_codes(codes)
            if cat is None:
                unknown.append(bid)
                disposition[bid] = CATEGORY_UNKNOWN
            else:
                excluded.append(bid)
                disposition[bid] = None
        else:
            disposition[bid] = None

    out = _membership_result_payload(
        specialty, missing, split_ids, manual=manual, unknown=unknown
    )
    out["disposition"] = disposition
    out["excluded"] = sorted(excluded)
    out["codes_by_bag"] = codes_by_bag
    return out


def apply_canonical_wf_review_day_bag_fixes(
    cursor,
    organization_id: int,
    selected_date_et: date,
    membership: Mapping[str, Any],
) -> dict[str, int]:
    """Clear stale review rows and align eligible bags with canonical membership."""
    import json as _json

    from backend.rinse_bag_completion import normalize_bag_id

    disposition = dict(membership.get("disposition") or {})
    codes_by_bag = dict(membership.get("codes_by_bag") or {})
    stats = {"cleared": 0, "set_specialty": 0, "set_missing": 0, "unchanged": 0}

    for bid, target in disposition.items():
        nb = normalize_bag_id(bid)
        if not nb:
            continue
        if target == CATEGORY_SPECIALTY:
            codes = [
                c
                for c in (codes_by_bag.get(nb) or [])
                if c in SPECIALTY_ITEMS_REASONS or c == REASON_WF_BULK_WORKITEM_REVIEW
            ]
            if not codes:
                codes = [REASON_WF_BULK_WORKITEM_REVIEW]
            cursor.execute(
                """
                UPDATE rinse_shift_monitor_day_bags
                SET review_reason_codes_json = %s, effective_status = 'review_required'
                WHERE organization_id = %s AND shift_date_et = %s AND bag_id = %s
                """,
                (_json.dumps(codes), int(organization_id), selected_date_et, nb),
            )
            stats["set_specialty"] += int(getattr(cursor, "rowcount", 0) or 0)
            continue
        if target == CATEGORY_MISSING_PORTAL:
            codes = [
                c
                for c in (codes_by_bag.get(nb) or [])
                if c in MISSING_FROM_PORTAL_REASONS
            ] or [REASON_DISAPPEARED_WITHOUT_COMPLETION]
            cursor.execute(
                """
                UPDATE rinse_shift_monitor_day_bags
                SET review_reason_codes_json = %s, effective_status = 'review_required'
                WHERE organization_id = %s AND shift_date_et = %s AND bag_id = %s
                """,
                (_json.dumps(codes), int(organization_id), selected_date_et, nb),
            )
            stats["set_missing"] += int(getattr(cursor, "rowcount", 0) or 0)
            continue
        if target == CATEGORY_MANUAL_REVIEW:
            stats["unchanged"] += 1
            continue
        if target in (CATEGORY_SPLIT_ORDER, CATEGORY_UNKNOWN, None):
            cursor.execute(
                """
                UPDATE rinse_shift_monitor_day_bags
                SET review_reason_codes_json = '[]',
                    effective_status = CASE
                        WHEN post_weight_lbs IS NOT NULL
                          OR canonical_completion_timestamp IS NOT NULL
                        THEN 'completed'
                        WHEN effective_status = 'review_required' THEN 'pending'
                        ELSE effective_status
                    END
                WHERE organization_id = %s AND shift_date_et = %s AND bag_id = %s
                  AND (review_reason_codes_json IS NOT NULL
                       AND review_reason_codes_json != '[]'
                       OR effective_status = 'review_required')
                """,
                (int(organization_id), selected_date_et, nb),
            )
            n = int(getattr(cursor, "rowcount", 0) or 0)
            if n:
                stats["cleared"] += n
            else:
                stats["unchanged"] += 1
    return stats


def _active_wf_review_bag_ids(membership: Mapping[str, Any]) -> set[str]:
    from backend.rinse_bag_completion import normalize_bag_id

    active: set[str] = set()
    for key in (
        CATEGORY_SPECIALTY,
        CATEGORY_MISSING_PORTAL,
        CATEGORY_SPLIT_ORDER,
        CATEGORY_MANUAL_REVIEW,
        CATEGORY_UNKNOWN,
    ):
        for bid in membership.get(key) or []:
            nb = normalize_bag_id(bid)
            if nb:
                active.add(nb)
    return active


def clear_stale_completed_wf_review_day_bag_codes(
    cursor,
    organization_id: int,
    selected_date_et: date,
    membership: Mapping[str, Any],
) -> int:
    """Drop review_reason_codes from completed WF day bags no longer in Review membership."""
    from backend.rinse_bag_completion import normalize_bag_id

    active = _active_wf_review_bag_ids(membership)
    cursor.execute(
        """
        SELECT bag_id, review_reason_codes_json, effective_status, canonical_completion_status
        FROM rinse_shift_monitor_day_bags
        WHERE organization_id = %s AND shift_date_et = %s AND service_type = 'WF'
          AND review_reason_codes_json IS NOT NULL
          AND review_reason_codes_json != '[]'
        """,
        (int(organization_id), selected_date_et),
    )
    cleared = 0
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            continue
        bid = normalize_bag_id(row.get("bag_id"))
        if not bid or bid in active:
            continue
        status = str(row.get("effective_status") or "").strip().lower()
        canon = str(row.get("canonical_completion_status") or "").strip().lower()
        if status != "completed" and "completed" not in canon:
            continue
        cursor.execute(
            """
            UPDATE rinse_shift_monitor_day_bags
            SET review_reason_codes_json = '[]'
            WHERE organization_id = %s AND shift_date_et = %s AND bag_id = %s
            """,
            (int(organization_id), selected_date_et, bid),
        )
        cleared += int(getattr(cursor, "rowcount", 0) or 0)
    return cleared


def persist_canonical_wf_review_on_headline(
    headline: dict[str, Any],
    membership: Mapping[str, Any],
) -> dict[str, Any]:
    """Overlay canonical Review membership onto a headline dict (in-memory)."""
    hl = dict(headline or {})
    specialty = list(membership.get(CATEGORY_SPECIALTY) or [])
    missing = list(membership.get(CATEGORY_MISSING_PORTAL) or [])
    split_ids = list(membership.get(CATEGORY_SPLIT_ORDER) or [])
    manual = list(membership.get(CATEGORY_MANUAL_REVIEW) or [])
    unknown = list(membership.get(CATEGORY_UNKNOWN) or [])
    codes_by_bag = dict(membership.get("codes_by_bag") or {})
    reasons: dict[str, list[str]] = {}
    for bid in specialty:
        codes = [
            c
            for c in (codes_by_bag.get(bid) or [])
            if c in SPECIALTY_ITEMS_REASONS or c == REASON_WF_BULK_WORKITEM_REVIEW
        ]
        if codes:
            reasons[bid] = codes
    for bid in missing:
        codes = [c for c in (codes_by_bag.get(bid) or []) if c in MISSING_FROM_PORTAL_REASONS]
        if codes:
            reasons[bid] = codes
    for bid in manual + unknown:
        codes = [str(c) for c in (codes_by_bag.get(bid) or []) if c]
        if codes:
            reasons[bid] = codes
    hl["review_reasons_by_bag"] = reasons
    by_reason: dict[str, list[str]] = {}
    for bid, codes in reasons.items():
        for code in codes or []:
            by_reason.setdefault(str(code), []).append(bid)
    for key in list(by_reason):
        by_reason[key] = sorted(set(by_reason[key]))
    hl["review_by_reason"] = by_reason
    segs = dict(hl.get("segments") or {})
    wf = dict(segs.get("wf") or {})
    bag_ids = dict(wf.get("bag_ids") or {})
    review_union = sorted(
        set(specialty) | set(missing) | set(split_ids) | set(manual) | set(unknown)
    )
    bag_ids["review_required"] = review_union
    wf["bag_ids"] = bag_ids
    exc = dict(wf.get("exceptions") or {})
    exc["review_required"] = len(review_union)
    wf["exceptions"] = exc
    segs["wf"] = wf
    hl["segments"] = segs
    root = dict(hl.get("specialty_metrics") or {})
    wf_pack = dict(root.get("wf") or root.get("all") or {})
    wf_pack["split_review"] = {
        "count": len(split_ids),
        "order_ids": split_ids,
        "orders": [{"bag_id": b} for b in split_ids],
    }
    root["wf"] = wf_pack
    hl["specialty_metrics"] = root
    return hl


def split_review_categories(
    headline: Mapping[str, Any] | None,
    *,
    membership: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Partition Review queues from explicit categories (headline-only fallback)."""
    if membership:
        return _membership_result_payload(
            list(membership.get(CATEGORY_SPECIALTY) or []),
            list(membership.get(CATEGORY_MISSING_PORTAL) or []),
            list(membership.get(CATEGORY_SPLIT_ORDER) or []),
            manual=list(membership.get(CATEGORY_MANUAL_REVIEW) or []),
            unknown=list(membership.get(CATEGORY_UNKNOWN) or []),
        )

    by_reason, by_bag = _headline_maps(headline)
    completed_bucket = _wf_completed_bucket(headline)
    candidates = _specialty_candidate_ids(headline, by_reason, by_bag)
    specialty: list[str] = []
    missing: list[str] = []
    manual: list[str] = []
    unknown: list[str] = []
    for bid in candidates:
        codes = _bag_codes(by_bag, by_reason, bid)
        if specialty_review_is_unresolved(codes):
            specialty.append(bid)
            continue
        if missing_portal_review_is_eligible(
            codes, in_completed_bucket=bid in completed_bucket
        ):
            missing.append(bid)
            continue
        if codes and category_for_reason_codes(codes) is None:
            unknown.append(bid)
            continue
        if bid in set(_wf_review_ids(headline)):
            manual.append(bid)

    split_ids = _split_review_ids_from_headline(headline)
    placed = set(specialty) | set(missing) | set(split_ids) | set(unknown) | set(manual)
    for bid in _wf_review_ids(headline):
        if bid not in placed:
            manual.append(bid)
    return _membership_result_payload(
        specialty, missing, split_ids, manual=manual, unknown=unknown
    )


def specialty_review_membership_ids(
    headline: Mapping[str, Any] | None,
    *,
    membership: Mapping[str, Any] | None = None,
) -> list[str]:
    """Canonical unresolved Specialty Review bag IDs (summary + drawer share this)."""
    if membership:
        return list(membership.get(CATEGORY_SPECIALTY) or [])
    return list(split_review_categories(headline).get(CATEGORY_SPECIALTY) or [])


def review_category_count_payload(
    headline: Mapping[str, Any] | None,
    *,
    cursor=None,
    organization_id: int | None = None,
    selected_date_et: date | None = None,
) -> dict[str, Any]:
    """Scalar Review counts from the same membership as the Review drawers."""
    if cursor is not None and organization_id is not None and selected_date_et is not None:
        split = compute_canonical_wf_review_membership(
            cursor,
            int(organization_id),
            selected_date_et,
            headline=headline,
        )
    else:
        split = split_review_categories(headline)
    counts = split["counts"]
    return {
        "split_available": True,
        "review_required": int(counts.get("review_required") or 0),
        "specialty_items": int(counts.get(CATEGORY_SPECIALTY) or 0),
        "missing_from_portal": int(counts.get(CATEGORY_MISSING_PORTAL) or 0),
        "split_order_review": int(counts.get(CATEGORY_SPLIT_ORDER) or 0),
        "manual_review": int(counts.get(CATEGORY_MANUAL_REVIEW) or 0),
        "unknown_review": int(counts.get(CATEGORY_UNKNOWN) or 0),
        "reason_category_map": split["reason_category_map"],
        "precedence": split["precedence"],
        "employee_performance_hint": split["employee_performance_hint"],
        "_membership": {
            CATEGORY_SPECIALTY: list(split.get(CATEGORY_SPECIALTY) or []),
            CATEGORY_MISSING_PORTAL: list(split.get(CATEGORY_MISSING_PORTAL) or []),
            CATEGORY_SPLIT_ORDER: list(split.get(CATEGORY_SPLIT_ORDER) or []),
            CATEGORY_MANUAL_REVIEW: list(split.get(CATEGORY_MANUAL_REVIEW) or []),
            CATEGORY_UNKNOWN: list(split.get(CATEGORY_UNKNOWN) or []),
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
            (
                review_category_count_payload(
                    headline,
                    cursor=cursor,
                    organization_id=organization_id,
                    selected_date_et=selected_date_et,
                ).get("_membership")
                or {}
            )
        )
    specialty = list(membership.get(CATEGORY_SPECIALTY) or [])
    missing = list(membership.get(CATEGORY_MISSING_PORTAL) or [])
    split_ids = list(membership.get(CATEGORY_SPLIT_ORDER) or [])
    manual = list(membership.get(CATEGORY_MANUAL_REVIEW) or [])
    unknown = list(membership.get(CATEGORY_UNKNOWN) or [])
    all_ids = list(
        dict.fromkeys([*specialty, *missing, *split_ids, *manual, *unknown])
    )
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
            total = len(specialty) + len(missing) + len(split_ids) + len(manual) + len(unknown)
            return {
                "specialty_items": len(specialty),
                "missing_from_portal": len(missing),
                "split_order_review": len(split_ids),
                "manual_review": len(manual),
                "unknown_review": len(unknown),
                "review_required": total,
            }
        spec_n = sum(1 for b in specialty if b in want)
        miss_n = sum(1 for b in missing if b in want)
        split_n = sum(1 for b in split_ids if b in want)
        manual_n = sum(1 for b in manual if b in want)
        unknown_n = sum(1 for b in unknown if b in want)
        return {
            "specialty_items": spec_n,
            "missing_from_portal": miss_n,
            "split_order_review": split_n,
            "manual_review": manual_n,
            "unknown_review": unknown_n,
            "review_required": spec_n + miss_n + split_n + manual_n + unknown_n,
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
    base = review_category_count_payload(
        headline,
        cursor=cursor,
        organization_id=organization_id,
        selected_date_et=selected_date_et,
    )
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
    if category == CATEGORY_MANUAL_REVIEW:
        if "MANAGER_SENT_FOR_REVIEW" in codes:
            return "Manager sent for review"
        return "Manual review"
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


def review_drawer_section_flags(
    codes: list[str] | tuple[str, ...] | None,
    *,
    bulk_cleared: bool | None = None,
    bulk_unresolved: bool | None = None,
) -> dict[str, bool]:
    """Which compact drawer action sections apply (multi-reason bags can have both)."""
    code_set = {str(c) for c in (codes or []) if c}
    has_bulk_code = REASON_WF_BULK_WORKITEM_REVIEW in code_set
    if bulk_unresolved is None:
        bulk_unresolved = has_bulk_code and bulk_cleared is not True
    else:
        bulk_unresolved = bool(bulk_unresolved)
    return {
        "has_specialty_bulk": bulk_unresolved,
        "has_specialty_review": bool(code_set & SPECIALTY_ITEMS_REASONS) or bulk_unresolved,
        "has_missing_portal": bool(code_set & MISSING_FROM_PORTAL_REASONS),
        "bulk_review_unresolved": bulk_unresolved,
        "bulk_review_cleared": bulk_cleared if has_bulk_code or bulk_cleared is not None else None,
    }


def _bulk_review_state_for_bag(
    codes: list[str] | tuple[str, ...] | None,
    *,
    bulk_lines: list | None,
    bulk_resolution: Mapping[str, Any] | None,
    bulk_scan: Mapping[str, Any] | None = None,
) -> tuple[bool | None, bool]:
    """Return (bulk_cleared, bulk_unresolved) for drawer UX."""
    from backend.rinse_bulk_workitems import bag_bulk_review_cleared

    code_set = {str(c) for c in (codes or []) if c}
    has_bulk_code = REASON_WF_BULK_WORKITEM_REVIEW in code_set
    lines = list(bulk_lines or [])
    scan = bulk_scan or {}
    has_bulk = bool(
        has_bulk_code or lines or bulk_resolution or int(scan.get("count") or 0) > 0
    )
    if not has_bulk:
        return None, False
    cleared = bag_bulk_review_cleared(bulk_resolution, lines)
    return cleared, not cleared


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

    from backend.rinse_bulk_workitems import load_bag_bulk_lines, load_bulk_resolutions
    from backend.rinse_veewash_shift_day import (
        get_day_record,
        load_day_bags_by_ids,
        summary_from_day_record,
    )

    t0 = time.perf_counter()
    cat = str(category or "").strip().lower()
    if cat not in REVIEW_DRAWER_CATEGORIES:
        return {
            "ok": False,
            "error": "invalid_category",
            "message": (
                "category must be specialty_items, missing_from_portal, "
                "split_order_review, manual_review, unknown_review, or review_required"
            ),
        }

    day = get_day_record(cursor, organization_id, selected_date_et)
    headline = summary_from_day_record(day) or {}
    membership = compute_canonical_wf_review_membership(
        cursor, organization_id, selected_date_et, headline=headline
    )
    try:
        clear_stale_completed_wf_review_day_bag_codes(
            cursor, organization_id, selected_date_et, membership
        )
    except Exception:
        pass
    split = split_review_categories(headline, membership=membership)
    specialty_ids = list(membership.get(CATEGORY_SPECIALTY) or [])
    missing_ids = list(membership.get(CATEGORY_MISSING_PORTAL) or [])
    split_ids = list(membership.get(CATEGORY_SPLIT_ORDER) or [])
    manual_ids = list(membership.get(CATEGORY_MANUAL_REVIEW) or [])
    unknown_ids = list(membership.get(CATEGORY_UNKNOWN) or [])
    union_ids = list(
        dict.fromkeys(
            [*specialty_ids, *missing_ids, *split_ids, *manual_ids, *unknown_ids]
        )
    )
    all_member_ids = list(union_ids)
    rows_by_id: dict[str, dict[str, Any]] = {}
    if all_member_ids:
        status_rows = load_day_bags_by_ids(
            cursor, organization_id, selected_date_et, all_member_ids, status_only=False
        )
        rows_by_id = {
            normalize_bag_id(r.get("bag_id")): r
            for r in status_rows
            if normalize_bag_id(r.get("bag_id"))
        }
    specialty_ids = _filter_wf_service_bag_ids(specialty_ids, rows_by_id)
    missing_ids = _filter_wf_service_bag_ids(missing_ids, rows_by_id)
    split_ids = _filter_wf_service_bag_ids(split_ids, rows_by_id)
    manual_ids = _filter_wf_service_bag_ids(manual_ids, rows_by_id)
    unknown_ids = _filter_wf_service_bag_ids(unknown_ids, rows_by_id)
    union_ids = list(
        dict.fromkeys(
            [*specialty_ids, *missing_ids, *split_ids, *manual_ids, *unknown_ids]
        )
    )
    drawer_counts = _membership_result_payload(
        specialty_ids,
        missing_ids,
        split_ids,
        manual=manual_ids,
        unknown=unknown_ids,
    )["counts"]

    if cat == CATEGORY_REVIEW_ALL:
        bag_ids = union_ids
    elif cat == CATEGORY_SPECIALTY:
        bag_ids = specialty_ids
    elif cat == CATEGORY_MISSING_PORTAL:
        bag_ids = missing_ids
    elif cat == CATEGORY_MANUAL_REVIEW:
        bag_ids = manual_ids
    elif cat == CATEGORY_UNKNOWN:
        bag_ids = unknown_ids
    else:
        bag_ids = split_ids
    by_reason, by_bag = _headline_maps(headline)

    rush = str(rush_filter or "all").strip().lower()
    if rush in ("rush", "non_rush", "non-rush"):
        want_rush = rush in ("rush",)
        filtered: list[str] = []
        if bag_ids:
            for bid in bag_ids:
                row = rows_by_id.get(bid) or {}
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

    # Counts share the same final membership as headline + other drawers.
    scoped_counts = dict(drawer_counts)
    scoped_counts[cat] = total
    if rush in ("all", ""):
        scoped_counts["review_required"] = int(drawer_counts.get("review_required") or 0)
    else:
        scoped_counts["review_required"] = total

    rows = []
    if page_ids:
        missing_rows = [bid for bid in page_ids if bid not in rows_by_id]
        if missing_rows:
            for r in load_day_bags_by_ids(
                cursor, organization_id, selected_date_et, missing_rows
            ):
                nb = normalize_bag_id(r.get("bag_id"))
                if nb:
                    rows_by_id[nb] = r
        rows = [rows_by_id[bid] for bid in page_ids if bid in rows_by_id]
    by_id = {normalize_bag_id(r.get("bag_id")): r for r in rows}
    by_reason, by_bag = _headline_maps(headline)

    bulk_lines: dict = {}
    bulk_res_page: dict = {}
    bulk_scans_page: dict = {}
    if page_ids:
        bulk_res_page = load_bulk_resolutions(
            cursor, organization_id, selected_date_et, page_ids
        )
        if cat in (
            CATEGORY_SPECIALTY,
            CATEGORY_MISSING_PORTAL,
            CATEGORY_MANUAL_REVIEW,
            CATEGORY_REVIEW_ALL,
        ):
            from backend.rinse_bulk_workitems import load_bulk_workitem_scan_map

            bulk_lines = load_bag_bulk_lines(
                cursor, organization_id, selected_date_et, page_ids
            )
            bulk_scans_page = load_bulk_workitem_scan_map(
                cursor, organization_id, page_ids, selected_date_et=selected_date_et
            )
    weight_map = _canonical_review_weights(
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
    if page_ids:
        name_rows = [{"bag_id": bid, "customer_name": None} for bid in page_ids]
        name_rows = resolve_customer_names_for_bags(
            cursor, organization_id, name_rows, selected_date_et=selected_date_et
        )
        name_by_id = {
            r["bag_id"]: review_customer_display_name(r.get("customer_name"))
            for r in name_rows
        }
    else:
        name_by_id = {}
    for bid in page_ids:
        row = by_id.get(bid) or {}
        snap = dict(row.get("bag_snapshot") or {})
        codes = list((membership.get("codes_by_bag") or {}).get(bid) or [])
        if not codes:
            codes = _resolve_bag_review_codes(bid, row, None, headline)
        if not codes:
            codes = list(snap.get("reason_codes") or [])
        codes = [str(c) for c in codes if c]
        qty_info = _specialty_qty_from_lines(bulk_lines.get(bid) or snap.get("bulk_workitems"))
        sev = split_evals.get(bid) or {}
        smeta = split_order_meta.get(bid) or {}
        if cat == CATEGORY_SPLIT_ORDER:
            reason = sev.get("review_reason") or smeta.get("review_reason")
            if reason and reason not in codes:
                codes = [str(reason)] + codes
        bulk_cleared, bulk_unresolved = _bulk_review_state_for_bag(
            codes,
            bulk_lines=bulk_lines.get(bid) or [],
            bulk_resolution=bulk_res_page.get(bid),
            bulk_scan=bulk_scans_page.get(bid),
        )
        flags = review_drawer_section_flags(
            codes,
            bulk_cleared=bulk_cleared,
            bulk_unresolved=bulk_unresolved,
        )
        bag_category = cat
        if cat == CATEGORY_REVIEW_ALL:
            bag_category = (membership.get("disposition") or {}).get(bid) or cat
        completion_employee = (
            snap.get("completed_by") or row.get("canonical_completion_employee")
        )
        completion_at = (
            snap.get("completion_at") or row.get("canonical_completion_timestamp")
        )
        bag_row = {
                "bag_id": bid,
                "customer_name": name_by_id.get(bid)
                or review_customer_display_name(
                    snap.get("customer_name"),
                    row.get("customer_name"),
                    smeta.get("customer_name"),
                ),
                "service_type": snap.get("service_type") or row.get("service_type"),
                "rush_flag": snap.get("rush_flag")
                or row.get("rush_status")
                or smeta.get("rush"),
                "category": bag_category,
                "reason_codes": codes,
                "short_reason": _short_reason(codes, bag_category),
                "specialty_summary": _short_specialty_summary(qty_info),
                "comforter_quantity": qty_info.get("comforter_quantity") or 0,
                "bath_mat_quantity": qty_info.get("bath_mat_quantity") or 0,
                "specialty_quantity": qty_info.get("specialty_quantity"),
                "specialty_item_class": qty_info.get("specialty_item_class"),
                "has_specialty_bulk": flags["has_specialty_bulk"],
                "has_specialty_review": flags["has_specialty_review"],
                "has_missing_portal": flags["has_missing_portal"],
                "bulk_review_cleared": bulk_cleared,
                "bulk_review_unresolved": bulk_unresolved,
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
            else (
                "Manual Review"
                if category == CATEGORY_MANUAL_REVIEW
                else (
                    "Other Review"
                    if category == CATEGORY_UNKNOWN
                    else "Specialty Items"
                )
            )
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
        load_bulk_workitem_scan_map,
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

    bulk_lines = load_bag_bulk_lines(
        cursor, organization_id, selected_date_et, [bid]
    ).get(bid) or []
    bulk_res = load_bulk_resolutions(
        cursor, organization_id, selected_date_et, [bid]
    ).get(bid)
    bulk_scan = (
        load_bulk_workitem_scan_map(
            cursor, organization_id, [bid], selected_date_et=selected_date_et
        )
        or {}
    ).get(bid)
    bulk_cleared, bulk_unresolved = _bulk_review_state_for_bag(
        codes,
        bulk_lines=bulk_lines,
        bulk_resolution=bulk_res,
        bulk_scan=bulk_scan,
    )
    flags = review_drawer_section_flags(
        codes,
        bulk_cleared=bulk_cleared,
        bulk_unresolved=bulk_unresolved,
    )
    category = category_for_reason_codes(codes)

    need_catalog = bool(flags["has_specialty_bulk"] or bulk_lines or bulk_res)
    catalog: list[dict[str, Any]] = []
    if need_catalog:
        catalog = list_workitems(cursor, organization_id, active_only=True)

    qty_info = _specialty_qty_from_lines(bulk_lines)
    completion_employee = snap.get("completed_by") or row.get("canonical_completion_employee")
    completion_at = snap.get("completion_at") or row.get("canonical_completion_timestamp")
    weight_map = _canonical_review_weights(cursor, organization_id, selected_date_et, [bid])
    weights = weight_map.get(bid) or {}

    name_rows = resolve_customer_names_for_bags(
        cursor,
        organization_id,
        [{"bag_id": bid, "customer_name": snap.get("customer_name") or row.get("customer_name")}],
        selected_date_et=selected_date_et,
    )
    customer_name = review_customer_display_name(
        (name_rows[0] if name_rows else {}).get("customer_name"),
        snap.get("customer_name"),
        row.get("customer_name"),
    )

    bag = {
        "bag_id": bid,
        "customer_name": customer_name,
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
        "has_specialty_review": flags["has_specialty_review"],
        "has_missing_portal": flags["has_missing_portal"],
        "bulk_review_cleared": bulk_cleared,
        "bulk_review_unresolved": bulk_unresolved,
        "corrected_pre_weight_lbs": weights.get("corrected_pre_weight_lbs"),
        "pre_weight_source": weights.get("pre_weight_source"),
        "review_category": category,
        "category": category,
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
