"""
Expand Step-1 Review Required with multi-reason codes and outcome priority.

Review Required takes priority over Completed/Pending for dashboard totals.
CWO bags are included in Active Workload via Review Required.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Mapping, Sequence

from backend.rinse_veewash_workload import (
    ENTRY_CLASS_CARRYOVER,
    ENTRY_CLASS_NEW,
    OUTCOME_COMPLETED,
    OUTCOME_PENDING,
    OUTCOME_REVIEW_REQUIRED,
    REASON_COMPLETED_WITHOUT_RECOGNIZED_ENTRY,
    REASON_COMPLETION_DETAILS_MISSING,
    REASON_DISAPPEARED_WITHOUT_COMPLETION,
    REASON_SCAN_CHRONOLOGY_STALE,
    REASON_SERVICE_CLASSIFICATION_MISMATCH,
    REASON_WF_BULK_WORKITEM_REVIEW,
    REASON_WF_ZERO_OR_MISSING_POST_WEIGHT,
    REASON_WF_ZERO_OR_MISSING_WEIGHT,  # noqa: F401 — alias
    SERVICE_HD,
    SERVICE_WF,
    _has_recognized_entry_for_service,
    _norm_bag,
    _service_of,
)


def _parse_weight(raw: Any) -> float | None:
    """Parse numeric weight; null/blank/non-numeric → None. Zero kept as 0.0."""
    from backend.rinse_wf_weight_events import normalize_scan_weight_lbs

    return normalize_scan_weight_lbs(raw)


def _valid_positive_weight(raw: Any) -> float | None:
    """Valid revenue weight: strictly > 0. Kept for callers outside missing-post review."""
    w = _parse_weight(raw)
    if w is None or w <= 0:
        return None
    return w


def purpose_is_weight_entry(purpose: Any) -> bool:
    """True for canonical weight-entry purpose (incl. trailing 'Last Scan' variants)."""
    p = str(purpose or "").strip().lower().replace("_", "-")
    return p == "weight-entry" or p.startswith("weight-entry ")


def _empty_weight_info() -> dict[str, Any]:
    return {
        "pre_weight_lbs": None,
        "post_weight_lbs": None,
        "pre_weight_at": None,
        "pre_weight_employee": None,
        "post_weight_at": None,
        "post_weight_employee": None,
        "weight_entry_count": 0,
        "post_weight_event_exists": False,
        "post_weight_value": None,
        "post_weight_valid_for_standard_weight_revenue": False,
        # Portal enrichment provenance (from rinse_bag_scan_events).
        "pre_weight_source": None,
        "pre_weight_observed_at": None,
        "pre_weight_attach_batch_id": None,
        "pre_weight_attach_reason": None,
        "post_weight_source": None,
        "post_weight_observed_at": None,
        "post_weight_attach_batch_id": None,
        "post_weight_attach_reason": None,
    }


def _copy_weight_provenance(dest: dict[str, Any], event: Mapping[str, Any], *, prefix: str) -> None:
    dest[f"{prefix}_weight_source"] = event.get("weight_source")
    dest[f"{prefix}_weight_observed_at"] = event.get("weight_observed_at")
    dest[f"{prefix}_weight_attach_batch_id"] = event.get("weight_attach_batch_id")
    dest[f"{prefix}_weight_attach_reason"] = event.get("weight_attach_reason")


def resolve_weight_entry_pair(
    weight_entry_scans: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """
    Canonical Pre/Post from chronological weight-entry scans only.

    Pre  = weight_entry_scans[0]
    Post = weight_entry_scans[1] if present

    No portal snapshots, no numeric inference, no replacements.
    A second event with weight 0 is a real Post Weight (not missing).
    """
    events = [e for e in (weight_entry_scans or []) if isinstance(e, Mapping)]
    out = _empty_weight_info()
    out["weight_entry_count"] = len(events)
    if not events:
        return out

    pre = events[0]
    pre_w = _parse_weight(pre.get("weight_lbs", pre.get("value")))
    out["pre_weight_lbs"] = pre_w
    out["pre_weight_at"] = pre.get("scanned_at_parsed", pre.get("scanned_at"))
    out["pre_weight_employee"] = pre.get("user_name", pre.get("employee"))
    _copy_weight_provenance(out, pre, prefix="pre")

    if len(events) < 2:
        return out

    post = events[1]
    post_w = _parse_weight(post.get("weight_lbs", post.get("value")))
    out["post_weight_event_exists"] = True
    out["post_weight_lbs"] = post_w
    out["post_weight_value"] = post_w
    out["post_weight_at"] = post.get("scanned_at_parsed", post.get("scanned_at"))
    out["post_weight_employee"] = post.get("user_name", post.get("employee"))
    out["post_weight_valid_for_standard_weight_revenue"] = post_w is not None and post_w > 0
    _copy_weight_provenance(out, post, prefix="post")
    return out


def derive_pre_post_weights(weight_values: Sequence[Any]) -> dict[str, Any]:
    """
    Test/helper adapter: treat each sequence item as one weight-entry scan's lbs.

    Production path uses ``resolve_weight_entry_pair`` / ``load_bag_weight_map``.
    """
    synthetic = [{"weight_lbs": v} for v in weight_values]
    return resolve_weight_entry_pair(synthetic)


# Back-compat alias — old event-map helper; no supplemental inference.
def derive_pre_post_from_weight_events(
    events: Sequence[Mapping[str, Any]],
    *,
    supplemental_positive: float | None = None,
) -> dict[str, Any]:
    _ = supplemental_positive  # ignored — scan chronology only
    normalized: list[dict[str, Any]] = []
    for ev in events or []:
        if not isinstance(ev, Mapping):
            continue
        if ev.get("is_weight_purpose") is False:
            continue
        normalized.append(
            {
                "weight_lbs": ev.get("value", ev.get("weight_lbs")),
                "scanned_at_parsed": ev.get("scanned_at_parsed", ev.get("scanned_at")),
                "user_name": ev.get("user_name", ev.get("employee")),
            }
        )
    return resolve_weight_entry_pair(normalized)


def _coerce_weight_info(raw: Any) -> dict[str, Any]:
    """Accept structured weight info or legacy scalar (treated as post value only)."""
    if isinstance(raw, Mapping):
        post_parsed = _parse_weight(
            raw.get("post_weight_lbs", raw.get("post", raw.get("weight_lbs")))
        )
        event_exists = raw.get("post_weight_event_exists")
        if event_exists is None:
            event_exists = post_parsed is not None
        post_value = raw.get("post_weight_value")
        post_value = _parse_weight(post_value) if post_value is not None else post_parsed
        count = raw.get("weight_entry_count")
        if count is None:
            if bool(event_exists):
                count = 2
            elif raw.get("pre_weight_lbs", raw.get("pre")) is not None:
                count = 1
            else:
                count = 0
        return {
            "pre_weight_lbs": _parse_weight(raw.get("pre_weight_lbs", raw.get("pre"))),
            "post_weight_lbs": post_parsed,
            "pre_weight_at": raw.get("pre_weight_at"),
            "pre_weight_employee": raw.get("pre_weight_employee"),
            "post_weight_at": raw.get("post_weight_at"),
            "post_weight_employee": raw.get("post_weight_employee"),
            "weight_entry_count": int(count or 0),
            "post_weight_event_exists": bool(event_exists),
            "post_weight_value": post_value,
            "post_weight_valid_for_standard_weight_revenue": bool(
                raw.get("post_weight_valid_for_standard_weight_revenue")
                if "post_weight_valid_for_standard_weight_revenue" in raw
                else (post_value is not None and post_value > 0)
            ),
            "pre_weight_source": raw.get("pre_weight_source"),
            "pre_weight_observed_at": raw.get("pre_weight_observed_at"),
            "pre_weight_attach_batch_id": raw.get("pre_weight_attach_batch_id"),
            "pre_weight_attach_reason": raw.get("pre_weight_attach_reason"),
            "post_weight_source": raw.get("post_weight_source"),
            "post_weight_observed_at": raw.get("post_weight_observed_at"),
            "post_weight_attach_batch_id": raw.get("post_weight_attach_batch_id"),
            "post_weight_attach_reason": raw.get("post_weight_attach_reason"),
        }
    post = _parse_weight(raw)
    return {
        **_empty_weight_info(),
        "post_weight_lbs": post,
        "post_weight_event_exists": post is not None,
        "post_weight_value": post,
        "post_weight_valid_for_standard_weight_revenue": post is not None and post > 0,
        "weight_entry_count": 2 if post is not None else 0,
    }



def expand_review_required(
    result: dict[str, Any],
    *,
    selected_date_et: date,
    presence_by_bag: Mapping[str, Mapping[str, Any]],
    entry_by_bag: Mapping[str, Mapping[str, Any]],
    wia_by_bag: Mapping[str, Mapping[str, Any]] | None = None,
    weight_by_bag: Mapping[str, Any] | None = None,
    shift_closed: bool = False,
    bulk_scan_by_bag: Mapping[str, Mapping[str, Any]] | None = None,
    bulk_resolution_by_bag: Mapping[str, Mapping[str, Any]] | None = None,
    bulk_lines_by_bag: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    registry_service_by_bag: Mapping[str, str] | None = None,
    last_scan_at_by_bag: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Mutate/return classification so Review Required includes CWO + WF post-weight gaps
    + WF bulk workitem review.

    Priority: Review > Completed > Pending. One bag → one review count.
    Review never removes bags from Active / service×rush population.

    create-workitem-bulk is WF-only for review UI.

    Service signal from scan purposes:
      - Hang Dry: workitems-added at/after first weight-entry (often with
        create-workitem-bulk too)
      - WF with work items: create-workitem-bulk only (no classification-
        relevant workitems-added)
      - workitems-added *before* the first weight-entry is ignored (false HD
        signal from upstream tagging; e.g. 04FRSEC71H)

    So bulk does not redefine a bag that has relevant workitems-added + HD
    portal/registry. Bulk without relevant WIA forces WF. Registry WF still
    overrides portal HD.

    WF_ZERO_OR_MISSING_POST_WEIGHT only when the bag is canonically completed
    and exactly one weight-entry scan exists (no second event). Recorded post=0
    is a real Post Weight event, not missing.
    """
    _ = shift_closed
    D = selected_date_et
    prev_day = D - timedelta(days=1)
    wia_map = wia_by_bag or {}
    weight_map = weight_by_bag or {}
    bulk_scans = bulk_scan_by_bag or {}
    bulk_resolutions = bulk_resolution_by_bag or {}
    bulk_lines = bulk_lines_by_bag or {}
    registry_svc = {
        _norm_bag(k): str(v or "").strip().upper()
        for k, v in (registry_service_by_bag or {}).items()
        if _norm_bag(k)
    }

    from backend.rinse_bulk_workitems import bag_bulk_review_cleared

    rows_by_id = {r.get("bag_id"): dict(r) for r in (result.get("rows") or []) if r.get("bag_id")}
    new_today = set(result.get("new_today") or [])
    carryover = set(result.get("carryover") or [])
    completed = set(result.get("completed_on_date") or [])
    pending = set(result.get("pending_end_of_date") or [])
    review = set(result.get("review_required") or result.get("disappeared_without_completion_exceptions") or [])
    cwo = set(
        result.get("completed_without_recognized_entry")
        or result.get("completed_without_entry_scan")
        or []
    )
    disappeared = set(result.get("disappeared_without_completion_exceptions") or [])
    reasons: dict[str, list[str]] = {
        bid: list(codes)
        for bid, codes in (result.get("review_reasons_by_bag") or {}).items()
    }

    def add_reason(bid: str, code: str) -> None:
        lst = reasons.setdefault(bid, [])
        if code not in lst:
            lst.append(code)

    def is_canonically_completed(bid: str, row: Mapping[str, Any]) -> bool:
        if bid in completed or bid in cwo:
            return True
        if REASON_COMPLETED_WITHOUT_RECOGNIZED_ENTRY in (reasons.get(bid) or []):
            return True
        if row.get("completion_date") or row.get("completion_at"):
            return True
        canon = str(row.get("canonical_status") or "").lower()
        return "completed" in canon

    def has_valid_entry(bid: str, row: Mapping[str, Any]) -> bool:
        if entry_by_bag.get(bid):
            return True
        if has_workitems_added(bid):
            return True
        return bool(row.get("entry_source") or row.get("original_entry_date") or row.get("first_entry_at"))

    def has_workitems_added(bid: str) -> bool:
        """True only for classification-relevant WIA (not before first weight-entry)."""
        wia = wia_map.get(bid)
        if not wia:
            return False
        wia_at = wia.get("first_entry_at") or wia.get("scanned_at_parsed") or wia.get("scanned_at")
        wt_info = weight_map.get(bid) if bid in weight_map else None
        first_wt = None
        if isinstance(wt_info, Mapping):
            first_wt = wt_info.get("pre_weight_at")
        if first_wt is not None and wia_at is not None and wia_at < first_wt:
            return False
        return True

    def resolve_service(bid: str, pres: Mapping[str, Any], row: Mapping[str, Any]) -> tuple[str, bool]:
        """
        Effective Step-1 service from portal/registry + scan purposes.

        - Registry WF overrides portal HD (explicit WF identity).
        - Hang Dry has classification-relevant workitems-added (often with
          create-workitem-bulk too). WIA before first weight-entry is ignored.
        - WF with work items has create-workitem-bulk only — no relevant WIA.
        - Therefore: bulk + HD portal/registry + relevant WIA → keep HD;
          bulk without relevant WIA → WF.
        - Facility racks never determine service.
        """
        portal = (
            _service_of(pres)
            or str(pres.get("service_type") or row.get("service_type") or "").upper()
        )
        reg = registry_svc.get(bid) or ""
        has_bulk = bool(bulk_scans.get(bid) and int((bulk_scans.get(bid) or {}).get("count") or 0) > 0)
        has_wia = has_workitems_added(bid)

        if reg == SERVICE_WF and portal == SERVICE_HD:
            return SERVICE_WF, True
        if reg == SERVICE_WF:
            return SERVICE_WF, portal == SERVICE_HD

        portal_or_reg_hd = portal == SERVICE_HD or reg == SERVICE_HD
        if has_bulk and portal_or_reg_hd:
            # True Hang Dry: relevant workitems-added is present (bulk may coexist).
            if has_wia:
                return SERVICE_HD, False
            # WF with work items: create-workitem-bulk only (or only early WIA).
            return SERVICE_WF, True

        if has_bulk:
            return SERVICE_WF, portal == SERVICE_HD or reg == SERVICE_HD
        if reg in (SERVICE_WF, SERVICE_HD) and portal and reg != portal:
            return reg, True
        return portal or reg or SERVICE_WF, False

    # --- Remap service for bulk / registry WF (before other reviews) ----------
    active = new_today | carryover
    for bid in list(active):
        bid = _norm_bag(bid)
        if not bid:
            continue
        pres = presence_by_bag.get(bid) or {}
        row = rows_by_id.get(bid) or {"bag_id": bid}
        svc, mismatched = resolve_service(bid, pres, row)
        portal = _service_of(pres) or str(pres.get("service_type") or row.get("service_type") or "").upper()
        rows_by_id[bid] = {
            **row,
            "service_type": svc,
            "portal_service_type": portal or row.get("portal_service_type"),
            "registry_service_type": registry_svc.get(bid) or row.get("registry_service_type"),
        }
        if mismatched:
            add_reason(bid, REASON_SERVICE_CLASSIFICATION_MISMATCH)

    # Seed disappeared reasons
    for bid in disappeared:
        add_reason(bid, REASON_DISAPPEARED_WITHOUT_COMPLETION)
        review.add(bid)

    # SCAN_CHRONOLOGY_STALE is warning-only (data_freshness banner).
    # Do not move ordinary in-process Pending bags into Review Required.
    # Presence.last_seen_at is scrape wall-clock — only flag pending bags with
    # zero persisted scan events (failed association), not idle in-process bags.
    stale_scan_chronology_bag_ids: list[str] = []
    last_scan_map = {
        _norm_bag(k): v
        for k, v in (last_scan_at_by_bag or {}).items()
        if _norm_bag(k)
    }
    for bid in list(pending):
        bid = _norm_bag(bid)
        if not bid or bid in review or bid in completed:
            continue
        pres = presence_by_bag.get(bid) or {}
        if int(pres.get("active") or 0) != 1:
            continue
        if last_scan_map.get(bid) is None:
            stale_scan_chronology_bag_ids.append(bid)

    # --- CWO + HD missing WIA while completed ---------------------------------
    for bid, pres in presence_by_bag.items():
        bid = _norm_bag(bid)
        if not bid:
            continue
        row = rows_by_id.get(bid) or {}
        comp_date = None
        if row.get("completion_date"):
            try:
                comp_date = date.fromisoformat(str(row["completion_date"])[:10])
            except ValueError:
                comp_date = None
        if bid in cwo:
            comp_date = D
        if comp_date != D and bid not in completed and bid not in cwo:
            continue

        svc, _mm = resolve_service(bid, pres, row)
        entry = entry_by_bag.get(bid)
        wia = wia_map.get(bid)
        recognized = _has_recognized_entry_for_service(svc, dirty_entry=entry, wia_entry=wia)

        is_completed_today = bid in completed or bid in cwo or (
            row.get("outcome") == OUTCOME_COMPLETED and comp_date == D
        ) or (
            row.get("final_bucket") == "completed_without_recognized_entry"
        )
        if not is_completed_today and comp_date != D:
            continue

        if not recognized:
            add_reason(bid, REASON_COMPLETED_WITHOUT_RECOGNIZED_ENTRY)
            cwo.add(bid)
            review.add(bid)
            completed.discard(bid)
            pending.discard(bid)
            entry_date = entry.get("entry_date") if entry else None
            if entry_date is not None and entry_date < D:
                carryover.add(bid)
                new_today.discard(bid)
                entry_class = ENTRY_CLASS_CARRYOVER
                is_new = False
            else:
                new_today.add(bid)
                carryover.discard(bid)
                entry_class = ENTRY_CLASS_NEW
                is_new = True
            rows_by_id[bid] = {
                **row,
                **{
                    "bag_id": bid,
                    "service_type": svc or row.get("service_type"),
                    "rush_flag": pres.get("rush_flag") or row.get("rush_flag"),
                    "customer_name": pres.get("customer_name") or row.get("customer_name"),
                    "portal_status": pres.get("portal_status") or row.get("portal_status"),
                    "active": int(pres.get("active") or 0),
                    "entry_class": entry_class,
                    "entry_source": (entry or {}).get("entry_source")
                    or "completion_without_recognized_entry",
                    "outcome": OUTCOME_REVIEW_REQUIRED,
                    "canonical_status": OUTCOME_COMPLETED,
                    "final_bucket": "review_required",
                    "entry_scan_missing": True,
                    "reason_codes": list(reasons.get(bid) or []),
                    "current_workload_date": D.isoformat(),
                    "carried_from_date": None if is_new else prev_day.isoformat(),
                    "completion_date": D.isoformat(),
                    "completion_at": row.get("completion_at"),
                    "completed_by": row.get("completed_by"),
                },
            }

    # --- WF create-workitem-bulk → Review Required (before missing-post) ------
    active = new_today | carryover
    for bid in list(active):
        bid = _norm_bag(bid)
        if not bid:
            continue
        scan_info = bulk_scans.get(bid)
        if not scan_info or int(scan_info.get("count") or 0) <= 0:
            continue
        pres = presence_by_bag.get(bid) or {}
        row = rows_by_id.get(bid) or {}
        svc, _mm = resolve_service(bid, pres, row)
        if svc != SERVICE_WF:
            continue
        rows_by_id[bid] = {**(rows_by_id.get(bid) or row), "service_type": SERVICE_WF}
        if bag_bulk_review_cleared(bulk_resolutions.get(bid), list(bulk_lines.get(bid) or [])):
            if bid in rows_by_id:
                rows_by_id[bid]["bulk_workitem_scan"] = {
                    "count": scan_info.get("count"),
                    "first_at": scan_info.get("first_at"),
                    "last_at": scan_info.get("last_at"),
                    "employee": scan_info.get("employee"),
                }
                rows_by_id[bid]["bulk_workitems"] = list(bulk_lines.get(bid) or [])
                rows_by_id[bid]["bulk_resolution"] = bulk_resolutions.get(bid)
            continue

        add_reason(bid, REASON_WF_BULK_WORKITEM_REVIEW)
        review.add(bid)
        if bid in completed:
            completed.discard(bid)
        if bid in pending:
            pending.discard(bid)
        row = rows_by_id.get(bid) or {"bag_id": bid}
        rows_by_id[bid] = {
            **row,
            "service_type": SERVICE_WF,
            "outcome": OUTCOME_REVIEW_REQUIRED,
            "final_bucket": "review_required",
            "reason_codes": list(reasons.get(bid) or []),
            "bulk_workitem_scan": {
                "count": scan_info.get("count"),
                "first_at": scan_info.get("first_at"),
                "last_at": scan_info.get("last_at"),
                "employee": scan_info.get("employee"),
            },
            "bulk_workitems": list(bulk_lines.get(bid) or []),
            "bulk_resolution": bulk_resolutions.get(bid),
        }

    # --- WF missing POST weight-entry — completed + exactly one weight-entry -
    # Recorded second weight-entry with value 0 is NOT missing.
    active = new_today | carryover
    for bid in list(active):
        pres = presence_by_bag.get(bid) or {}
        row = rows_by_id.get(bid) or {}
        svc, _mm = resolve_service(bid, pres, row)
        if svc != SERVICE_WF:
            continue
        info = _coerce_weight_info(
            weight_map.get(bid)
            if bid in weight_map
            else {
                "pre_weight_lbs": row.get("pre_weight_lbs"),
                "post_weight_lbs": row.get("post_weight_lbs", row.get("weight_lbs")),
                "post_weight_event_exists": row.get("post_weight_event_exists"),
                "post_weight_value": row.get("post_weight_value"),
                "weight_entry_count": row.get("weight_entry_count"),
                "pre_weight_at": row.get("pre_weight_at"),
                "pre_weight_employee": row.get("pre_weight_employee"),
                "post_weight_at": row.get("post_weight_at"),
                "post_weight_employee": row.get("post_weight_employee"),
            }
        )
        pre_w = info["pre_weight_lbs"]
        post_w = info["post_weight_lbs"]
        post_exists = bool(info.get("post_weight_event_exists"))
        post_value = info.get("post_weight_value")
        entry_count = int(info.get("weight_entry_count") or 0)
        if bid in rows_by_id:
            rows_by_id[bid]["pre_weight_lbs"] = pre_w
            rows_by_id[bid]["post_weight_lbs"] = post_w
            rows_by_id[bid]["post_weight_event_exists"] = post_exists
            rows_by_id[bid]["post_weight_value"] = post_value
            rows_by_id[bid]["weight_entry_count"] = entry_count
            rows_by_id[bid]["pre_weight_at"] = info.get("pre_weight_at")
            rows_by_id[bid]["pre_weight_employee"] = info.get("pre_weight_employee")
            rows_by_id[bid]["post_weight_at"] = info.get("post_weight_at")
            rows_by_id[bid]["post_weight_employee"] = info.get("post_weight_employee")
            rows_by_id[bid]["pre_weight_source"] = info.get("pre_weight_source")
            rows_by_id[bid]["pre_weight_observed_at"] = info.get("pre_weight_observed_at")
            rows_by_id[bid]["pre_weight_attach_batch_id"] = info.get(
                "pre_weight_attach_batch_id"
            )
            rows_by_id[bid]["pre_weight_attach_reason"] = info.get(
                "pre_weight_attach_reason"
            )
            rows_by_id[bid]["post_weight_source"] = info.get("post_weight_source")
            rows_by_id[bid]["post_weight_observed_at"] = info.get(
                "post_weight_observed_at"
            )
            rows_by_id[bid]["post_weight_attach_batch_id"] = info.get(
                "post_weight_attach_batch_id"
            )
            rows_by_id[bid]["post_weight_attach_reason"] = info.get(
                "post_weight_attach_reason"
            )
            rows_by_id[bid]["post_weight_valid_for_standard_weight_revenue"] = bool(
                info.get("post_weight_valid_for_standard_weight_revenue")
            )
            rows_by_id[bid]["weight_lbs"] = (
                post_value if post_value is not None else (post_w if post_w is not None else pre_w)
            )

        if entry_count != 1 or post_exists:
            continue
        if not is_canonically_completed(bid, row):
            continue

        add_reason(bid, REASON_WF_ZERO_OR_MISSING_POST_WEIGHT)
        review.add(bid)
        if bid in completed:
            completed.discard(bid)
        if bid in pending and bid in review:
            pending.discard(bid)
        row = rows_by_id.get(bid) or {"bag_id": bid}
        canon = row.get("canonical_status") or row.get("outcome") or OUTCOME_PENDING
        if bid in cwo or REASON_COMPLETED_WITHOUT_RECOGNIZED_ENTRY in (reasons.get(bid) or []):
            canon = OUTCOME_COMPLETED
        elif row.get("completion_date") or row.get("completion_at"):
            canon = OUTCOME_COMPLETED
        elif bid in completed or is_canonically_completed(bid, row):
            canon = OUTCOME_COMPLETED
        rows_by_id[bid] = {
            **row,
            "pre_weight_lbs": pre_w,
            "post_weight_lbs": post_w,
            "post_weight_event_exists": False,
            "post_weight_value": post_value,
            "weight_entry_count": entry_count,
            "post_weight_valid_for_standard_weight_revenue": False,
            "weight_lbs": post_w if post_w is not None else pre_w,
            "outcome": OUTCOME_REVIEW_REQUIRED,
            "canonical_status": canon,
            "final_bucket": "review_required",
            "reason_codes": list(reasons.get(bid) or []),
        }

    # Ensure mismatched classification bags in review when flagged
    for bid, codes in list(reasons.items()):
        if REASON_SERVICE_CLASSIFICATION_MISMATCH in codes and bid in (new_today | carryover):
            review.add(bid)
            if bid in completed:
                completed.discard(bid)
            if bid in pending:
                pending.discard(bid)
            row = rows_by_id.get(bid) or {"bag_id": bid}
            rows_by_id[bid] = {
                **row,
                "outcome": OUTCOME_REVIEW_REQUIRED,
                "final_bucket": "review_required",
                "reason_codes": list(codes),
            }

    # Ensure disappeared stay in review not pending/completed
    for bid in disappeared:
        pending.discard(bid)
        completed.discard(bid)
        review.add(bid)
        row = rows_by_id.get(bid) or {"bag_id": bid}
        rows_by_id[bid] = {
            **row,
            "outcome": OUTCOME_REVIEW_REQUIRED,
            "final_bucket": "review_required",
            "reason_codes": list(reasons.get(bid) or [REASON_DISAPPEARED_WITHOUT_COMPLETION]),
        }

    # Sync reason_codes onto all review rows
    for bid in review:
        row = rows_by_id.get(bid)
        if not row:
            continue
        row["reason_codes"] = list(reasons.get(bid) or row.get("reason_codes") or [])
        row["outcome"] = OUTCOME_REVIEW_REQUIRED
        row["final_bucket"] = "review_required"

    new_today_l = sorted(new_today)
    carryover_l = sorted(carryover)
    completed_l = sorted(completed - review)
    pending_l = sorted(pending - review)
    review_l = sorted(review)
    cwo_l = sorted(cwo)
    active_n = len(new_today_l) + len(carryover_l)

    result = dict(result)
    result["new_today"] = new_today_l
    result["carryover"] = carryover_l
    result["completed_on_date"] = completed_l
    result["pending_end_of_date"] = pending_l
    result["review_required"] = review_l
    result["disappeared_without_completion_exceptions"] = sorted(disappeared)
    result["completed_without_recognized_entry"] = cwo_l
    result["completed_without_entry_scan"] = cwo_l
    result["review_reasons_by_bag"] = {b: list(reasons[b]) for b in sorted(reasons)}
    result["stale_scan_chronology_bag_ids"] = sorted(set(stale_scan_chronology_bag_ids))
    result["rows"] = [rows_by_id[b] for b in sorted(rows_by_id)]
    result["counts"] = {
        **(result.get("counts") or {}),
        "new_today": len(new_today_l),
        "carryover": len(carryover_l),
        "total_active_workload": active_n,
        "established_workload": active_n,
        "completed_on_date": len(completed_l),
        "pending_end_of_date": len(pending_l),
        "review_required": len(review_l),
        "disappeared_without_completion": len(disappeared),
        "completed_without_recognized_entry": len(cwo_l),
        "completed_without_entry_scan": len(cwo_l),
        "total_operational": active_n,
    }
    result["reconciliation"] = {
        "total_active_workload_equals_new_plus_carryover": active_n
        == len(new_today_l) + len(carryover_l),
        "members_partitioned": active_n
        == len(completed_l) + len(pending_l) + len(review_l),
        "active_equals_completed_plus_pending_plus_review": active_n
        == len(completed_l) + len(pending_l) + len(review_l),
    }
    return result


