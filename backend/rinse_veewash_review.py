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
    REASON_WF_ZERO_OR_MISSING_WEIGHT,
    SERVICE_HD,
    SERVICE_WF,
    _has_recognized_entry_for_service,
    _norm_bag,
    _service_of,
)


def _parse_weight(raw: Any) -> float | None:
    """Null/blank → None (ignored). Zero and positives are kept as numeric values."""
    if raw is None:
        return None
    if isinstance(raw, str) and not raw.strip():
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _post_weight_invalid(raw: Any) -> bool:
    """Post weight missing or <= 0 triggers WF Review Required."""
    w = _parse_weight(raw)
    if w is None:
        return True
    return w <= 0


def derive_pre_post_weights(weight_values: Sequence[Any]) -> dict[str, float | None]:
    """
    From chronological scrape weight readings (nulls ignored):

    - pre  = first non-null weight
    - post = later non-null weight when the value changes during the cycle
             (latest changed value wins)

    A single non-null reading sets pre only; post stays None until a change.
    """
    pre: float | None = None
    post: float | None = None
    for raw in weight_values:
        w = _parse_weight(raw)
        if w is None:
            continue
        if pre is None:
            pre = w
            continue
        if w != pre:
            post = w
    return {"pre_weight_lbs": pre, "post_weight_lbs": post}


def _coerce_weight_info(raw: Any) -> dict[str, float | None]:
    """Accept structured {pre,post} or legacy scalar (treated as post)."""
    if isinstance(raw, Mapping):
        return {
            "pre_weight_lbs": _parse_weight(
                raw.get("pre_weight_lbs", raw.get("pre"))
            ),
            "post_weight_lbs": _parse_weight(
                raw.get("post_weight_lbs", raw.get("post", raw.get("weight_lbs")))
            ),
        }
    # Legacy float/int → post only (tests / older callers)
    return {"pre_weight_lbs": None, "post_weight_lbs": _parse_weight(raw)}


def expand_review_required(
    result: dict[str, Any],
    *,
    selected_date_et: date,
    presence_by_bag: Mapping[str, Mapping[str, Any]],
    entry_by_bag: Mapping[str, Mapping[str, Any]],
    wia_by_bag: Mapping[str, Mapping[str, Any]] | None = None,
    weight_by_bag: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Mutate/return classification so Review Required includes CWO + WF post-weight gaps.

    Priority: Review > Completed > Pending. One bag → one review count.
    WF Review for weight uses post_weight only (pre may be null/zero without review).
    """
    D = selected_date_et
    prev_day = D - timedelta(days=1)
    wia_map = wia_by_bag or {}
    weight_map = weight_by_bag or {}

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

        svc = _service_of(pres) or str(pres.get("service_type") or row.get("service_type") or "").upper()
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

    # --- WF zero / missing POST weight (Active members) ----------------------
    active = new_today | carryover
    for bid in list(active):
        pres = presence_by_bag.get(bid) or {}
        row = rows_by_id.get(bid) or {}
        svc = _service_of(pres) or str(row.get("service_type") or "").upper()
        if svc != SERVICE_WF:
            continue
        info = _coerce_weight_info(
            weight_map.get(bid)
            if bid in weight_map
            else {
                "pre_weight_lbs": row.get("pre_weight_lbs"),
                "post_weight_lbs": row.get("post_weight_lbs", row.get("weight_lbs")),
            }
        )
        pre_w = info["pre_weight_lbs"]
        post_w = info["post_weight_lbs"]
        if bid in rows_by_id:
            rows_by_id[bid]["pre_weight_lbs"] = pre_w
            rows_by_id[bid]["post_weight_lbs"] = post_w
            # Display weight prefers post, else pre (for chronology summaries).
            rows_by_id[bid]["weight_lbs"] = post_w if post_w is not None else pre_w

        if not _post_weight_invalid(post_w):
            continue

        add_reason(bid, REASON_WF_ZERO_OR_MISSING_WEIGHT)
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
        rows_by_id[bid] = {
            **row,
            "pre_weight_lbs": pre_w,
            "post_weight_lbs": post_w,
            "weight_lbs": post_w if post_w is not None else pre_w,
            "outcome": OUTCOME_REVIEW_REQUIRED,
            "canonical_status": canon,
            "final_bucket": "review_required",
            "reason_codes": list(reasons.get(bid) or []),
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

    # Rebuild ordered lists
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
) -> dict[str, dict[str, float | None]]:
    """
    Load pre/post WF weights from scrape chronology.

    Null weight_lbs rows are ignored. First non-null → pre; a later changed
    non-null value → post (latest change wins). Review uses post only.

    Latest Step-1 ``correct_weight`` corrections override ``post_weight_lbs``.
    """
    from backend.ta_helpers import table_exists

    ids = sorted({_norm_bag(b) for b in bag_ids if _norm_bag(b)})
    empty = {b: {"pre_weight_lbs": None, "post_weight_lbs": None} for b in ids}
    if not ids:
        return empty

    out = dict(empty)
    if table_exists(cursor, "rinse_bag_scan_events"):
        placeholders = ",".join(["%s"] * len(ids))
        cursor.execute(
            f"""
            SELECT bag_id, weight_lbs, scanned_at_parsed, id
            FROM rinse_bag_scan_events
            WHERE organization_id = %s
              AND bag_id IN ({placeholders})
              AND weight_lbs IS NOT NULL
            ORDER BY scanned_at_parsed ASC, id ASC
            """,
            (int(organization_id), *ids),
        )
        series: dict[str, list[Any]] = {b: [] for b in ids}
        for row in cursor.fetchall() or []:
            bid = _norm_bag(row.get("bag_id"))
            if bid in series:
                series[bid].append(row.get("weight_lbs"))
        out = {bid: derive_pre_post_weights(vals) for bid, vals in series.items()}

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
            post = _parse_weight(raw.get("post_weight_lbs", raw.get("weight_lbs")))
            if post is None:
                continue
            out[bid] = {
                "pre_weight_lbs": out[bid].get("pre_weight_lbs"),
                "post_weight_lbs": post,
            }
    return out
