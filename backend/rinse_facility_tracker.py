"""Facility Tracker Today — management monitoring by Entered / Carryover / Total workload."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable, Mapping, Sequence

from backend.rinse_folding_et import naive_et_day_end_exclusive, naive_et_day_start, period_datetime_bounds_et
from backend.rinse_processing_settings import DEFAULT_FACILITY_ENTRY_RACKS
from backend.rinse_scan_time import normalize_rack_value, system_datetime_to_et
from backend.rinse_shift_analysis import resolve_effective_rush_for_row
from backend.rinse_work_pipeline import bag_is_sent_or_left
from backend.ta_helpers import table_exists

_STATUS_KEYS = ("pending", "completed", "left_sent", "still_at_facility")
_BUCKET_KEYS = ("rush_wf", "rush_hd", "nonrush_wf", "nonrush_hd", "unknown_needs_review")


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


def _scan_et_date(ts: datetime | None) -> date | None:
    if not isinstance(ts, datetime):
        return None
    local = system_datetime_to_et(ts)
    return local.date() if local is not None else None


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


def load_first_facility_entry_dates(
    cursor,
    organization_id: int,
    *,
    entry_racks: Iterable[str] | None = None,
    through_date: date | None = None,
) -> dict[str, date]:
    """First ET date each bag scanned a configured facility entry rack."""
    if not table_exists(cursor, "rinse_bag_scan_events"):
        return {}
    racks = list(entry_racks or DEFAULT_FACILITY_ENTRY_RACKS)
    rack_keys = _entry_rack_keys(racks)
    if not rack_keys:
        return {}

    org = int(organization_id)
    end_exclusive = naive_et_day_end_exclusive(through_date) if through_date else None
    params: list[Any] = [org]
    end_clause = ""
    if end_exclusive is not None:
        end_clause = " AND scanned_at_parsed < %s"
        params.append(end_exclusive)

    cursor.execute(
        f"""
        SELECT bag_id, rack, scanned_at_parsed
        FROM rinse_bag_scan_events
        WHERE organization_id = %s
          AND scanned_at_parsed IS NOT NULL
          AND bag_id IS NOT NULL AND TRIM(bag_id) != ''
          AND rack IS NOT NULL AND TRIM(rack) != ''
          {end_clause}
        ORDER BY bag_id, scanned_at_parsed
        """,
        tuple(params),
    )
    out: dict[str, date] = {}
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            continue
        if not rack_is_facility_entry(row.get("rack"), racks):
            continue
        bid = str(row.get("bag_id") or "").strip().upper()
        if not bid:
            continue
        ts = row.get("scanned_at_parsed")
        if not isinstance(ts, datetime):
            continue
        d = _scan_et_date(ts)
        if d is None:
            continue
        if bid not in out or d < out[bid]:
            out[bid] = d
    return out


def _bucket_for_classified_row(row: Mapping[str, Any]) -> str | None:
    from backend.rinse_simple_shift_performance import _bucket_for_row

    return _bucket_for_row(row)


def _sent_or_left_timestamp(
    rec: Mapping[str, Any],
    pending_row: Mapping[str, Any] | None,
    events: Sequence[Mapping[str, Any]] | None,
    completion: Any,
) -> datetime | None:
    merged = {**dict(pending_row or {}), **dict(rec)}
    stage = merged.get("stage_detail") or {}
    if isinstance(stage, dict):
        raw = stage.get("sent_to_rinse_timestamp")
        if isinstance(raw, datetime):
            return raw
        if isinstance(raw, str) and raw.strip():
            try:
                return datetime.fromisoformat(raw.replace("Z", "+00:00")[:26])
            except ValueError:
                pass
    if completion and getattr(completion, "completion_at", None) and bag_is_sent_or_left(
        pending_row, completion, merged, events
    ):
        return completion.completion_at
    for ev in events or []:
        purpose = str(ev.get("purpose") or "").lower()
        if "sent-to-rinse" in purpose or purpose in {"sent-to-vendor", "checked-out"}:
            ts = ev.get("scanned_at_parsed")
            if isinstance(ts, datetime):
                return ts
    return None


def departed_facility_before_day(
    rec: Mapping[str, Any],
    pending_row: Mapping[str, Any] | None,
    events: Sequence[Mapping[str, Any]] | None,
    completion: Any,
    *,
    day_start: datetime,
) -> bool:
    """True when bag left/sent before the selected ET day starts."""
    merged = {**dict(pending_row or {}), **dict(rec)}
    if not bag_is_sent_or_left(pending_row, completion, merged, events):
        return False
    ts = _sent_or_left_timestamp(rec, pending_row, events, completion)
    if ts is None:
        return False
    return ts < day_start


def classify_facility_bag_status(
    rec: Mapping[str, Any],
    pending_row: Mapping[str, Any] | None,
    events: Sequence[Mapping[str, Any]] | None,
    completion: Any,
) -> str:
    """pending | left_sent | still_at_facility (completed subset uses left/still split)."""
    merged = {**dict(pending_row or {}), **dict(rec)}
    completed = bool(rec.get("completed")) or bool(getattr(completion, "completed", False))
    if not completed:
        return "pending"
    if bag_is_sent_or_left(pending_row, completion, merged, events):
        return "left_sent"
    return "still_at_facility"


def load_carryover_bag_ids(
    first_entry_dates: Mapping[str, date],
    *,
    target_date: date,
    records_by_bag: Mapping[str, Mapping[str, Any]],
    pending_by_bag: Mapping[str, Mapping[str, Any]],
    events_by_bag: Mapping[str, Sequence[Mapping[str, Any]]],
    completions_by_bag: Mapping[str, Any] | None = None,
) -> set[str]:
    """
    Bags that entered before target_date ET and were still in facility workload on target_date.
    Excludes bags that left/sent before the selected day starts.
    """
    day_start = naive_et_day_start(target_date)
    out: set[str] = set()
    completions_by_bag = completions_by_bag or {}
    for bid, first_d in first_entry_dates.items():
        if first_d >= target_date:
            continue
        rec = records_by_bag.get(bid) or {"bag_id": bid}
        pending = pending_by_bag.get(bid)
        events = events_by_bag.get(bid) or []
        completion = completions_by_bag.get(bid)
        if departed_facility_before_day(rec, pending, events, completion, day_start=day_start):
            continue
        out.add(bid)
    return out


def _empty_status_counts() -> dict[str, int]:
    return {k: 0 for k in _STATUS_KEYS}


def _empty_bucket_map() -> dict[str, dict[str, int]]:
    return {b: _empty_status_counts().copy() for b in _BUCKET_KEYS}


def _empty_id_map() -> dict[str, list[str]]:
    return {k: [] for k in _STATUS_KEYS}


def _inc_status(
    status_counts: dict[str, int],
    status_ids: dict[str, list[str]],
    bid: str,
    status: str,
) -> None:
    if status == "pending":
        status_counts["pending"] += 1
        status_ids["pending"].append(bid)
    elif status == "left_sent":
        status_counts["completed"] += 1
        status_counts["left_sent"] += 1
        status_ids["completed"].append(bid)
        status_ids["left_sent"].append(bid)
    else:
        status_counts["completed"] += 1
        status_counts["still_at_facility"] += 1
        status_ids["completed"].append(bid)
        status_ids["still_at_facility"].append(bid)


def _build_management_section_block(
    bag_ids: Iterable[str],
    meta_by_bag: Mapping[str, Mapping[str, Any]],
    target_date: date,
    *,
    prefix: str,
    title: str,
    records_by_bag: Mapping[str, Mapping[str, Any]],
    pending_by_bag: Mapping[str, Mapping[str, Any]],
    events_by_bag: Mapping[str, Sequence[Mapping[str, Any]]],
    completions_by_bag: Mapping[str, Any] | None = None,
    first_entry_dates: Mapping[str, date] | None = None,
) -> dict[str, Any]:
    from backend.rinse_simple_shift_performance import _finalize_section_counts

    completions_by_bag = completions_by_bag or {}
    first_entry_dates = first_entry_dates or {}
    counts = {b: 0 for b in _BUCKET_KEYS}
    bucket_ids: dict[str, list[str]] = {f"{b}_ids": [] for b in _BUCKET_KEYS}
    status_counts = _empty_status_counts()
    status_ids = _empty_id_map()
    by_bucket_status: dict[str, dict[str, int]] = _empty_bucket_map()
    unique_ids = sorted({str(b).strip().upper() for b in bag_ids if b})

    for bid in unique_ids:
        base = dict(meta_by_bag.get(bid) or {"bag_id": bid})
        base["bag_id"] = bid
        base["effective_rush"] = resolve_effective_rush_for_row(base, target_date)
        bucket = _bucket_for_classified_row(base) or "unknown_needs_review"
        if bucket not in counts:
            bucket = "unknown_needs_review"
        counts[bucket] += 1
        bucket_ids[f"{bucket}_ids"].append(bid)

        rec = records_by_bag.get(bid) or {"bag_id": bid}
        pending = pending_by_bag.get(bid)
        events = events_by_bag.get(bid) or []
        completion = completions_by_bag.get(bid)
        status = classify_facility_bag_status(rec, pending, events, completion)
        _inc_status(status_counts, status_ids, bid, status)
        if status == "pending":
            by_bucket_status[bucket]["pending"] += 1
        else:
            by_bucket_status[bucket]["completed"] += 1
            by_bucket_status[bucket][status] += 1

    rush_total = counts["rush_wf"] + counts["rush_hd"]
    nonrush_total = counts["nonrush_wf"] + counts["nonrush_hd"] + counts["unknown_needs_review"]

    section: dict[str, Any] = {
        "scope": prefix,
        "title": title,
        "total": len(unique_ids),
        "rush_total": rush_total,
        "nonrush_total": nonrush_total,
        "rush_wf": counts["rush_wf"],
        "rush_hd": counts["rush_hd"],
        "nonrush_wf": counts["nonrush_wf"],
        "nonrush_hd": counts["nonrush_hd"],
        "unknown_needs_review": counts["unknown_needs_review"],
        "bag_ids": unique_ids,
        **counts,
        **{k: sorted(set(v)) for k, v in bucket_ids.items()},
        "status": {
            **status_counts,
            **{f"{k}_ids": sorted(set(v)) for k, v in status_ids.items()},
        },
        "by_bucket_status": by_bucket_status,
        "drilldown_prefix": prefix,
        "first_entry_dates": {bid: first_entry_dates[bid].isoformat() for bid in unique_ids if bid in first_entry_dates},
    }
    _finalize_section_counts(section)
    section["status_reconciled"] = (
        status_counts["pending"] + status_counts["completed"] == len(unique_ids)
        and status_counts["left_sent"] + status_counts["still_at_facility"] == status_counts["completed"]
    )
    return section


def build_facility_management_tracker(
    cursor,
    organization_id: int,
    *,
    target_date: date,
    entry_racks: Iterable[str],
    meta_by_bag: Mapping[str, Mapping[str, Any]],
    records_by_bag: Mapping[str, Mapping[str, Any]],
    pending_by_bag: Mapping[str, Mapping[str, Any]],
    events_by_bag: Mapping[str, Sequence[Mapping[str, Any]]],
    completions_by_bag: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Three-section management tracker: Entered Today, Carryover, Total Facility Workload."""
    racks = list(entry_racks or DEFAULT_FACILITY_ENTRY_RACKS)
    first_entry_dates = load_first_facility_entry_dates(
        cursor, organization_id, entry_racks=racks, through_date=target_date
    )
    entered_today_ids = load_facility_entry_bag_ids(
        cursor,
        organization_id,
        period_start=target_date,
        period_end=target_date,
        entry_racks=racks,
    )
    carryover_ids = load_carryover_bag_ids(
        first_entry_dates,
        target_date=target_date,
        records_by_bag=records_by_bag,
        pending_by_bag=pending_by_bag,
        events_by_bag=events_by_bag,
        completions_by_bag=completions_by_bag,
    )
    carryover_ids -= entered_today_ids
    total_ids = entered_today_ids | carryover_ids

    common = dict(
        meta_by_bag=meta_by_bag,
        target_date=target_date,
        records_by_bag=records_by_bag,
        pending_by_bag=pending_by_bag,
        events_by_bag=events_by_bag,
        completions_by_bag=completions_by_bag,
        first_entry_dates=first_entry_dates,
    )
    entered = _build_management_section_block(
        entered_today_ids, prefix="ft_entered", title="Entered Today", **common
    )
    carryover = _build_management_section_block(
        carryover_ids, prefix="ft_carryover", title="Carryover", **common
    )
    total = _build_management_section_block(
        total_ids, prefix="ft_total", title="Total Facility Workload", **common
    )

    return {
        "entry_racks": racks,
        "period": target_date.isoformat(),
        "target_date": target_date.isoformat(),
        "description": "Management facility tracker for selected ET day",
        "entered_today": entered,
        "carryover": carryover,
        "total_workload": total,
        "reconciliation": {
            "total_equals_entered_plus_carryover": total["total"] == entered["total"] + carryover["total"],
            "entered_total": entered["total"],
            "carryover_total": carryover["total"],
            "total_workload": total["total"],
        },
        # Legacy flat fields (Entered Today only)
        "total": entered["total"],
        "rush_wf": entered["rush_wf"],
        "rush_hd": entered["rush_hd"],
        "nonrush_wf": entered["nonrush_wf"],
        "nonrush_hd": entered["nonrush_hd"],
        "unknown_needs_review": entered["unknown_needs_review"],
        "bag_ids": entered["bag_ids"],
        "completed": entered["status"]["completed"],
        "still_active": entered["status"]["pending"],
        "sent_or_left": entered["status"]["left_sent"],
        "still_at_facility": entered["status"]["still_at_facility"],
        "completed_ids": entered["status"]["completed_ids"],
        "still_active_ids": entered["status"]["pending_ids"],
        "sent_or_left_ids": entered["status"]["left_sent_ids"],
        "still_at_facility_ids": entered["status"]["still_at_facility_ids"],
    }


