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
    """Parse numeric weight; null/blank/non-numeric → None. Zero/negatives kept as floats."""
    if raw is None:
        return None
    if isinstance(raw, str) and not raw.strip():
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _valid_positive_weight(raw: Any) -> float | None:
    """Valid revenue weight: strictly > 0. Ignores null/blank/non-numeric/≤0."""
    w = _parse_weight(raw)
    if w is None or w <= 0:
        return None
    return w


def derive_pre_post_weights(weight_values: Sequence[Any]) -> dict[str, Any]:
    """
    Chronological weight-event derivation.

    - Null/blank/non-numeric/negative are skipped as non-events when passed as bare values
    - Zero is a real recorded weight event (not treated as missing)
    - Pre  = first event with a numeric value >= 0 (prefer first > 0 when present)
    - Post = second numeric event (may be 0)

    Also returns:
      post_weight_event_exists
      post_weight_value  (includes 0)
      post_weight_valid_for_standard_weight_revenue  (True only when post > 0)
    """
    events: list[float] = []
    for raw in weight_values:
        w = _parse_weight(raw)
        if w is None or w < 0:
            continue
        events.append(w)

    empty = {
        "pre_weight_lbs": None,
        "post_weight_lbs": None,
        "post_weight_event_exists": False,
        "post_weight_value": None,
        "post_weight_valid_for_standard_weight_revenue": False,
    }
    if not events:
        return empty

    # Prefer first strictly positive as pre when available; else first numeric (may be 0).
    pre_idx = next((i for i, v in enumerate(events) if v > 0), 0)
    pre = events[pre_idx]
    remaining = events[pre_idx + 1 :]
    if not remaining:
        return {
            "pre_weight_lbs": pre,
            "post_weight_lbs": None,
            "post_weight_event_exists": False,
            "post_weight_value": None,
            "post_weight_valid_for_standard_weight_revenue": False,
        }
    post = remaining[0]
    return {
        "pre_weight_lbs": pre,
        "post_weight_lbs": post,
        "post_weight_event_exists": True,
        "post_weight_value": post,
        "post_weight_valid_for_standard_weight_revenue": post > 0,
    }


def derive_pre_post_from_weight_events(
    events: Sequence[Mapping[str, Any]],
    *,
    supplemental_positive: float | None = None,
) -> dict[str, Any]:
    """
    Event-aware derivation.

    ``events`` items: {value: float|None, is_weight_purpose: bool}
    A weight-entry purpose with null lbs still counts as a weight event.
    Null purpose values are treated as recorded 0 for post-slot display when the
    event exists (ingestion often stores 0 as NULL).
    """
    slots: list[float | None] = []
    for ev in events or []:
        if not isinstance(ev, Mapping):
            continue
        w = _parse_weight(ev.get("value"))
        is_purpose = bool(ev.get("is_weight_purpose"))
        if w is not None and w < 0:
            continue
        if w is not None:
            slots.append(w)
        elif is_purpose:
            slots.append(None)  # event exists, numeric unknown
        # else skip non-weight nulls

    # Fill first missing/zero-ish pre from supplemental positive (folding/registry).
    if supplemental_positive is not None and supplemental_positive > 0:
        if not slots:
            slots = [supplemental_positive]
        elif slots[0] is None or slots[0] == 0:
            slots[0] = supplemental_positive
        elif not any(s is not None and s > 0 for s in slots):
            slots.insert(0, supplemental_positive)

    numeric_for_derive: list[float] = []
    for i, s in enumerate(slots):
        if s is None:
            # Event with unknown lbs → treat as 0 so event chronology is preserved.
            numeric_for_derive.append(0.0)
        else:
            numeric_for_derive.append(float(s))

    derived = derive_pre_post_weights(numeric_for_derive)
    # post_weight_event_exists follows slot count, not only positive seconds.
    if len(slots) >= 2:
        second = slots[1]
        post_val = 0.0 if second is None else float(second)
        derived["post_weight_event_exists"] = True
        derived["post_weight_value"] = post_val
        derived["post_weight_lbs"] = post_val
        derived["post_weight_valid_for_standard_weight_revenue"] = post_val > 0
    return derived