def build_review_by_reason(result: Mapping[str, Any]) -> dict[str, list[str]]:
    """Group review bag IDs by reason_code (a bag may appear in multiple groups)."""
    out: dict[str, list[str]] = {}
    reasons = result.get("review_reasons_by_bag") or {}
    for bid, codes in reasons.items():
        for code in codes or []:
            code = str(code or "").strip()
            if code == "WF_ZERO_OR_MISSING_WEIGHT":
                code = REASON_WF_ZERO_OR_MISSING_POST_WEIGHT
            if not code:
                continue
            out.setdefault(str(code), []).append(bid)
    for bid in result.get("disappeared_without_completion_exceptions") or []:
        out.setdefault(REASON_DISAPPEARED_WITHOUT_COMPLETION, [])
        if bid not in out[REASON_DISAPPEARED_WITHOUT_COMPLETION]:
            out[REASON_DISAPPEARED_WITHOUT_COMPLETION].append(bid)
    for bid in result.get("completed_without_recognized_entry") or []:
        out.setdefault(REASON_COMPLETED_WITHOUT_RECOGNIZED_ENTRY, [])
        if bid not in out[REASON_COMPLETED_WITHOUT_RECOGNIZED_ENTRY]:
            out[REASON_COMPLETED_WITHOUT_RECOGNIZED_ENTRY].append(bid)
    for k in list(out):
        out[k] = sorted(set(out[k]))
    return out


