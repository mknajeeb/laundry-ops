"""
Simplified bag activity rules for Scope B shift/day performance.

Canonical completion, weighing/sorting/washing/drying/folding credit, and weight difference.
All activity timestamps are naive ET wall times (rinse_bag_scan_events.scanned_at_parsed).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from collections.abc import Callable
from typing import Any, Mapping, Sequence

from backend.rinse_bag_completion import rack_contains_clean
from backend.rinse_bag_stage_bounds import (
    event_ts,
    events_after_ts,
    events_on_or_after,
    first_drying_after,
    first_start_cleaning_after,
    first_weight_after_anchor,
    gaming_events_from_records,
    lifecycle_anchor,
    load_washer_bounds,
    sort_key_ev,
    ts_valid,
    visible_timeline,
)
from backend.rinse_scan_time import system_datetime_to_et
from backend.rinse_scan_purpose import (
    is_add_photos_purpose,
    is_create_issue_purpose,
    is_create_workitem_purpose,
    is_drying_purpose,
    is_ghost_cleaning_purpose,
    is_processed_by_vendor_purpose,
    is_quality_control_completed_purpose,
    is_received_from_vendor_purpose,
    is_start_cleaning_purpose,
    is_weight_entry_purpose,
    normalize_scan_purpose,
    purpose_contains_workitem,
)

ROLE_WEIGHING = "weighing"
ROLE_SORTING = "sorting"
ROLE_WASHING = "washing"
ROLE_DRYING = "drying"
ROLE_FOLDING = "folding"
ROLE_ISSUES = "issues"
ROLE_WORKITEMS = "workitems"

ALL_ROLES = (
    ROLE_WEIGHING,
    ROLE_SORTING,
    ROLE_WASHING,
    ROLE_DRYING,
    ROLE_FOLDING,
    ROLE_ISSUES,
    ROLE_WORKITEMS,
)


def is_cleaning_purpose_for_activity_start(raw: str | None) -> bool:
    """Cleaning purpose usable for weighing/sorting start anchors."""
    return is_ghost_cleaning_purpose(raw) or is_start_cleaning_purpose(raw)


def _operator(ev: Mapping[str, Any] | None) -> str | None:
    if not ev:
        return None
    name = str(ev.get("user") or ev.get("user_name") or "").strip()
    return name or None


def _weight_lbs_from_event(ev: Mapping[str, Any] | None) -> float | None:
    if not ev:
        return None
    for key in ("weight_lbs", "weight_num", "weight"):
        raw = ev.get(key)
        if raw is None:
            continue
        try:
            v = float(raw)
            if v > 0:
                return v
        except (TypeError, ValueError):
            continue
    return None


def _last_cleaning_before(
    timeline: Sequence[Mapping[str, Any]], *, before: datetime
) -> Mapping[str, Any] | None:
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


def _occurrence_et_key(ts: datetime) -> datetime:
    """Normalize scan wall time to naive ET for dedupe/comparison."""
    et = system_datetime_to_et(ts)
    if et is not None:
        return et.replace(tzinfo=None)
    return ts


def unique_occurrence_times(
    events: Sequence[Mapping[str, Any]],
    purpose_matches: Callable[[str | None], bool],
) -> list[tuple[Mapping[str, Any], datetime]]:
    """
    Chronological unique occurrences for one normalized purpose family.

    Duplicate rows at the same ET instant count once. Returned timestamps are
    strictly increasing by ET wall time.
    """
    keyed: list[tuple[Mapping[str, Any], datetime, datetime]] = []
    for ev in events:
        if not purpose_matches(ev.get("purpose")):
            continue
        ts = event_ts(ev)
        if not ts_valid(ts):
            continue
        keyed.append((ev, ts, _occurrence_et_key(ts)))
    keyed.sort(key=lambda item: (item[2], sort_key_ev(item[0])))
    out: list[tuple[Mapping[str, Any], datetime]] = []
    seen_et: set[datetime] = set()
    for ev, ts, et_key in keyed:
        if et_key in seen_et:
            continue
        seen_et.add(et_key)
        out.append((ev, ts))
    return out


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


def _is_synthetic_weight_evidence(ev: Mapping[str, Any]) -> bool:
    """Synthetic near-complete recovery rows are not portal completion evidence."""
    from backend.rinse_wf_weight_events import is_synthetic_post_processing_weight_event

    return is_synthetic_post_processing_weight_event(ev)


def _all_weight_entries_after_anchor(
    anchored: Sequence[Mapping[str, Any]],
) -> list[tuple[Mapping[str, Any], datetime]]:
    out: list[tuple[Mapping[str, Any], datetime]] = []
    for ev in anchored:
        if not is_weight_entry_purpose(ev.get("purpose")):
            continue
        if _is_synthetic_weight_evidence(ev):
            continue
        ts = event_ts(ev)
        if ts_valid(ts):
            out.append((ev, ts))
    return out


def _first_clean_rack_event(
    timeline: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any] | None, datetime | None]:
    for ev in timeline:
        if rack_contains_clean(ev.get("rack")):
            ts = event_ts(ev)
            if ts_valid(ts):
                return ev, ts
    return None, None


def find_strong_completion_evidence_v2(
    timeline: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any], datetime, str] | None:
    """
    Earliest strong completion without CLEAN rack.

    Signals: processed-by-vendor, received-from-vendor, quality-control-completed,
    second/post-process weight-entry after first valid post-anchor weight.
    """
    tl = list(timeline)
    best: tuple[datetime, Mapping[str, Any], str] | None = None

    def _consider(ts: datetime, ev: Mapping[str, Any], kind: str) -> None:
        nonlocal best
        if best is None or ts < best[0]:
            best = (ts, ev, kind)

    anchor_ts, _ = lifecycle_anchor(tl)
    anchored = events_on_or_after(tl, anchor_ts) if anchor_ts is not None else visible_timeline(tl)
    weights = _all_weight_entries_after_anchor(anchored)
    if len(weights) >= 2:
        ev, ts = weights[1]
        _consider(ts, ev, "second-weight-entry")

    processed_at: datetime | None = None
    for ev in tl:
        ts = event_ts(ev)
        if not ts_valid(ts):
            continue
        purpose = ev.get("purpose")
        if is_processed_by_vendor_purpose(purpose):
            processed_at = ts
            _consider(ts, ev, "processed-by-vendor")
        elif is_received_from_vendor_purpose(purpose):
            _consider(ts, ev, "received-from-vendor")
        elif is_quality_control_completed_purpose(purpose):
            _consider(ts, ev, "quality-control-completed")

    if processed_at is not None:
        for ev in tl:
            ts = event_ts(ev)
            if not ts_valid(ts) or ts <= processed_at:
                continue
            if not is_weight_entry_purpose(ev.get("purpose")):
                continue
            if _is_synthetic_weight_evidence(ev):
                continue
            _consider(ts, ev, "weight-entry-after-processed-by-vendor")
            break

    if best is None:
        return None
    ts, ev, kind = best
    return ev, ts, kind


@dataclass
class BagCompletionResult:
    completed: bool
    via_clean_rack: bool
    completion_at: datetime | None
    completion_user: str | None
    completion_kind: str | None
    exception_code: str | None
    needs_review: bool


def evaluate_bag_completion_v2(
    timeline: Sequence[Mapping[str, Any]],
) -> BagCompletionResult:
    tl = gaming_events_from_records(timeline)
    clean_ev, clean_at = _first_clean_rack_event(tl)
    if clean_ev is not None and ts_valid(clean_at):
        return BagCompletionResult(
            completed=True,
            via_clean_rack=True,
            completion_at=clean_at,
            completion_user=_operator(clean_ev),
            completion_kind="clean-rack",
            exception_code=None,
            needs_review=False,
        )

    evidence = find_strong_completion_evidence_v2(tl)
    if evidence is None:
        return BagCompletionResult(
            completed=False,
            via_clean_rack=False,
            completion_at=None,
            completion_user=None,
            completion_kind=None,
            exception_code=None,
            needs_review=False,
        )

    ev, ts, kind = evidence
    return BagCompletionResult(
        completed=True,
        via_clean_rack=False,
        completion_at=ts,
        completion_user=_operator(ev),
        completion_kind=kind,
        exception_code="COMPLETED_WITHOUT_FINAL_CLEAN_SCAN",
        needs_review=True,
    )


@dataclass
class WeightDifferenceResult:
    flagged: bool
    first_weight_lbs: float | None
    second_weight_lbs: float | None
    difference_lbs: float | None
    threshold_lbs: float
    first_weight_at: datetime | None = None
    second_weight_at: datetime | None = None
    first_weight_user: str | None = None
    second_weight_user: str | None = None
    comparable: bool = False
    unavailable_reason: str | None = None


def evaluate_weight_difference(
    timeline: Sequence[Mapping[str, Any]],
    *,
    threshold_lbs: float = 5.0,
) -> WeightDifferenceResult:
    tl = gaming_events_from_records(timeline)
    anchor_ts, _ = lifecycle_anchor(tl)
    anchored = events_on_or_after(tl, anchor_ts) if anchor_ts is not None else visible_timeline(tl)
    weights = _all_weight_entries_after_anchor(anchored)
    empty = WeightDifferenceResult(
        flagged=False,
        first_weight_lbs=None,
        second_weight_lbs=None,
        difference_lbs=None,
        threshold_lbs=threshold_lbs,
        unavailable_reason="No comparable first/second weights",
    )
    if len(weights) < 2:
        if len(weights) == 1:
            w1_ev, w1_ts = weights[0]
            return WeightDifferenceResult(
                flagged=False,
                first_weight_lbs=_weight_lbs_from_event(w1_ev),
                second_weight_lbs=None,
                difference_lbs=None,
                threshold_lbs=threshold_lbs,
                first_weight_at=w1_ts,
                first_weight_user=_operator(w1_ev),
                unavailable_reason="No comparable first/second weights",
            )
        return empty

    w1_ev, w1_ts = weights[0]
    w2_ev, w2_ts = weights[1]
    w1 = _weight_lbs_from_event(w1_ev)
    w2 = _weight_lbs_from_event(w2_ev)
    if w1 is None or w2 is None:
        return WeightDifferenceResult(
            flagged=False,
            first_weight_lbs=w1,
            second_weight_lbs=w2,
            difference_lbs=None,
            threshold_lbs=threshold_lbs,
            first_weight_at=w1_ts,
            second_weight_at=w2_ts,
            first_weight_user=_operator(w1_ev),
            second_weight_user=_operator(w2_ev),
            unavailable_reason="No comparable first/second weights",
        )
    diff = abs(w2 - w1)
    return WeightDifferenceResult(
        flagged=diff >= threshold_lbs,
        first_weight_lbs=w1,
        second_weight_lbs=w2,
        difference_lbs=round(diff, 2),
        threshold_lbs=threshold_lbs,
        first_weight_at=w1_ts,
        second_weight_at=w2_ts,
        first_weight_user=_operator(w1_ev),
        second_weight_user=_operator(w2_ev),
        comparable=True,
    )


def sorting_bounds_v2(
    anchored: Sequence[Mapping[str, Any]],
    weight_ts: datetime,
    weight_ev: Mapping[str, Any],
    *,
    full_timeline: Sequence[Mapping[str, Any]] | None = None,
) -> tuple[Mapping[str, Any] | None, Mapping[str, Any] | None, Mapping[str, Any] | None]:
    """
    Returns (add_photos_ev, sorting_start_ev, sorting_end_ev).
    Sorting exists only when add-photos occurs after first weight.
    """
    add_ev = _first_add_photos_after(anchored, after_ts=weight_ts)
    if add_ev is None:
        return None, None, None
    add_ts = event_ts(add_ev)
    if not ts_valid(add_ts):
        return add_ev, None, None

    cleaning_ev = _last_cleaning_before(
        list(full_timeline) if full_timeline is not None else list(anchored),
        before=add_ts,
    )
    sorting_start_ev = cleaning_ev if cleaning_ev is not None else weight_ev

    after_weight = events_after_ts(anchored, weight_ts)
    start_cleaning_ev = first_start_cleaning_after(anchored, after_ts=weight_ts)
    if start_cleaning_ev is not None:
        sc_ts = event_ts(start_cleaning_ev)
        before_sc = [ev for ev in after_weight if ts_valid(event_ts(ev)) and event_ts(ev) < sc_ts]
        sorting_end_ev = max(before_sc, key=sort_key_ev) if before_sc else None
    else:
        sorting_end_ev = max(after_weight, key=sort_key_ev) if after_weight else None

    return add_ev, sorting_start_ev, sorting_end_ev


@dataclass
class BagActivityCredit:
    bag_id: str
    role: str
    employee: str | None
    activity_at: datetime
    start_time: datetime | None = None
    end_time: datetime | None = None
    lbs: float | None = None
    customer: str | None = None
    needs_review: bool = False
    flags: tuple[str, ...] = field(default_factory=tuple)
    activity_kind: str | None = None


def extract_bag_activity_credits(
    bag_id: str,
    events: Sequence[Mapping[str, Any]],
    *,
    customer: str | None = None,
    default_lbs: float | None = None,
) -> list[BagActivityCredit]:
    """All role credits for one bag from its scan timeline."""
    bid = str(bag_id or "").strip()
    tl = gaming_events_from_records(events)
    credits: list[BagActivityCredit] = []

    anchor_ts, _ = lifecycle_anchor(tl)
    anchored = events_on_or_after(tl, anchor_ts) if anchor_ts is not None else visible_timeline(tl)
    weight_ev, weight_ts = first_weight_after_anchor(anchored)

    if weight_ev is not None and weight_ts is not None:
        w_user = _operator(weight_ev)
        w_start_ev = _last_cleaning_before(tl, before=weight_ts)
        w_flags: list[str] = []
        if w_start_ev is None:
            w_flags.append("WEIGHING_START_CLEANING_MISSING")
        credits.append(
            BagActivityCredit(
                bag_id=bid,
                role=ROLE_WEIGHING,
                employee=w_user,
                activity_at=weight_ts,
                start_time=event_ts(w_start_ev) if w_start_ev else None,
                end_time=weight_ts,
                lbs=default_lbs or _weight_lbs_from_event(weight_ev),
                customer=customer,
                needs_review=not w_user or not w_start_ev,
                flags=tuple(w_flags),
                activity_kind="weight-entry",
            )
        )

        from backend.rinse_sorting_session import compute_sorting_session

        sort_session = compute_sorting_session(
            anchored, tl, weight_ev=weight_ev, weight_ts=weight_ts
        )
        if sort_session is not None:
            sort_start_ts = (
                event_ts(sort_session.sort_start_ev) if sort_session.sort_start_ev else weight_ts
            )
            sort_end_ts = (
                event_ts(sort_session.sort_end_ev) if sort_session.sort_end_ev else None
            )
            activity_ts = sort_end_ts if ts_valid(sort_end_ts) else sort_start_ts
            end_ev = sort_session.sort_end_ev or sort_session.add_photos_ev
            if ts_valid(activity_ts):
                flags: tuple[str, ...] = ()
                if sort_session.confidence == "inferred":
                    flags = ("INFERRED_SORTING_BEFORE_WASH_HANDOFF",)
                if sort_end_ts is None:
                    flags = (*flags, "MISSING_SORTING_END")
                credits.append(
                    BagActivityCredit(
                        bag_id=bid,
                        role=ROLE_SORTING,
                        employee=sort_session.employee,
                        activity_at=activity_ts,
                        start_time=sort_start_ts if ts_valid(sort_start_ts) else weight_ts,
                        end_time=sort_end_ts,
                        lbs=default_lbs,
                        customer=customer,
                        needs_review=sort_end_ts is None,
                        flags=flags,
                        activity_kind=(
                            normalize_scan_purpose(end_ev.get("purpose"))
                            if end_ev is not None
                            else "add-photos"
                        ),
                    )
                )

    start_cleaning_ev = first_start_cleaning_after(anchored)
    if start_cleaning_ev is not None:
        sc_ts = event_ts(start_cleaning_ev)
        if ts_valid(sc_ts):
            _, load_end, load_end_ts = load_washer_bounds(anchored)
            wash_end = load_end_ts if load_end_ts is not None else sc_ts
            dry_ev = first_drying_after(anchored, after_ts=sc_ts)
            credits.append(
                BagActivityCredit(
                    bag_id=bid,
                    role=ROLE_WASHING,
                    employee=_operator(start_cleaning_ev),
                    activity_at=sc_ts,
                    start_time=sc_ts,
                    end_time=wash_end,
                    lbs=default_lbs,
                    customer=customer,
                    needs_review=dry_ev is None,
                    flags=("DRYING_PURPOSE_MISSING",) if dry_ev is None else (),
                    activity_kind="start-cleaning",
                )
            )

    dry_ev = first_drying_after(anchored)
    if dry_ev is not None:
        dry_ts = event_ts(dry_ev)
        if ts_valid(dry_ts):
            credits.append(
                BagActivityCredit(
                    bag_id=bid,
                    role=ROLE_DRYING,
                    employee=_operator(dry_ev),
                    activity_at=dry_ts,
                    start_time=dry_ts,
                    end_time=dry_ts,
                    lbs=default_lbs,
                    customer=customer,
                    activity_kind="drying",
                )
            )

    completion = evaluate_bag_completion_v2(events)
    if completion.completed and ts_valid(completion.completion_at):
        credits.append(
            BagActivityCredit(
                bag_id=bid,
                role=ROLE_FOLDING,
                employee=completion.completion_user,
                activity_at=completion.completion_at,
                start_time=completion.completion_at,
                end_time=completion.completion_at,
                lbs=default_lbs,
                customer=customer,
                needs_review=completion.needs_review,
                flags=(completion.exception_code,) if completion.exception_code else (),
                activity_kind=completion.completion_kind,
            )
        )

    for ev in tl:
        if is_create_issue_purpose(ev.get("purpose")):
            ts = event_ts(ev)
            if ts_valid(ts):
                credits.append(
                    BagActivityCredit(
                        bag_id=bid,
                        role=ROLE_ISSUES,
                        employee=_operator(ev),
                        activity_at=ts,
                        start_time=ts,
                        end_time=ts,
                        customer=customer,
                        activity_kind="create-issue",
                    )
                )

    if weight_ts is not None:
        for ev in events_after_ts(anchored, weight_ts):
            purpose = ev.get("purpose")
            if not (is_create_workitem_purpose(purpose) or purpose_contains_workitem(purpose)):
                continue
            ts = event_ts(ev)
            if ts_valid(ts):
                credits.append(
                    BagActivityCredit(
                        bag_id=bid,
                        role=ROLE_WORKITEMS,
                        employee=_operator(ev),
                        activity_at=ts,
                        start_time=ts,
                        end_time=ts,
                        customer=customer,
                        activity_kind="workitem",
                    )
                )

    return credits


def credit_in_et_period(
    credit: BagActivityCredit,
    *,
    period_start: datetime,
    period_end_exclusive: datetime,
) -> bool:
    ts = credit.activity_at
    if not ts_valid(ts):
        return False
    return period_start <= ts < period_end_exclusive
