"""
Wash & Fold bag gaming / performance stage timings from Rinse scan events.

Weighing and sorting use post–sent-to-vendor anchor and shared stage bounds.
Folding uses existing evaluate_folding_performance_for_bag unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence

from backend.rinse_bag_completion import rack_contains_clean
from backend.rinse_bag_folding import FoldingResult, evaluate_folding_performance_for_bag
from backend.rinse_bag_stage_bounds import (
    event_ts as _event_ts,
    events_on_or_after as _events_on_or_after,
    first_drying_after as _first_drying_after,
    first_start_cleaning_after as _first_start_cleaning_after,
    first_weight_after_anchor as _first_weight_after_anchor,
    gaming_events_from_records,
    lifecycle_anchor as _lifecycle_anchor,
    load_washer_bounds as _load_washer_bounds,
    sort_key_ev as _sort_key_ev,
    ts_valid as _ts_valid,
    weighing_performance_bounds as _weighing_performance_bounds,
    _first_add_photos_after,
)
from backend.rinse_processing_settings import DEFAULT_DRYING_MINUTES, DEFAULT_WASHING_MINUTES
from backend.rinse_scan_purpose import (
    is_create_issue_purpose,
    is_create_workitem_purpose,
    is_start_cleaning_purpose,
    normalize_scan_purpose,
)
from backend.rinse_sorting_session import (
    canonical_add_photos_for_weight,
    compute_sorting_session,
    sorting_session_bounds,
)

STAGE_COMPLETED = "COMPLETED"
STAGE_EXCEPTION = "EXCEPTION"

SORTING_INTERRUPTED_BY_WORKITEM = "SORTING_INTERRUPTED_BY_WORKITEM"
SORTING_INTERRUPTED_BY_ISSUE = "SORTING_INTERRUPTED_BY_ISSUE"

WEIGHT_ENTRY_MISSING = "WEIGHT_ENTRY_MISSING"
WEIGHING_START_SCAN_MISSING = "WEIGHING_START_SCAN_MISSING"
WEIGHING_START_CLEANING_MISSING = "WEIGHING_START_CLEANING_MISSING"
WEIGHING_DURATION_INVALID = "WEIGHING_DURATION_INVALID"

EXCEPTION_MISSING_SORTING_END = "MISSING_SORTING_END"
EXCEPTION_SORTING_ADD_PHOTOS_MISSING = "SORTING_ADD_PHOTOS_MISSING"
EXCEPTION_INVALID_SORTING_TIMESTAMPS = "INVALID_SORTING_TIMESTAMPS"

START_CLEANING_MISSING = "START_CLEANING_MISSING"
DRYING_PURPOSE_MISSING = "DRYING_PURPOSE_MISSING"
WASH_LOAD_DURATION_INVALID = "WASH_LOAD_DURATION_INVALID"
WASH_LOAD_DURATION_TOO_SHORT = "WASH_LOAD_DURATION_TOO_SHORT"
WASH_LOAD_DURATION_TOO_LONG = "WASH_LOAD_DURATION_TOO_LONG"

PERF_STAGE_LOAD_WASHER = "LOAD_WASHER"
PERF_STAGE_LOAD_DRYER = "LOAD_DRYER"


@dataclass(frozen=True)
class WashLoadLimits:
    min_seconds: int | None = None
    max_seconds: int | None = None


@dataclass(frozen=True)
class StageTiming:
    start_time: datetime | None
    end_time: datetime | None
    end_event_purpose: str | None
    duration_seconds: int | None
    status: str
    exception_codes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "start_time": self.start_time,
            "end_time": self.end_time,
            "end_event_purpose": self.end_event_purpose,
            "duration_seconds": self.duration_seconds,
            "duration_minutes": round(self.duration_seconds / 60.0, 2)
            if self.duration_seconds is not None
            else None,
            "status": self.status,
            "exception_codes": list(self.exception_codes),
        }


def _duration_seconds(start: datetime | None, end: datetime | None) -> int | None:
    if not _ts_valid(start) or not _ts_valid(end):
        return None
    sec = int((end - start).total_seconds())
    return sec if sec >= 0 else None


def _anchored_timeline(timeline: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    anchor_ts, _ = _lifecycle_anchor(timeline)
    return _events_on_or_after(timeline, anchor_ts)


def evaluate_weighing_stage(timeline: Sequence[Mapping[str, Any]]) -> StageTiming:
    cleaning_ev, weight_ev = _weighing_performance_bounds(timeline)
    if weight_ev is None:
        return StageTiming(
            start_time=None,
            end_time=None,
            end_event_purpose=None,
            duration_seconds=None,
            status=STAGE_EXCEPTION,
            exception_codes=(WEIGHT_ENTRY_MISSING,),
        )
    end_at = _event_ts(weight_ev)
    if not _ts_valid(end_at):
        return StageTiming(
            start_time=None,
            end_time=None,
            end_event_purpose=None,
            duration_seconds=None,
            status=STAGE_EXCEPTION,
            exception_codes=(WEIGHT_ENTRY_MISSING, WEIGHING_DURATION_INVALID),
        )
    if cleaning_ev is None:
        return StageTiming(
            start_time=None,
            end_time=end_at,
            end_event_purpose="weight-entry",
            duration_seconds=None,
            status=STAGE_EXCEPTION,
            exception_codes=(
                WEIGHING_START_CLEANING_MISSING,
                WEIGHING_START_SCAN_MISSING,
            ),
        )
    start_at = _event_ts(cleaning_ev)
    dur = _duration_seconds(start_at, end_at)
    if dur is None:
        return StageTiming(
            start_time=start_at,
            end_time=end_at,
            end_event_purpose="weight-entry",
            duration_seconds=None,
            status=STAGE_EXCEPTION,
            exception_codes=(WEIGHING_DURATION_INVALID,),
        )
    return StageTiming(
        start_time=start_at,
        end_time=end_at,
        end_event_purpose="weight-entry",
        duration_seconds=dur,
        status=STAGE_COMPLETED,
        exception_codes=(),
    )


def evaluate_sorting_stage(timeline: Sequence[Mapping[str, Any]]) -> StageTiming:
    anchored = _anchored_timeline(timeline)
    weight_ev, weight_ts = _first_weight_after_anchor(anchored)
    if weight_ev is None or weight_ts is None:
        return StageTiming(
            start_time=None,
            end_time=None,
            end_event_purpose=None,
            duration_seconds=None,
            status=STAGE_EXCEPTION,
            exception_codes=(WEIGHT_ENTRY_MISSING,),
        )
    session = compute_sorting_session(
        anchored, timeline, weight_ev=weight_ev, weight_ts=weight_ts
    )
    if session is None:
        add_missing = canonical_add_photos_for_weight(anchored, weight_ts) is None
        return StageTiming(
            start_time=None,
            end_time=None,
            end_event_purpose=None,
            duration_seconds=None,
            status=STAGE_EXCEPTION,
            exception_codes=(
                (EXCEPTION_SORTING_ADD_PHOTOS_MISSING,)
                if add_missing
                else (WEIGHT_ENTRY_MISSING,)
            ),
        )
    start_ev = session.sort_start_ev
    end_ev = session.sort_end_ev
    start_at = _event_ts(start_ev)
    if end_ev is None:
        return StageTiming(
            start_time=start_at,
            end_time=None,
            end_event_purpose=None,
            duration_seconds=None,
            status=STAGE_EXCEPTION,
            exception_codes=(EXCEPTION_MISSING_SORTING_END,),
        )
    end_at = _event_ts(end_ev)
    end_purpose = normalize_scan_purpose(end_ev.get("purpose"))
    dur = _duration_seconds(start_at, end_at)
    if dur is None:
        return StageTiming(
            start_time=start_at,
            end_time=end_at,
            end_event_purpose=end_purpose,
            duration_seconds=None,
            status=STAGE_EXCEPTION,
            exception_codes=(EXCEPTION_INVALID_SORTING_TIMESTAMPS,),
        )
    return StageTiming(
        start_time=start_at,
        end_time=end_at,
        end_event_purpose=end_purpose,
        duration_seconds=dur,
        status=STAGE_COMPLETED,
        exception_codes=(),
    )


def evaluate_load_washer_stage(timeline: Sequence[Mapping[str, Any]]) -> StageTiming:
    anchored = _anchored_timeline(timeline)
    start_ev, end_ev, _load_end_ts = _load_washer_bounds(anchored)
    if start_ev is None:
        return StageTiming(
            start_time=None,
            end_time=None,
            end_event_purpose=None,
            duration_seconds=None,
            status=STAGE_EXCEPTION,
            exception_codes=(START_CLEANING_MISSING,),
        )
    start_at = _event_ts(start_ev)
    if end_ev is None:
        return StageTiming(
            start_time=start_at,
            end_time=None,
            end_event_purpose=None,
            duration_seconds=None,
            status=STAGE_EXCEPTION,
            exception_codes=(START_CLEANING_MISSING,),
        )
    end_at = _event_ts(end_ev)
    dur = _duration_seconds(start_at, end_at)
    return StageTiming(
        start_time=start_at,
        end_time=end_at,
        end_event_purpose=normalize_scan_purpose(end_ev.get("purpose")),
        duration_seconds=dur,
        status=STAGE_COMPLETED if dur is not None else STAGE_EXCEPTION,
        exception_codes=() if dur is not None else (WASH_LOAD_DURATION_INVALID,),
    )


def evaluate_in_washing_stage(
    timeline: Sequence[Mapping[str, Any]],
    *,
    washing_minutes: int = DEFAULT_WASHING_MINUTES,
) -> StageTiming:
    del washing_minutes
    anchored = _anchored_timeline(timeline)
    load_start, load_end, load_end_ts = _load_washer_bounds(anchored)
    start_cleaning_ev = _first_start_cleaning_after(anchored)
    start_ev = load_start or start_cleaning_ev
    if start_ev is None:
        return StageTiming(
            start_time=None,
            end_time=None,
            end_event_purpose=None,
            duration_seconds=None,
            status=STAGE_EXCEPTION,
            exception_codes=(START_CLEANING_MISSING,),
        )
    in_wash_start = load_end_ts if load_end_ts is not None else _event_ts(start_ev)
    dry_ev = _first_drying_after(anchored, after_ts=in_wash_start)
    end_at = _event_ts(dry_ev) if dry_ev else None
    dur = _duration_seconds(in_wash_start, end_at) if end_at else None
    return StageTiming(
        start_time=in_wash_start,
        end_time=end_at,
        end_event_purpose="drying" if dry_ev else None,
        duration_seconds=dur,
        status=STAGE_COMPLETED if end_at else STAGE_EXCEPTION,
        exception_codes=() if end_at else (DRYING_PURPOSE_MISSING,),
    )


def evaluate_load_dryer_stage(timeline: Sequence[Mapping[str, Any]]) -> StageTiming:
    anchored = _anchored_timeline(timeline)
    dry_ev = _first_drying_after(anchored)
    if dry_ev is None:
        return StageTiming(
            start_time=None,
            end_time=None,
            end_event_purpose=None,
            duration_seconds=0,
            status=STAGE_EXCEPTION,
            exception_codes=(DRYING_PURPOSE_MISSING,),
        )
    dry_ts = _event_ts(dry_ev)
    return StageTiming(
        start_time=dry_ts,
        end_time=dry_ts,
        end_event_purpose="drying",
        duration_seconds=0,
        status=STAGE_COMPLETED,
        exception_codes=(),
    )


def evaluate_in_drying_stage(
    timeline: Sequence[Mapping[str, Any]],
    *,
    drying_minutes: int = DEFAULT_DRYING_MINUTES,
) -> StageTiming:
    del drying_minutes
    anchored = _anchored_timeline(timeline)
    dry_ev = _first_drying_after(anchored)
    if dry_ev is None:
        return StageTiming(
            start_time=None,
            end_time=None,
            end_event_purpose=None,
            duration_seconds=None,
            status=STAGE_EXCEPTION,
            exception_codes=(DRYING_PURPOSE_MISSING,),
        )
    start_at = _event_ts(dry_ev)
    clean_at: datetime | None = None
    for ev in timeline:
        if rack_contains_clean(ev.get("rack")):
            ts = _event_ts(ev)
            if _ts_valid(ts) and ts >= start_at:
                clean_at = ts
                break
    dur = _duration_seconds(start_at, clean_at) if clean_at else None
    return StageTiming(
        start_time=start_at,
        end_time=clean_at,
        end_event_purpose="clean-rack" if clean_at else None,
        duration_seconds=dur,
        status=STAGE_COMPLETED if clean_at else STAGE_EXCEPTION,
        exception_codes=() if clean_at else (DRYING_PURPOSE_MISSING,),
    )


def evaluate_wash_load_stage(
    timeline: Sequence[Mapping[str, Any]],
    *,
    limits: WashLoadLimits | None = None,
) -> StageTiming:
    """Legacy combined wash/load stage (start-cleaning → drying) on anchored timeline."""
    anchored = _anchored_timeline(timeline)
    start_ev = _first_start_cleaning_after(anchored)
    if start_ev is None:
        return StageTiming(
            start_time=None,
            end_time=None,
            end_event_purpose=None,
            duration_seconds=None,
            status=STAGE_EXCEPTION,
            exception_codes=(START_CLEANING_MISSING,),
        )
    start_at = _event_ts(start_ev)
    if not _ts_valid(start_at):
        return StageTiming(
            start_time=None,
            end_time=None,
            end_event_purpose=None,
            duration_seconds=None,
            status=STAGE_EXCEPTION,
            exception_codes=(START_CLEANING_MISSING, WASH_LOAD_DURATION_INVALID),
        )
    dry_ev = _first_drying_after(anchored, after_ts=start_at)
    if dry_ev is None:
        return StageTiming(
            start_time=start_at,
            end_time=None,
            end_event_purpose=None,
            duration_seconds=None,
            status=STAGE_EXCEPTION,
            exception_codes=(DRYING_PURPOSE_MISSING,),
        )
    end_at = _event_ts(dry_ev)
    dur = _duration_seconds(start_at, end_at)
    if dur is None:
        return StageTiming(
            start_time=start_at,
            end_time=end_at,
            end_event_purpose="drying",
            duration_seconds=None,
            status=STAGE_EXCEPTION,
            exception_codes=(WASH_LOAD_DURATION_INVALID,),
        )
    codes: list[str] = []
    lim = limits or WashLoadLimits()
    if lim.min_seconds is not None and lim.min_seconds > 0 and dur < lim.min_seconds:
        codes.append(WASH_LOAD_DURATION_TOO_SHORT)
    if lim.max_seconds is not None and lim.max_seconds > 0 and dur > lim.max_seconds:
        codes.append(WASH_LOAD_DURATION_TOO_LONG)
    return StageTiming(
        start_time=start_at,
        end_time=end_at,
        end_event_purpose="drying",
        duration_seconds=dur,
        status=STAGE_COMPLETED if not codes else STAGE_EXCEPTION,
        exception_codes=tuple(codes),
    )


def bag_workitem_issue_indicators(timeline: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    workitems = [ev for ev in timeline if is_create_workitem_purpose(ev.get("purpose"))]
    issues = [ev for ev in timeline if is_create_issue_purpose(ev.get("purpose"))]
    return {
        "create_workitem_count": len(workitems),
        "create_issue_count": len(issues),
        "has_workitem": len(workitems) > 0,
        "has_issue": len(issues) > 0,
    }


def aggregate_daily_workitem_issue_indicators(
    bag_timelines: Sequence[Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    total_workitems = 0
    total_issues = 0
    bags_with_workitems = 0
    bags_with_issues = 0
    for timeline in bag_timelines:
        ind = bag_workitem_issue_indicators(timeline)
        total_workitems += int(ind["create_workitem_count"])
        total_issues += int(ind["create_issue_count"])
        if ind["has_workitem"]:
            bags_with_workitems += 1
        if ind["has_issue"]:
            bags_with_issues += 1
    return {
        "total_create_workitems": total_workitems,
        "total_create_issues": total_issues,
        "bags_with_workitems": bags_with_workitems,
        "bags_with_issues": bags_with_issues,
    }


def folding_stage_from_result(result: FoldingResult) -> dict[str, Any]:
    return {
        "start_time": result.folding_start_at,
        "end_time": result.folding_end_at,
        "duration_seconds": result.duration_seconds,
        "duration_minutes": round(result.duration_seconds / 60.0, 2)
        if result.duration_seconds is not None
        else None,
        "status": result.status,
        "exception_code": result.exception_code,
        "warning_codes": list(result.warning_codes),
        "assigned_user_name": result.assigned_user_name,
    }


def evaluate_bag_gaming_performance(
    events: Sequence[Mapping[str, Any]],
    *,
    registry_row: Mapping[str, Any] | None = None,
    rules: Any = None,
    wash_load_limits: WashLoadLimits | None = None,
    washing_minutes: int = DEFAULT_WASHING_MINUTES,
    drying_minutes: int = DEFAULT_DRYING_MINUTES,
) -> dict[str, Any]:
    timeline = gaming_events_from_records(events)
    weighing = evaluate_weighing_stage(timeline)
    sorting = evaluate_sorting_stage(timeline)
    load_washer = evaluate_load_washer_stage(timeline)
    in_washing = evaluate_in_washing_stage(timeline, washing_minutes=washing_minutes)
    load_dryer = evaluate_load_dryer_stage(timeline)
    in_drying = evaluate_in_drying_stage(timeline, drying_minutes=drying_minutes)
    wash_load = evaluate_wash_load_stage(timeline, limits=wash_load_limits)
    folding_result = evaluate_folding_performance_for_bag(
        events, registry_row=registry_row, rules=rules
    )
    indicators = bag_workitem_issue_indicators(timeline)
    return {
        "weighing": weighing.to_dict(),
        "sorting": sorting.to_dict(),
        "load_washer": load_washer.to_dict(),
        "in_washing": in_washing.to_dict(),
        "load_dryer": load_dryer.to_dict(),
        "in_drying": in_drying.to_dict(),
        "wash_load": wash_load.to_dict(),
        "folding": folding_stage_from_result(folding_result),
        "indicators": indicators,
        "folding_result": folding_result,
    }


ACTIVITY_WEIGHING = "weighing"
ACTIVITY_SORTING = "sorting"
ACTIVITY_WASH_LOAD = "wash_load"
ACTIVITY_FOLDING = "folding"

ALL_GAMING_ACTIVITIES = (
    ACTIVITY_WEIGHING,
    ACTIVITY_SORTING,
    ACTIVITY_WASH_LOAD,
    ACTIVITY_FOLDING,
)

REVIEW_USER_MISSING = "ACTIVITY_USER_MISSING"
REVIEW_USER_AMBIGUOUS = "ACTIVITY_USER_AMBIGUOUS"
REVIEW_STAGE_INCOMPLETE = "ACTIVITY_STAGE_INCOMPLETE"


def _normalize_user_name(raw: str | None) -> str | None:
    name = str(raw or "").strip()
    return name or None


def _event_user(ev: Mapping[str, Any] | None) -> str | None:
    if not ev:
        return None
    return _normalize_user_name(ev.get("user") or ev.get("user_name"))


def _users_match(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    return a.casefold() == b.casefold()


@dataclass(frozen=True)
class BagActivitySlice:
    bag_id: str
    activity: str
    start_time: datetime | None
    end_time: datetime | None
    assigned_user: str | None
    needs_review: bool
    review_reasons: tuple[str, ...]
    stage_status: str | None
    exception_codes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "bag_id": self.bag_id,
            "activity": self.activity,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "assigned_user": self.assigned_user,
            "needs_review": self.needs_review,
            "review_reasons": list(self.review_reasons),
            "stage_status": self.stage_status,
            "exception_codes": list(self.exception_codes),
        }


def _weighing_boundary_events(
    timeline: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any] | None, Mapping[str, Any] | None]:
    return _weighing_performance_bounds(timeline)


def _sorting_boundary_events(
    timeline: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any] | None, Mapping[str, Any] | None]:
    anchored = _anchored_timeline(timeline)
    weight_ev, weight_ts = _first_weight_after_anchor(anchored)
    if weight_ev is None or weight_ts is None:
        return None, None
    return sorting_session_bounds(
        anchored, timeline, weight_ev=weight_ev, weight_ts=weight_ts
    )


def _wash_load_boundary_events(
    timeline: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any] | None, Mapping[str, Any] | None]:
    anchored = _anchored_timeline(timeline)
    start_ev = _first_start_cleaning_after(anchored)
    if start_ev is None:
        return None, None
    start_at = _event_ts(start_ev)
    if not _ts_valid(start_at):
        return start_ev, None
    dry_ev = _first_drying_after(anchored, after_ts=start_at)
    return start_ev, dry_ev


def _slice_from_stage(
    *,
    bag_id: str,
    activity: str,
    stage: StageTiming,
    start_ev: Mapping[str, Any] | None,
    end_ev: Mapping[str, Any] | None,
    assigned_user: str | None,
    extra_review: Sequence[str] = (),
) -> BagActivitySlice:
    reasons: list[str] = list(extra_review)
    if stage.status == STAGE_EXCEPTION:
        reasons.append(REVIEW_STAGE_INCOMPLETE)
    if not assigned_user:
        reasons.append(REVIEW_USER_MISSING)
    return BagActivitySlice(
        bag_id=bag_id,
        activity=activity,
        start_time=stage.start_time,
        end_time=stage.end_time,
        assigned_user=assigned_user,
        needs_review=bool(reasons),
        review_reasons=tuple(dict.fromkeys(reasons)),
        stage_status=stage.status,
        exception_codes=stage.exception_codes,
    )


def build_bag_activity_slices(
    bag_id: str,
    events: Sequence[Mapping[str, Any]],
    *,
    registry_row: Mapping[str, Any] | None = None,
    rules: Any = None,
    wash_load_limits: WashLoadLimits | None = None,
) -> list[BagActivitySlice]:
    bid = str(bag_id or "").strip()
    timeline = gaming_events_from_records(events)
    slices: list[BagActivitySlice] = []

    weighing = evaluate_weighing_stage(timeline)
    w_start_ev, w_end_ev = _weighing_boundary_events(timeline)
    w_start_user = _event_user(w_start_ev)
    w_end_user = _event_user(w_end_ev)
    w_review: list[str] = []
    if w_start_user and w_end_user and not _users_match(w_start_user, w_end_user):
        w_review.append(REVIEW_USER_AMBIGUOUS)
    slices.append(
        _slice_from_stage(
            bag_id=bid,
            activity=ACTIVITY_WEIGHING,
            stage=weighing,
            start_ev=w_start_ev,
            end_ev=w_end_ev,
            assigned_user=w_end_user,
            extra_review=w_review,
        )
    )

    sorting = evaluate_sorting_stage(timeline)
    s_start_ev, s_end_ev = _sorting_boundary_events(timeline)
    anchored = _anchored_timeline(timeline)
    _, weight_ts = _first_weight_after_anchor(anchored)
    add_ev = _first_add_photos_after(anchored, after_ts=weight_ts) if weight_ts else None
    s_start_user = _event_user(s_start_ev)
    s_end_user = _event_user(s_end_ev)
    s_assigned = _event_user(add_ev) or s_end_user
    s_review: list[str] = []
    if s_start_user and s_assigned and not _users_match(s_start_user, s_assigned):
        s_review.append(REVIEW_USER_AMBIGUOUS)
    slices.append(
        _slice_from_stage(
            bag_id=bid,
            activity=ACTIVITY_SORTING,
            stage=sorting,
            start_ev=s_start_ev,
            end_ev=s_end_ev,
            assigned_user=s_assigned,
            extra_review=s_review,
        )
    )

    wash_load = evaluate_wash_load_stage(timeline, limits=wash_load_limits)
    wl_start_ev, wl_end_ev = _wash_load_boundary_events(timeline)
    wl_start_user = _event_user(wl_start_ev)
    wl_end_user = _event_user(wl_end_ev)
    wl_review: list[str] = []
    if wl_start_user and wl_end_user and not _users_match(wl_start_user, wl_end_user):
        wl_review.append(REVIEW_USER_AMBIGUOUS)
    wl_assigned = wl_start_user or wl_end_user
    slices.append(
        _slice_from_stage(
            bag_id=bid,
            activity=ACTIVITY_WASH_LOAD,
            stage=wash_load,
            start_ev=wl_start_ev,
            end_ev=wl_end_ev,
            assigned_user=wl_assigned,
            extra_review=wl_review,
        )
    )

    folding_result = evaluate_folding_performance_for_bag(
        events, registry_row=registry_row, rules=rules
    )
    fold_review: list[str] = []
    if folding_result.status == STAGE_EXCEPTION:
        fold_review.append(REVIEW_STAGE_INCOMPLETE)
    fold_user = _normalize_user_name(folding_result.assigned_user_name)
    if not fold_user:
        fold_review.append(REVIEW_USER_MISSING)
    slices.append(
        BagActivitySlice(
            bag_id=bid,
            activity=ACTIVITY_FOLDING,
            start_time=folding_result.folding_start_at,
            end_time=folding_result.folding_end_at,
            assigned_user=fold_user,
            needs_review=bool(fold_review),
            review_reasons=tuple(dict.fromkeys(fold_review)),
            stage_status=folding_result.status,
            exception_codes=(folding_result.exception_code,)
            if folding_result.exception_code
            else (),
        )
    )
    return slices


def build_bag_activity_slices_for_bags(
    bags: Sequence[Mapping[str, Any]],
    *,
    wash_load_limits: WashLoadLimits | None = None,
) -> list[BagActivitySlice]:
    out: list[BagActivitySlice] = []
    for bag in bags:
        bid = str(bag.get("bag_id") or "").strip()
        if not bid:
            continue
        out.extend(
            build_bag_activity_slices(
                bid,
                bag.get("events") or [],
                registry_row=bag.get("registry_row"),
                rules=bag.get("rules"),
                wash_load_limits=wash_load_limits,
            )
        )
    return out