def apply_facility_management_drilldown_tags(
    records: list[dict[str, Any]],
    tracker: Mapping[str, Any],
    *,
    pending_by_bag: Mapping[str, Mapping[str, Any]],
    events_by_bag: Mapping[str, Sequence[Mapping[str, Any]]],
    completions_by_bag: Mapping[str, Any] | None = None,
    first_entry_dates: Mapping[str, date] | None = None,
) -> None:
    """Attach ft_* drilldown tags and management fields to shift monitor records."""
    completions_by_bag = completions_by_bag or {}
    first_entry_dates = first_entry_dates or {}
    sections = (
        ("ft_entered", tracker.get("entered_today") or {}),
        ("ft_carryover", tracker.get("carryover") or {}),
        ("ft_total", tracker.get("total_workload") or {}),
    )
    membership: dict[str, set[str]] = {}
    for prefix, block in sections:
        for bid in block.get("bag_ids") or []:
            membership.setdefault(str(bid).strip().upper(), set()).add(prefix)

    rec_by_id = {str(r.get("bag_id") or "").strip().upper(): r for r in records if r.get("bag_id")}
    for bid, prefixes in membership.items():
        rec = rec_by_id.get(bid)
        if not rec:
            continue
        pending = pending_by_bag.get(bid)
        events = events_by_bag.get(bid) or []
        completion = completions_by_bag.get(bid)
        status = classify_facility_bag_status(rec, pending, events, completion)
        bucket = rec.get("rush_bucket") or "unknown_needs_review"
        if bucket not in _BUCKET_KEYS:
            bucket = "unknown_needs_review"
        left = status == "left_sent"
        still_at = status == "still_at_facility"
        tags = set(rec.get("drilldown_tags") or [])
        for prefix in prefixes:
            tags.add(prefix)
            tags.add(f"{prefix}_{status}")
            tags.add(f"{prefix}_{bucket}")
            tags.add(f"{prefix}_{bucket}_{status}")
            if bucket == "unknown_needs_review":
                tags.add(f"{prefix}_unknown_needs_review")
            if prefix == "ft_entered":
                tags.add("facility_tracker")
                tags.add(f"facility_{bucket}")
                if bucket == "unknown_needs_review":
                    tags.add("facility_unknown_needs_review")
        rec["drilldown_tags"] = sorted(tags)
        rec["facility_entered_date"] = (
            first_entry_dates[bid].isoformat() if bid in first_entry_dates else None
        )
        rec["facility_status"] = status
        rec["facility_left_sent"] = left
        rec["facility_still_at_facility"] = still_at
        rec["facility_segments"] = sorted(prefixes)


