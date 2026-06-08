"""Facility Tracker Today — bags that entered via facility entry rack scan on selected ET date(s)."""

from __future__ import annotations

from datetime import date
from typing import Any, Iterable, Mapping

from backend.rinse_folding_et import naive_et_day_end_exclusive, period_datetime_bounds_et
from backend.rinse_processing_settings import DEFAULT_FACILITY_ENTRY_RACKS
from backend.rinse_scan_time import normalize_rack_value
from backend.rinse_shift_analysis import resolve_effective_rush_for_row
from backend.ta_helpers import table_exists


def _entry_rack_keys(entry_racks: Iterable[str]) -> set[str]:
    keys: set[str] = set()
    for rack in entry_racks:
        norm = normalize_rack_value(rack)
        if norm:
            keys.add(norm.casefold())
    return keys


def rack_is_facility_entry(rack: Any, entry_racks: Iterable[str]) -> bool:
    norm = normalize_rack_value(rack)
    if not norm:
        return False
    return norm.casefold() in _entry_rack_keys(entry_racks)


def load_facility_entry_bag_ids(
    cursor,
    organization_id: int,
    *,
    period_start: date,
    period_end: date,
    entry_racks: Iterable[str] | None = None,
) -> set[str]:
    """Bags with a facility entry rack scan on any day in [period_start, period_end] ET."""
    if not table_exists(cursor, "rinse_bag_scan_events"):
        return set()
    racks = list(entry_racks or DEFAULT_FACILITY_ENTRY_RACKS)
    rack_keys = _entry_rack_keys(racks)
    if not rack_keys:
        return set()

    org = int(organization_id)
    start_dt, _end_incl = period_datetime_bounds_et(period_start, period_end)
    end_exclusive = naive_et_day_end_exclusive(period_end)
    cursor.execute(
        """
        SELECT DISTINCT bag_id, rack
        FROM rinse_bag_scan_events
        WHERE organization_id = %s
          AND scanned_at_parsed IS NOT NULL
          AND scanned_at_parsed >= %s
          AND scanned_at_parsed < %s
          AND bag_id IS NOT NULL AND TRIM(bag_id) != ''
          AND rack IS NOT NULL AND TRIM(rack) != ''
        """,
        (org, start_dt, end_exclusive),
    )
    out: set[str] = set()
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            continue
        bid = str(row.get("bag_id") or "").strip().upper()
        if not bid:
            continue
        if rack_is_facility_entry(row.get("rack"), racks):
            out.add(bid)
    return out


def _bucket_for_classified_row(row: Mapping[str, Any]) -> str | None:
    from backend.rinse_simple_shift_performance import _bucket_for_row

    return _bucket_for_row(row)


def _inc_bucket(
    counts: dict[str, int],
    bucket_ids: dict[str, list[str]],
    bid: str,
    bucket: str | None,
) -> None:
    if bucket == "rush_wf":
        counts["rush_wf"] += 1
        bucket_ids["rush_wf_ids"].append(bid)
    elif bucket == "rush_hd":
        counts["rush_hd"] += 1
        bucket_ids["rush_hd_ids"].append(bid)
    elif bucket == "nonrush_wf":
        counts["nonrush_wf"] += 1
        bucket_ids["nonrush_wf_ids"].append(bid)
    elif bucket == "nonrush_hd":
        counts["nonrush_hd"] += 1
        bucket_ids["nonrush_hd_ids"].append(bid)
    else:
        counts["unknown_needs_review"] += 1
        bucket_ids["unknown_ids"].append(bid)


def classify_bag_ids_into_section(
    bag_ids: Iterable[str],
    meta_by_bag: Mapping[str, Mapping[str, Any]],
    target_date: date,
    *,
    source: str,
    drilldown_filter: str,
    scope_label: str,
) -> dict[str, Any]:
    """Shared Rush/WF/HD classification for facility tracker and active work scopes."""
    counts = {
        "rush_wf": 0,
        "rush_hd": 0,
        "nonrush_wf": 0,
        "nonrush_hd": 0,
        "unknown_needs_review": 0,
    }
    bucket_ids: dict[str, list[str]] = {
        "rush_wf_ids": [],
        "rush_hd_ids": [],
        "nonrush_wf_ids": [],
        "nonrush_hd_ids": [],
        "unknown_ids": [],
    }
    unique_ids = sorted({str(b).strip().upper() for b in bag_ids if b})
    for bid in unique_ids:
        base = dict(meta_by_bag.get(bid) or {"bag_id": bid})
        base["bag_id"] = bid
        base["effective_rush"] = resolve_effective_rush_for_row(base, target_date)
        _inc_bucket(counts, bucket_ids, bid, _bucket_for_classified_row(base))

    from backend.rinse_simple_shift_performance import _finalize_section_counts

    section: dict[str, Any] = {
        "scope": scope_label,
        "total": len(unique_ids),
        **counts,
        "source": source,
        "drilldown_filter": drilldown_filter,
        "bag_ids": unique_ids,
        **{k: sorted(set(v)) for k, v in bucket_ids.items()},
    }
    _finalize_section_counts(section)
    return section


