"""
Wash & Fold bag gaming / performance stage timings from Rinse scan events.

Weighing, sorting, and wash/load use **purpose labels only** (not rack detection).
Folding uses existing evaluate_folding_performance_for_bag unchanged (may use rack logic).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence

from backend.rinse_bag_completion import (
    _parsed_scan_datetime,
    _progressive_timeline_sort_key,
)
from backend.rinse_bag_folding import FoldingResult, evaluate_folding_performance_for_bag
from backend.rinse_scan_purpose import (
    is_add_photos_purpose,
    is_cleaning_related_purpose,
    is_create_issue_purpose,
    is_create_workitem_or_issue_purpose,
    is_create_workitem_purpose,
    is_drying_purpose,
    is_split_load_purpose,
    is_start_cleaning_purpose,
    is_weight_entry_purpose,
    normalize_scan_purpose,
)

STAGE_COMPLETED = "COMPLETED"
STAGE_EXCEPTION = "EXCEPTION"

# Deprecated — do not emit (timing markers only).
SORTING_INTERRUPTED_BY_WORKITEM = "SORTING_INTERRUPTED_BY_WORKITEM"
SORTING_INTERRUPTED_BY_ISSUE = "SORTING_INTERRUPTED_BY_ISSUE"

# Weighing
WEIGHT_ENTRY_MISSING = "WEIGHT_ENTRY_MISSING"
WEIGHING_START_SCAN_MISSING = "WEIGHING_START_SCAN_MISSING"
WEIGHING_DURATION_INVALID = "WEIGHING_DURATION_INVALID"

# Sorting
EXCEPTION_MISSING_SORTING_END = "MISSING_SORTING_END"
EXCEPTION_INVALID_SORTING_TIMESTAMPS = "INVALID_SORTING_TIMESTAMPS"

# Wash/load
START_CLEANING_MISSING = "START_CLEANING_MISSING"
DRYING_PURPOSE_MISSING = "DRYING_PURPOSE_MISSING"
WASH_LOAD_DURATION_INVALID = "WASH_LOAD_DURATION_INVALID"
WASH_LOAD_DURATION_TOO_SHORT = "WASH_LOAD_DURATION_TOO_SHORT"
WASH_LOAD_DURATION_TOO_LONG = "WASH_LOAD_DURATION_TOO_LONG"


@dataclass(frozen=True)
class WashLoadLimits:
    """Optional tenant thresholds; None disables min/max checks."""

    min_seconds: int | None = None
    max_seconds: int | None = None


def gaming_events_from_records(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Timeline events with purpose for gaming stage evaluation."""
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


def _ts_valid(ts: datetime | None) -> bool:
    return ts is not None and ts != datetime.min


def _event_ts(ev: Mapping[str, Any]) -> datetime | None:
    return _parsed_scan_datetime(ev)


def _sort_key_ev(ev: Mapping[str, Any]) -> tuple:
    ts = _event_ts(ev)
    return (
        ts is None,
        ts or datetime.min,
        int(ev.get("scan_index") or 0),
        int(ev.get("id") or 0),
    )


def _duration_seconds(start: datetime | None, end: datetime | None) -> int | None:
    if not _ts_valid(start) or not _ts_valid(end):
        return None
    sec = int((end - start).total_seconds())
    return sec if sec >= 0 else None


def _last_cleaning_purpose_before(
    timeline: Sequence[Mapping[str, Any]], *, before: datetime
) -> Mapping[str, Any] | None:
    candidates = [
        ev
        for ev in timeline
        if is_cleaning_related_purpose(ev.get("purpose"))
        and _ts_valid(_event_ts(ev))
        and _event_ts(ev) < before
    ]
    if not candidates:
        return None
    return max(candidates, key=_sort_key_ev)


def _first_cleaning_purpose_after(
    timeline: Sequence[Mapping[str, Any]], *, after: datetime, before: datetime | None
) -> Mapping[str, Any] | None:
    for ev in timeline:
        if not is_cleaning_related_purpose(ev.get("purpose")):
            continue
        ts = _event_ts(ev)
        if not _ts_valid(ts) or ts <= after:
            continue
        if before is not None and ts >= before:
            continue
        return ev
    return None