# Legacy helpers kept for overlap debug
def classify_bag_ids_into_section(
    bag_ids: Iterable[str],
    meta_by_bag: Mapping[str, Mapping[str, Any]],
    target_date: date,
    *,
    source: str,
    drilldown_filter: str,
    scope_label: str,
) -> dict[str, Any]:
    from backend.rinse_simple_shift_performance import _finalize_section_counts

    counts = {b: 0 for b in _BUCKET_KEYS}
    bucket_ids: dict[str, list[str]] = {f"{b}_ids": [] for b in _BUCKET_KEYS}
    unique_ids = sorted({str(b).strip().upper() for b in bag_ids if b})
    for bid in unique_ids:
        base = dict(meta_by_bag.get(bid) or {"bag_id": bid})
        base["bag_id"] = bid
        base["effective_rush"] = resolve_effective_rush_for_row(base, target_date)
        bucket = _bucket_for_classified_row(base) or "unknown_needs_review"
        if bucket not in counts:
            bucket = "unknown_needs_review"
        counts[bucket] += 1
        bucket_ids[f"{bucket}_ids"].append(bid)

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


def enrich_facility_tracker_status(
    section: dict[str, Any],
    *,
    bag_ids: Iterable[str],
    records_by_bag: Mapping[str, Mapping[str, Any]],
    active_bag_ids: Iterable[str],
    staging_bag_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Legacy enrich — prefer build_facility_management_tracker."""
    active = {str(b).strip().upper() for b in active_bag_ids if b}
    staging = {str(b).strip().upper() for b in (staging_bag_ids or []) if b}
    completed_ids: list[str] = []
    still_active_ids: list[str] = []
    sent_or_left_ids: list[str] = []
    still_at_facility_ids: list[str] = []
    missing_staging_ids: list[str] = []

    for bid in sorted({str(b).strip().upper() for b in bag_ids if b}):
        rec = records_by_bag.get(bid) or {}
        if rec.get("completed"):
            completed_ids.append(bid)
        if bid in active:
            still_active_ids.append(bid)
        if rec.get("facility_left_sent") or (
            not rec.get("facility_left_sent") and rec.get("completed") is False
        ):
            pass
        status = rec.get("facility_status")
        if status == "left_sent":
            sent_or_left_ids.append(bid)
        elif status == "still_at_facility":
            still_at_facility_ids.append(bid)
        elif rec.get("completed") and bid not in sent_or_left_ids:
            if status != "pending":
                still_at_facility_ids.append(bid)
        if staging and bid not in staging:
            missing_staging_ids.append(bid)

    section["completed"] = len(completed_ids)
    section["still_active"] = len(still_active_ids)
    section["sent_or_left"] = len(sent_or_left_ids)
    section["sent_or_checked_out"] = len(sent_or_left_ids)
    section["still_at_facility"] = len(still_at_facility_ids)
    section["completed_ids"] = completed_ids
    section["still_active_ids"] = still_active_ids
    section["sent_or_left_ids"] = sent_or_left_ids
    section["sent_or_checked_out_ids"] = sent_or_left_ids
    section["still_at_facility_ids"] = still_at_facility_ids
    section["missing_staging_ids"] = missing_staging_ids
    return section


def build_scope_overlap_debug(
    *,
    facility_bag_ids: Iterable[str],
    active_bag_ids: Iterable[str],
    records_by_bag: Mapping[str, Mapping[str, Any]] | None = None,
    pipeline_debug: Mapping[str, Any] | None = None,
    management_tracker: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    from backend.rinse_work_pipeline import build_current_work_pipeline_debug

    facility = {str(b).strip().upper() for b in facility_bag_ids if b}
    active = {str(b).strip().upper() for b in active_bag_ids if b}
    pipeline = pipeline_debug or build_current_work_pipeline_debug(
        facility_bag_ids=facility,
        pipeline_bag_ids=active,
        staging_bag_ids=active,
        completed_excluded=[],
        sent_excluded=[],
    )
    mgmt = management_tracker or {}
    entered_block = mgmt.get("entered_today") or {}
    carry_block = mgmt.get("carryover") or {}
    entered_and_active = sorted(facility & active)
    entered_completed = sorted(facility - set(pipeline.get("entered_today_still_active") or entered_and_active))
    return {
        "current_work_pipeline": dict(pipeline),
        "facility_management": {
            "entered_today_total": entered_block.get("total"),
            "carryover_total": carry_block.get("total"),
            "total_workload": (mgmt.get("total_workload") or {}).get("total"),
            "reconciliation": mgmt.get("reconciliation"),
        },
        "entered_today_and_still_active": pipeline.get("entered_today_still_active") or entered_and_active,
        "entered_today_and_completed": entered_completed,
        "carryover_active_from_prior_day": carry_block.get("bag_ids") or pipeline.get("carryover_active_from_prior_day") or sorted(active - facility),
        "facility_only_count": len(facility - active),
        "active_only_count": len(active - facility),
        "overlap_count": len(facility & active),
    }
