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

EXCEPTION_MISSING_FOLDING = "MISSING_FOLDING"
EXCEPTION_MISSING_CLEAN = "MISSING_CLEAN"
EXCEPTION_CLEAN_BEFORE_FOLDING = "CLEAN_BEFORE_FOLDING"
EXCEPTION_INVALID_TIMESTAMPS = "INVALID_TIMESTAMPS"
EXCEPTION_MISSING_ASSIGNED_USER = "MISSING_ASSIGNED_USER"
WARNING_MULTIPLE_FOLDING_SCANS = "MULTIPLE_FOLDING_SCANS"
WARNING_MULTIPLE_CLEAN_SCANS = "MULTIPLE_CLEAN_SCANS"

FOLDING_WARNING_CODES = frozenset(
    {WARNING_MULTIPLE_FOLDING_SCANS, WARNING_MULTIPLE_CLEAN_SCANS}
)

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

    def to_performance_row(self, *, registry_completion_status: str) -> dict[str, Any]:
        return {
            "status": self.status,
            "exception_code": self.exception_code,
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
) -> FoldingResult:
    return FoldingResult(
        status=STATUS_EXCEPTION,
        exception_code=code,
        folding_start_at=folding_start_at,
        folding_end_at=folding_end_at,
        duration_seconds=None,
        folding_start_event_id=None,
        folding_end_event_id=None,
        folding_start_rack=None,
        folding_end_rack=None,
        assigned_user_name=None,
        assigned_user_name_source=None,
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


def evaluate_folding_performance_for_bag(
    events: Sequence[Mapping[str, Any]],
    *,
    registry_row: Mapping[str, Any] | None = None,
) -> FoldingResult:
    """
    Compute FOLDING → CLEAN interval for one bag.

    registry_row is used for weight snapshot upstream only — never for work_date.
    """
    normalized = events_from_records(events)
    if not normalized:
        return _exception_result(EXCEPTION_MISSING_FOLDING, registry_row=registry_row)

    timeline = sorted(normalized, key=_progressive_timeline_sort_key)

    folding_indices: list[int] = []
    clean_indices: list[int] = []
    for i, ev in enumerate(timeline):
        if rack_contains_folding(ev.get("rack")):
            folding_indices.append(i)
        if rack_contains_clean(ev.get("rack")):
            clean_indices.append(i)

    if not folding_indices:
        return _exception_result(
            EXCEPTION_MISSING_FOLDING,
            registry_row=registry_row,
            clean_scan_count=len(clean_indices),
            clean_scan_at=_first_clean_scan_at_in_timeline(timeline, clean_indices),
            timeline=timeline,
        )

    first_folding_i = folding_indices[0]
    folding_ev = timeline[first_folding_i]
    folding_at = _parsed_scan_datetime(folding_ev)

    if not _timestamp_valid(folding_at):
        return _exception_result(
            EXCEPTION_INVALID_TIMESTAMPS,
            registry_row=registry_row,
            folding_scan_count=len(folding_indices),
            clean_scan_count=len(clean_indices),
            folding_start_at=folding_at if _timestamp_valid(folding_at) else None,
            timeline=timeline,
        )

    for ci in clean_indices:
        if ci < first_folding_i:
            return _exception_result(
                EXCEPTION_CLEAN_BEFORE_FOLDING,
                registry_row=registry_row,
                folding_scan_count=len(folding_indices),
                clean_scan_count=len(clean_indices),
                folding_start_at=folding_at,
                clean_scan_at=_parsed_scan_datetime(timeline[ci]),
                timeline=timeline,
            )
        clean_at_check = _parsed_scan_datetime(timeline[ci])
        if _timestamp_valid(clean_at_check) and clean_at_check < folding_at:
            return _exception_result(
                EXCEPTION_CLEAN_BEFORE_FOLDING,
                registry_row=registry_row,
                folding_scan_count=len(folding_indices),
                clean_scan_count=len(clean_indices),
                folding_start_at=folding_at,
                clean_scan_at=clean_at_check,
                timeline=timeline,
            )

    end_clean_ev = None
    end_clean_i: int | None = None
    clean_after_count = 0
    for ci in clean_indices:
        if ci <= first_folding_i:
            continue
        ev = timeline[ci]
        clean_at = _parsed_scan_datetime(ev)
        if not _timestamp_valid(clean_at):
            continue
        if clean_at <= folding_at:
            continue
        clean_after_count += 1
        if end_clean_ev is None:
            end_clean_ev = ev
            end_clean_i = ci

    if end_clean_ev is None:
        return _exception_result(
            EXCEPTION_MISSING_CLEAN,
            registry_row=registry_row,
            folding_scan_count=len(folding_indices),
            clean_scan_count=len(clean_indices),
            folding_start_at=folding_at,
            timeline=timeline,
        )

    clean_at = _parsed_scan_datetime(end_clean_ev)
    if not _timestamp_valid(clean_at):
        return _exception_result(
            EXCEPTION_INVALID_TIMESTAMPS,
            registry_row=registry_row,
            folding_scan_count=len(folding_indices),
            clean_scan_count=len(clean_indices),
            folding_start_at=folding_at,
            folding_end_at=clean_at if _timestamp_valid(clean_at) else None,
            timeline=timeline,
        )

    duration = int((clean_at - folding_at).total_seconds())
    if duration <= 0:
        return _exception_result(
            EXCEPTION_INVALID_TIMESTAMPS,
            registry_row=registry_row,
            folding_scan_count=len(folding_indices),
            clean_scan_count=len(clean_indices),
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
            duration_seconds=None,
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

    warning: str | None = None
    if end_clean_i is not None:
        folding_before_end = sum(1 for fi in folding_indices if fi <= end_clean_i)
        if folding_before_end > 1:
            warning = WARNING_MULTIPLE_FOLDING_SCANS
    if clean_after_count > 1 and warning is None:
        warning = WARNING_MULTIPLE_CLEAN_SCANS

    return FoldingResult(
        status=STATUS_CALCULATED,
        exception_code=warning,
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