def load_bag_weight_map(
    cursor, organization_id: int, bag_ids: list[str]
) -> dict[str, dict[str, Any]]:
    """
    Pre/Post from chronological ``weight-entry`` scans only.

    Pre  = first weight-entry
    Post = second weight-entry (value may be 0)

    No portal/registry/folding inference. Manager ``correct_weight`` may override
    effective post without mutating source scans.
    """
    from backend.ta_helpers import table_exists

    ids = sorted({_norm_bag(b) for b in bag_ids if _norm_bag(b)})
    empty = {b: _empty_weight_info() for b in ids}
    if not ids:
        return empty

    out = dict(empty)
    events_by: dict[str, list[dict[str, Any]]] = {b: [] for b in ids}

    if table_exists(cursor, "rinse_bag_scan_events"):
        from backend.ta_helpers import table_has_column

        placeholders = ",".join(["%s"] * len(ids))
        provenance_cols = ""
        if table_has_column(cursor, "rinse_bag_scan_events", "weight_source"):
            provenance_cols = (
                ", weight_observed_at, weight_source, "
                "weight_attach_batch_id, weight_attach_reason"
            )
        cursor.execute(
            f"""
            SELECT bag_id, weight_lbs, purpose, scanned_at_parsed, user_name, id
                   {provenance_cols}
            FROM rinse_bag_scan_events
            WHERE organization_id = %s
              AND bag_id IN ({placeholders})
              AND scanned_at_parsed IS NOT NULL
            ORDER BY scanned_at_parsed ASC, id ASC
            """,
            (int(organization_id), *ids),
        )
        for row in cursor.fetchall() or []:
            bid = _norm_bag(row.get("bag_id"))
            if bid not in events_by:
                continue
            if not purpose_is_weight_entry(row.get("purpose")):
                continue
            events_by[bid].append(
                {
                    "weight_lbs": row.get("weight_lbs"),
                    "scanned_at_parsed": row.get("scanned_at_parsed"),
                    "user_name": row.get("user_name"),
                    "weight_source": row.get("weight_source"),
                    "weight_observed_at": row.get("weight_observed_at"),
                    "weight_attach_batch_id": row.get("weight_attach_batch_id"),
                    "weight_attach_reason": row.get("weight_attach_reason"),
                }
            )

    for bid in ids:
        out[bid] = resolve_weight_entry_pair(events_by.get(bid) or [])

    if table_exists(cursor, "rinse_step1_corrections"):
        placeholders = ",".join(["%s"] * len(ids))
        cursor.execute(
            f"""
            SELECT bag_id, new_values, created_at, id
            FROM rinse_step1_corrections
            WHERE organization_id = %s
              AND bag_id IN ({placeholders})
              AND action = 'correct_weight'
            ORDER BY created_at ASC, id ASC
            """,
            (int(organization_id), *ids),
        )
        for row in cursor.fetchall() or []:
            bid = _norm_bag(row.get("bag_id"))
            if bid not in out:
                continue
            raw = row.get("new_values")
            if isinstance(raw, str):
                try:
                    import json

                    raw = json.loads(raw)
                except Exception:
                    raw = {}
            if not isinstance(raw, dict):
                continue
            post = _parse_weight(
                raw.get(
                    "corrected_post_weight_lbs",
                    raw.get("post_weight_lbs", raw.get("weight_lbs")),
                )
            )
            if post is None:
                continue
            detected = out[bid]
            out[bid] = {
                **detected,
                "post_weight_lbs": post,
                "post_weight_event_exists": True,
                "post_weight_value": post,
                "post_weight_valid_for_standard_weight_revenue": post > 0,
                "weight_entry_count": max(int(detected.get("weight_entry_count") or 0), 2),
                "detected_pre_weight_lbs": detected.get("pre_weight_lbs"),
                "detected_post_weight_lbs": detected.get("post_weight_lbs"),
                "corrected_post_weight_lbs": post,
            }
    return out


def load_registry_service_map(
    cursor, organization_id: int, bag_ids: list[str]
) -> dict[str, str]:
    """bag_id → registry service_type (WF/HD) when present."""
    from backend.ta_helpers import table_exists

    ids = sorted({_norm_bag(b) for b in bag_ids if _norm_bag(b)})
    if not ids or not table_exists(cursor, "rinse_bag_registry"):
        return {}
    placeholders = ",".join(["%s"] * len(ids))
    cursor.execute(
        f"""
        SELECT bag_id, service_type
        FROM rinse_bag_registry
        WHERE organization_id = %s AND bag_id IN ({placeholders})
        """,
        (int(organization_id), *ids),
    )
    out: dict[str, str] = {}
    for row in cursor.fetchall() or []:
        bid = _norm_bag(row.get("bag_id"))
        svc = str(row.get("service_type") or "").strip().upper()
        if bid and svc in (SERVICE_WF, SERVICE_HD):
            out[bid] = svc
    return out
