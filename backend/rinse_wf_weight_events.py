"""WF weight-entry identity and completion helpers for At Vendor module."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence

from backend.rinse_bag_stage_bounds import event_ts, events_on_or_after, sort_key_ev
from backend.rinse_scan_purpose import (
    is_add_photos_purpose,
    is_complete_cleaning_purpose,
    is_drying_purpose,
    is_move_bag_purpose,
    is_processed_by_vendor_purpose,
    is_start_cleaning_purpose,
    is_weight_entry_purpose,
    normalize_scan_purpose,
)
from backend.rinse_scan_time import system_datetime_to_et

_WEIGHT_NUM_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:lbs?|lb\.?)?", re.I)

WF_POST_PROCESSING_WEIGHT_SIGNAL = "post_processing_weight"


def normalize_scan_weight_lbs(raw: Any, *, allow_unit_suffix: bool = False) -> float | None:
    """
    Shared scan/portal weight normalization.

    - numeric / numeric-string → float (0 preserved)
    - blank / null / "(None)" / NaN → None
    - non-numeric garbage → None
    - "13 lbs" only when allow_unit_suffix=True
    """
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    # pandas / numpy blank cells often arrive as float NaN.
    try:
        if isinstance(raw, float) and math.isnan(raw):
            return None
    except TypeError:
        pass
    if isinstance(raw, str):
        s = raw.strip().replace(",", "")
        if not s or s in ("(None)", "None", "null", "nan", "NaN"):
            return None
        try:
            return round(float(s), 4)
        except ValueError:
            if not allow_unit_suffix:
                return None
            m = _WEIGHT_NUM_RE.search(s)
            if not m:
                return None
            try:
                return round(float(m.group(1)), 4)
            except (TypeError, ValueError):
                return None
    try:
        val = float(raw)
        if math.isnan(val) or math.isinf(val):
            return None
        return round(val, 4)
    except (TypeError, ValueError):
        return None


def parse_weight_lbs_from_scan_event(record: Mapping[str, Any] | None) -> float | None:
    """Extract numeric weight (lbs) from a scan row when present (0 is valid)."""
    if not record:
        return None
    for key in ("weight_lbs", "weight_num", "weight", "value"):
        lbs = normalize_scan_weight_lbs(record.get(key))
        if lbs is not None:
            return lbs

    raw_json = record.get("raw_json")
    if isinstance(raw_json, str):
        try:
            raw_json = json.loads(raw_json)
        except (json.JSONDecodeError, TypeError):
            raw_json = None
    if isinstance(raw_json, dict):
        for key in (
            "Weight",
            "weight",
            "# WF LBS",
            "WF LBS",
            "weight_lbs",
            "weight_num",
            "pounds",
            "lbs",
            "entered_value",
        ):
            lbs = normalize_scan_weight_lbs(raw_json.get(key), allow_unit_suffix=True)
            if lbs is not None:
                return lbs

    purpose = str(record.get("purpose") or "")
    return normalize_scan_weight_lbs(purpose, allow_unit_suffix=True)


def _occurrence_et_key(ts: datetime) -> datetime:
    et = system_datetime_to_et(ts)
    if et is not None:
        return et.replace(tzinfo=None)
    return ts


def _weight_event_identity(
    ev: Mapping[str, Any],
    ts: datetime,
) -> tuple[datetime, float | None]:
    """Identity key: ET timestamp + parsed weight when available."""
    et = system_datetime_to_et(ts)
    ts_key = _occurrence_et_key(et.replace(tzinfo=None) if et is not None else ts)
    return ts_key, parse_weight_lbs_from_scan_event(ev)


@dataclass(frozen=True)
class WfWeightEvent:
    event: dict[str, Any]
    timestamp: datetime
    weight_lbs: float | None


@dataclass(frozen=True)
class WfWeightCompletion:
    signal: str
    completion_ts: datetime
    first_weight_lbs: float | None
    second_weight_lbs: float | None
    first_weight_timestamp: datetime | None
    second_weight_timestamp: datetime | None

    @property
    def weight_delta(self) -> float | None:
        if self.first_weight_lbs is None or self.second_weight_lbs is None:
            return None
        return round(abs(self.second_weight_lbs - self.first_weight_lbs), 4)


def distinct_wf_weight_events(
    timeline: Sequence[Mapping[str, Any]],
    *,
    anchor_ts: datetime,
    as_of_end: datetime,
) -> list[WfWeightEvent]:
    """
    Chronological distinct WF weight-entry events after anchor.

    Same timestamp rows collapse to one unless parsed weight values differ.
    """
    anchored = events_on_or_after(timeline, anchor_ts)
    keyed: list[tuple[dict[str, Any], datetime, tuple[datetime, float | None]]] = []
    for ev in anchored:
        if not is_weight_entry_purpose(ev.get("purpose")):
            continue
        ts = event_ts(ev)
        if ts is None or ts > as_of_end:
            continue
        row = dict(ev)
        lbs = parse_weight_lbs_from_scan_event(row)
        if lbs is not None:
            row.setdefault("weight_lbs", lbs)
        keyed.append((row, ts, _weight_event_identity(row, ts)))
    keyed.sort(key=lambda item: (item[2][0], sort_key_ev(item[0])))

    out: list[WfWeightEvent] = []
    seen: set[tuple[datetime, float | None]] = set()
    for row, ts, identity in keyed:
        if identity in seen:
            continue
        seen.add(identity)
        out.append(WfWeightEvent(event=row, timestamp=ts, weight_lbs=identity[1]))
    return out


def is_wf_processing_purpose(raw: str | None) -> bool:
    """WF processing events that gate post-processing weight completion."""
    return (
        is_start_cleaning_purpose(raw)
        or is_drying_purpose(raw)
        or is_add_photos_purpose(raw)
        or is_complete_cleaning_purpose(raw)
    )


def _latest_wf_processing_after_anchor(
    timeline: Sequence[Mapping[str, Any]],
    *,
    anchor_ts: datetime,
    as_of_end: datetime,
) -> tuple[datetime | None, str | None]:
    latest_ts: datetime | None = None
    latest_purpose: str | None = None
    for ev in events_on_or_after(timeline, anchor_ts):
        if not is_wf_processing_purpose(ev.get("purpose")):
            continue
        ts = event_ts(ev)
        if ts is None or ts > as_of_end:
            continue
        if latest_ts is None or ts > latest_ts:
            latest_ts = ts
            latest_purpose = str(ev.get("purpose") or "")
    return latest_ts, latest_purpose


def _post_processing_weight_events(
    weights: Sequence[WfWeightEvent],
    latest_proc_ts: datetime,
) -> list[WfWeightEvent]:
    """
    Distinct weight-entry events that qualify as post-processing.

    Normally strictly after latest processing; same-minute tie allowed when an
    earlier pre-clean weight exists (portal often batches final weigh with
    add-photos / processed-by-vendor at one timestamp).
    """
    has_pre_clean = any(w.timestamp < latest_proc_ts for w in weights)
    out: list[WfWeightEvent] = []
    for w in weights:
        if w.timestamp > latest_proc_ts:
            out.append(w)
        elif w.timestamp == latest_proc_ts and has_pre_clean:
            out.append(w)
    return out


def is_synthetic_post_processing_weight_event(ev: Mapping[str, Any]) -> bool:
    """True for the auditable near-complete recovery event, never a portal scan."""
    if str(ev.get("source_filename") or "") == "near_complete_wf_weight_backfill":
        return True
    raw = ev.get("raw_json")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            raw = None
    return bool(
        isinstance(raw, dict)
        and raw.get("synthetic") is True
        and raw.get("backfill_source") == "near_complete_wf_weight_backfill"
    )


def preferred_post_processing_weight_event(
    weights: Sequence[WfWeightEvent],
) -> WfWeightEvent | None:
    """
    Prefer a real portal post-weight over recovery evidence.

    A real event can arrive after recovery with an earlier portal timestamp.
    Selecting by provenance first prevents the synthetic row from retaining
    completion attribution merely because its generated timestamp is later.
    """
    if not weights:
        return None
    real = [w for w in weights if not is_synthetic_post_processing_weight_event(w.event)]
    return (real or list(weights))[-1]


def derive_wf_clean_weight_fields(
    timeline: Sequence[Mapping[str, Any]],
    *,
    anchor_ts: datetime,
    as_of_end: datetime,
    observations: Sequence[Mapping[str, Any]] | None = None,
    manual_pre_lbs: float | None = None,
    manual_post_lbs: float | None = None,
) -> dict[str, Any]:
    """
    Pre/post clean weight display fields for WF At Vendor rows.

    Uses the shared current-cycle resolver (entry → garments-reviewed gated
    PRE/POST events). Lifetime ordinal first/second weight-entry is not used.
    """
    from backend.rinse_current_cycle_weight import resolve_current_cycle_weights
    from backend.rinse_processing_settings import DEFAULT_FACILITY_ENTRY_RACKS

    selected_date_et = as_of_end.date() if isinstance(as_of_end, datetime) else as_of_end
    resolved = resolve_current_cycle_weights(
        timeline,
        selected_date_et=selected_date_et,
        observations=observations,
        entry_racks=list(DEFAULT_FACILITY_ENTRY_RACKS),
        as_of_end=as_of_end,
        manual_pre_lbs=manual_pre_lbs,
        manual_post_lbs=manual_post_lbs,
    )
    # Keep processing metadata for UI diagnostics (non-authoritative for PRE/POST).
    latest_proc_ts, latest_proc_purpose = _latest_wf_processing_after_anchor(
        timeline, anchor_ts=anchor_ts, as_of_end=as_of_end
    )
    pre_lbs = resolved.pre_weight_lbs
    post_lbs = resolved.post_weight_lbs
    clean_delta = (
        round(abs(post_lbs - pre_lbs), 4)
        if pre_lbs is not None and post_lbs is not None
        else None
    )
    return {
        "pre_clean_weight": pre_lbs,
        "pre_clean_weight_time": resolved.pre_weight_event_at.isoformat()
        if resolved.pre_weight_event_at
        else None,
        "post_clean_weight": post_lbs,
        "post_clean_weight_time": resolved.post_weight_event_at.isoformat()
        if resolved.post_weight_event_at
        else None,
        "clean_weight_delta": clean_delta,
        "latest_processing_time": latest_proc_ts.isoformat() if latest_proc_ts else None,
        "latest_processing_purpose": latest_proc_purpose,
        "pre_resolution_status": resolved.pre_resolution_status,
        "post_resolution_status": resolved.post_resolution_status,
        "resolution_reason": resolved.resolution_reason,
    }


def wf_post_processing_weight_completion(
    timeline: Sequence[Mapping[str, Any]],
    *,
    anchor_ts: datetime,
    as_of_end: datetime,
) -> WfWeightCompletion | None:
    """
    WF completes when a distinct post-processing weight-entry exists relative to
    the latest processing scan (including same-minute final weigh when pre-clean
    weight was recorded earlier).
    """
    latest_proc_ts, _ = _latest_wf_processing_after_anchor(
        timeline, anchor_ts=anchor_ts, as_of_end=as_of_end
    )
    if latest_proc_ts is None:
        return None

    weights = distinct_wf_weight_events(timeline, anchor_ts=anchor_ts, as_of_end=as_of_end)
    post_weights = _post_processing_weight_events(weights, latest_proc_ts)
    if not post_weights:
        return None

    post = preferred_post_processing_weight_event(post_weights)
    if post is None:
        return None
    pre = weights[0] if weights else None
    return WfWeightCompletion(
        signal=WF_POST_PROCESSING_WEIGHT_SIGNAL,
        completion_ts=post.timestamp,
        first_weight_lbs=pre.weight_lbs if pre else None,
        second_weight_lbs=post.weight_lbs,
        first_weight_timestamp=pre.timestamp if pre else None,
        second_weight_timestamp=post.timestamp,
    )


# Legacy helpers retained for audit scripts and historical comparisons.
def wf_processing_final_weight_completion(
    timeline: Sequence[Mapping[str, Any]],
    *,
    anchor_ts: datetime,
    as_of_end: datetime,
) -> WfWeightCompletion | None:
    return wf_post_processing_weight_completion(
        timeline, anchor_ts=anchor_ts, as_of_end=as_of_end
    )


def wf_two_weight_completion(
    timeline: Sequence[Mapping[str, Any]],
    *,
    anchor_ts: datetime,
    as_of_end: datetime,
) -> WfWeightCompletion | None:
    weights = distinct_wf_weight_events(timeline, anchor_ts=anchor_ts, as_of_end=as_of_end)
    if len(weights) < 2:
        return None
    first, second = weights[0], weights[1]
    if second.timestamp < first.timestamp:
        return None
    if second.timestamp == first.timestamp:
        if first.weight_lbs is None or second.weight_lbs is None or first.weight_lbs == second.weight_lbs:
            return None
    signal = str(second.event.get("purpose") or "weight-entry")
    return WfWeightCompletion(
        signal=signal,
        completion_ts=second.timestamp,
        first_weight_lbs=first.weight_lbs,
        second_weight_lbs=second.weight_lbs,
        first_weight_timestamp=first.timestamp,
        second_weight_timestamp=second.timestamp,
    )


def wf_operational_completion(
    timeline: Sequence[Mapping[str, Any]],
    *,
    anchor_ts: datetime,
    as_of_end: datetime,
    weight_events: Sequence[WfWeightEvent] | None = None,
) -> WfWeightCompletion | None:
    """Legacy operational fallback (no longer used for WF At Vendor completion)."""
    weights = list(weight_events or [])
    if not weights:
        weights = distinct_wf_weight_events(timeline, anchor_ts=anchor_ts, as_of_end=as_of_end)
    has_weight = len(weights) >= 1

    best: tuple[datetime, str, str] | None = None
    for ev in events_on_or_after(timeline, anchor_ts):
        ts = event_ts(ev)
        if ts is None or ts > as_of_end:
            continue
        purpose = ev.get("purpose")
        rack = str(ev.get("rack") or "").lower()
        signal: str | None = None
        if is_processed_by_vendor_purpose(purpose):
            signal = "processed-by-vendor"
        elif normalize_scan_purpose(purpose) == "delivery-prep-completed":
            signal = "delivery-prep-completed"
        elif is_move_bag_purpose(purpose) and "clean" in rack and "dirty" not in rack:
            signal = "move-bag-clean-rack"
        elif has_weight and is_complete_cleaning_purpose(purpose):
            signal = "complete-cleaning"
        if signal and (best is None or ts < best[0]):
            best = (ts, signal, str(purpose or signal))

    if best is None:
        return None
    ts, signal, _ = best
    first = weights[0] if weights else None
    return WfWeightCompletion(
        signal=signal,
        completion_ts=ts,
        first_weight_lbs=first.weight_lbs if first else None,
        second_weight_lbs=None,
        first_weight_timestamp=first.timestamp if first else None,
        second_weight_timestamp=None,
    )
