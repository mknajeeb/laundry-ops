"""
Standardized weighing session start/end measurement for display and analytics.

Productivity credit calculation keeps its own bounds; use this module wherever
weighing duration is measured or shown in chronology views.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence

from backend.rinse_bag_activity_rules import is_cleaning_purpose_for_activity_start
from backend.rinse_bag_stage_bounds import event_ts, sort_key_ev, ts_valid
from backend.rinse_scan_purpose import is_weight_entry_purpose, normalize_scan_purpose
from backend.rinse_sorting_session import session_source_label


def _operator(ev: Mapping[str, Any] | None) -> str | None:
    if ev is None:
        return None
    name = str(ev.get("user") or ev.get("user_name") or ev.get("User") or "").strip()
    return name or None


def _operators_match(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    return a.casefold() == b.casefold()


def _cleaning_in_cycle_window(
    ev: Mapping[str, Any],
    *,
    before_ts: datetime,
    not_before_ts: datetime | None,
) -> bool:
    """True when cleaning is before weight and inside the current vendor cycle."""
    if not is_cleaning_purpose_for_activity_start(ev.get("purpose")):
        return False
    ts = event_ts(ev)
    if not ts_valid(ts) or ts >= before_ts:
        return False
    # Ignore scans at/before the cycle floor (latest sent-to-vendor).
    if not_before_ts is not None and ts_valid(not_before_ts) and ts <= not_before_ts:
        return False
    return True


def _last_cleaning_before_ts_by_employee(
    timeline: Sequence[Mapping[str, Any]],
    *,
    before_ts: datetime,
    employee: str | None,
    not_before_ts: datetime | None = None,
) -> Mapping[str, Any] | None:
    if not employee:
        return None
    candidates = [
        ev
        for ev in timeline
        if _cleaning_in_cycle_window(ev, before_ts=before_ts, not_before_ts=not_before_ts)
        and _operators_match(_operator(ev), employee)
    ]
    return max(candidates, key=sort_key_ev) if candidates else None


def _last_cleaning_before_ts(
    timeline: Sequence[Mapping[str, Any]],
    *,
    before_ts: datetime,
    not_before_ts: datetime | None = None,
) -> Mapping[str, Any] | None:
    candidates = [
        ev
        for ev in timeline
        if _cleaning_in_cycle_window(ev, before_ts=before_ts, not_before_ts=not_before_ts)
    ]
    return max(candidates, key=sort_key_ev) if candidates else None


def _weighing_start_ev(
    timeline: Sequence[Mapping[str, Any]],
    *,
    weight_ev: Mapping[str, Any],
    weight_ts: datetime,
    not_before_ts: datetime | None = None,
) -> Mapping[str, Any]:
    """
    Weigh start: latest same-employee cleaning/start-cleaning before weight-entry
    in the current vendor cycle, else weight-entry (zero-duration fallback, inferred).

    Prior-cycle cleanings (at/before *not_before_ts*, typically latest sent-to-vendor)
    must never become the start for a current-cycle weight-entry.
    """
    weight_employee = _operator(weight_ev)
    if weight_employee:
        cleaning = _last_cleaning_before_ts_by_employee(
            timeline,
            before_ts=weight_ts,
            employee=weight_employee,
            not_before_ts=not_before_ts,
        )
        if cleaning is not None:
            return cleaning
        return weight_ev

    cleaning = _last_cleaning_before_ts(
        timeline, before_ts=weight_ts, not_before_ts=not_before_ts
    )
    if cleaning is not None:
        return cleaning
    return weight_ev


def _session_confidence(
    weigh_start_ev: Mapping[str, Any] | None,
    weigh_end_ev: Mapping[str, Any] | None,
) -> str:
    start_exact = weigh_start_ev is not None and is_cleaning_purpose_for_activity_start(
        weigh_start_ev.get("purpose")
    )
    end_exact = weigh_end_ev is not None and is_weight_entry_purpose(
        weigh_end_ev.get("purpose")
    )
    if start_exact and end_exact:
        return "exact"
    return "inferred"


@dataclass(frozen=True)
class WeighingSessionResult:
    weight_ev: Mapping[str, Any]
    weigh_start_ev: Mapping[str, Any]
    weigh_end_ev: Mapping[str, Any]
    employee: str | None
    confidence: str

    @property
    def weigh_start_et(self) -> datetime | None:
        return event_ts(self.weigh_start_ev)

    @property
    def weigh_end_et(self) -> datetime | None:
        return event_ts(self.weigh_end_ev)

    @property
    def end_event_purpose(self) -> str | None:
        return normalize_scan_purpose(self.weigh_end_ev.get("purpose"))


def compute_weighing_session(
    timeline: Sequence[Mapping[str, Any]],
    *,
    weight_ev: Mapping[str, Any],
    weight_ts: datetime,
    not_before_ts: datetime | None = None,
) -> WeighingSessionResult:
    """
    Standardized weigh session for one weight cycle.

    Weigh end is always the weight-entry event; later sorting/washing/drying/folding
    scans do not extend weighing time.

    When *not_before_ts* is set (lifecycle sent-to-vendor anchor), weigh start may only
    come from cleaning/start-cleaning strictly after that floor. Missing current-cycle
    start evidence falls back to the weight-entry itself — never a prior-cycle scan.
    """
    weigh_start_ev = _weighing_start_ev(
        timeline,
        weight_ev=weight_ev,
        weight_ts=weight_ts,
        not_before_ts=not_before_ts,
    )
    weigh_end_ev = weight_ev
    employee = _operator(weight_ev) or _operator(weigh_start_ev)
    confidence = _session_confidence(weigh_start_ev, weigh_end_ev)
    return WeighingSessionResult(
        weight_ev=weight_ev,
        weigh_start_ev=weigh_start_ev,
        weigh_end_ev=weigh_end_ev,
        employee=employee,
        confidence=confidence,
    )


def weighing_session_source_label(
    weigh_start_ev: Mapping[str, Any] | None,
    weigh_end_ev: Mapping[str, Any] | None,
) -> str:
    return session_source_label(weigh_start_ev, weigh_end_ev)
