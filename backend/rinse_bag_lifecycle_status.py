"""
Per-bag lifecycle status derived from scan purposes, portal presence, and registry.

Rules:
- Ghost only exact normalized purpose ``cleaning`` (not start-cleaning, not CLEAN rack).
- Lifecycle is anchored at first ``sent-to-vendor``; events before anchor are ignored.
- ``CLEAN`` rack scan means FOLDED_COMPLETED (case-insensitive contains).
- ``LOAD_WASHER`` / ``LOAD_DRYER`` are performance stages only — not ``current_lifecycle_status``.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Mapping, Sequence

from backend.rinse_bag_completion import rack_contains_clean, user_is_internal
from backend.rinse_bag_stage_bounds import (
    event_ts as _event_ts,
    events_after_ts as _events_after_ts,
    events_on_or_after as _events_on_or_after,
    first_drying_after as _first_drying_after,
    first_start_cleaning_after as _first_start_cleaning_after,
    first_weight_after_anchor as _first_weight_after_anchor,
    gaming_events_from_records,
    lifecycle_anchor as _lifecycle_anchor,
    load_washer_bounds as _load_washer_bounds,
    sort_key_ev as _sort_key_ev,
    sorting_bounds_after_weight as _sorting_bounds_after_weight,
    ts_valid as _ts_valid,
    visible_timeline as _visible_timeline,
)
from backend.rinse_processing_settings import (
    DEFAULT_DRYING_MINUTES,
    DEFAULT_REJECT_AFTER_CREATE_ISSUE,
    DEFAULT_WASHING_MINUTES,
)
from backend.rinse_scan_purpose import (
    is_create_bulk_workitem_purpose,
    is_create_issue_purpose,
    is_create_workitem_purpose,
    is_ghost_cleaning_purpose,
    normalize_scan_purpose,
    purpose_contains_workitem,
)
from backend.rinse_shift_operational_exceptions import (
    CHECKOUT_WITHOUT_CLEAN_RACK,
    COMPLETED_WITHOUT_FINAL_CLEAN_SCAN,
    NEEDS_REVIEW_EXTERNAL_SCAN_AFTER_CLEAN,
    ORDER_REJECTED_FULL,
    evaluate_completed_without_final_clean_scan,
    evaluate_order_rejected_full,
)

ASSIGNED_NOT_SENT_TO_VENDOR = "ASSIGNED_NOT_SENT_TO_VENDOR"
SENT_TO_VENDOR = "SENT_TO_VENDOR"
PENDING_WEIGHING = "PENDING_WEIGHING"
WEIGHED_NOT_STARTED = "WEIGHED_NOT_STARTED"
SORTED_READY_FOR_WASH = "SORTED_READY_FOR_WASH"
IN_WASHING = "IN_WASHING"
IN_DRYING = "IN_DRYING"
FOLDED_COMPLETED = "FOLDED_COMPLETED"
SENT_TO_RINSE = "SENT_TO_RINSE"
LIFECYCLE_UNKNOWN = "UNKNOWN"

# Performance stage keys — not lifecycle statuses
LOAD_WASHER = "LOAD_WASHER"
LOAD_DRYER = "LOAD_DRYER"

# Legacy alias
RETURNED_TO_RINSE = SENT_TO_RINSE

ALL_LIFECYCLE_STATUSES = (
    ASSIGNED_NOT_SENT_TO_VENDOR,
    SENT_TO_VENDOR,
    PENDING_WEIGHING,
    WEIGHED_NOT_STARTED,
    SORTED_READY_FOR_WASH,
    IN_WASHING,
    IN_DRYING,
    FOLDED_COMPLETED,
    SENT_TO_RINSE,
    LIFECYCLE_UNKNOWN,
)

SENT_TO_RINSE_MISSING_FROM_NEXT_PORTAL_SCRAPE = "MISSING_FROM_NEXT_PORTAL_SCRAPE"
SENT_TO_RINSE_EXTERNAL_USER_AFTER_CLEAN = "EXTERNAL_USER_SCAN_AFTER_CLEAN"

CHECKOUT_STATUS_NOT_CHECKED_OUT = "NOT_CHECKED_OUT"
CHECKOUT_STATUS_CHECKED_OUT = "CHECKED_OUT"
CHECKOUT_STATUS_NEEDS_REVIEW = "CHECKOUT_NEEDS_REVIEW"

_LOGISTICS_CHECKED_OUT = frozenset({"SENT_TO_RINSE", "CHECKED_OUT", "FORCE_CHECKOUT"})


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
    visible = _visible_timeline(timeline)
    issues = [ev for ev in visible if is_create_issue_purpose(ev.get("purpose"))]
    workitems = [ev for ev in visible if is_create_workitem_purpose(ev.get("purpose"))]
    bulk = [ev for ev in visible if is_create_bulk_workitem_purpose(ev.get("purpose"))]
    all_workitem = [ev for ev in visible if purpose_contains_workitem(ev.get("purpose"))]
    return {
        "has_create_issue": len(issues) > 0,
        "has_create_workitem": len(workitems) > 0,
        "has_create_bulk_workitem": len(bulk) > 0,
        "has_workitem": len(all_workitem) > 0,
        "create_issue_count": len(issues),
        "create_workitem_count": len(workitems),
        "create_bulk_workitem_count": len(bulk),
        "workitem_count": len(all_workitem),
    }


def _first_clean_rack_event(
    timeline: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any] | None, datetime | None]:
    for ev in timeline:
        if rack_contains_clean(ev.get("rack")):
            ts = _event_ts(ev)
            if _ts_valid(ts):
                return ev, ts
    return None, None


def _is_mapped_internal_operator(name: str, mapped_users: set[str]) -> bool:
    n = name.casefold()
    return any(n == m.casefold() for m in mapped_users if m)


def _is_internal_operator(name: str, mapped_users: set[str]) -> bool:
    if not name:
        return False
    return user_is_internal(name) or _is_mapped_internal_operator(name, mapped_users)


def _derive_checkout_status(
    logistics_status: str | None,
    *,
    has_clean_rack: bool,
) -> tuple[str, bool, bool]:
    logistics = str(logistics_status or "").strip().upper()
    if logistics not in _LOGISTICS_CHECKED_OUT:
        return CHECKOUT_STATUS_NOT_CHECKED_OUT, False, False
    if has_clean_rack:
        return CHECKOUT_STATUS_CHECKED_OUT, False, False
    return CHECKOUT_STATUS_NEEDS_REVIEW, True, True


def _evaluate_sent_to_rinse(
    timeline: Sequence[Mapping[str, Any]],
    *,
    clean_ev: Mapping[str, Any] | None,
    clean_at: datetime | None,
    missing_from_next_portal_scrape: bool,
    mapped_users: set[str],
) -> tuple[bool, str | None, datetime | None, dict[str, Any] | None, bool]:
    if clean_ev is None or clean_at is None:
        return False, None, None, None, False

    if missing_from_next_portal_scrape:
        return (
            True,
            SENT_TO_RINSE_MISSING_FROM_NEXT_PORTAL_SCRAPE,
            clean_at,
            _status_source_from_event(clean_ev),
            False,
        )

    external_after: list[Mapping[str, Any]] = []
    for ev in timeline:
        ts = _event_ts(ev)
        if not _ts_valid(ts) or ts <= clean_at:
            continue
        op = _operator_name(ev)
        if not op or _is_internal_operator(op, mapped_users):
            continue
        external_after.append(ev)

    if external_after:
        ev = max(external_after, key=_sort_key_ev)
        return (
            True,
            SENT_TO_RINSE_EXTERNAL_USER_AFTER_CLEAN,
            _event_ts(ev),
            _status_source_from_event(ev),
            True,
        )

    return False, None, None, None, False


def _collect_exception_flags(
    anchored: Sequence[Mapping[str, Any]],
    full_timeline: Sequence[Mapping[str, Any]],
    *,
    anchor_ts: datetime | None,
    reject_after_create_issue_minutes: int,
    needs_review_external: bool,
    checkout_without_clean: bool,
    evaluation_time: datetime | None,
) -> tuple[list[str], dict[str, Any] | None]:
    flags: list[str] = []

    reject_detail = evaluate_order_rejected_full(
        anchored,
        window_minutes=reject_after_create_issue_minutes,
        after=anchor_ts,
        evaluation_time=evaluation_time,
    )
    if reject_detail and reject_detail.get("order_rejected_full"):
        flags.append(ORDER_REJECTED_FULL)

    missing_clean = evaluate_completed_without_final_clean_scan(full_timeline)
    if missing_clean:
        flags.append(COMPLETED_WITHOUT_FINAL_CLEAN_SCAN)

    if needs_review_external:
        flags.append(NEEDS_REVIEW_EXTERNAL_SCAN_AFTER_CLEAN)

    if checkout_without_clean:
        flags.append(CHECKOUT_WITHOUT_CLEAN_RACK)

    return flags, reject_detail


def derive_bag_lifecycle_status(
    events: Sequence[Mapping[str, Any]],
    *,
    bag_id: str,
    order_id: str | None = None,
    ready_for_vendor_presence: bool = False,
    at_vendor_presence: bool = False,
    logistics_status: str | None = None,
    mapped_internal_users: Sequence[str] | None = None,
    washing_minutes: int = DEFAULT_WASHING_MINUTES,
    drying_minutes: int = DEFAULT_DRYING_MINUTES,
    reject_after_create_issue_minutes: int = DEFAULT_REJECT_AFTER_CREATE_ISSUE,
    missing_from_next_portal_scrape: bool = False,
    evaluation_time: datetime | None = None,
    folding_result: Any = None,
) -> dict[str, Any]:
    bid = str(bag_id or "").strip()
    oid = str(order_id or bid).strip() or bid
    timeline = gaming_events_from_records(events)
    mapped_users = {str(u).strip() for u in (mapped_internal_users or []) if str(u).strip()}

    anchor_ts, anchor_ev = _lifecycle_anchor(timeline)
    anchored = _events_on_or_after(timeline, anchor_ts)
    operational_flags = operational_flags_from_timeline(timeline)

    clean_ev, clean_at = _first_clean_rack_event(timeline)
    folded_completed = clean_ev is not None

    checkout_status, checkout_review, checkout_no_clean = _derive_checkout_status(
        logistics_status,
        has_clean_rack=folded_completed,
    )

    sent_to_rinse, str_reason, str_ts, str_source, external_review = _evaluate_sent_to_rinse(
        timeline,
        clean_ev=clean_ev,
        clean_at=clean_at,
        missing_from_next_portal_scrape=missing_from_next_portal_scrape,
        mapped_users=mapped_users,
    )

    exception_flags, reject_detail = _collect_exception_flags(
        anchored,
        timeline,
        anchor_ts=anchor_ts,
        reject_after_create_issue_minutes=reject_after_create_issue_minutes,
        needs_review_external=external_review,
        checkout_without_clean=checkout_no_clean,
        evaluation_time=evaluation_time,
    )

    needs_review = external_review or checkout_review
    status: str
    status_timestamp: datetime | None = None
    status_source_event: dict[str, Any] | None = None
    stage_detail: dict[str, Any] = {
        "lifecycle_anchor_time": anchor_ts,
        "lifecycle_anchor_event": _status_source_from_event(anchor_ev),
        "washing_minutes": int(washing_minutes),
        "drying_minutes": int(drying_minutes),
    }
    if reject_detail is not None:
        stage_detail["reject_after_create_issue"] = reject_detail

    if sent_to_rinse:
        status = SENT_TO_RINSE
        status_timestamp = str_ts or clean_at
        status_source_event = str_source
        stage_detail["sent_to_rinse_reason"] = str_reason
        stage_detail["sent_to_rinse_timestamp"] = status_timestamp
        stage_detail["sent_to_rinse_source"] = str_source
    elif folded_completed:
        status = FOLDED_COMPLETED
        status_timestamp = clean_at
        status_source_event = _status_source_from_event(clean_ev)
    else:
        weight_ev, weight_ts = _first_weight_after_anchor(anchored)
        start_cleaning_ev = _first_start_cleaning_after(anchored)
        drying_ev = _first_drying_after(anchored)
        load_start, load_end, load_end_ts = _load_washer_bounds(anchored)

        if drying_ev is not None:
            dry_ts = _event_ts(drying_ev)
            status = IN_DRYING
            status_timestamp = dry_ts
            status_source_event = _status_source_from_event(drying_ev)
            stage_detail[LOAD_DRYER] = {
                "start_time": dry_ts,
                "end_time": dry_ts,
            }
            stage_detail["in_drying"] = {
                "start_time": dry_ts,
                "expected_end_time": dry_ts + timedelta(minutes=int(drying_minutes)),
            }
        elif start_cleaning_ev is not None or load_start is not None:
            sc_ev = load_start or start_cleaning_ev
            in_wash_start_ts = load_end_ts if load_end_ts is not None else _event_ts(sc_ev)
            status = IN_WASHING
            status_timestamp = in_wash_start_ts
            status_source_event = _status_source_from_event(load_end or sc_ev)
            stage_detail[LOAD_WASHER] = {
                "start_time": _event_ts(sc_ev),
                "end_time": _event_ts(load_end) if load_end else None,
                "end_purpose": normalize_scan_purpose(load_end.get("purpose"))
                if load_end
                else None,
            }
            stage_detail["in_washing"] = {
                "start_time": in_wash_start_ts,
                "expected_end_time": in_wash_start_ts
                + timedelta(minutes=int(washing_minutes)),
            }
        elif weight_ev is not None and weight_ts is not None:
            sorting_start, sorting_end = _sorting_bounds_after_weight(anchored, weight_ts)
            after_weight = _events_after_ts(anchored, weight_ts)
            if after_weight:
                status = SORTED_READY_FOR_WASH
                status_timestamp = _event_ts(sorting_end) if sorting_end else weight_ts
                status_source_event = _status_source_from_event(sorting_end or sorting_start)
                stage_detail["sorting"] = {
                    "start_time": _event_ts(sorting_start) if sorting_start else None,
                    "end_time": _event_ts(sorting_end) if sorting_end else None,
                }
            else:
                status = WEIGHED_NOT_STARTED
                status_timestamp = weight_ts
                status_source_event = _status_source_from_event(weight_ev)
        elif anchor_ts is not None or at_vendor_presence:
            if anchor_ts is not None:
                status = PENDING_WEIGHING
                status_timestamp = anchor_ts
                status_source_event = _status_source_from_event(anchor_ev)
            else:
                status = SENT_TO_VENDOR
                status_source_event = _presence_source(kind="at_vendor", present=at_vendor_presence)
        elif ready_for_vendor_presence:
            status = ASSIGNED_NOT_SENT_TO_VENDOR
            status_source_event = _presence_source(kind="ready_for_vendor", present=True)
        else:
            status = LIFECYCLE_UNKNOWN
            status_source_event = None

    return {
        "bag_id": bid,
        "order_id": oid,
        "current_lifecycle_status": status,
        "checkout_status": checkout_status,
        "status_timestamp": status_timestamp,
        "status_source_event": status_source_event,
        "operational_flags": operational_flags,
        "exception_flags": exception_flags,
        "needs_review": needs_review,
        "stage_detail": stage_detail,
        "presence_inputs": {
            "ready_for_vendor_presence": bool(ready_for_vendor_presence),
            "at_vendor_presence": bool(at_vendor_presence),
            "logistics_status": logistics_status,
            "missing_from_next_portal_scrape": bool(missing_from_next_portal_scrape),
        },
        "checkout_inputs": {
            "logistics_status": logistics_status,
            "has_clean_rack": folded_completed,
        },
    }