def _coerce_weight_info(raw: Any) -> dict[str, Any]:
    """Accept structured {pre,post,...} or legacy scalar (treated as post)."""
    if isinstance(raw, Mapping):
        post_raw = raw.get("post_weight_lbs", raw.get("post", raw.get("weight_lbs")))
        post_parsed = _parse_weight(post_raw)
        event_exists = raw.get("post_weight_event_exists")
        if event_exists is None:
            event_exists = post_parsed is not None
        post_value = raw.get("post_weight_value")
        if post_value is None:
            post_value = post_parsed
        else:
            post_value = _parse_weight(post_value)
        return {
            "pre_weight_lbs": _parse_weight(raw.get("pre_weight_lbs", raw.get("pre"))),
            "post_weight_lbs": post_parsed,
            "post_weight_event_exists": bool(event_exists),
            "post_weight_value": post_value,
            "post_weight_valid_for_standard_weight_revenue": bool(
                raw.get("post_weight_valid_for_standard_weight_revenue")
                if "post_weight_valid_for_standard_weight_revenue" in raw
                else (post_value is not None and post_value > 0)
            ),
        }
    post = _parse_weight(raw)
    return {
        "pre_weight_lbs": None,
        "post_weight_lbs": post,
        "post_weight_event_exists": post is not None,
        "post_weight_value": post,
        "post_weight_valid_for_standard_weight_revenue": post is not None and post > 0,
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
) -> dict[str, Any]:
    """
    Mutate/return classification so Review Required includes CWO + WF post-weight gaps
    + WF bulk workitem review.

    Priority: Review > Completed > Pending. One bag → one review count.
    Review never removes bags from Active / service×rush population.

    create-workitem-bulk forces Step-1 service_type = WF (bulk is WF-only).
    Registry WF preferred over portal HD when they disagree.

    WF missing-post review only when no post weight *event* exists
    (recorded post=0 is not missing).
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
        if wia_map.get(bid):
            return True
        return bool(row.get("entry_source") or row.get("original_entry_date") or row.get("first_entry_at"))

    def resolve_service(bid: str, pres: Mapping[str, Any], row: Mapping[str, Any]) -> tuple[str, bool]:
        """Return (effective_service, mismatched). Bulk → WF; registry WF overrides portal HD."""
        portal = (
            _service_of(pres)
            or str(pres.get("service_type") or row.get("service_type") or "").upper()
        )
        reg = registry_svc.get(bid) or ""
        has_bulk = bool(bulk_scans.get(bid) and int((bulk_scans.get(bid) or {}).get("count") or 0) > 0)
        if has_bulk:
            return SERVICE_WF, portal == SERVICE_HD or reg == SERVICE_HD
        if reg == SERVICE_WF and portal == SERVICE_HD:
            return SERVICE_WF, True
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

    # --- WF missing POST *event* — only after canonical completion ------------
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
            }
        )
        pre_w = info["pre_weight_lbs"]
        post_w = info["post_weight_lbs"]
        post_exists = bool(info.get("post_weight_event_exists"))
        post_value = info.get("post_weight_value")
        if bid in rows_by_id:
            rows_by_id[bid]["pre_weight_lbs"] = pre_w
            rows_by_id[bid]["post_weight_lbs"] = post_w
            rows_by_id[bid]["post_weight_event_exists"] = post_exists
            rows_by_id[bid]["post_weight_value"] = post_value
            rows_by_id[bid]["post_weight_valid_for_standard_weight_revenue"] = bool(
                info.get("post_weight_valid_for_standard_weight_revenue")
            )
            rows_by_id[bid]["weight_lbs"] = (
                post_value if post_value is not None else (post_w if post_w is not None else pre_w)
            )

        if post_exists:
            continue
        if not has_valid_entry(bid, row):
            continue
        if _valid_positive_weight(pre_w) is None:
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
    Load pre/post WF weights from chronological weight events.

    Distinguishes:
      - post_weight_event_exists (second weight event present, value may be 0)
      - post_weight_value (includes 0)
      - post_weight_valid_for_standard_weight_revenue (post > 0)

    Latest Step-1 ``correct_weight`` corrections override effective post only
    (source scans are never modified).
    """
    from backend.ta_helpers import table_exists

    ids = sorted({_norm_bag(b) for b in bag_ids if _norm_bag(b)})
    empty = {
        b: {
            "pre_weight_lbs": None,
            "post_weight_lbs": None,
            "post_weight_event_exists": False,
            "post_weight_value": None,
            "post_weight_valid_for_standard_weight_revenue": False,
        }
        for b in ids
    }
    if not ids:
        return empty

    out = dict(empty)
    events_by: dict[str, list[dict[str, Any]]] = {b: [] for b in ids}
    supplemental: dict[str, float] = {}

    if table_exists(cursor, "rinse_bag_scan_events"):
        placeholders = ",".join(["%s"] * len(ids))
        cursor.execute(
            f"""
            SELECT bag_id, weight_lbs, purpose, scanned_at_parsed, id
            FROM rinse_bag_scan_events
            WHERE organization_id = %s
              AND bag_id IN ({placeholders})
              AND (
                weight_lbs IS NOT NULL
                OR LOWER(COALESCE(purpose, '')) LIKE '%%weight%%'
              )
            ORDER BY scanned_at_parsed ASC, id ASC
            """,
            (int(organization_id), *ids),
        )
        for row in cursor.fetchall() or []:
            bid = _norm_bag(row.get("bag_id"))
            if bid not in events_by:
                continue
            purpose = str(row.get("purpose") or "")
            events_by[bid].append(
                {
                    "value": row.get("weight_lbs"),
                    "is_weight_purpose": "weight" in purpose.lower(),
                }
            )

    # Supplemental positive weights from folding / registry when scan lbs are null.
    if table_exists(cursor, "rinse_folding_performance"):
        placeholders = ",".join(["%s"] * len(ids))
        cursor.execute(
            f"""
            SELECT bag_id, weight_lbs
            FROM rinse_folding_performance
            WHERE organization_id = %s AND bag_id IN ({placeholders})
            """,
            (int(organization_id), *ids),
        )
        for row in cursor.fetchall() or []:
            bid = _norm_bag(row.get("bag_id"))
            w = _valid_positive_weight(row.get("weight_lbs"))
            if bid and w is not None:
                supplemental[bid] = w
    if table_exists(cursor, "rinse_bag_registry"):
        placeholders = ",".join(["%s"] * len(ids))
        cursor.execute(
            f"""
            SELECT bag_id, weight_num
            FROM rinse_bag_registry
            WHERE organization_id = %s AND bag_id IN ({placeholders})
            """,
            (int(organization_id), *ids),
        )
        for row in cursor.fetchall() or []:
            bid = _norm_bag(row.get("bag_id"))
            w = _valid_positive_weight(row.get("weight_num"))
            if bid and w is not None and bid not in supplemental:
                supplemental[bid] = w

    for bid in ids:
        out[bid] = derive_pre_post_from_weight_events(
            events_by.get(bid) or [],
            supplemental_positive=supplemental.get(bid),
        )

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
            # Corrections may set post including 0.
            post = _parse_weight(
                raw.get("corrected_post_weight_lbs", raw.get("post_weight_lbs", raw.get("weight_lbs")))
            )
            if post is None:
                continue
            detected = out[bid]
            out[bid] = {
                **detected,
                "pre_weight_lbs": detected.get("pre_weight_lbs"),
                "post_weight_lbs": post,
                "post_weight_event_exists": True,
                "post_weight_value": post,
                "post_weight_valid_for_standard_weight_revenue": post > 0,
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
