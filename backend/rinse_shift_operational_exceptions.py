"""Shift Analysis operational exceptions and workitem/issue stats."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Mapping, Sequence

from backend.rinse_bag_completion import rack_contains_clean
from backend.rinse_bag_gaming_performance import (
    STAGE_COMPLETED,
    _event_ts,
    _ts_valid,
    evaluate_sorting_stage,
    gaming_events_from_records,
)
from backend.rinse_bag_stage_bounds import workitem_eligible_events
from backend.rinse_processing_settings import (
    DEFAULT_REJECT_AFTER_CREATE_ISSUE,
    DEFAULT_REJECT_NO_START,
)
from backend.rinse_scan_purpose import (
    is_create_bulk_workitem_purpose,
    is_create_issue_purpose,
    is_create_workitem_purpose,
    is_drying_purpose,
    is_processed_by_vendor_purpose,
    is_start_cleaning_purpose,
)

ORDER_REJECT_NO_START_CLEANING_AFTER_LIMIT = "ORDER_REJECT_NO_START_CLEANING_AFTER_LIMIT"
ORDER_REJECTED_FULL = "ORDER_REJECTED_FULL"
COMPLETED_WITHOUT_FINAL_CLEAN_SCAN = "COMPLETED_WITHOUT_FINAL_CLEAN_SCAN"
NEEDS_REVIEW_EXTERNAL_SCAN_AFTER_CLEAN = "NEEDS_REVIEW_EXTERNAL_SCAN_AFTER_CLEAN"
CHECKOUT_WITHOUT_CLEAN_RACK = "CHECKOUT_WITHOUT_CLEAN_RACK"
# Legacy alias — same operational meaning, do not use for lifecycle SENT_TO_RINSE.
SENT_TO_RINSE_WITHOUT_CLEAN_RACK = CHECKOUT_WITHOUT_CLEAN_RACK

# Legacy alias for stored filters / old clients
ORDER_REJECT_NO_START_CLEANING_30_MIN = ORDER_REJECT_NO_START_CLEANING_AFTER_LIMIT

OPERATIONAL_EXCEPTION_LABELS: dict[str, str] = {
    ORDER_REJECT_NO_START_CLEANING_AFTER_LIMIT: "Rejected — no washing started within limit",
    ORDER_REJECTED_FULL: "Order rejected — washing not started after create-issue",
    COMPLETED_WITHOUT_FINAL_CLEAN_SCAN: "Completed without final scan",
    NEEDS_REVIEW_EXTERNAL_SCAN_AFTER_CLEAN: "External scan after CLEAN — review",
    CHECKOUT_WITHOUT_CLEAN_RACK: "Checked out without CLEAN rack scan",
    SENT_TO_RINSE_WITHOUT_CLEAN_RACK: "Checked out without CLEAN rack scan",
}

OPERATIONAL_STAT_LABELS: dict[str, str] = {
    "order_reject_no_start_cleaning_after_limit": "Rejected — no wash started",
    "completed_without_final_clean_scan": "Completed without final scan",
    "bags_with_issues": "Bags with issues",
    "bags_with_workitems": "Bags with workitems",
    "bags_with_bulk_workitems": "Bags with bulk workitems",
    "total_issue_events": "Total issue events",
    "total_workitem_events": "Total workitem events",
    "total_bulk_workitem_events": "Total bulk workitem events",
}


def _has_washing_completion_evidence(
    timeline: Sequence[Mapping[str, Any]],
    *,
    after: datetime | None = None,
) -> bool:
    """True when scan timeline shows washing/completion after an optional anchor."""
    for ev in timeline:
        ts = _event_ts(ev)
        if after is not None:
            if not _ts_valid(ts) or not _ts_valid(after) or ts <= after:
                continue
        purpose = ev.get("purpose")
        if is_start_cleaning_purpose(purpose):
            return True
        if is_drying_purpose(purpose):
            return True
        if is_processed_by_vendor_purpose(purpose):
            return True
        rack = str(ev.get("rack") or "").strip()
        if rack and rack_contains_clean(rack):
            return True
    return False


def bag_workitem_issue_stats(timeline: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    eligible = workitem_eligible_events(timeline)
    workitems = [ev for ev in eligible if is_create_workitem_purpose(ev.get("purpose"))]
    bulk = [ev for ev in eligible if is_create_bulk_workitem_purpose(ev.get("purpose"))]
    issues = [ev for ev in timeline if is_create_issue_purpose(ev.get("purpose"))]
    return {
        "create_workitem_count": len(workitems),
        "create_issue_count": len(issues),
        "create_bulk_workitem_count": len(bulk),
        "has_workitem": len(workitems) > 0,
        "has_issue": len(issues) > 0,
        "has_bulk_workitem": len(bulk) > 0,
    }


def evaluate_order_reject_no_start_cleaning_after_limit(
    timeline: Sequence[Mapping[str, Any]],
    *,
    window_minutes: int = DEFAULT_REJECT_NO_START,
) -> dict[str, Any] | None:
    """
    Reject when no create-issue exists, sorting/prep ended, and no start-cleaning
    within ``window_minutes`` after sorting end.
    """
    limit = max(1, int(window_minutes or DEFAULT_REJECT_NO_START))
    tl = list(timeline)
    create_issue_present = any(is_create_issue_purpose(ev.get("purpose")) for ev in tl)
    if create_issue_present:
        return None

    sorting = evaluate_sorting_stage(tl)
    if sorting.status != STAGE_COMPLETED or sorting.end_time is None:
        return None

    sorting_end = sorting.end_time
    deadline = sorting_end + timedelta(minutes=limit)

    if _has_washing_completion_evidence(tl, after=sorting_end):
        return None

    actual_start_cleaning: datetime | None = None
    for ev in tl:
        if not is_start_cleaning_purpose(ev.get("purpose")):
            continue
        ts = _event_ts(ev)
        if _ts_valid(ts) and ts > sorting_end:
            actual_start_cleaning = ts
            break

    if actual_start_cleaning is not None:
        return None

    reason = f"No start-cleaning within {limit} minutes after sorting/prep end"
    return {
        "exception_code": ORDER_REJECT_NO_START_CLEANING_AFTER_LIMIT,
        "exception_label": OPERATIONAL_EXCEPTION_LABELS[ORDER_REJECT_NO_START_CLEANING_AFTER_LIMIT],
        "configured_limit_minutes": limit,
        "sorting_prep_end_time": sorting_end,
        "expected_latest_start_cleaning_time": deadline,
        "actual_start_cleaning_time": actual_start_cleaning,
        "create_issue_present": False,
        "reason": reason,
    }


def _resolve_evaluation_time(
    timeline: Sequence[Mapping[str, Any]],
    evaluation_time: datetime | None,
) -> datetime:
    if evaluation_time is not None and _ts_valid(evaluation_time):
        return evaluation_time
    latest: datetime | None = None
    for ev in timeline:
        ts = _event_ts(ev)
        if _ts_valid(ts) and (latest is None or ts > latest):
            latest = ts
    return latest if latest is not None else datetime.utcnow()


def evaluate_order_rejected_full(
    timeline: Sequence[Mapping[str, Any]],
    *,
    window_minutes: int = DEFAULT_REJECT_AFTER_CREATE_ISSUE,
    after: datetime | None = None,
    evaluation_time: datetime | None = None,
) -> dict[str, Any] | None:
    """
    Time-gated full-order reject when create-issue exists and washing did not start
    within ``window_minutes`` after create-issue, evaluated only once
    ``evaluation_time`` is past the reject deadline.
    """
    limit = max(1, int(window_minutes or DEFAULT_REJECT_AFTER_CREATE_ISSUE))
    issue_ev: Mapping[str, Any] | None = None
    issue_at: datetime | None = None
    for ev in timeline:
        if not is_create_issue_purpose(ev.get("purpose")):
            continue
        ts = _event_ts(ev)
        if not _ts_valid(ts):
            continue
        if after is not None and _ts_valid(after) and ts < after:
            continue
        if issue_at is None or ts < issue_at:
            issue_ev = ev
            issue_at = ts
    if issue_ev is None or issue_at is None:
        return None

    deadline = issue_at + timedelta(minutes=limit)
    eval_at = _resolve_evaluation_time(timeline, evaluation_time)

    actual_start: datetime | None = None
    for ev in timeline:
        if not is_start_cleaning_purpose(ev.get("purpose")):
            continue
        ts = _event_ts(ev)
        if not _ts_valid(ts) or ts <= issue_at:
            continue
        if actual_start is None or ts < actual_start:
            actual_start = ts

    if actual_start is not None:
        return {
            "exception_code": None,
            "order_rejected_full": False,
            "configured_limit_minutes": limit,
            "create_issue_time": issue_at,
            "reject_deadline": deadline,
            "evaluation_time": eval_at,
            "actual_start_cleaning_after_issue": actual_start,
            "reason": "Start-cleaning occurred after create-issue",
        }

    for ev in timeline:
        ts = _event_ts(ev)
        if not _ts_valid(ts) or ts <= issue_at:
            continue
        purpose = ev.get("purpose")
        rack = str(ev.get("rack") or "").strip()
        if (
            is_drying_purpose(purpose)
            or is_processed_by_vendor_purpose(purpose)
            or (rack and rack_contains_clean(rack))
        ):
            return {
                "exception_code": None,
                "order_rejected_full": False,
                "configured_limit_minutes": limit,
                "create_issue_time": issue_at,
                "reject_deadline": deadline,
                "evaluation_time": eval_at,
                "actual_start_cleaning_after_issue": None,
                "reason": "Washing/completion evidence after create-issue",
            }

    if eval_at <= deadline:
        return {
            "exception_code": None,
            "order_rejected_full": False,
            "configured_limit_minutes": limit,
            "create_issue_time": issue_at,
            "reject_deadline": deadline,
            "evaluation_time": eval_at,
            "actual_start_cleaning_after_issue": actual_start,
            "reason": "Reject deadline not yet reached at evaluation time",
        }

    reason = "No start-cleaning within limit after create-issue"
    return {
        "exception_code": ORDER_REJECTED_FULL,
        "exception_label": OPERATIONAL_EXCEPTION_LABELS[ORDER_REJECTED_FULL],
        "order_rejected_full": True,
        "configured_limit_minutes": limit,
        "create_issue_time": issue_at,
        "reject_deadline": deadline,
        "evaluation_time": eval_at,
        "actual_start_cleaning_after_issue": actual_start,
        "expected_latest_start_cleaning_time": deadline,
        "actual_start_cleaning_time": actual_start,
        "reason": reason,
    }


def evaluate_completed_without_final_clean_scan(
    timeline: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    """Exception when PROCESSED BY VENDOR exists but no rack scan contains CLEAN."""
    tl = list(timeline)
    processed_ev: Mapping[str, Any] | None = None
    processed_at: datetime | None = None
    for ev in tl:
        if not is_processed_by_vendor_purpose(ev.get("purpose")):
            continue
        ts = _event_ts(ev)
        if _ts_valid(ts):
            processed_ev = ev
            processed_at = ts
            break

    if processed_ev is None or processed_at is None:
        return None

    clean_racks: list[dict[str, Any]] = []
    rack_scans_after: list[dict[str, Any]] = []
    for ev in tl:
        ts = _event_ts(ev)
        if not _ts_valid(ts):
            continue
        rack = str(ev.get("rack") or "").strip()
        if not rack:
            continue
        entry = {
            "rack": rack,
            "scanned_at": ts,
            "user_name": ev.get("user") or ev.get("user_name"),
            "contains_clean": rack_contains_clean(rack),
        }
        if entry["contains_clean"]:
            clean_racks.append(entry)
        if ts > processed_at:
            rack_scans_after.append(entry)

    if clean_racks:
        return None

    return {
        "exception_code": COMPLETED_WITHOUT_FINAL_CLEAN_SCAN,
        "exception_label": OPERATIONAL_EXCEPTION_LABELS[COMPLETED_WITHOUT_FINAL_CLEAN_SCAN],
        "processed_by_vendor_at": processed_at,
        "rack_scans_after_processed": rack_scans_after,
        "has_clean_rack_after_processed": False,
        "reason": "No rack scan containing CLEAN when PROCESSED BY VENDOR is present",
    }


def evaluate_bag_operational_profile(
    events: Sequence[Mapping[str, Any]],
    *,
    bag_meta: Mapping[str, Any] | None = None,
    reject_no_start_cleaning_minutes: int = DEFAULT_REJECT_NO_START,
) -> dict[str, Any]:
    """Full operational evaluation for one bag (exceptions + workitem stats)."""
    meta = dict(bag_meta or {})
    timeline = gaming_events_from_records(events)
    workitem_stats = bag_workitem_issue_stats(timeline)

    exceptions: list[dict[str, Any]] = []
    reject = evaluate_order_reject_no_start_cleaning_after_limit(
        timeline, window_minutes=reject_no_start_cleaning_minutes
    )
    if reject:
        exceptions.append(reject)
    missing_clean = evaluate_completed_without_final_clean_scan(timeline)
    if missing_clean:
        exceptions.append(missing_clean)

    primary = exceptions[0] if exceptions else None
    bid = str(meta.get("bag_id") or "").strip()

    return {
        "bag_id": bid,
        "order_id": meta.get("order_id") or bid,
        "customer": meta.get("customer") or meta.get("name_clean"),
        "name_clean": meta.get("name_clean") or meta.get("customer"),
        "weight_lbs": meta.get("weight_lbs") or meta.get("weight_num"),
        "rush": bool(meta.get("rush")),
        "rush_label": meta.get("rush_label") or ("Rush" if meta.get("rush") else "Non-Rush"),
        "group": meta.get("group"),
        "is_completed": bool(meta.get("is_completed")),
        "pending_bucket": meta.get("pending_bucket"),
        "activity": "operational",
        "status": "EXCEPTION" if exceptions else ("COMPLETED" if meta.get("is_completed") else "PENDING"),
        "exception_code": primary.get("exception_code") if primary else None,
        "exception_label": primary.get("exception_label") if primary else None,
        "exception_codes": [ex["exception_code"] for ex in exceptions],
        "exception_details": {ex["exception_code"]: ex for ex in exceptions},
        "in_scoring": False,
        "reason_not_scoring": primary.get("exception_code") if primary else None,
        "workitem_stats": workitem_stats,
    }


def aggregate_operational_stats(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    stats = {
        "order_reject_no_start_cleaning_after_limit": 0,
        "completed_without_final_clean_scan": 0,
        "bags_with_issues": 0,
        "bags_with_workitems": 0,
        "bags_with_bulk_workitems": 0,
        "total_issue_events": 0,
        "total_workitem_events": 0,
        "total_bulk_workitem_events": 0,
    }
    for row in records:
        codes = row.get("exception_codes") or []
        if ORDER_REJECT_NO_START_CLEANING_AFTER_LIMIT in codes:
            stats["order_reject_no_start_cleaning_after_limit"] += 1
        if COMPLETED_WITHOUT_FINAL_CLEAN_SCAN in codes:
            stats["completed_without_final_clean_scan"] += 1
        ws = row.get("workitem_stats") or {}
        if ws.get("has_issue"):
            stats["bags_with_issues"] += 1
        if ws.get("has_workitem"):
            stats["bags_with_workitems"] += 1
        if ws.get("has_bulk_workitem"):
            stats["bags_with_bulk_workitems"] += 1
        stats["total_issue_events"] += int(ws.get("create_issue_count") or 0)
        stats["total_workitem_events"] += int(ws.get("create_workitem_count") or 0)
        stats["total_bulk_workitem_events"] += int(ws.get("create_bulk_workitem_count") or 0)
    return stats


def _drill_filter_matches(filter_key: str, codes: list[str], ws: dict[str, Any]) -> bool:
    if filter_key in (
        "order_reject_no_start_cleaning_after_limit",
        "order_reject_no_start_cleaning_30_min",
    ):
        return ORDER_REJECT_NO_START_CLEANING_AFTER_LIMIT in codes
    if filter_key == "completed_without_final_clean_scan":
        return COMPLETED_WITHOUT_FINAL_CLEAN_SCAN in codes
    if filter_key == "bags_with_issues":
        return bool(ws.get("has_issue"))
    if filter_key == "bags_with_workitems":
        return bool(ws.get("has_workitem"))
    if filter_key == "bags_with_bulk_workitems":
        return bool(ws.get("has_bulk_workitem"))
    if filter_key == "total_issue_events":
        return int(ws.get("create_issue_count") or 0) > 0
    if filter_key == "total_workitem_events":
        return int(ws.get("create_workitem_count") or 0) > 0
    if filter_key == "total_bulk_workitem_events":
        return int(ws.get("create_bulk_workitem_count") or 0) > 0
    return False


def filter_operational_records(
    records: Sequence[Mapping[str, Any]],
    *,
    drill_filter: str | None,
    rush_group: str | None = None,
    pending_bucket: str | None = None,
) -> list[dict[str, Any]]:
    """Filter operational records for dashboard drilldown."""
    out: list[dict[str, Any]] = []
    for row in records:
        if not isinstance(row, dict):
            continue
        if rush_group == "rush" and not row.get("rush"):
            continue
        if rush_group == "non_rush" and row.get("rush"):
            continue
        if pending_bucket == "completed" and not row.get("is_completed"):
            continue
        if pending_bucket == "pending" and row.get("is_completed"):
            continue
        if pending_bucket in ("not_weighed", "weighed_not_washed", "in_washing"):
            if row.get("pending_bucket") != pending_bucket:
                continue
        if not drill_filter:
            out.append(row)
            continue
        ws = row.get("workitem_stats") or {}
        codes = row.get("exception_codes") or []
        if _drill_filter_matches(drill_filter, codes, ws):
            out.append(row)
    return out
