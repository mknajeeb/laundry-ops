"""
Person + shift-level Wash & Fold gaming / performance aggregation.

Layer 2 on top of bag-level stage timing (``rinse_bag_gaming_performance``).
Supports split-work scenarios: different people may own weighing, sorting, wash/load, folding.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence

from backend.rinse_bag_gaming_performance import (
    ACTIVITY_FOLDING,
    ACTIVITY_SORTING,
    ACTIVITY_WASH_LOAD,
    ACTIVITY_WEIGHING,
    ALL_GAMING_ACTIVITIES,
    BagActivitySlice,
    WashLoadLimits,
    _duration_seconds,
    _event_ts,
    _normalize_user_name,
    _ts_valid,
    _users_match,
    aggregate_daily_workitem_issue_indicators,
    build_bag_activity_slices_for_bags,
    gaming_events_from_records,
    STAGE_EXCEPTION,
)
from backend.rinse_scan_purpose import is_drying_purpose, is_start_cleaning_purpose


def _normalize_selected_activities(selected: Sequence[str] | None) -> tuple[str, ...]:
    if not selected:
        return ALL_GAMING_ACTIVITIES
    out: list[str] = []
    allowed = set(ALL_GAMING_ACTIVITIES)
    for raw in selected:
        act = str(raw or "").strip().lower()
        if act in allowed and act not in out:
            out.append(act)
    return tuple(out) if out else ALL_GAMING_ACTIVITIES


def _in_shift_window(ts: datetime | None, *, clock_in: datetime, clock_out: datetime) -> bool:
    if not _ts_valid(ts):
        return False
    return clock_in <= ts <= clock_out


def _activity_metric_dict(
    *,
    bag_count: int,
    first_start: datetime | None,
    last_end: datetime | None,
) -> dict[str, Any]:
    dur = _duration_seconds(first_start, last_end)
    return {
        "bag_count": bag_count,
        "first_start_time": first_start,
        "last_end_time": last_end,
        "duration_seconds": dur,
        "duration_minutes": round(dur / 60.0, 2) if dur is not None else None,
    }


def _empty_activity_metric() -> dict[str, Any]:
    return _activity_metric_dict(bag_count=0, first_start=None, last_end=None)


def _slices_for_person(
    slices: Sequence[BagActivitySlice],
    *,
    rinse_user_name: str,
    activity: str,
    clock_in: datetime,
    clock_out: datetime,
) -> list[BagActivitySlice]:
    matched: list[BagActivitySlice] = []
    for sl in slices:
        if sl.activity != activity:
            continue
        if not sl.assigned_user or not _users_match(sl.assigned_user, rinse_user_name):
            continue
        if sl.stage_status == STAGE_EXCEPTION and sl.end_time is None:
            continue
        if not _in_shift_window(sl.end_time, clock_in=clock_in, clock_out=clock_out):
            continue
        matched.append(sl)
    return matched


def _weighing_shift_metrics(
    slices: Sequence[BagActivitySlice],
    *,
    rinse_user_name: str,
    clock_in: datetime,
    clock_out: datetime,
) -> dict[str, Any]:
    matched = _slices_for_person(
        slices,
        rinse_user_name=rinse_user_name,
        activity=ACTIVITY_WEIGHING,
        clock_in=clock_in,
        clock_out=clock_out,
    )
    if not matched:
        return _empty_activity_metric()

    starts = [
        sl.start_time
        for sl in matched
        if _in_shift_window(sl.start_time, clock_in=clock_in, clock_out=clock_out)
        and sl.start_time is not None
        and sl.start_time >= clock_in
    ]
    ends = [
        sl.end_time
        for sl in matched
        if sl.end_time is not None and sl.end_time <= clock_out
    ]
    bag_ids = {sl.bag_id for sl in matched if sl.bag_id}
    return _activity_metric_dict(
        bag_count=len(bag_ids),
        first_start=min(starts) if starts else None,
        last_end=max(ends) if ends else None,
    )


def _sorting_shift_metrics(
    slices: Sequence[BagActivitySlice],
    *,
    rinse_user_name: str,
    clock_in: datetime,
    clock_out: datetime,
) -> dict[str, Any]:
    matched = _slices_for_person(
        slices,
        rinse_user_name=rinse_user_name,
        activity=ACTIVITY_SORTING,
        clock_in=clock_in,
        clock_out=clock_out,
    )
    if not matched:
        return _empty_activity_metric()

    starts = [
        sl.start_time
        for sl in matched
        if _in_shift_window(sl.start_time, clock_in=clock_in, clock_out=clock_out)
        and sl.start_time is not None
        and sl.start_time >= clock_in
    ]
    ends = [
        sl.end_time
        for sl in matched
        if sl.end_time is not None and sl.end_time <= clock_out
    ]
    bag_ids = {sl.bag_id for sl in matched if sl.bag_id}
    return _activity_metric_dict(
        bag_count=len(bag_ids),
        first_start=min(starts) if starts else None,
        last_end=max(ends) if ends else None,
    )


def _folding_shift_metrics(
    slices: Sequence[BagActivitySlice],
    *,
    rinse_user_name: str,
    clock_in: datetime,
    clock_out: datetime,
) -> dict[str, Any]:
    matched = _slices_for_person(
        slices,
        rinse_user_name=rinse_user_name,
        activity=ACTIVITY_FOLDING,
        clock_in=clock_in,
        clock_out=clock_out,
    )
    if not matched:
        return _empty_activity_metric()

    starts = [
        sl.start_time
        for sl in matched
        if _in_shift_window(sl.start_time, clock_in=clock_in, clock_out=clock_out)
        and sl.start_time is not None
        and sl.start_time >= clock_in
    ]
    ends = [
        sl.end_time
        for sl in matched
        if sl.end_time is not None and sl.end_time <= clock_out
    ]
    bag_ids = {sl.bag_id for sl in matched if sl.bag_id}
    return _activity_metric_dict(
        bag_count=len(bag_ids),
        first_start=min(starts) if starts else None,
        last_end=max(ends) if ends else None,
    )


def _wash_load_shift_metrics(
    slices: Sequence[BagActivitySlice],
    *,
    rinse_user_name: str,
    clock_in: datetime,
    clock_out: datetime,
    shift_events: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    matched = _slices_for_person(
        slices,
        rinse_user_name=rinse_user_name,
        activity=ACTIVITY_WASH_LOAD,
        clock_in=clock_in,
        clock_out=clock_out,
    )
    bag_ids = {sl.bag_id for sl in matched if sl.bag_id}

    sc_starts: list[datetime] = []
    wash_ends: list[datetime] = []
    for ev in gaming_events_from_records(shift_events):
        purpose = ev.get("purpose")
        if not (is_start_cleaning_purpose(purpose) or is_drying_purpose(purpose)):
            continue
        user = _normalize_user_name(ev.get("user") or ev.get("user_name"))
        if not _users_match(user, rinse_user_name):
            continue
        ts = _event_ts(ev)
        if not _in_shift_window(ts, clock_in=clock_in, clock_out=clock_out):
            continue
        if ts is None or ts < clock_in:
            continue
        if is_start_cleaning_purpose(purpose):
            sc_starts.append(ts)
        wash_ends.append(ts)

    if not sc_starts and not wash_ends and not bag_ids:
        return _empty_activity_metric()

    return _activity_metric_dict(
        bag_count=len(bag_ids),
        first_start=min(sc_starts) if sc_starts else None,
        last_end=max(wash_ends) if wash_ends else None,
    )


def _combined_metrics(
    activity_metrics: Mapping[str, Mapping[str, Any]],
    selected: Sequence[str],
) -> dict[str, Any]:
    selected_metrics = [activity_metrics[a] for a in selected if a in activity_metrics]
    if not selected_metrics:
        return {
            "distinct_bag_count": 0,
            "first_start_time": None,
            "last_end_time": None,
            "duration_seconds": None,
            "duration_minutes": None,
        }

    bag_count = 0
    for m in selected_metrics:
        bag_count = max(bag_count, int(m.get("bag_count") or 0))

    starts = [
        m["first_start_time"]
        for m in selected_metrics
        if m.get("first_start_time") is not None
    ]
    ends = [
        m["last_end_time"]
        for m in selected_metrics
        if m.get("last_end_time") is not None
    ]
    first_start = min(starts) if starts else None
    last_end = max(ends) if ends else None
    dur = _duration_seconds(first_start, last_end)

    return {
        "distinct_bag_count": bag_count,
        "first_start_time": first_start,
        "last_end_time": last_end,
        "duration_seconds": dur,
        "duration_minutes": round(dur / 60.0, 2) if dur is not None else None,
    }


def _shift_indicators(
    bags: Sequence[Mapping[str, Any]],
    *,
    touched_bag_ids: set[str],
) -> dict[str, Any]:
    timelines = []
    for bag in bags:
        bid = str(bag.get("bag_id") or "").strip()
        if bid not in touched_bag_ids:
            continue
        timelines.append(gaming_events_from_records(bag.get("events") or []))
    if not timelines:
        return {
            "create_workitem_count": 0,
            "create_issue_count": 0,
            "bags_with_workitems": 0,
            "bags_with_issues": 0,
        }
    agg = aggregate_daily_workitem_issue_indicators(timelines)
    return {
        "create_workitem_count": agg["total_create_workitems"],
        "create_issue_count": agg["total_create_issues"],
        "bags_with_workitems": agg["bags_with_workitems"],
        "bags_with_issues": agg["bags_with_issues"],
    }


def _needs_review_entries(
    slices: Sequence[BagActivitySlice],
    *,
    rinse_user_name: str,
    clock_in: datetime,
    clock_out: datetime,
    selected: Sequence[str],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for sl in slices:
        if sl.activity not in selected:
            continue
        if not sl.needs_review:
            continue
        relevant = False
        if sl.assigned_user and _users_match(sl.assigned_user, rinse_user_name):
            relevant = True
        elif sl.end_time and _in_shift_window(sl.end_time, clock_in=clock_in, clock_out=clock_out):
            relevant = True
        elif sl.start_time and _in_shift_window(sl.start_time, clock_in=clock_in, clock_out=clock_out):
            relevant = True
        if relevant:
            out.append(sl.to_dict())
    return out


def evaluate_person_shift_gaming(
    *,
    user_id: str | int | None,
    user_name: str,
    shift_id: str | int,
    clock_in: datetime,
    clock_out: datetime,
    bags: Sequence[Mapping[str, Any]],
    selected_activities: Sequence[str] | None = None,
    rinse_user_name: str | None = None,
    wash_load_limits: WashLoadLimits | None = None,
    activity_slices: Sequence[BagActivitySlice] | None = None,
) -> dict[str, Any]:
    """
    Person/shift gaming output: per-activity and combined metrics for selected activities.

    ``bags`` entries: ``{"bag_id": str, "events": [...], "registry_row"?: ..., "rules"?: ...}``
    """
    if not _ts_valid(clock_in) or not _ts_valid(clock_out) or clock_out < clock_in:
        raise ValueError("clock_out must be after clock_in")

    rinse_name = _normalize_user_name(rinse_user_name) or _normalize_user_name(user_name)
    if not rinse_name:
        raise ValueError("user_name or rinse_user_name required")

    selected = _normalize_selected_activities(selected_activities)
    slices = list(activity_slices) if activity_slices is not None else build_bag_activity_slices_for_bags(
        bags, wash_load_limits=wash_load_limits
    )

    shift_events: list[Mapping[str, Any]] = []
    for bag in bags:
        for ev in bag.get("events") or []:
            shift_events.append(ev)

    activity_metrics: dict[str, dict[str, Any]] = {}
    if ACTIVITY_WEIGHING in selected:
        activity_metrics[ACTIVITY_WEIGHING] = _weighing_shift_metrics(
            slices,
            rinse_user_name=rinse_name,
            clock_in=clock_in,
            clock_out=clock_out,
        )
    if ACTIVITY_SORTING in selected:
        activity_metrics[ACTIVITY_SORTING] = _sorting_shift_metrics(
            slices,
            rinse_user_name=rinse_name,
            clock_in=clock_in,
            clock_out=clock_out,
        )
    if ACTIVITY_WASH_LOAD in selected:
        activity_metrics[ACTIVITY_WASH_LOAD] = _wash_load_shift_metrics(
            slices,
            rinse_user_name=rinse_name,
            clock_in=clock_in,
            clock_out=clock_out,
            shift_events=shift_events,
        )
    if ACTIVITY_FOLDING in selected:
        activity_metrics[ACTIVITY_FOLDING] = _folding_shift_metrics(
            slices,
            rinse_user_name=rinse_name,
            clock_in=clock_in,
            clock_out=clock_out,
        )

    combined = _combined_metrics(activity_metrics, selected)
    combined_bag_ids: set[str] = set()
    for act in selected:
        for sl in slices:
            if sl.activity != act:
                continue
            if not sl.assigned_user or not _users_match(sl.assigned_user, rinse_name):
                continue
            if sl.stage_status == STAGE_EXCEPTION and sl.end_time is None:
                continue
            if sl.bag_id and _in_shift_window(sl.end_time, clock_in=clock_in, clock_out=clock_out):
                combined_bag_ids.add(sl.bag_id)
    combined["distinct_bag_count"] = len(combined_bag_ids)

    return {
        "user_id": user_id,
        "user_name": user_name,
        "rinse_user_name": rinse_name,
        "shift_id": shift_id,
        "clock_in": clock_in,
        "clock_out": clock_out,
        "selected_activities": list(selected),
        "activity_metrics": activity_metrics,
        "combined_metrics": combined,
        "indicators": _shift_indicators(bags, touched_bag_ids=combined_bag_ids),
        "needs_review": _needs_review_entries(
            slices,
            rinse_user_name=rinse_name,
            clock_in=clock_in,
            clock_out=clock_out,
            selected=selected,
        ),
    }