def _first_start_cleaning(
    timeline: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    for ev in timeline:
        if is_start_cleaning_purpose(ev.get("purpose")):
            return ev
    return None


def _first_drying_after(
    timeline: Sequence[Mapping[str, Any]], *, after: datetime
) -> Mapping[str, Any] | None:
    for ev in timeline:
        if not is_drying_purpose(ev.get("purpose")):
            continue
        ts = _event_ts(ev)
        if _ts_valid(ts) and ts > after:
            return ev
    return None


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


def evaluate_weighing_stage(timeline: Sequence[Mapping[str, Any]]) -> StageTiming:
    weight_ev = next((ev for ev in timeline if is_weight_entry_purpose(ev.get("purpose"))), None)
    if not weight_ev:
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

    start_ev = _last_cleaning_purpose_before(timeline, before=end_at)
    if start_ev is None:
        return StageTiming(
            start_time=None,
            end_time=end_at,
            end_event_purpose="weight-entry",
            duration_seconds=None,
            status=STAGE_EXCEPTION,
            exception_codes=(WEIGHING_START_SCAN_MISSING,),
        )

    start_at = _event_ts(start_ev)
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


def _first_sorting_phase_boundary(
    timeline: Sequence[Mapping[str, Any]], *, after: datetime
) -> datetime | None:
    """Earliest sorting-end-class purpose marker after ``after`` (caps sorting-start window)."""
    bounds: list[datetime] = []
    for ev in timeline:
        ts = _event_ts(ev)
        if not _ts_valid(ts) or ts <= after:
            continue
        if (
            is_create_workitem_or_issue_purpose(ev.get("purpose"))
            or is_split_load_purpose(ev.get("purpose"))
            or is_add_photos_purpose(ev.get("purpose"))
            or is_start_cleaning_purpose(ev.get("purpose"))
        ):
            bounds.append(ts)
    return min(bounds) if bounds else None


def _resolve_sorting_start(
    timeline: Sequence[Mapping[str, Any]],
) -> tuple[datetime | None, Mapping[str, Any] | None]:
    weight_ev = next((ev for ev in timeline if is_weight_entry_purpose(ev.get("purpose"))), None)
    if not weight_ev:
        return None, None
    weight_at = _event_ts(weight_ev)
    if not _ts_valid(weight_at):
        return None, weight_ev

    phase_end = _first_sorting_phase_boundary(timeline, after=weight_at)

    cleaning_ev = _first_cleaning_purpose_after(
        timeline, after=weight_at, before=phase_end
    )

    if cleaning_ev is not None:
        return _event_ts(cleaning_ev), cleaning_ev
    return weight_at, weight_ev


def _pick_sorting_end(
    timeline: Sequence[Mapping[str, Any]], *, sorting_start: datetime
) -> tuple[datetime | None, str | None, Mapping[str, Any] | None]:
    after = [ev for ev in timeline if _ts_valid(_event_ts(ev)) and _event_ts(ev) > sorting_start]

    workitem_issue = [ev for ev in after if is_create_workitem_or_issue_purpose(ev.get("purpose"))]
    if workitem_issue:
        ev = max(workitem_issue, key=_sort_key_ev)
        return _event_ts(ev), normalize_scan_purpose(ev.get("purpose")), ev

    for pred, purpose_label in (
        (is_split_load_purpose, "split-load"),
        (is_add_photos_purpose, "add-photos"),
    ):
        for ev in after:
            if pred(ev.get("purpose")):
                return _event_ts(ev), purpose_label, ev

    for ev in after:
        if is_start_cleaning_purpose(ev.get("purpose")):
            return _event_ts(ev), normalize_scan_purpose(ev.get("purpose")), ev

    for ev in after:
        if is_cleaning_related_purpose(ev.get("purpose")):
            return _event_ts(ev), normalize_scan_purpose(ev.get("purpose")), ev

    return None, None, None


def evaluate_sorting_stage(timeline: Sequence[Mapping[str, Any]]) -> StageTiming:
    start_at, _start_ev = _resolve_sorting_start(timeline)
    if start_at is None:
        return StageTiming(
            start_time=None,
            end_time=None,
            end_event_purpose=None,
            duration_seconds=None,
            status=STAGE_EXCEPTION,
            exception_codes=(WEIGHT_ENTRY_MISSING,),
        )

    end_at, end_purpose, _end_ev = _pick_sorting_end(timeline, sorting_start=start_at)
    if end_at is None:
        return StageTiming(
            start_time=start_at,
            end_time=None,
            end_event_purpose=None,
            duration_seconds=None,
            status=STAGE_EXCEPTION,
            exception_codes=(EXCEPTION_MISSING_SORTING_END,),
        )

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


def evaluate_wash_load_stage(
    timeline: Sequence[Mapping[str, Any]],
    *,
    limits: WashLoadLimits | None = None,
) -> StageTiming:
    start_ev = _first_start_cleaning(timeline)
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

    dry_ev = _first_drying_after(timeline, after=start_at)
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
    """Expose existing folding result without changing folding rules."""
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
) -> dict[str, Any]:
    """
    Per-bag gaming/performance timings: weighing, sorting, wash_load, folding (existing).
    """
    timeline = gaming_events_from_records(events)
    weighing = evaluate_weighing_stage(timeline)
    sorting = evaluate_sorting_stage(timeline)
    wash_load = evaluate_wash_load_stage(timeline, limits=wash_load_limits)
    folding_result = evaluate_folding_performance_for_bag(
        events, registry_row=registry_row, rules=rules
    )
    indicators = bag_workitem_issue_indicators(timeline)
    return {
        "weighing": weighing.to_dict(),
        "sorting": sorting.to_dict(),
        "wash_load": wash_load.to_dict(),
        "folding": folding_stage_from_result(folding_result),
        "indicators": indicators,
        "folding_result": folding_result,
    }


