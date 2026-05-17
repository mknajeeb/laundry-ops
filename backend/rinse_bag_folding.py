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


def _resolve_work_date(
    registry_row: Mapping[str, Any] | None,
    folding_start_at: datetime | None,
) -> date | None:
    if registry_row:
        dc = registry_row.get("date_clean")
        if isinstance(dc, date) and not isinstance(dc, datetime):
            return dc
        if isinstance(dc, datetime):
            return dc.date()
        if dc is not None:
            try:
                import pandas as pd

                p = pd.Timestamp(dc)
                if not pd.isna(p):
                    return p.date()
            except Exception:
                pass
    if folding_start_at and folding_start_at != datetime.min:
        return folding_start_at.date()
    return None


def _timestamp_valid(ts: datetime) -> bool:
    return ts is not None and ts != datetime.min


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
) -> FoldingResult:
    return FoldingResult(
        status=STATUS_EXCEPTION,
        exception_code=code,
        folding_start_at=None,
        folding_end_at=None,
        duration_seconds=None,
        folding_start_event_id=None,
        folding_end_event_id=None,
        folding_start_rack=None,
        folding_end_rack=None,
        assigned_user_name=None,
        assigned_user_name_source=None,
        folding_scan_count=folding_scan_count,
        clean_scan_count=clean_scan_count,
        work_date=_resolve_work_date(registry_row, None),
    )


def evaluate_folding_performance_for_bag(
    events: Sequence[Mapping[str, Any]],
    *,
    registry_row: Mapping[str, Any] | None = None,
) -> FoldingResult:
    """
    Compute FOLDING → CLEAN interval for one bag.

    registry_row should be COMPLETED; used for work_date and weight snapshot upstream.
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
        )

    for ci in clean_indices:
        if ci < first_folding_i:
            return _exception_result(
                EXCEPTION_CLEAN_BEFORE_FOLDING,
                registry_row=registry_row,
                folding_scan_count=len(folding_indices),
                clean_scan_count=len(clean_indices),
            )
        clean_at_check = _parsed_scan_datetime(timeline[ci])
        if _timestamp_valid(clean_at_check) and clean_at_check < folding_at:
            return _exception_result(
                EXCEPTION_CLEAN_BEFORE_FOLDING,
                registry_row=registry_row,
                folding_scan_count=len(folding_indices),
                clean_scan_count=len(clean_indices),
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
        )

    clean_at = _parsed_scan_datetime(end_clean_ev)
    if not _timestamp_valid(clean_at):
        return _exception_result(
            EXCEPTION_INVALID_TIMESTAMPS,
            registry_row=registry_row,
            folding_scan_count=len(folding_indices),
            clean_scan_count=len(clean_indices),
        )

    duration = int((clean_at - folding_at).total_seconds())
    if duration <= 0:
        return _exception_result(
            EXCEPTION_INVALID_TIMESTAMPS,
            registry_row=registry_row,
            folding_scan_count=len(folding_indices),
            clean_scan_count=len(clean_indices),
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
            work_date=_resolve_work_date(registry_row, folding_at),
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
        work_date=_resolve_work_date(registry_row, folding_at),
    )


def registry_is_completed(registry_row: Mapping[str, Any] | None) -> bool:
    if not registry_row:
        return False
    return str(registry_row.get("completion_status") or "").upper() == COMPLETION_COMPLETED
