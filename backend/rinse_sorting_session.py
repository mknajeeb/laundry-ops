"""
Standardized sorting session start/end measurement for display and analytics.

Productivity credit calculation (``sorting_bounds_v2`` in rinse_bag_activity_rules)
keeps its own bounds; use this module wherever sorting duration is measured or shown.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence

from backend.rinse_bag_activity_rules import (
    _first_add_photos_after,
    is_cleaning_purpose_for_activity_start,
)
from backend.rinse_bag_stage_bounds import event_ts, sort_key_ev, ts_valid
from backend.rinse_scan_purpose import (
    is_add_photos_purpose,
    is_complete_cleaning_purpose,
    is_create_issue_purpose,
    is_drying_purpose,
    is_lifecycle_sorting_progress_marker_purpose,
    is_ready_washer_purpose,
    is_split_load_purpose,
    is_start_cleaning_purpose,
    is_washer_settings_purpose,
    is_weight_entry_purpose,
    normalize_scan_purpose,
    purpose_contains_workitem,
)


def _operator(ev: Mapping[str, Any] | None) -> str | None:
    if ev is None:
        return None
    name = str(ev.get("user") or ev.get("user_name") or ev.get("User") or "").strip()
    return name or None


def _operators_match(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    return a.casefold() == b.casefold()


def same_scan_event(
    left: Mapping[str, Any] | None,
    right: Mapping[str, Any] | None,
) -> bool:
    """True when *left* and *right* refer to the same scan row (not just the same timestamp)."""
    if left is None or right is None:
        return False
    if left is right:
        return True
    left_id, right_id = left.get("id"), right.get("id")
    if left_id is not None and right_id is not None:
        return left_id == right_id
    return sort_key_ev(left) == sort_key_ev(right)


def canonical_add_photos_for_weight(
    anchored: Sequence[Mapping[str, Any]],
    weight_ts: datetime,
) -> Mapping[str, Any] | None:
    """First canonical add-photos strictly after *weight_ts* (one sort cycle anchor)."""
    return _first_add_photos_after(anchored, after_ts=weight_ts)


def _is_post_sort_downstream_scan(raw: str | None) -> bool:
    """Wash/dry/setup scans after a sort cycle that block a later add-photos row."""
    return (
        is_ready_washer_purpose(raw)
        or is_washer_settings_purpose(raw)
        or is_start_cleaning_purpose(raw)
        or is_drying_purpose(raw)
        or is_complete_cleaning_purpose(raw)
    )


def _never_sort_end_extension_purpose(raw: str | None) -> bool:
    """Purposes that must not extend measured sorting end time."""
    return (
        is_washer_settings_purpose(raw)
        or is_start_cleaning_purpose(raw)
        or is_drying_purpose(raw)
        or is_complete_cleaning_purpose(raw)
        or is_add_photos_purpose(raw)
    )


def has_post_sort_downstream_between(
    anchored: Sequence[Mapping[str, Any]],
    *,
    after_ts: datetime,
    before_ts: datetime,
) -> bool:
    """True when wash/dry/setup scans occur after *after_ts* and before *before_ts*."""
    if not ts_valid(after_ts) or not ts_valid(before_ts) or after_ts >= before_ts:
        return False
    for ev in anchored:
        ts = event_ts(ev)
        if not ts_valid(ts) or ts <= after_ts or ts >= before_ts:
            continue
        if _is_post_sort_downstream_scan(ev.get("purpose")):
            return True
    return False


def _last_cleaning_before_ts_by_employee(
    timeline: Sequence[Mapping[str, Any]],
    *,
    before_ts: datetime,
    employee: str | None,
) -> Mapping[str, Any] | None:
    if not employee:
        return None
    candidates = [
        ev
        for ev in timeline
        if is_cleaning_purpose_for_activity_start(ev.get("purpose"))
        and ts_valid(event_ts(ev))
        and event_ts(ev) < before_ts
        and _operators_match(_operator(ev), employee)
    ]
    return max(candidates, key=sort_key_ev) if candidates else None


def _last_weight_before_ts_by_employee(
    anchored: Sequence[Mapping[str, Any]],
    *,
    before_ts: datetime,
    employee: str | None,
) -> Mapping[str, Any] | None:
    if not employee:
        return None
    candidates = [
        ev
        for ev in anchored
        if is_weight_entry_purpose(ev.get("purpose"))
        and ts_valid(event_ts(ev))
        and event_ts(ev) < before_ts
        and _operators_match(_operator(ev), employee)
    ]
    return max(candidates, key=sort_key_ev) if candidates else None


def _last_cleaning_before_ts(
    timeline: Sequence[Mapping[str, Any]],
    *,
    before_ts: datetime,
) -> Mapping[str, Any] | None:
    candidates = [
        ev
        for ev in timeline
        if is_cleaning_purpose_for_activity_start(ev.get("purpose"))
        and ts_valid(event_ts(ev))
        and event_ts(ev) < before_ts
    ]
    return max(candidates, key=sort_key_ev) if candidates else None


def _next_cleaning_start_ts_by_employee(
    timeline: Sequence[Mapping[str, Any]],
    *,
    after_ts: datetime,
    employee: str | None,
) -> datetime | None:
    if not employee:
        return None
    candidates = [
        event_ts(ev)
        for ev in timeline
        if is_cleaning_purpose_for_activity_start(ev.get("purpose"))
        and ts_valid(event_ts(ev))
        and event_ts(ev) > after_ts
        and _operators_match(_operator(ev), employee)
    ]
    if not candidates:
        return None
    return min(candidates)


def _sorting_start_ev(
    anchored: Sequence[Mapping[str, Any]],
    timeline: Sequence[Mapping[str, Any]],
    *,
    add_photos_ev: Mapping[str, Any],
    add_ts: datetime,
) -> Mapping[str, Any]:
    """
    Sort start: latest same-employee cleaning before add-photos, else same-employee
    weight-entry, else add-photos (zero-duration fallback).
    """
    sort_employee = _operator(add_photos_ev)
    if sort_employee:
        cleaning = _last_cleaning_before_ts_by_employee(
            timeline, before_ts=add_ts, employee=sort_employee
        )
        if cleaning is not None:
            return cleaning
        weight = _last_weight_before_ts_by_employee(
            anchored, before_ts=add_ts, employee=sort_employee
        )
        if weight is not None:
            return weight
        return add_photos_ev

    cleaning = _last_cleaning_before_ts(timeline, before_ts=add_ts)
    if cleaning is not None:
        return cleaning
    return add_photos_ev


def _sorting_end_ev(
    anchored: Sequence[Mapping[str, Any]],
    timeline: Sequence[Mapping[str, Any]],
    *,
    add_photos_ev: Mapping[str, Any],
    add_ts: datetime,
    cycle_employee: str | None,
) -> Mapping[str, Any]:
    """
    Sort end priority (never move backward):
    1. add-photos (base)
    2. split-load after add-photos
    3. latest create-issue after add-photos or split-load
    4. latest create-workitem / workitems-added strictly after current end
    5. same-user ready-washer only when end is still add-photos, before next cleaning
    """
    end_ev = add_photos_ev
    end_ts = add_ts

    after_add: list[Mapping[str, Any]] = []
    for ev in anchored:
        ts = event_ts(ev)
        if not ts_valid(ts) or ts <= add_ts:
            continue
        if _never_sort_end_extension_purpose(ev.get("purpose")):
            continue
        after_add.append(ev)

    split_loads = [
        ev for ev in after_add if is_split_load_purpose(ev.get("purpose"))
    ]
    if split_loads:
        end_ev = max(split_loads, key=sort_key_ev)
        end_ts = event_ts(end_ev) or end_ts

    create_issues = [
        ev
        for ev in after_add
        if is_create_issue_purpose(ev.get("purpose"))
        and ts_valid(event_ts(ev))
        and (event_ts(ev) or end_ts) >= add_ts
    ]
    if create_issues:
        latest_issue = max(create_issues, key=sort_key_ev)
        issue_ts = event_ts(latest_issue)
        if ts_valid(issue_ts) and issue_ts >= end_ts:
            end_ev = latest_issue
            end_ts = issue_ts

    workitems = [
        ev
        for ev in after_add
        if purpose_contains_workitem(ev.get("purpose"))
        and not is_create_issue_purpose(ev.get("purpose"))
        and ts_valid(event_ts(ev))
        and (event_ts(ev) or end_ts) > end_ts
    ]
    if workitems:
        end_ev = max(workitems, key=sort_key_ev)
        end_ts = event_ts(end_ev) or end_ts

    if same_scan_event(end_ev, add_photos_ev) and cycle_employee:
        next_cleaning_ts = _next_cleaning_start_ts_by_employee(
            timeline, after_ts=end_ts, employee=cycle_employee
        )
        ready_candidates = [
            ev
            for ev in after_add
            if is_ready_washer_purpose(ev.get("purpose"))
            and _operators_match(_operator(ev), cycle_employee)
            and ts_valid(event_ts(ev))
            and (event_ts(ev) or end_ts) > end_ts
            and (
                next_cleaning_ts is None
                or (event_ts(ev) or end_ts) < next_cleaning_ts
            )
        ]
        if ready_candidates:
            end_ev = max(ready_candidates, key=sort_key_ev)

    return end_ev


def _is_exact_sort_end_purpose(raw: str | None) -> bool:
    if is_lifecycle_sorting_progress_marker_purpose(raw):
        return True
    return is_ready_washer_purpose(raw)


def _session_confidence(
    sort_start_ev: Mapping[str, Any] | None,
    sort_end_ev: Mapping[str, Any] | None,
) -> str:
    start_exact = sort_start_ev is not None and is_cleaning_purpose_for_activity_start(
        sort_start_ev.get("purpose")
    )
    end_exact = sort_end_ev is not None and _is_exact_sort_end_purpose(
        sort_end_ev.get("purpose")
    )
    if start_exact and end_exact:
        return "exact"
    return "inferred"


def session_source_label(
    sort_start_ev: Mapping[str, Any] | None,
    sort_end_ev: Mapping[str, Any] | None,
) -> str:
    start_p = normalize_scan_purpose(sort_start_ev.get("purpose")) if sort_start_ev else ""
    end_p = normalize_scan_purpose(sort_end_ev.get("purpose")) if sort_end_ev else ""
    if start_p and end_p:
        return f"{start_p} → {end_p}"
    return end_p or start_p or "unknown"


@dataclass(frozen=True)
class SortingSessionResult:
    add_photos_ev: Mapping[str, Any]
    sort_start_ev: Mapping[str, Any]
    sort_end_ev: Mapping[str, Any]
    employee: str | None
    confidence: str

    @property
    def sort_start_et(self) -> datetime | None:
        return event_ts(self.sort_start_ev)

    @property
    def sort_end_et(self) -> datetime | None:
        return event_ts(self.sort_end_ev)

    @property
    def end_event_purpose(self) -> str | None:
        return normalize_scan_purpose(self.sort_end_ev.get("purpose"))


def compute_sorting_session(
    anchored: Sequence[Mapping[str, Any]],
    timeline: Sequence[Mapping[str, Any]],
    *,
    weight_ev: Mapping[str, Any],
    weight_ts: datetime,
    add_photos_ev: Mapping[str, Any] | None = None,
) -> SortingSessionResult | None:
    """
    Standardized sort session for one weight cycle.

    Returns None when no canonical add-photos exists after *weight_ts*.
    """
    add_ev = add_photos_ev or canonical_add_photos_for_weight(anchored, weight_ts)
    if add_ev is None:
        return None
    add_ts = event_ts(add_ev)
    if not ts_valid(add_ts):
        return None

    cycle_employee = _operator(add_ev)
    sort_start_ev = _sorting_start_ev(
        anchored, timeline, add_photos_ev=add_ev, add_ts=add_ts
    )
    sort_end_ev = _sorting_end_ev(
        anchored,
        timeline,
        add_photos_ev=add_ev,
        add_ts=add_ts,
        cycle_employee=cycle_employee,
    )
    employee = (
        cycle_employee
        or _operator(sort_end_ev)
        or _operator(sort_start_ev)
        or _operator(weight_ev)
    )
    confidence = _session_confidence(sort_start_ev, sort_end_ev)
    return SortingSessionResult(
        add_photos_ev=add_ev,
        sort_start_ev=sort_start_ev,
        sort_end_ev=sort_end_ev,
        employee=employee,
        confidence=confidence,
    )


def sorting_session_bounds(
    anchored: Sequence[Mapping[str, Any]],
    timeline: Sequence[Mapping[str, Any]],
    *,
    weight_ev: Mapping[str, Any],
    weight_ts: datetime,
) -> tuple[Mapping[str, Any] | None, Mapping[str, Any] | None]:
    """(sort_start_ev, sort_end_ev) for first weight cycle — display/analytics helper."""
    session = compute_sorting_session(
        anchored, timeline, weight_ev=weight_ev, weight_ts=weight_ts
    )
    if session is None:
        return None, None
    return session.sort_start_ev, session.sort_end_ev