def build_facility_tracker_section(
    bag_ids: Iterable[str],
    meta_by_bag: Mapping[str, Mapping[str, Any]],
    target_date: date,
    *,
    entry_racks: Iterable[str],
    period_start: date,
    period_end: date,
) -> dict[str, Any]:
    period_label = (
        period_start.isoformat()
        if period_start == period_end
        else f"{period_start.isoformat()}..{period_end.isoformat()}"
    )
    section = classify_bag_ids_into_section(
        bag_ids,
        meta_by_bag,
        target_date,
        source="facility entry rack scan",
        drilldown_filter="facility_tracker",
        scope_label="facility_tracker_today",
    )
    section["entry_racks"] = list(entry_racks)
    section["period"] = period_label
    section["description"] = "Bags that entered via facility entry rack on selected date(s)"
    return section


def _bag_is_sent_or_checked_out(rec: Mapping[str, Any], meta: Mapping[str, Any]) -> bool:
    from backend.rinse_simple_shift_performance import _logistics_sent

    lifecycle = str(rec.get("current_status") or meta.get("current_lifecycle_status") or "").upper()
    checkout = str(meta.get("checkout_status") or "").upper()
    if lifecycle in {"SENT_TO_RINSE", "FOLDED_COMPLETED", "CHECKED_OUT", "FORCE_CHECKOUT"}:
        if checkout in {"CHECKED_OUT", "CHECKOUT_NOT_RECORDED"} or lifecycle == "SENT_TO_RINSE":
            return True
    return _logistics_sent(meta)


def enrich_facility_tracker_status(
    section: dict[str, Any],
    *,
    bag_ids: Iterable[str],
    records_by_bag: Mapping[str, Mapping[str, Any]],
    active_bag_ids: Iterable[str],
    staging_bag_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    active = {str(b).strip().upper() for b in active_bag_ids if b}
    staging = {str(b).strip().upper() for b in (staging_bag_ids or []) if b}
    completed_ids: list[str] = []
    still_active_ids: list[str] = []
    sent_or_checked_out_ids: list[str] = []
    missing_staging_ids: list[str] = []

    for bid in sorted({str(b).strip().upper() for b in bag_ids if b}):
        rec = records_by_bag.get(bid) or {}
        meta = rec if isinstance(rec, dict) else {}
        if rec.get("completed"):
            completed_ids.append(bid)
        if bid in active:
            still_active_ids.append(bid)
        if _bag_is_sent_or_checked_out(rec, meta):
            sent_or_checked_out_ids.append(bid)
        if staging and bid not in staging:
            missing_staging_ids.append(bid)

    section["completed"] = len(completed_ids)
    section["still_active"] = len(still_active_ids)
    section["sent_or_checked_out"] = len(sent_or_checked_out_ids)
    section["completed_ids"] = completed_ids
    section["still_active_ids"] = still_active_ids
    section["sent_or_checked_out_ids"] = sent_or_checked_out_ids
    section["missing_staging_ids"] = missing_staging_ids
    return section


def build_scope_overlap_debug(
    *,
    facility_bag_ids: Iterable[str],
    active_bag_ids: Iterable[str],
    records_by_bag: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    facility = {str(b).strip().upper() for b in facility_bag_ids if b}
    active = {str(b).strip().upper() for b in active_bag_ids if b}
    records_by_bag = records_by_bag or {}

    entered_and_active = sorted(facility & active)
    entered_not_active: list[str] = []
    for bid in sorted(facility - active):
        rec = records_by_bag.get(bid) or {}
        entered_not_active.append(bid)

    return {
        "entered_today_and_still_active": entered_and_active,
        "entered_today_and_completed": sorted(facility - active),
        "carryover_active_from_prior_day": sorted(active - facility),
        "facility_only_count": len(facility - active),
        "active_only_count": len(active - facility),
        "overlap_count": len(facility & active),
    }
