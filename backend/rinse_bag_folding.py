"""
Folding performance from scan-events (FOLDING rack → CLEAN rack interval).

Only meaningful for bags that are COMPLETED in rinse_bag_registry; caller enforces.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Mapping, Sequence

from backend.rinse_bag_completion import (
    COMPLETION_COMPLETED,
    events_from_records,
    rack_contains_clean,
    _parsed_scan_datetime,
    _progressive_timeline_sort_key,
)

STATUS_CALCULATED = "CALCULATED"
STATUS_EXCEPTION = "EXCEPTION"
STATUS_EXCLUDED = "EXCLUDED"

EXCEPTION_MISSING_SCAN_EVENTS = "MISSING_SCAN_EVENTS"
EXCEPTION_MISSING_FOLDING = "MISSING_FOLDING"
EXCEPTION_MISSING_CLEAN = "MISSING_CLEAN"
EXCEPTION_CLEAN_BEFORE_FOLDING = "CLEAN_BEFORE_FOLDING"
EXCEPTION_INVALID_TIMESTAMPS = "INVALID_TIMESTAMPS"
EXCEPTION_MISSING_ASSIGNED_USER = "MISSING_ASSIGNED_USER"
EXCEPTION_MULTIPLE_FOLDING_SCANS = "MULTIPLE_FOLDING_SCANS"
EXCEPTION_FOLDING_DURATION_TOO_SHORT = "FOLDING_DURATION_TOO_SHORT"
EXCEPTION_FOLDING_DURATION_TOO_LONG = "FOLDING_DURATION_TOO_LONG"
EXCEPTION_OVERLAP_OR_INVALID_TIMING = "OVERLAP_OR_INVALID_TIMING"
WARNING_MULTIPLE_CLEAN_SCANS = "MULTIPLE_CLEAN_SCANS"

MIN_FOLDING_DURATION_SECONDS = 600

FOLDING_WARNING_CODES = frozenset(
    {WARNING_MULTIPLE_CLEAN_SCANS, EXCEPTION_MULTIPLE_FOLDING_SCANS}
)


def parse_stored_warning_codes(raw: Any) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(x) for x in raw if x]
    import json

    try:
        parsed = json.loads(str(raw))
        if isinstance(parsed, list):
            return [str(x) for x in parsed if x]
    except (json.JSONDecodeError, TypeError):
        pass
    return []

SOURCE_FOLDING_SCAN = "FOLDING_SCAN"
SOURCE_CLEAN_SCAN_FALLBACK = "CLEAN_SCAN_FALLBACK"
SOURCE_MANUAL = "MANUAL"


def rack_contains_folding(rack: Any) -> bool:
    return "folding" in str(rack or "").lower()


def usable_user_name(user: Any) -> bool:
    return bool(str(user or "").strip())


def _user_from_event(ev: Mapping[str, Any]) -> str:
    return str(ev.get("user") or "").strip()


def _timestamp_valid(ts: datetime | None) -> bool:
    return ts is not None and ts != datetime.min


def _date_from_scan_ts(ts: datetime | None) -> date | None:
    if _timestamp_valid(ts):
        return ts.date()
    return None


def _datetime_from_registry_field(registry_row: Mapping[str, Any] | None, key: str) -> datetime | None:
    if not registry_row:
        return None
    val = registry_row.get(key)
    if isinstance(val, datetime):
        return val if _timestamp_valid(val) else None
    if val is not None and str(val) not in ("", "NaT", "None"):
        try:
            import pandas as pd

            p = pd.Timestamp(val)
            if not pd.isna(p):
                dt = p.to_pydatetime()
                return dt if _timestamp_valid(dt) else None
        except Exception:
            pass
    return None


def _registry_completed_at(registry_row: Mapping[str, Any] | None) -> datetime | None:
    for key in ("completed_at", "trigger_scan_at", "first_clean_scan_at"):
        dt = _datetime_from_registry_field(registry_row, key)
        if dt:
            return dt
    return None


def _best_timeline_scan_date(
    timeline: Sequence[Mapping[str, Any]],
    *,
    registry_row: Mapping[str, Any] | None = None,
) -> date | None:
    """Best available calendar date from scan timestamps (never portal date_clean)."""
    best: datetime | None = None
    for ev in timeline:
        ts = _parsed_scan_datetime(ev)
        if _timestamp_valid(ts) and (best is None or ts > best):
            best = ts
    if best:
        return best.date()
    reg = _registry_completed_at(registry_row)
    return _date_from_scan_ts(reg)


def _first_clean_scan_at_in_timeline(
    timeline: Sequence[Mapping[str, Any]],
    clean_indices: Sequence[int],
) -> datetime | None:
    for ci in clean_indices:
        ts = _parsed_scan_datetime(timeline[ci])
        if _timestamp_valid(ts):
            return ts
    return None


def _resolve_work_date_calculated(folding_end_at: datetime | None) -> date | None:
    """CALCULATED: work_date = DATE(folding_end_at) where end is the CLEAN scan."""
    return _date_from_scan_ts(folding_end_at)


def _resolve_work_date_exception(
    code: str,
    *,
    folding_start_at: datetime | None = None,
    folding_end_at: datetime | None = None,
    clean_scan_at: datetime | None = None,
    timeline: Sequence[Mapping[str, Any]] | None = None,
    registry_row: Mapping[str, Any] | None = None,
) -> date | None:
    tl = list(timeline or [])

    if code == EXCEPTION_MISSING_CLEAN:
        return _date_from_scan_ts(folding_start_at)

    if code == EXCEPTION_MISSING_FOLDING:
        d = _date_from_scan_ts(clean_scan_at)
        if d:
            return d
        return _date_from_scan_ts(_registry_completed_at(registry_row))

    if code == EXCEPTION_CLEAN_BEFORE_FOLDING:
        d = _date_from_scan_ts(clean_scan_at) or _date_from_scan_ts(folding_start_at)
        if d:
            return d
        return _best_timeline_scan_date(tl, registry_row=registry_row)

    if code == EXCEPTION_INVALID_TIMESTAMPS:
        for ts in (folding_end_at, folding_start_at, clean_scan_at):
            d = _date_from_scan_ts(ts)
            if d:
                return d
        return _best_timeline_scan_date(tl, registry_row=registry_row)

    if code == EXCEPTION_MISSING_ASSIGNED_USER:
        return _date_from_scan_ts(folding_end_at) or _date_from_scan_ts(folding_start_at)

    return _best_timeline_scan_date(tl, registry_row=registry_row)


@dataclass(frozen=True)
class FoldingResult:
    status: str
    exception_code: str | None
    folding_start_at: datetime | None
    folding_end_at: datetime | None
    duration_seconds: int | None
    folding_start_event_id: int | None
    folding_end_event_id: int | None
    folding_start_rack: str | None
    folding_end_rack: str | None
    assigned_user_name: str | None
    assigned_user_name_source: str | None
    folding_scan_count: int
    clean_scan_count: int
    work_date: date | None
    warning_codes: tuple[str, ...] = ()

    def to_performance_row(self, *, registry_completion_status: str) -> dict[str, Any]:
        import json

        return {
            "status": self.status,
            "exception_code": self.exception_code,
            "warning_codes": json.dumps(list(self.warning_codes))
            if self.warning_codes
            else None,
            "folding_start_at": self.folding_start_at,
            "folding_end_at": self.folding_end_at,
            "duration_seconds": self.duration_seconds,
            "folding_start_event_id": self.folding_start_event_id,
            "folding_end_event_id": self.folding_end_event_id,
            "folding_start_rack": self.folding_start_rack,
            "folding_end_rack": self.folding_end_rack,
            "assigned_user_name": self.assigned_user_name,
            "assigned_user_name_source": self.assigned_user_name_source,
            "folding_scan_count": self.folding_scan_count,
            "clean_scan_count": self.clean_scan_count,
            "work_date": self.work_date,
            "registry_completion_status": registry_completion_status,
        }


def _secondary_scan_warnings(
    *,
    multiple_folding: bool,
    clean_after_count: int,
    rules: Any,
) -> tuple[str, ...]:
    """Non-primary scan conditions (lower priority than duration / missing-scan exceptions)."""
    from backend.rinse_folding_exception_rules import (
        MULTIPLE_CLEAN_BEHAVIOR_EXCEPTION,
        MULTIPLE_FOLDING_BEHAVIOR_EXCEPTION,
    )

    warnings: list[str] = []
    if clean_after_count > 1 and not rules.multiple_clean_scans_as_exception:
        warnings.append(WARNING_MULTIPLE_CLEAN_SCANS)
    if multiple_folding and rules.multiple_folding_scans_behavior != MULTIPLE_FOLDING_BEHAVIOR_EXCEPTION:
        warnings.append(EXCEPTION_MULTIPLE_FOLDING_SCANS)
    return tuple(warnings)


def _exception_result(
    code: str,
    *,
    registry_row: Mapping[str, Any] | None,
    folding_scan_count: int = 0,
    clean_scan_count: int = 0,
    folding_start_at: datetime | None = None,
    folding_end_at: datetime | None = None,
    clean_scan_at: datetime | None = None,
    timeline: Sequence[Mapping[str, Any]] | None = None,
    duration_seconds: int | None = None,
    warning_codes: Sequence[str] | None = None,
    folding_start_event_id: int | None = None,
    folding_end_event_id: int | None = None,
    folding_start_rack: str | None = None,
    folding_end_rack: str | None = None,
    assigned_user_name: str | None = None,
    assigned_user_name_source: str | None = None,
) -> FoldingResult:
    return FoldingResult(
        status=STATUS_EXCEPTION,
        exception_code=code,
        warning_codes=tuple(warning_codes or ()),
        folding_start_at=folding_start_at,
        folding_end_at=folding_end_at,
        duration_seconds=duration_seconds,
        folding_start_event_id=folding_start_event_id,
        folding_end_event_id=folding_end_event_id,
        folding_start_rack=folding_start_rack,
        folding_end_rack=folding_end_rack,
        assigned_user_name=assigned_user_name,
        assigned_user_name_source=assigned_user_name_source,
        folding_scan_count=folding_scan_count,
        clean_scan_count=clean_scan_count,
        work_date=_resolve_work_date_exception(
            code,
            folding_start_at=folding_start_at,
            folding_end_at=folding_end_at,
            clean_scan_at=clean_scan_at,
            timeline=timeline,
            registry_row=registry_row,
        ),
    )


def _pick_index(indices: list[int], *, use_latest: bool) -> int:
    if not indices:
        raise ValueError("indices required")
    return indices[-1] if use_latest else indices[0]


def _clean_candidates_after_folding(
    timeline: Sequence[Mapping[str, Any]],
    folding_indices: list[int],
    clean_indices: list[int],
    folding_i: int,
    folding_at: datetime,
) -> list[tuple[int, datetime, Mapping[str, Any]]]:
    out: list[tuple[int, datetime, Mapping[str, Any]]] = []
    for ci in clean_indices:
        if ci <= folding_i:
            continue
        ev = timeline[ci]
        clean_at = _parsed_scan_datetime(ev)
        if not _timestamp_valid(clean_at) or clean_at <= folding_at:
            continue
        out.append((ci, clean_at, ev))
    return out


def evaluate_folding_performance_for_bag(
    events: Sequence[Mapping[str, Any]],
    *,
    registry_row: Mapping[str, Any] | None = None,
    rules: Any = None,
) -> FoldingResult:
    """
    Compute FOLDING → CLEAN interval for one bag.

    registry_row is used for weight snapshot upstream only — never for work_date.
    ``rules`` is a FoldingExceptionRules instance (tenant settings); defaults match legacy constants.
    """
    from backend.rinse_folding_exception_rules import (
        FoldingExceptionRules,
        parse_exception_rules_payload,
    )

    if rules is None:
        rules = parse_exception_rules_payload(None)
    elif isinstance(rules, dict):
        rules = parse_exception_rules_payload(rules)
    elif not isinstance(rules, FoldingExceptionRules):
        rules = parse_exception_rules_payload(None)

    from backend.rinse_folding_exception_rules import (
        MULTIPLE_CLEAN_BEHAVIOR_EXCEPTION,
        MULTIPLE_CLEAN_WARNING_LATEST,
        MULTIPLE_FOLDING_BEHAVIOR_EXCEPTION,
        MULTIPLE_FOLDING_WARNING_LATEST,
    )

    min_secs = rules.min_duration_seconds
    max_secs = rules.max_duration_seconds
    fold_pick_latest = (
        rules.multiple_folding_scans_behavior == MULTIPLE_FOLDING_WARNING_LATEST
    )
    clean_pick_latest = rules.multiple_clean_scans_behavior == MULTIPLE_CLEAN_WARNING_LATEST

    normalized = events_from_records(events)
    if not normalized:
        return _exception_result(EXCEPTION_MISSING_SCAN_EVENTS, registry_row=registry_row)

    timeline = sorted(normalized, key=_progressive_timeline_sort_key)

    folding_indices: list[int] = []
    clean_indices: list[int] = []
    for i, ev in enumerate(timeline):
        if rack_contains_folding(ev.get("rack")):
            folding_indices.append(i)
        if rack_contains_clean(ev.get("rack")):
            clean_indices.append(i)

    multiple_folding = len(folding_indices) > 1

    if not folding_indices:
        if rules.rule_missing_folding:
            return _exception_result(
                EXCEPTION_MISSING_FOLDING,
                registry_row=registry_row,
                clean_scan_count=len(clean_indices),
                clean_scan_at=_first_clean_scan_at_in_timeline(timeline, clean_indices),
                timeline=timeline,
            )
        return FoldingResult(
            status=STATUS_CALCULATED,
            exception_code=EXCEPTION_MISSING_FOLDING,
            folding_start_at=None,
            folding_end_at=_first_clean_scan_at_in_timeline(timeline, clean_indices),
            duration_seconds=None,
            folding_start_event_id=None,
            folding_end_event_id=None,
            folding_start_rack=None,
            folding_end_rack=None,
            assigned_user_name=None,
            assigned_user_name_source=None,
            folding_scan_count=0,
            clean_scan_count=len(clean_indices),
            work_date=_best_timeline_scan_date(timeline, registry_row=registry_row),
        )

    folding_i = _pick_index(folding_indices, use_latest=fold_pick_latest)
    folding_ev = timeline[folding_i]
    folding_at = _parsed_scan_datetime(folding_ev)

    if not _timestamp_valid(folding_at):
        code = (
            EXCEPTION_OVERLAP_OR_INVALID_TIMING
            if rules.rule_overlap_invalid_timing
            else EXCEPTION_INVALID_TIMESTAMPS
        )
        return _exception_result(
            code,
            registry_row=registry_row,
            folding_scan_count=len(folding_indices),
            clean_scan_count=len(clean_indices),
            folding_start_at=None,
            timeline=timeline,
        )

    if rules.rule_clean_before_folding:
        for ci in clean_indices:
            clean_at_check = _parsed_scan_datetime(timeline[ci])
            if ci < folding_i or (
                _timestamp_valid(clean_at_check) and clean_at_check < folding_at
            ):
                return _exception_result(
                    EXCEPTION_CLEAN_BEFORE_FOLDING,
                    registry_row=registry_row,
                    folding_scan_count=len(folding_indices),
                    clean_scan_count=len(clean_indices),
                    folding_start_at=folding_at,
                    clean_scan_at=clean_at_check,
                    timeline=timeline,
                )

    clean_after = _clean_candidates_after_folding(
        timeline, folding_indices, clean_indices, folding_i, folding_at
    )

    if not clean_after:
        if rules.rule_missing_clean:
            return _exception_result(
                EXCEPTION_MISSING_CLEAN,
                registry_row=registry_row,
                folding_scan_count=len(folding_indices),
                clean_scan_count=len(clean_indices),
                folding_start_at=folding_at,
                timeline=timeline,
            )
        return FoldingResult(
            status=STATUS_CALCULATED,
            exception_code=EXCEPTION_MISSING_CLEAN,
            folding_start_at=folding_at,
            folding_end_at=None,
            duration_seconds=None,
            folding_start_event_id=folding_ev.get("id"),
            folding_end_event_id=None,
            folding_start_rack=str(folding_ev.get("rack") or "")[:128] or None,
            folding_end_rack=None,
            assigned_user_name=_user_from_event(folding_ev) or None,
            assigned_user_name_source=SOURCE_FOLDING_SCAN if usable_user_name(_user_from_event(folding_ev)) else None,
            folding_scan_count=len(folding_indices),
            clean_scan_count=len(clean_indices),
            work_date=_resolve_work_date_calculated(folding_at),
        )

    end_clean_i, clean_at, end_clean_ev = (
        clean_after[-1] if clean_pick_latest else clean_after[0]
    )
    clean_after_count = len(clean_after)

    if not _timestamp_valid(clean_at):
        code = (
            EXCEPTION_OVERLAP_OR_INVALID_TIMING
            if rules.rule_overlap_invalid_timing
            else EXCEPTION_INVALID_TIMESTAMPS
        )
        return _exception_result(
            code,
            registry_row=registry_row,
            folding_scan_count=len(folding_indices),
            clean_scan_count=clean_after_count,
            folding_start_at=folding_at,
            folding_end_at=None,
            timeline=timeline,
        )

    duration = int((clean_at - folding_at).total_seconds())

    if rules.rule_overlap_invalid_timing and duration <= 0:
        return _exception_result(
            EXCEPTION_OVERLAP_OR_INVALID_TIMING,
            registry_row=registry_row,
            folding_scan_count=len(folding_indices),
            clean_scan_count=clean_after_count,
            folding_start_at=folding_at,
            folding_end_at=clean_at,
            timeline=timeline,
        )
    if duration <= 0:
        return _exception_result(
            EXCEPTION_INVALID_TIMESTAMPS,
            registry_row=registry_row,
            folding_scan_count=len(folding_indices),
            clean_scan_count=clean_after_count,
            folding_start_at=folding_at,
            folding_end_at=clean_at,
            timeline=timeline,
        )

    folding_user = _user_from_event(folding_ev)
    clean_user = _user_from_event(end_clean_ev)
    assigned: str | None = None
    source: str | None = None
    if usable_user_name(folding_user):
        assigned = folding_user
        source = SOURCE_FOLDING_SCAN
    elif usable_user_name(clean_user):
        assigned = clean_user
        source = SOURCE_CLEAN_SCAN_FALLBACK
    else:
        return FoldingResult(
            status=STATUS_EXCEPTION,
            exception_code=EXCEPTION_MISSING_ASSIGNED_USER,
            folding_start_at=folding_at,
            folding_end_at=clean_at,
            duration_seconds=duration,
            folding_start_event_id=folding_ev.get("id"),
            folding_end_event_id=end_clean_ev.get("id"),
            folding_start_rack=str(folding_ev.get("rack") or "")[:128] or None,
            folding_end_rack=str(end_clean_ev.get("rack") or "")[:128] or None,
            assigned_user_name=None,
            assigned_user_name_source=None,
            folding_scan_count=len(folding_indices),
            clean_scan_count=clean_after_count,
            work_date=_resolve_work_date_calculated(clean_at),
        )

    secondary_warnings = _secondary_scan_warnings(
        multiple_folding=multiple_folding,
        clean_after_count=clean_after_count,
        rules=rules,
    )

    if min_secs > 0 and duration < min_secs:
        return _exception_result(
            EXCEPTION_FOLDING_DURATION_TOO_SHORT,
            registry_row=registry_row,
            folding_scan_count=len(folding_indices),
            clean_scan_count=clean_after_count,
            folding_start_at=folding_at,
            folding_end_at=clean_at,
            timeline=timeline,
            duration_seconds=duration,
            warning_codes=secondary_warnings,
            folding_start_event_id=folding_ev.get("id"),
            folding_end_event_id=end_clean_ev.get("id"),
            folding_start_rack=str(folding_ev.get("rack") or "")[:128] or None,
            folding_end_rack=str(end_clean_ev.get("rack") or "")[:128] or None,
            assigned_user_name=assigned,
            assigned_user_name_source=source,
        )

    if max_secs is not None and duration > max_secs:
        return _exception_result(
            EXCEPTION_FOLDING_DURATION_TOO_LONG,
            registry_row=registry_row,
            folding_scan_count=len(folding_indices),
            clean_scan_count=clean_after_count,
            folding_start_at=folding_at,
            folding_end_at=clean_at,
            timeline=timeline,
            duration_seconds=duration,
            warning_codes=secondary_warnings,
            folding_start_event_id=folding_ev.get("id"),
            folding_end_event_id=end_clean_ev.get("id"),
            folding_start_rack=str(folding_ev.get("rack") or "")[:128] or None,
            folding_end_rack=str(end_clean_ev.get("rack") or "")[:128] or None,
            assigned_user_name=assigned,
            assigned_user_name_source=source,
        )

    if clean_after_count > 1 and rules.multiple_clean_scans_as_exception:
        return _exception_result(
            WARNING_MULTIPLE_CLEAN_SCANS,
            registry_row=registry_row,
            folding_scan_count=len(folding_indices),
            clean_scan_count=clean_after_count,
            folding_start_at=folding_at,
            folding_end_at=clean_at,
            timeline=timeline,
            duration_seconds=duration,
            warning_codes=secondary_warnings,
            folding_start_event_id=folding_ev.get("id"),
            folding_end_event_id=end_clean_ev.get("id"),
            folding_start_rack=str(folding_ev.get("rack") or "")[:128] or None,
            folding_end_rack=str(end_clean_ev.get("rack") or "")[:128] or None,
            assigned_user_name=assigned,
            assigned_user_name_source=source,
        )

    if multiple_folding and rules.multiple_folding_scans_behavior == MULTIPLE_FOLDING_BEHAVIOR_EXCEPTION:
        mf_secondary = tuple(
            w for w in secondary_warnings if w != EXCEPTION_MULTIPLE_FOLDING_SCANS
        )
        return _exception_result(
            EXCEPTION_MULTIPLE_FOLDING_SCANS,
            registry_row=registry_row,
            folding_scan_count=len(folding_indices),
            clean_scan_count=clean_after_count,
            folding_start_at=folding_at,
            folding_end_at=clean_at,
            timeline=timeline,
            duration_seconds=duration,
            warning_codes=mf_secondary,
            folding_start_event_id=folding_ev.get("id"),
            folding_end_event_id=end_clean_ev.get("id"),
            folding_start_rack=str(folding_ev.get("rack") or "")[:128] or None,
            folding_end_rack=str(end_clean_ev.get("rack") or "")[:128] or None,
            assigned_user_name=assigned,
            assigned_user_name_source=source,
        )

    primary_warning: str | None = None
    if multiple_folding:
        primary_warning = EXCEPTION_MULTIPLE_FOLDING_SCANS
    elif clean_after_count > 1:
        primary_warning = WARNING_MULTIPLE_CLEAN_SCANS

    return FoldingResult(
        status=STATUS_CALCULATED,
        exception_code=primary_warning,
        warning_codes=(),
        folding_start_at=folding_at,
        folding_end_at=clean_at,
        duration_seconds=duration,
        folding_start_event_id=folding_ev.get("id"),
        folding_end_event_id=end_clean_ev.get("id"),
        folding_start_rack=str(folding_ev.get("rack") or "")[:128] or None,
        folding_end_rack=str(end_clean_ev.get("rack") or "")[:128] or None,
        assigned_user_name=assigned,
        assigned_user_name_source=source,
        folding_scan_count=len(folding_indices),
        clean_scan_count=clean_after_count,
        work_date=_resolve_work_date_calculated(clean_at),
    )


def registry_is_completed(registry_row: Mapping[str, Any] | None) -> bool:
    if not registry_row:
        return False
    return str(registry_row.get("completion_status") or "").upper() == COMPLETION_COMPLETED