# --- Layer 2: per-bag activity slices for person/shift aggregation ---

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
    """One bag's activity assignment for shift-level gaming aggregation."""

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
    weight_ev = next((ev for ev in timeline if is_weight_entry_purpose(ev.get("purpose"))), None)
    if not weight_ev:
        return None, None
    end_at = _event_ts(weight_ev)
    if not _ts_valid(end_at):
        return None, weight_ev
    start_ev = _last_cleaning_purpose_before(timeline, before=end_at)
    return start_ev, weight_ev


def _sorting_boundary_events(
    timeline: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any] | None, Mapping[str, Any] | None]:
    start_at, start_ev = _resolve_sorting_start(timeline)
    if start_at is None:
        return None, None
    end_at, _end_purpose, end_ev = _pick_sorting_end(timeline, sorting_start=start_at)
    if end_at is None:
        return start_ev, None
    return start_ev, end_ev


def _wash_load_boundary_events(
    timeline: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any] | None, Mapping[str, Any] | None]:
    start_ev = _first_start_cleaning(timeline)
    if start_ev is None:
        return None, None
    start_at = _event_ts(start_ev)
    if not _ts_valid(start_at):
        return start_ev, None
    dry_ev = _first_drying_after(timeline, after=start_at)
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
    """
    Per-bag activity assignments for shift-level gaming.

    User assignment rules (purpose-based for weighing/sorting/wash_load):
    - weighing: weight-entry operator (flag if start/end operators differ)
    - sorting: sorting end-marker operator (flag if start/end operators differ)
    - wash_load: start-cleaning operator (flag if drying operator differs)
    - folding: existing folding assigned_user_name
    """
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
    s_start_user = _event_user(s_start_ev)
    s_end_user = _event_user(s_end_ev)
    s_review: list[str] = []
    if s_start_user and s_end_user and not _users_match(s_start_user, s_end_user):
        s_review.append(REVIEW_USER_AMBIGUOUS)
    slices.append(
        _slice_from_stage(
            bag_id=bid,
            activity=ACTIVITY_SORTING,
            stage=sorting,
            start_ev=s_start_ev,
            end_ev=s_end_ev,
            assigned_user=s_end_user,
            extra_review=s_review,
        )
    )

    wash_load = evaluate_wash_load_stage(timeline, limits=wash_load_limits)
    wl_start_ev, wl_end_ev = _wash_load_boundary_events(timeline)
    wl_start_user = _event_user(wl_start_ev)
    wl_end_user = _event_user(wl_end_ev)
    wl_review: list[str] = []
    if (
        wl_start_user
        and wl_end_user
        and not _users_match(wl_start_user, wl_end_user)
    ):
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
    """Build activity slices for many bags. Each bag dict needs ``bag_id`` and ``events``."""
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
