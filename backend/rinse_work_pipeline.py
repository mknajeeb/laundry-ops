"""Current Work Pipeline — pending facility bags including carryover (excludes completed/sent)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Mapping, Sequence

from backend.rinse_bag_lifecycle_status import (
    SENT_TO_RINSE,
    SENT_TO_RINSE_EXTERNAL_USER_AFTER_CLEAN,
    SENT_TO_RINSE_MISSING_FROM_NEXT_PORTAL_SCRAPE,
)
from backend.rinse_shift_analysis import LIFECYCLE_COMPLETED_STATUSES

_LOGISTICS_SENT = frozenset({"SENT_TO_RINSE", "FORCE_CHECKOUT", "CHECKED_OUT"})


def _logistics_sent(row: Mapping[str, Any]) -> bool:
    logistics = str(row.get("logistics_status") or row.get("status") or "").upper()
    return logistics in _LOGISTICS_SENT


def bag_is_sent_or_left(
    pending_row: Mapping[str, Any] | None,
    completion: Any,
    meta: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]] | None = None,
) -> bool:
    """Operational sent/left — lifecycle, staging logistics, scan/scrape signals (not manual checkout)."""
    merged: dict[str, Any] = {**dict(meta or {}), **dict(pending_row or {})}
    lifecycle = str(
        merged.get("current_lifecycle_status")
        or merged.get("current_status")
        or merged.get("lifecycle_status")
        or ""
    ).upper()
    if lifecycle in _LOGISTICS_SENT or lifecycle == SENT_TO_RINSE:
        return True
    if _logistics_sent(merged):
        return True
    stage = merged.get("stage_detail") or {}
    if isinstance(stage, dict):
        reason = str(stage.get("sent_to_rinse_reason") or "")
        if reason in {
            SENT_TO_RINSE_EXTERNAL_USER_AFTER_CLEAN,
            SENT_TO_RINSE_MISSING_FROM_NEXT_PORTAL_SCRAPE,
        }:
            return True
    if completion and getattr(completion, "completed", False):
        for ev in events or []:
            purpose = str(ev.get("purpose") or "").lower()
            if "sent-to-rinse" in purpose or purpose in {"sent-to-vendor", "checked-out"}:
                return True
    return False


def bag_is_pipeline_eligible(
    pending_row: Mapping[str, Any] | None,
    completion: Any,
    meta: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]] | None = None,
) -> bool:
    """Bag still pending in facility workflow — includes carryover, excludes completed/sent."""
    if not pending_row or not isinstance(pending_row, dict):
        return False
    scope = str(pending_row.get("record_scope") or "")
    if scope == "incoming" or scope not in ("wf_lifecycle", "hd_lifecycle"):
        return False
    if not pending_row.get("in_active_staging"):
        return False
    lifecycle = str(pending_row.get("current_lifecycle_status") or "").upper()
    if lifecycle in LIFECYCLE_COMPLETED_STATUSES:
        return False
    if completion and getattr(completion, "completed", False):
        return False
    if bag_is_sent_or_left(pending_row, completion, meta, events):
        return False
    return True


def build_last_wash_detail(
    *,
    at: datetime,
    bag_id: str,
    customer: Any,
    user: Any,
    service_type: Any,
    rush_label: Any,
    rush_bucket: Any,
) -> dict[str, Any]:
    return {
        "at": at.isoformat(),
        "time": at.isoformat(),
        "bag_id": bag_id,
        "customer": customer,
        "employee": user,
        "user": user,
        "service_type": service_type,
        "rush_label": rush_label,
        "rush_bucket": rush_bucket,
    }


def update_last_wash_if_newer(
    current: dict[str, Any] | None,
    candidate: dict[str, Any],
) -> dict[str, Any]:
    if not current:
        return candidate
    cur_at = current.get("at")
    new_at = candidate.get("at")
    if not new_at:
        return current
    if not cur_at or new_at > cur_at:
        return candidate
    return current


def build_current_work_pipeline_debug(
    *,
    facility_bag_ids: Iterable[str],
    pipeline_bag_ids: Iterable[str],
    staging_bag_ids: Iterable[str],
    completed_excluded: Iterable[str],
    sent_excluded: Iterable[str],
) -> dict[str, Any]:
    facility = {str(b).strip().upper() for b in facility_bag_ids if b}
    pipeline = {str(b).strip().upper() for b in pipeline_bag_ids if b}
    staging = {str(b).strip().upper() for b in staging_bag_ids if b}
    entered_today_still_active = sorted(facility & pipeline)
    carryover = sorted(pipeline - facility)
    active_without_entry_scan = sorted(pipeline - facility)
    return {
        "entered_today_still_active": entered_today_still_active,
        "carryover_active_from_prior_day": carryover,
        "active_without_entry_scan": active_without_entry_scan,
        "completed_excluded": sorted({str(b).strip().upper() for b in completed_excluded if b}),
        "sent_excluded": sorted({str(b).strip().upper() for b in sent_excluded if b}),
        "pipeline_total": len(pipeline),
        "staging_total": len(staging),
        "facility_today_total": len(facility),
        "overlap_count": len(facility & pipeline),
    }
