"""
Shared scan-timeline bounds for lifecycle status and performance stages.

Lifecycle ghost-filters exact ``cleaning``; weighing performance reads exact
``cleaning`` from the raw timeline as weigh-task start.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence

from backend.rinse_bag_completion import _parsed_scan_datetime, _progressive_timeline_sort_key
from backend.rinse_scan_purpose import (
    is_drying_purpose,
    is_ghost_cleaning_purpose,
    is_load_washer_end_purpose,
    is_sent_to_vendor_purpose,
    is_start_cleaning_purpose,
    is_weight_entry_purpose,
)

# Performance stage keys (not lifecycle statuses)
PERF_STAGE_LOAD_WASHER = "LOAD_WASHER"
PERF_STAGE_LOAD_DRYER = "LOAD_DRYER"


def gaming_events_from_records(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in records:
        out.append(
            {
                "id": r.get("id"),
                "rack": r.get("rack") if "rack" in r else r.get("Rack"),
                "user": r.get("user_name") if "user_name" in r else r.get("User"),
                "scanned_at_parsed": r.get("scanned_at_parsed"),
                "scan_index": r.get("scan_index") if "scan_index" in r else r.get("Scan Index"),
                "purpose": r.get("purpose") if "purpose" in r else r.get("Purpose"),
            }
        )
    return sorted(out, key=_progressive_timeline_sort_key)


def ts_valid(ts: datetime | None) -> bool:
    return ts is not None and ts != datetime.min


def event_ts(ev: Mapping[str, Any]) -> datetime | None:
    return _parsed_scan_datetime(ev)


def sort_key_ev(ev: Mapping[str, Any]) -> tuple:
    ts = event_ts(ev)
    return (
        ts is None,
        ts or datetime.min,
        int(ev.get("scan_index") or 0),
        int(ev.get("id") or 0),
    )


def visible_timeline(timeline: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [ev for ev in timeline if not is_ghost_cleaning_purpose(ev.get("purpose"))]


def lifecycle_anchor(
    timeline: Sequence[Mapping[str, Any]],
) -> tuple[datetime | None, Mapping[str, Any] | None]:
    candidates: list[Mapping[str, Any]] = []
    for ev in timeline:
        if not is_sent_to_vendor_purpose(ev.get("purpose")):
            continue
        ts = event_ts(ev)
        if ts_valid(ts):
            candidates.append(ev)
    if not candidates:
        return None, None
    ev = min(candidates, key=sort_key_ev)
    return event_ts(ev), ev


def events_on_or_after(
    timeline: Sequence[Mapping[str, Any]], anchor_ts: datetime | None
) -> list[dict[str, Any]]:
    visible = visible_timeline(timeline)
    if anchor_ts is None:
        return visible
    return [ev for ev in visible if ts_valid(event_ts(ev)) and event_ts(ev) >= anchor_ts]


def events_after_ts(
    anchored: Sequence[Mapping[str, Any]], after_ts: datetime
) -> list[dict[str, Any]]:
    return [ev for ev in anchored if ts_valid(event_ts(ev)) and event_ts(ev) > after_ts]


def first_weight_after_anchor(
    anchored: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any] | None, datetime | None]:
    for ev in anchored:
        if not is_weight_entry_purpose(ev.get("purpose")):
            continue
        ts = event_ts(ev)
        if ts_valid(ts):
            return ev, ts
    return None, None


def last_exact_cleaning_before(
    timeline: Sequence[Mapping[str, Any]], *, before: datetime
) -> Mapping[str, Any] | None:
    """Exact ``cleaning`` purpose only — used for weighing performance start."""
    candidates = [
        ev
        for ev in timeline
        if is_ghost_cleaning_purpose(ev.get("purpose"))
        and ts_valid(event_ts(ev))
        and event_ts(ev) < before
    ]
    if not candidates:
        return None
    return max(candidates, key=sort_key_ev)


def first_start_cleaning_after(
    anchored: Sequence[Mapping[str, Any]], *, after_ts: datetime | None = None
) -> Mapping[str, Any] | None:
    for ev in anchored:
        if not is_start_cleaning_purpose(ev.get("purpose")):
            continue
        ts = event_ts(ev)
        if not ts_valid(ts):
            continue
        if after_ts is not None and ts_valid(after_ts) and ts <= after_ts:
            continue
        return ev
    return None


def sorting_bounds_after_weight(
    anchored: Sequence[Mapping[str, Any]], weight_ts: datetime
) -> tuple[Mapping[str, Any] | None, Mapping[str, Any] | None]:
    after_weight = events_after_ts(anchored, weight_ts)
    if not after_weight:
        return None, None
    sorting_start_ev = after_weight[0]
    start_cleaning_ev = first_start_cleaning_after(anchored, after_ts=weight_ts)
    if start_cleaning_ev is not None:
        sc_ts = event_ts(start_cleaning_ev)
        before_sc = [
            ev for ev in after_weight if ts_valid(event_ts(ev)) and event_ts(ev) < sc_ts
        ]
        sorting_end_ev = max(before_sc, key=sort_key_ev) if before_sc else None
    else:
        sorting_end_ev = max(after_weight, key=sort_key_ev)
    return sorting_start_ev, sorting_end_ev


def load_washer_bounds(
    anchored: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any] | None, Mapping[str, Any] | None, datetime | None]:
    start_ev = first_start_cleaning_after(anchored)
    if start_ev is None:
        return None, None, None
    start_ts = event_ts(start_ev)
    end_candidates = [
        ev
        for ev in anchored
        if ts_valid(event_ts(ev))
        and event_ts(ev) >= start_ts
        and is_load_washer_end_purpose(ev.get("purpose"))
    ]
    if not end_candidates:
        return start_ev, None, None
    end_ev = max(end_candidates, key=sort_key_ev)
    return start_ev, end_ev, event_ts(end_ev)


def first_drying_after(
    anchored: Sequence[Mapping[str, Any]], *, after_ts: datetime | None = None
) -> Mapping[str, Any] | None:
    for ev in anchored:
        if not is_drying_purpose(ev.get("purpose")):
            continue
        ts = event_ts(ev)
        if not ts_valid(ts):
            continue
        if after_ts is not None and ts_valid(after_ts) and ts < after_ts:
            continue
        return ev
    return None


def weighing_performance_bounds(
    timeline: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any] | None, Mapping[str, Any] | None]:
    """Returns (cleaning_start_ev, post_anchor_weight_ev)."""
    anchored = events_on_or_after(timeline, lifecycle_anchor(timeline)[0])
    weight_ev, weight_ts = first_weight_after_anchor(anchored)
    if weight_ev is None or weight_ts is None:
        return None, None
    cleaning_ev = last_exact_cleaning_before(timeline, before=weight_ts)
    return cleaning_ev, weight_ev
