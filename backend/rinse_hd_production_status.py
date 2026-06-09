"""
HD (Hang Dry) production stage logic — separate from WF weighing/folding workflow.

HD is never weighed. Stages derive from workitem + add-photos after facility entry.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence

from backend.rinse_bag_lifecycle_status import SENT_TO_RINSE
from backend.rinse_bag_stage_bounds import (
    event_ts,
    events_on_or_after,
    gaming_events_from_records,
    lifecycle_anchor,
    ts_valid,
)
from backend.rinse_scan_purpose import (
    is_add_photos_purpose,
    is_create_workitem_purpose,
    purpose_contains_workitem,
)

HD_NOT_STARTED = "HD_NOT_STARTED"
HD_STARTED_CLEANING = "HD_STARTED_CLEANING"
HD_COMPLETED = "HD_COMPLETED"
HD_SENT_LEFT = "HD_SENT_LEFT"
HD_STILL_AT_FACILITY = "HD_STILL_AT_FACILITY"

HD_STAGE_LABELS = {
    HD_NOT_STARTED: "HD Not Started",
    HD_STARTED_CLEANING: "HD Started Cleaning",
    HD_COMPLETED: "HD Completed",
    HD_SENT_LEFT: "HD Sent / Left",
    HD_STILL_AT_FACILITY: "HD Still at Facility",
}

_WF_WEIGHING_STATUSES = frozenset(
    {
        "PENDING_WEIGHING",
        "WEIGHED_NOT_STARTED",
        "NOT_WEIGHED",
        "WEIGHED",
    }
)
_LOGISTICS_SENT = frozenset({"SENT_TO_RINSE", "FORCE_CHECKOUT", "CHECKED_OUT", "SENT_TO_RINSE"})


def _first_workitem_after(
    timeline: Sequence[Mapping[str, Any]], anchor_ts: datetime | None
) -> tuple[datetime | None, Mapping[str, Any] | None]:
    pool = events_on_or_after(timeline, anchor_ts) if anchor_ts else list(timeline)
    for ev in pool:
        purpose = ev.get("purpose")
        if not (is_create_workitem_purpose(purpose) or purpose_contains_workitem(purpose)):
            continue
        ts = event_ts(ev)
        if ts_valid(ts):
            return ts, ev
    return None, None


def _first_add_photos_after(
    timeline: Sequence[Mapping[str, Any]], after_ts: datetime | None
) -> tuple[datetime | None, Mapping[str, Any] | None]:
    if after_ts is None:
        return None, None
    for ev in events_on_or_after(timeline, after_ts):
        if not is_add_photos_purpose(ev.get("purpose")):
            continue
        ts = event_ts(ev)
        if ts_valid(ts) and ts > after_ts:
            return ts, ev
    return None, None


def _is_sent_or_left(
    *,
    logistics_status: str | None,
    lifecycle_status: str | None,
) -> bool:
    logistics = str(logistics_status or "").strip().upper()
    if logistics in _LOGISTICS_SENT:
        return True
    return str(lifecycle_status or "").strip().upper() == SENT_TO_RINSE


def derive_hd_production_status(
    events: Sequence[Mapping[str, Any]],
    *,
    at_vendor_presence: bool = False,
    logistics_status: str | None = None,
    lifecycle_status: str | None = None,
) -> dict[str, Any]:
    """
    Derive HD production stage from scan events (never WF weighing stages).
    """
    timeline = gaming_events_from_records(events)
    anchor_ts, anchor_ev = lifecycle_anchor(timeline)
    at_facility = anchor_ts is not None or bool(at_vendor_presence)

    workitem_ts, workitem_ev = _first_workitem_after(timeline, anchor_ts)
    add_photos_ts, add_photos_ev = _first_add_photos_after(timeline, workitem_ts)

    sent_left = _is_sent_or_left(
        logistics_status=logistics_status,
        lifecycle_status=lifecycle_status,
    )

    hd_completed = add_photos_ts is not None
    hd_started = workitem_ts is not None

    if sent_left:
        stage = HD_SENT_LEFT
    elif hd_completed and not sent_left:
        stage = HD_STILL_AT_FACILITY
    elif hd_completed:
        stage = HD_COMPLETED
    elif hd_started:
        stage = HD_STARTED_CLEANING
    elif at_facility:
        stage = HD_NOT_STARTED
    else:
        stage = HD_NOT_STARTED

    return {
        "hd_stage": stage,
        "hd_stage_label": HD_STAGE_LABELS.get(stage, stage),
        "hd_started": hd_started,
        "hd_completed": hd_completed,
        "workitem_time": workitem_ts.isoformat() if isinstance(workitem_ts, datetime) else None,
        "add_photos_time_after_workitem": (
            add_photos_ts.isoformat() if isinstance(add_photos_ts, datetime) else None
        ),
        "sent_left": sent_left,
        "sent_left_signal": "logistics_or_lifecycle" if sent_left else None,
        "facility_anchor_time": anchor_ts.isoformat() if isinstance(anchor_ts, datetime) else None,
        "facility_anchor_event": anchor_ev.get("purpose") if isinstance(anchor_ev, dict) else None,
    }


def hd_stage_drilldown_tag(stage: str) -> str:
    """Map HD stage constant to drilldown tag (snake_case)."""
    mapping = {
        HD_NOT_STARTED: "hd_not_started",
        HD_STARTED_CLEANING: "hd_started_cleaning",
        HD_COMPLETED: "hd_completed",
        HD_SENT_LEFT: "hd_sent_left",
        HD_STILL_AT_FACILITY: "hd_still_at_facility",
    }
    return mapping.get(stage, "hd_unknown")


def is_hd_wrongly_in_wf_weighing(
    *,
    service_type: str | None,
    lifecycle_status: str | None,
    drilldown_tags: Sequence[str] | None,
) -> bool:
    svc = str(service_type or "").strip().upper()
    if svc != "HD":
        return False
    tags = set(drilldown_tags or [])
    wf_weigh_tags = {
        "shift_weighed",
        "shift_not_weighed",
        "wf_weighed",
        "wf_not_weighed",
        "pending_wash",
        "pending_wash_rush",
        "pending_wash_nonrush",
        "wf_pending_wash_rush",
        "wf_pending_wash_nonrush",
        "yet_to_fold",
        "wf_pending_folding",
        "weight_difference",
    }
    if tags & wf_weigh_tags:
        return True
    status = str(lifecycle_status or "").strip().upper()
    return status in _WF_WEIGHING_STATUSES
