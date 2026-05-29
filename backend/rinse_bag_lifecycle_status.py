"""
Per-bag lifecycle status derived from scan purposes, portal presence, and registry.

Lifecycle status is separate from operational_flags and exception_flags.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence

from backend.rinse_bag_completion import COMPLETION_COMPLETED, rack_contains_clean, user_is_internal
from backend.rinse_bag_folding import STATUS_CALCULATED, evaluate_folding_performance_for_bag
from backend.rinse_bag_gaming_performance import (
    _event_ts,
    _pick_sorting_end,
    _resolve_sorting_start,
    _sort_key_ev,
    _ts_valid,
    evaluate_bag_gaming_performance,
    gaming_events_from_records,
)
from backend.rinse_processing_settings import DEFAULT_REJECT_NO_START
from backend.rinse_scan_purpose import (
    is_create_bulk_workitem_purpose,
    is_create_issue_purpose,
    is_create_workitem_purpose,
    is_drying_purpose,
    is_received_from_vendor_purpose,
    is_sent_to_vendor_purpose,
    is_sorting_prep_end_marker_purpose,
    is_start_cleaning_purpose,
    is_weight_entry_purpose,
    normalize_scan_purpose,
)
from backend.rinse_shift_operational_exceptions import (
    COMPLETED_WITHOUT_FINAL_CLEAN_SCAN,
    ORDER_REJECT_NO_START_CLEANING_AFTER_LIMIT,
    evaluate_completed_without_final_clean_scan,
    evaluate_order_reject_no_start_cleaning_after_limit,
)

ASSIGNED_NOT_SENT_TO_VENDOR = "ASSIGNED_NOT_SENT_TO_VENDOR"
SENT_TO_VENDOR = "SENT_TO_VENDOR"
PENDING_WEIGHING = "PENDING_WEIGHING"
WEIGHED_NOT_STARTED = "WEIGHED_NOT_STARTED"
SORTED_READY_FOR_WASH = "SORTED_READY_FOR_WASH"
IN_WASHING = "IN_WASHING"
IN_DRYING = "IN_DRYING"
FOLDED_COMPLETED = "FOLDED_COMPLETED"
RETURNED_TO_RINSE = "RETURNED_TO_RINSE"
LIFECYCLE_UNKNOWN = "UNKNOWN"

ALL_LIFECYCLE_STATUSES = (
    ASSIGNED_NOT_SENT_TO_VENDOR,
    SENT_TO_VENDOR,
    PENDING_WEIGHING,
    WEIGHED_NOT_STARTED,
    SORTED_READY_FOR_WASH,
    IN_WASHING,
    IN_DRYING,
    FOLDED_COMPLETED,
    RETURNED_TO_RINSE,
    LIFECYCLE_UNKNOWN,
)

_LOGISTICS_RETURNED = frozenset({"SENT_TO_RINSE", "CHECKED_OUT", "FORCE_CHECKOUT"})


def _operator_name(ev: Mapping[str, Any]) -> str:
    return str(ev.get("user") or ev.get("user_name") or "").strip()


def _status_source_from_event(ev: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not ev:
        return None
    ts = _event_ts(ev)
    return {
        "scan_event_id": ev.get("id"),
        "purpose": ev.get("purpose"),
        "purpose_norm": normalize_scan_purpose(ev.get("purpose")),
        "rack": ev.get("rack"),
        "user_name": _operator_name(ev) or None,
        "scanned_at": ts if _ts_valid(ts) else None,
    }


def _presence_source(*, kind: str, present: bool) -> dict[str, Any] | None:
    if not present:
        return None
    return {"source_kind": kind, "present": True}


def operational_flags_from_timeline(timeline: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    issues = [ev for ev in timeline if is_create_issue_purpose(ev.get("purpose"))]
    workitems = [ev for ev in timeline if is_create_workitem_purpose(ev.get("purpose"))]
    bulk = [ev for ev in timeline if is_create_bulk_workitem_purpose(ev.get("purpose"))]
    return {
        "has_create_issue": len(issues) > 0,
        "has_create_workitem": len(workitems) > 0,
        "has_create_bulk_workitem": len(bulk) > 0,
        "create_issue_count": len(issues),
        "create_workitem_count": len(workitems),
        "create_bulk_workitem_count": len(bulk),
    }


def _is_mapped_internal_operator(name: str, mapped_users: set[str]) -> bool:
    n = name.casefold()
    return any(n == m.casefold() for m in mapped_users if m)


def _is_internal_operator(name: str, mapped_users: set[str]) -> bool:
    if not name:
        return False
    return user_is_internal(name) or _is_mapped_internal_operator(name, mapped_users)


def _registry_completed(registry_row: Mapping[str, Any] | None) -> bool:
    if not registry_row:
        return False
    return str(registry_row.get("completion_status") or "").upper() == COMPLETION_COMPLETED


def _registry_completed_at(registry_row: Mapping[str, Any] | None) -> datetime | None:
    if not registry_row:
        return None
    for key in ("completed_at", "trigger_scan_at", "first_clean_scan_at"):
        ts = registry_row.get(key)
        if isinstance(ts, datetime) and _ts_valid(ts):
            return ts
    return None


def _first_event_matching(
    timeline: Sequence[Mapping[str, Any]], pred
) -> Mapping[str, Any] | None:
    for ev in timeline:
        if pred(ev.get("purpose")):
            return ev
    return None


def _has_purpose(timeline: Sequence[Mapping[str, Any]], pred) -> bool:
    return _first_event_matching(timeline, pred) is not None


def _in_operational_queue(
    timeline: Sequence[Mapping[str, Any]],
    *,
    at_vendor_presence: bool,
) -> bool:
    return at_vendor_presence or _has_purpose(timeline, is_sent_to_vendor_purpose)


def _latest_sorting_prep_end_event(
    timeline: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    sorting_start, _ = _resolve_sorting_start(timeline)
    if sorting_start is None:
        return None
    after = [ev for ev in timeline if _ts_valid(_event_ts(ev)) and _event_ts(ev) > sorting_start]
    prep = [ev for ev in after if is_sorting_prep_end_marker_purpose(ev.get("purpose"))]
    if not prep:
        return None
    return max(prep, key=_sort_key_ev)


def _has_sorting_prep_end_marker(timeline: Sequence[Mapping[str, Any]]) -> bool:
    return _latest_sorting_prep_end_event(timeline) is not None


def _folding_calculated(
    events: Sequence[Mapping[str, Any]],
    registry_row: Mapping[str, Any] | None,
    folding_result: Any,
) -> bool:
    if folding_result is not None:
        return str(getattr(folding_result, "status", "") or "").upper() == STATUS_CALCULATED
    if not _registry_completed(registry_row):
        return False
    try:
        fr = evaluate_folding_performance_for_bag(events, registry_row=registry_row)
        return str(fr.status or "").upper() == STATUS_CALCULATED
    except Exception:
        return False


def _collect_exception_flags(
    timeline: Sequence[Mapping[str, Any]],
    events: Sequence[Mapping[str, Any]],
    *,
    registry_row: Mapping[str, Any] | None,
    reject_no_start_cleaning_minutes: int,
    folding_result: Any,
) -> list[str]:
    flags: list[str] = []

    reject = evaluate_order_reject_no_start_cleaning_after_limit(
        timeline, window_minutes=reject_no_start_cleaning_minutes
    )
    if reject:
        flags.append(ORDER_REJECT_NO_START_CLEANING_AFTER_LIMIT)

    missing_clean = evaluate_completed_without_final_clean_scan(timeline)
    if missing_clean:
        flags.append(COMPLETED_WITHOUT_FINAL_CLEAN_SCAN)

    if folding_result is None and _registry_completed(registry_row):
        try:
            folding_result = evaluate_folding_performance_for_bag(events, registry_row=registry_row)
        except Exception:
            folding_result = None

    if folding_result is not None:
        code = str(getattr(folding_result, "exception_code", "") or "").strip()
        if code:
            flags.append(code)
        for w in getattr(folding_result, "warning_codes", ()) or ():
            wc = str(w or "").strip()
            if wc and wc not in flags:
                flags.append(wc)

    gaming = evaluate_bag_gaming_performance(events, registry_row=registry_row)
    for stage_key in ("weighing", "sorting", "wash_load"):
        stage = gaming.get(stage_key) if isinstance(gaming, dict) else None
        if not isinstance(stage, dict):
            continue
        for code in stage.get("exception_codes") or []:
            c = str(code or "").strip()
            if c and c not in flags:
                flags.append(c)

    return flags


def _evaluate_returned(
    timeline: Sequence[Mapping[str, Any]],
    *,
    registry_row: Mapping[str, Any] | None,
    logistics_status: str | None,
    mapped_users: set[str],
) -> tuple[bool, dict[str, Any] | None, bool]:
    """
    Returns (is_returned, status_source_event, needs_review).
    """
    logistics = str(logistics_status or "").strip().upper()
    if logistics in _LOGISTICS_RETURNED:
        return True, {"source_kind": "logistics_status", "logistics_status": logistics}, False

    recv_ev = _first_event_matching(timeline, is_received_from_vendor_purpose)
    if recv_ev is not None:
        return True, _status_source_from_event(recv_ev), False

    completed = _registry_completed(registry_row)
    completed_at = _registry_completed_at(registry_row)
    if not completed:
        return False, None, False

    external_after: list[Mapping[str, Any]] = []
    for ev in timeline:
        ts = _event_ts(ev)
        if completed_at is not None and _ts_valid(ts) and ts <= completed_at:
            continue
        op = _operator_name(ev)
        if not op:
            continue
        if not _is_internal_operator(op, mapped_users):
            external_after.append(ev)

    if external_after:
        ev = max(external_after, key=_sort_key_ev)
        return True, _status_source_from_event(ev), True

    return False, None, False


def derive_bag_lifecycle_status(
    events: Sequence[Mapping[str, Any]],
    *,
    bag_id: str,
    order_id: str | None = None,
    ready_for_vendor_presence: bool = False,
    at_vendor_presence: bool = False,
    logistics_status: str | None = None,
    registry_row: Mapping[str, Any] | None = None,
    mapped_internal_users: Sequence[str] | None = None,
    reject_no_start_cleaning_minutes: int = DEFAULT_REJECT_NO_START,
    folding_result: Any = None,
) -> dict[str, Any]:
    """
    Derive normalized lifecycle status for one bag.

    ``ready_for_vendor_presence`` and ``at_vendor_presence`` are optional portal
    presence inputs (future ``rinse_cleaner_ticket_presence`` table). When absent,
    lifecycle falls back to scan-purpose signals only.
    """
    bid = str(bag_id or "").strip()
    oid = str(order_id or bid).strip() or bid
    timeline = gaming_events_from_records(events)
    mapped_users = {str(u).strip() for u in (mapped_internal_users or []) if str(u).strip()}

    operational_flags = operational_flags_from_timeline(timeline)
    exception_flags = _collect_exception_flags(
        timeline,
        events,
        registry_row=registry_row,
        reject_no_start_cleaning_minutes=reject_no_start_cleaning_minutes,
        folding_result=folding_result,
    )

    has_sent_to_vendor = _has_purpose(timeline, is_sent_to_vendor_purpose)
    in_queue = _in_operational_queue(timeline, at_vendor_presence=at_vendor_presence)
    has_weight = _has_purpose(timeline, is_weight_entry_purpose)
    has_start_cleaning = _has_purpose(timeline, is_start_cleaning_purpose)
    has_drying = _has_purpose(timeline, is_drying_purpose)
    has_sorting_prep_end = _has_sorting_prep_end_marker(timeline)
    completed = _registry_completed(registry_row) or _folding_calculated(
        events, registry_row, folding_result
    )

    needs_review = False
    status: str
    status_timestamp: datetime | None = None
    status_source_event: dict[str, Any] | None = None

    returned, returned_source, returned_review = _evaluate_returned(
        timeline,
        registry_row=registry_row,
        logistics_status=logistics_status,
        mapped_users=mapped_users,
    )
    if returned_review:
        needs_review = True

    if returned:
        status = RETURNED_TO_RINSE
        status_source_event = returned_source
        if returned_source and returned_source.get("scanned_at"):
            status_timestamp = returned_source["scanned_at"]
    elif completed:
        status = FOLDED_COMPLETED
        status_timestamp = _registry_completed_at(registry_row)
        if folding_result is not None and getattr(folding_result, "folding_end_at", None):
            status_timestamp = folding_result.folding_end_at
        clean_ev = None
        for ev in timeline:
            if rack_contains_clean(ev.get("rack")):
                clean_ev = ev
                break
        status_source_event = _status_source_from_event(clean_ev)
        if status_source_event and status_source_event.get("scanned_at"):
            status_timestamp = status_source_event["scanned_at"]
    elif has_drying and not returned:
        status = IN_DRYING
        dry_ev = _first_event_matching(timeline, is_drying_purpose)
        status_source_event = _status_source_from_event(dry_ev)
        status_timestamp = _event_ts(dry_ev) if dry_ev else None
    elif has_start_cleaning and not has_drying:
        status = IN_WASHING
        start_ev = _first_event_matching(timeline, is_start_cleaning_purpose)
        status_source_event = _status_source_from_event(start_ev)
        status_timestamp = _event_ts(start_ev) if start_ev else None
    elif has_sorting_prep_end and not has_start_cleaning:
        status = SORTED_READY_FOR_WASH
        prep_ev = _latest_sorting_prep_end_event(timeline)
        status_source_event = _status_source_from_event(prep_ev)
        status_timestamp = _event_ts(prep_ev) if prep_ev else None
    elif has_weight and not has_sorting_prep_end and not has_start_cleaning:
        status = WEIGHED_NOT_STARTED
        weight_ev = _first_event_matching(timeline, is_weight_entry_purpose)
        status_source_event = _status_source_from_event(weight_ev)
        status_timestamp = _event_ts(weight_ev) if weight_ev else None
    elif in_queue and not has_weight:
        if has_sent_to_vendor:
            status = PENDING_WEIGHING
            sent_ev = _first_event_matching(timeline, is_sent_to_vendor_purpose)
            status_source_event = _status_source_from_event(sent_ev)
            status_timestamp = _event_ts(sent_ev) if sent_ev else None
        else:
            status = SENT_TO_VENDOR
            status_source_event = _presence_source(kind="at_vendor", present=at_vendor_presence)
    elif in_queue:
        status = SENT_TO_VENDOR
        sent_ev = _first_event_matching(timeline, is_sent_to_vendor_purpose)
        status_source_event = _status_source_from_event(sent_ev) or _presence_source(
            kind="at_vendor", present=at_vendor_presence
        )
        status_timestamp = _event_ts(sent_ev) if sent_ev else None
    elif ready_for_vendor_presence and not has_sent_to_vendor and not at_vendor_presence:
        status = ASSIGNED_NOT_SENT_TO_VENDOR
        status_source_event = _presence_source(kind="ready_for_vendor", present=True)
    else:
        status = LIFECYCLE_UNKNOWN
        status_source_event = None

    return {
        "bag_id": bid,
        "order_id": oid,
        "current_lifecycle_status": status,
        "status_timestamp": status_timestamp,
        "status_source_event": status_source_event,
        "operational_flags": operational_flags,
        "exception_flags": exception_flags,
        "needs_review": needs_review,
        "presence_inputs": {
            "ready_for_vendor_presence": bool(ready_for_vendor_presence),
            "at_vendor_presence": bool(at_vendor_presence),
            "logistics_status": logistics_status,
        },
    }
