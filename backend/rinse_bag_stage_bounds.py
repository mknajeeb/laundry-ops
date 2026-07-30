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
    is_add_photos_purpose,
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
        row = {
            "id": r.get("id"),
            "rack": r.get("rack") if "rack" in r else r.get("Rack"),
            "user": r.get("user_name") if "user_name" in r else r.get("User"),
            "user_name": r.get("user_name") if "user_name" in r else r.get("User"),
            "scanned_at_parsed": r.get("scanned_at_parsed"),
            "scan_index": r.get("scan_index") if "scan_index" in r else r.get("Scan Index"),
            "purpose": r.get("purpose") if "purpose" in r else r.get("Purpose"),
        }
        for key in ("weight_lbs", "weight_num", "weight", "source_filename", "raw_json"):
            if key in r and r[key] is not None:
                row[key] = r[key]
        out.append(row)
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
    # Latest sent-to-vendor anchors the current lifecycle (repeat-trip bags return through
    # VeeWash). See docs/postmortems/repeat_trip_scan_cycle_fix_2026-06-25.md.
    candidates: list[Mapping[str, Any]] = []
    for ev in timeline:
        if not is_sent_to_vendor_purpose(ev.get("purpose")):
            continue
        ts = event_ts(ev)
        if ts_valid(ts):
            candidates.append(ev)
    if not candidates:
        return None, None
    ev = max(candidates, key=sort_key_ev)
    return event_ts(ev), ev


def lifecycle_anchor_as_of(
    timeline: Sequence[Mapping[str, Any]],
    *,
    as_of_end: datetime,
) -> tuple[datetime | None, Mapping[str, Any] | None]:
    """
    Latest sent-to-vendor at or before as_of_end — current lifecycle for that cutoff.

    Shared by Sorting / Washing / Drying / Ready-to-Fold current-cycle selectors.
    Events after as_of_end must not affect the selected-day result.
    """
    candidates: list[Mapping[str, Any]] = []
    for ev in timeline:
        if not is_sent_to_vendor_purpose(ev.get("purpose")):
            continue
        ts = event_ts(ev)
        if ts_valid(ts) and ts <= as_of_end:
            candidates.append(ev)
    if not candidates:
        return None, None
    ev = max(candidates, key=sort_key_ev)
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


def workitem_eligible_events(
    timeline: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """
    Scan events eligible for workitem operational counts.

    Requires sent-to-vendor anchor and first post-anchor weight-entry; only
    events strictly after that weight-entry are included.
    """
    anchor_ts, _ = lifecycle_anchor(timeline)
    if anchor_ts is None:
        return []
    anchored = events_on_or_after(timeline, anchor_ts)
    _, weight_ts = first_weight_after_anchor(anchored)
    if weight_ts is None:
        return []
    return events_after_ts(anchored, weight_ts)


def is_cleaning_purpose_for_activity_start(raw: str | None) -> bool:
    """Ghost ``cleaning`` or ``start-cleaning`` — activity start anchors."""
    return is_ghost_cleaning_purpose(raw) or is_start_cleaning_purpose(raw)


def last_exact_cleaning_before(
    timeline: Sequence[Mapping[str, Any]], *, before: datetime
) -> Mapping[str, Any] | None:
    """Last cleaning purpose before timestamp — weighing/sorting start anchor."""
    candidates = [
        ev
        for ev in timeline
        if is_cleaning_purpose_for_activity_start(ev.get("purpose"))
        and ts_valid(event_ts(ev))
        and event_ts(ev) < before
    ]
    if not candidates:
        return None
    return max(candidates, key=sort_key_ev)


def _first_add_photos_after(
    anchored: Sequence[Mapping[str, Any]], *, after_ts: datetime
) -> Mapping[str, Any] | None:
    for ev in anchored:
        if not is_add_photos_purpose(ev.get("purpose")):
            continue
        ts = event_ts(ev)
        if ts_valid(ts) and ts > after_ts:
            return ev
    return None


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
    anchored: Sequence[Mapping[str, Any]],
    weight_ts: datetime,
    *,
    full_timeline: Sequence[Mapping[str, Any]] | None = None,
) -> tuple[Mapping[str, Any] | None, Mapping[str, Any] | None]:
    """
    Sorting requires first add-photos after weight. Start = last cleaning before add-photos,
    or first weight-entry when cleaning is missing. End = latest event before start-cleaning,
    or latest post-weight event when start-cleaning is missing.
    """
    weight_ev: Mapping[str, Any] | None = None
    for ev in anchored:
        if is_weight_entry_purpose(ev.get("purpose")) and event_ts(ev) == weight_ts:
            weight_ev = ev
            break
    if weight_ev is None:
        for ev in anchored:
            if is_weight_entry_purpose(ev.get("purpose")):
                ts = event_ts(ev)
                if ts_valid(ts) and ts == weight_ts:
                    weight_ev = ev
                    break

    add_ev = _first_add_photos_after(anchored, after_ts=weight_ts)
    if add_ev is None:
        return None, None

    add_ts = event_ts(add_ev)
    if not ts_valid(add_ts):
        return None, None

    cleaning_ev = last_exact_cleaning_before(
        list(full_timeline) if full_timeline is not None else list(anchored),
        before=add_ts,
    )
    sorting_start_ev = cleaning_ev if cleaning_ev is not None else weight_ev

    after_weight = events_after_ts(anchored, weight_ts)
    start_cleaning_ev = first_start_cleaning_after(anchored, after_ts=weight_ts)
    if start_cleaning_ev is not None:
        sc_ts = event_ts(start_cleaning_ev)
        before_sc = [
            ev for ev in after_weight if ts_valid(event_ts(ev)) and event_ts(ev) < sc_ts
        ]
        sorting_end_ev = max(before_sc, key=sort_key_ev) if before_sc else None
    else:
        sorting_end_ev = max(after_weight, key=sort_key_ev) if after_weight else None
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
