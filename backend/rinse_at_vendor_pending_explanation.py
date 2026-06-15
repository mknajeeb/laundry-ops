"""Display-only pending explanations for At Vendor rows (does not affect completion)."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any, Mapping, Sequence

from backend.rinse_bag_activity_rules import unique_occurrence_times
from backend.rinse_bag_stage_bounds import event_ts
from backend.rinse_scan_purpose import (
    is_add_photos_purpose,
    is_assembly_printed_ct_purpose,
    is_complete_cleaning_purpose,
    is_hd_add_photos_interruption_purpose,
    is_move_bag_purpose,
    is_processed_by_vendor_purpose,
    is_received_from_vendor_purpose,
    is_weight_entry_purpose,
    normalize_scan_purpose,
)
from backend.rinse_wf_weight_events import distinct_wf_weight_events

PENDING_WHY_LABELS: dict[str, str] = {
    "missing_sent_to_vendor": "Awaiting sent-to-vendor scan",
    "missing_weight_entry": "Missing weight-entry after sent-to-vendor",
    "missing_second_weight": "Missing second weight",
    "weight_once_no_completion": "Weight recorded once; completion scan missing",
    "same_ts_weight_dupes": "Same-time weight uploads only — need second physical weigh",
    "cleaning_started_not_completed": "Cleaning started, not completed",
    "awaiting_complete_cleaning": "Awaiting complete-cleaning",
    "awaiting_vendor_delivery": "Awaiting delivery/vendor completion signal",
    "hd_missing_second_add_photos": "Missing second add-photos",
    "hd_issue_interruption": "Issue/workitem interruption before second add-photos",
    "awaiting_hd_completion_signal": "Awaiting garments-reviewed / complete-cleaning / assembly signal",
    "hd_pending": "Pending — HD completion signal missing",
}


def _is_cleaning_started_purpose(raw: str | None) -> bool:
    if is_complete_cleaning_purpose(raw):
        return False
    p = normalize_scan_purpose(raw)
    return p == "cleaning" or p.startswith("cleaning ") or p == "start-cleaning"


def _is_garments_reviewed_purpose(raw: str | None) -> bool:
    return "garments-reviewed" in normalize_scan_purpose(raw)


def _is_hd_completion_purpose(raw: str | None) -> bool:
    return (
        is_complete_cleaning_purpose(raw)
        or is_assembly_printed_ct_purpose(raw)
        or _is_garments_reviewed_purpose(raw)
    )


def _anchored_events(
    events: Sequence[Mapping[str, Any]],
    *,
    anchor_ts: datetime | None,
    as_of_end: datetime,
) -> list[Mapping[str, Any]]:
    if anchor_ts is None:
        return []
    out: list[Mapping[str, Any]] = []
    for ev in events:
        ts = event_ts(ev)
        if ts is not None and ts >= anchor_ts and ts <= as_of_end:
            out.append(ev)
    return out


def _wf_same_ts_weight_dupes(anchored: Sequence[Mapping[str, Any]]) -> bool:
    by_ts: dict[str, int] = {}
    for ev in anchored:
        if not is_weight_entry_purpose(ev.get("purpose")):
            continue
        ts = event_ts(ev)
        if ts is None:
            continue
        key = str(ts)
        by_ts[key] = by_ts.get(key, 0) + 1
    return any(count > 1 for count in by_ts.values()) and len(by_ts) == 1


def _wf_has_vendor_delivery_signal(anchored: Sequence[Mapping[str, Any]]) -> bool:
    for ev in anchored:
        purpose = ev.get("purpose")
        rack = str(ev.get("rack") or "").lower()
        if is_processed_by_vendor_purpose(purpose):
            return True
        if is_received_from_vendor_purpose(purpose):
            return True
        if normalize_scan_purpose(purpose) == "delivery-prep-completed":
            return True
        if is_move_bag_purpose(purpose) and "clean" in rack and "dirty" not in rack:
            return True
    return False


def derive_pending_explanation(
    *,
    service_type: str,
    events: Sequence[Mapping[str, Any]],
    anchor_ts: datetime | None,
    as_of_end: datetime,
) -> dict[str, Any]:
    """Return display-only pending explanation fields for a Pending At Vendor row."""
    svc = (service_type or "").upper()
    anchored = _anchored_events(events, anchor_ts=anchor_ts, as_of_end=as_of_end)
    summary_keys: list[str] = []

    if anchor_ts is None:
        key = "missing_sent_to_vendor"
        return {
            "pending_why_key": key,
            "pending_why_label": PENDING_WHY_LABELS[key],
            "pending_why_summary_keys": [key],
        }

    if svc == "HD":
        add_photos = unique_occurrence_times(anchored, is_add_photos_purpose)
        interruption = any(
            is_hd_add_photos_interruption_purpose(ev.get("purpose")) for ev in anchored
        )
        has_hd_completion = any(_is_hd_completion_purpose(ev.get("purpose")) for ev in anchored)
        if len(add_photos) < 2:
            summary_keys.append("hd_missing_second_add_photos")
        if interruption and len(add_photos) < 2:
            key = "hd_issue_interruption"
            summary_keys.append(key)
        elif len(add_photos) < 2:
            key = "hd_missing_second_add_photos"
        elif has_hd_completion:
            key = "awaiting_hd_completion_signal"
            summary_keys.append(key)
        else:
            key = "hd_pending"
        return {
            "pending_why_key": key,
            "pending_why_label": PENDING_WHY_LABELS.get(key, PENDING_WHY_LABELS["hd_pending"]),
            "pending_why_summary_keys": sorted(set(summary_keys or [key])),
        }

    weights = distinct_wf_weight_events(anchored, anchor_ts=anchor_ts, as_of_end=as_of_end)
    distinct_weight_count = len(weights)
    same_ts_dupes = _wf_same_ts_weight_dupes(anchored)
    has_complete_cleaning = any(
        is_complete_cleaning_purpose(ev.get("purpose")) for ev in anchored
    )
    has_cleaning_started = any(_is_cleaning_started_purpose(ev.get("purpose")) for ev in anchored)
    has_vendor_signal = _wf_has_vendor_delivery_signal(anchored)

    if distinct_weight_count < 2:
        summary_keys.append("missing_second_weight")
    if same_ts_dupes:
        summary_keys.append("same_ts_weight_dupes")
    if distinct_weight_count >= 1 and not has_complete_cleaning:
        summary_keys.append("missing_complete_cleaning")
    if has_cleaning_started and not has_complete_cleaning:
        summary_keys.append("cleaning_started_not_completed")

    if distinct_weight_count == 0:
        key = "missing_weight_entry"
    elif same_ts_dupes:
        key = "same_ts_weight_dupes"
    elif has_cleaning_started and not has_complete_cleaning:
        key = "cleaning_started_not_completed"
    elif has_vendor_signal:
        key = "awaiting_vendor_delivery"
        summary_keys.append(key)
    elif distinct_weight_count == 1 and not has_cleaning_started:
        key = "weight_once_no_completion"
    elif distinct_weight_count == 1 and not has_complete_cleaning:
        key = "awaiting_complete_cleaning"
    else:
        key = "missing_second_weight"

    return {
        "pending_why_key": key,
        "pending_why_label": PENDING_WHY_LABELS[key],
        "pending_why_summary_keys": sorted(set(summary_keys)),
    }


def summarize_rush_pending_why(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate display-only counts for Rush Pending supervisor panel."""
    counts = Counter(
        {
            "missing_second_weight": 0,
            "same_ts_weight_dupes": 0,
            "missing_complete_cleaning": 0,
            "cleaning_started_not_completed": 0,
            "hd_missing_second_add_photos": 0,
            "hd_issue_interruption": 0,
        }
    )
    rush_pending = 0
    for row in rows:
        if row.get("rush_bucket") != "RUSH" or row.get("at_vendor_status") != "Pending":
            continue
        rush_pending += 1
        for key in row.get("pending_why_summary_keys") or []:
            if key in counts:
                counts[key] += 1
    return {
        "total_rush_pending": rush_pending,
        "missing_second_weight": counts["missing_second_weight"],
        "same_ts_weight_dupes": counts["same_ts_weight_dupes"],
        "missing_complete_cleaning": counts["missing_complete_cleaning"],
        "cleaning_started_not_completed": counts["cleaning_started_not_completed"],
        "hd_missing_second_add_photos": counts["hd_missing_second_add_photos"],
        "hd_issue_interruption": counts["hd_issue_interruption"],
    }
