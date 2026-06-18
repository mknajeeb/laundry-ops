"""
Read-only shift operations timeline — all bag/order and employee activity for an ET day.

Uses rinse_bag_scan_events only; does not alter productivity, completion, or scan data.
Separate from sorting chronology (which focuses on sorting sessions only).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Any, Mapping, Sequence

from backend.rinse_bag_completion import rack_contains_clean
from backend.rinse_bag_gaming_performance import evaluate_bag_gaming_performance
from backend.rinse_bag_stage_bounds import event_ts, gaming_events_from_records, ts_valid
from backend.rinse_folding_et import naive_et_day_end_inclusive, naive_et_day_start
from backend.rinse_scan_purpose import (
    is_add_photos_purpose,
    is_assembly_printed_ct_purpose,
    is_complete_cleaning_purpose,
    is_create_issue_purpose,
    is_create_workitem_issue_or_bulk_purpose,
    is_drying_purpose,
    is_ghost_cleaning_purpose,
    is_lifecycle_sorting_progress_marker_purpose,
    is_load_washer_end_purpose,
    is_processed_by_vendor_purpose,
    is_quality_control_completed_purpose,
    is_split_load_purpose,
    is_start_cleaning_purpose,
    is_weight_entry_purpose,
    normalize_scan_purpose,
)
from backend.ta_helpers import table_exists

ACTIVITY_SORTING = "sorting"
ACTIVITY_WEIGHING = "weighing"
ACTIVITY_WASHING = "washing"
ACTIVITY_DRYING = "drying"
ACTIVITY_FOLDING = "folding"
ACTIVITY_OTHER = "other"

ALL_ACTIVITY_CATEGORIES = (
    ACTIVITY_SORTING,
    ACTIVITY_WEIGHING,
    ACTIVITY_WASHING,
    ACTIVITY_DRYING,
    ACTIVITY_FOLDING,
    ACTIVITY_OTHER,
)

VIEW_SHIFT_TIMELINE = "shift_timeline"
VIEW_ORDER_JOURNEY = "order_journey"
VIEW_EMPLOYEE_ACTIVITY = "employee_activity"
ALL_VIEWS = (VIEW_SHIFT_TIMELINE, VIEW_ORDER_JOURNEY, VIEW_EMPLOYEE_ACTIVITY)


def purpose_to_activity_category(
    raw: str | None,
    *,
    rack: str | None = None,
) -> str:
    """Map normalized scan purpose (+ optional rack) to timeline activity category."""
    if is_weight_entry_purpose(raw):
        return ACTIVITY_WEIGHING
    if is_drying_purpose(raw):
        return ACTIVITY_DRYING
    if (
        is_start_cleaning_purpose(raw)
        or is_load_washer_end_purpose(raw)
        or is_complete_cleaning_purpose(raw)
        or is_processed_by_vendor_purpose(raw)
    ):
        return ACTIVITY_WASHING
    if is_quality_control_completed_purpose(raw) or is_assembly_printed_ct_purpose(raw):
        return ACTIVITY_FOLDING
    if rack and rack_contains_clean(rack):
        return ACTIVITY_FOLDING
    if (
        is_lifecycle_sorting_progress_marker_purpose(raw)
        or is_add_photos_purpose(raw)
        or is_split_load_purpose(raw)
        or is_create_workitem_issue_or_bulk_purpose(raw)
        or is_create_issue_purpose(raw)
        or is_ghost_cleaning_purpose(raw)
    ):
        return ACTIVITY_SORTING
    return ACTIVITY_OTHER


def _operator(ev: Mapping[str, Any] | None) -> str | None:
    if ev is None:
        return None
    for key in ("user_name", "user", "User"):
        val = ev.get(key)
        if val:
            return str(val).strip() or None
    return None


def _duration_seconds(start: datetime | None, end: datetime | None) -> int:
    if not ts_valid(start) or not ts_valid(end):
        return 0
    sec = int((end - start).total_seconds())
    return max(sec, 0)


def _clip_duration_to_day(
    start: datetime | None,
    end: datetime | None,
    *,
    day_start: datetime,
    day_end: datetime,
) -> int:
    if not ts_valid(start) or not ts_valid(end):
        return 0
    clip_start = max(start, day_start)
    clip_end = min(end, day_end)
    if clip_end < clip_start:
        return 0
    return int((clip_end - clip_start).total_seconds())


def _event_on_day(ts: datetime | None, day_start: datetime, day_end: datetime) -> bool:
    if not ts_valid(ts):
        return False
    return day_start <= ts <= day_end


def _timeline_row_from_event(ev: Mapping[str, Any]) -> dict[str, Any]:
    purpose_raw = ev.get("purpose")
    purpose_norm = normalize_scan_purpose(purpose_raw)
    rack = str(ev.get("rack") or "").strip() or None
    category = purpose_to_activity_category(purpose_raw, rack=rack)
    ts = event_ts(ev)
    return {
        "timestamp_et": ts,
        "employee": _operator(ev),
        "bag_id": str(ev.get("bag_id") or "").strip(),
        "activity_category": category,
        "activity_label": purpose_norm or purpose_raw or ACTIVITY_OTHER,
        "purpose_raw": purpose_raw,
        "purpose_normalized": purpose_norm,
        "rack": rack,
        "scan_index": ev.get("scan_index"),
        "event_id": ev.get("id"),
    }


def _load_scan_events_on_day(
    cursor,
    organization_id: int,
    day_start: datetime,
    day_end: datetime,
) -> list[dict[str, Any]]:
    if not table_exists(cursor, "rinse_bag_scan_events"):
        return []
    cursor.execute(
        """
        SELECT bag_id, id, rack, user_name, purpose, scanned_at_parsed, scan_index
        FROM rinse_bag_scan_events
        WHERE organization_id = %s
          AND scanned_at_parsed >= %s
          AND scanned_at_parsed <= %s
        ORDER BY scanned_at_parsed ASC, scan_index ASC, id ASC
        """,
        (int(organization_id), day_start, day_end),
    )
    return [dict(r) for r in cursor.fetchall() or [] if isinstance(r, dict)]


def build_shift_timeline_rows(day_events: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = [_timeline_row_from_event(ev) for ev in day_events]
    rows.sort(
        key=lambda r: (
            r.get("timestamp_et") is None,
            r.get("timestamp_et") or datetime.min,
            int(r.get("scan_index") or 0),
            int(r.get("event_id") or 0),
        )
    )
    for idx, row in enumerate(rows, start=1):
        row["index"] = idx
    return rows


def _stage_dict(label: str, stage: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not stage or not isinstance(stage, dict):
        return None
    start = stage.get("start_time")
    end = stage.get("end_time")
    if not ts_valid(start) and not ts_valid(end):
        return None
    return {
        "stage": label,
        "start_et": start,
        "end_et": end,
        "duration_seconds": stage.get("duration_seconds"),
        "status": stage.get("status"),
        "assigned_user": stage.get("assigned_user_name") or stage.get("assigned_user"),
    }


def build_order_journey_for_bag(
    bag_id: str,
    all_events: Sequence[Mapping[str, Any]],
    day_events: Sequence[Mapping[str, Any]],
    *,
    day_start: datetime,
    day_end: datetime,
) -> dict[str, Any]:
    bid = str(bag_id or "").strip()
    day_rows = [_timeline_row_from_event(ev) for ev in day_events]
    day_ts = [r["timestamp_et"] for r in day_rows if ts_valid(r.get("timestamp_et"))]
    first_day = min(day_ts) if day_ts else None
    last_day = max(day_ts) if day_ts else None
    elapsed = _duration_seconds(first_day, last_day)

    perf = evaluate_bag_gaming_performance(list(all_events))
    washing_sec = _clip_duration_to_day(
        perf.get("load_washer", {}).get("start_time"),
        perf.get("in_washing", {}).get("end_time") or perf.get("load_washer", {}).get("end_time"),
        day_start=day_start,
        day_end=day_end,
    )
    if washing_sec == 0:
        washing_sec = _clip_duration_to_day(
            perf.get("wash_load", {}).get("start_time"),
            perf.get("wash_load", {}).get("end_time"),
            day_start=day_start,
            day_end=day_end,
        )
    drying_sec = _clip_duration_to_day(
        perf.get("load_dryer", {}).get("start_time") or perf.get("in_drying", {}).get("start_time"),
        perf.get("in_drying", {}).get("end_time") or perf.get("load_dryer", {}).get("end_time"),
        day_start=day_start,
        day_end=day_end,
    )

    stages: list[dict[str, Any]] = []
    for label, key in (
        ("weighing", "weighing"),
        ("sorting", "sorting"),
        ("washing", "wash_load"),
        ("drying", "in_drying"),
        ("folding", "folding"),
    ):
        st = _stage_dict(label, perf.get(key))
        if st:
            stages.append(st)

    employees = sorted({r.get("employee") for r in day_rows if r.get("employee")})

    return {
        "bag_id": bid,
        "first_activity_et": first_day,
        "last_activity_et": last_day,
        "elapsed_seconds": elapsed,
        "scan_count_on_day": len(day_rows),
        "employees_on_day": employees,
        "stages": stages,
        "washing_seconds_on_day": washing_sec,
        "drying_seconds_on_day": drying_sec,
    }


def _append_activity_block(
    blocks: list[dict[str, Any]],
    *,
    category: str | None,
    start: datetime | None,
    end: datetime | None,
    bag_ids: set[str],
    scan_count: int,
) -> None:
    blocks.append(
        {
            "category": category,
            "start_et": start,
            "end_et": end,
            "duration_seconds": _duration_seconds(start, end),
            "bag_ids": sorted(bag_ids),
            "scan_count": scan_count,
        }
    )


def build_employee_activity(
    timeline_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    by_employee: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in timeline_rows:
        emp = str(row.get("employee") or "").strip() or "Unknown"
        by_employee[emp].append(dict(row))

    result: list[dict[str, Any]] = []
    for employee in sorted(by_employee.keys(), key=lambda x: x.lower()):
        evs = sorted(
            by_employee[employee],
            key=lambda r: (
                r.get("timestamp_et") is None,
                r.get("timestamp_et") or datetime.min,
            ),
        )
        blocks: list[dict[str, Any]] = []
        gaps: list[dict[str, Any]] = []

        if evs:
            block_category = evs[0].get("activity_category")
            block_start = evs[0].get("timestamp_et")
            block_end = block_start
            block_bags: set[str] = set()
            block_scans = 0
            if evs[0].get("bag_id"):
                block_bags.add(str(evs[0]["bag_id"]))
            block_scans = 1

            for ev in evs[1:]:
                ts = ev.get("timestamp_et")
                cat = ev.get("activity_category")
                if cat == block_category:
                    block_end = ts
                    block_scans += 1
                    if ev.get("bag_id"):
                        block_bags.add(str(ev["bag_id"]))
                else:
                    _append_activity_block(
                        blocks,
                        category=block_category,
                        start=block_start,
                        end=block_end,
                        bag_ids=block_bags,
                        scan_count=block_scans,
                    )
                    if ts_valid(block_end) and ts_valid(ts):
                        gap_sec = max(int((ts - block_end).total_seconds()), 0)
                        if gap_sec > 0:
                            gaps.append(
                                {
                                    "after_block_index": len(blocks),
                                    "start_et": block_end,
                                    "end_et": ts,
                                    "duration_seconds": gap_sec,
                                }
                            )
                    block_category = cat
                    block_start = ts
                    block_end = ts
                    block_bags = {str(ev["bag_id"])} if ev.get("bag_id") else set()
                    block_scans = 1

            _append_activity_block(
                blocks,
                category=block_category,
                start=block_start,
                end=block_end,
                bag_ids=block_bags,
                scan_count=block_scans,
            )

        time_by_category: dict[str, int] = {c: 0 for c in ALL_ACTIVITY_CATEGORIES}
        for blk in blocks:
            cat = str(blk.get("category") or ACTIVITY_OTHER)
            if cat not in time_by_category:
                cat = ACTIVITY_OTHER
            time_by_category[cat] += int(blk.get("duration_seconds") or 0)

        result.append(
            {
                "employee": employee,
                "blocks": blocks,
                "idle_gaps": gaps,
                "time_by_category_seconds": time_by_category,
                "total_active_seconds": sum(time_by_category.values()),
                "total_idle_seconds": sum(int(g.get("duration_seconds") or 0) for g in gaps),
                "scan_count": len(evs),
            }
        )
    return result


def build_bag_detail(
    bag_id: str,
    all_events: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    bid = str(bag_id or "").strip()
    timeline = gaming_events_from_records(list(all_events))
    perf = evaluate_bag_gaming_performance(list(all_events))

    scan_history: list[dict[str, Any]] = []
    for ev in timeline:
        row = _timeline_row_from_event({**ev, "bag_id": bid})
        scan_history.append(
            {
                **row,
                "timestamp_et": event_ts(ev),
            }
        )

    processing_stages: list[dict[str, Any]] = []
    for label, key in (
        ("weighing", "weighing"),
        ("sorting", "sorting"),
        ("load_washer", "load_washer"),
        ("in_washing", "in_washing"),
        ("load_dryer", "load_dryer"),
        ("in_drying", "in_drying"),
        ("wash_load", "wash_load"),
        ("folding", "folding"),
    ):
        st = _stage_dict(label, perf.get(key))
        if st:
            processing_stages.append(st)

    return {
        "bag_id": bid,
        "scan_history": scan_history,
        "processing_timeline": processing_stages,
        "indicators": perf.get("indicators") or {},
    }


def build_operations_timeline_summary(
    timeline_rows: Sequence[Mapping[str, Any]],
    order_journeys: Sequence[Mapping[str, Any]],
    employee_activity: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if not timeline_rows:
        return {
            "first_activity_et": None,
            "last_activity_et": None,
            "total_active_orders": 0,
            "total_scans": 0,
            "total_sorting_seconds": 0,
            "total_washing_seconds": 0,
            "total_drying_seconds": 0,
            "total_folding_seconds": 0,
        }

    timestamps = [r["timestamp_et"] for r in timeline_rows if ts_valid(r.get("timestamp_et"))]
    bag_ids = {str(r.get("bag_id") or "").strip() for r in timeline_rows if r.get("bag_id")}

    cat_totals: dict[str, int] = {c: 0 for c in ALL_ACTIVITY_CATEGORIES}
    for emp_row in employee_activity:
        tbc = emp_row.get("time_by_category_seconds") or {}
        for cat, sec in tbc.items():
            if cat in cat_totals:
                cat_totals[cat] += int(sec or 0)

    washing_from_journeys = sum(int(j.get("washing_seconds_on_day") or 0) for j in order_journeys)
    drying_from_journeys = sum(int(j.get("drying_seconds_on_day") or 0) for j in order_journeys)

    return {
        "first_activity_et": min(timestamps) if timestamps else None,
        "last_activity_et": max(timestamps) if timestamps else None,
        "total_active_orders": len(bag_ids),
        "total_scans": len(timeline_rows),
        "total_sorting_seconds": cat_totals.get(ACTIVITY_SORTING, 0),
        "total_washing_seconds": max(cat_totals.get(ACTIVITY_WASHING, 0), washing_from_journeys),
        "total_drying_seconds": max(cat_totals.get(ACTIVITY_DRYING, 0), drying_from_journeys),
        "total_folding_seconds": cat_totals.get(ACTIVITY_FOLDING, 0),
    }


def build_operations_timeline_payload(
    cursor,
    organization_id: int,
    *,
    selected_date_et: date,
    view_filter: str | None = None,
    bag_id_filter: str | None = None,
) -> dict[str, Any]:
    from backend.rinse_shift_analysis import _load_scan_events_for_bags

    day_start = naive_et_day_start(selected_date_et)
    day_end = naive_et_day_end_inclusive(selected_date_et)

    day_events = _load_scan_events_on_day(cursor, int(organization_id), day_start, day_end)
    if bag_id_filter:
        bid = str(bag_id_filter).strip()
        day_events = [e for e in day_events if str(e.get("bag_id") or "").strip() == bid]

    bag_ids = sorted(
        {str(e.get("bag_id") or "").strip() for e in day_events if e.get("bag_id")}
    )
    events_by_bag = _load_scan_events_for_bags(cursor, int(organization_id), bag_ids)

    timeline_rows = build_shift_timeline_rows(day_events)
    employee_rows = build_employee_activity(timeline_rows)

    order_journeys: list[dict[str, Any]] = []
    for bid in bag_ids:
        bag_day = [e for e in day_events if str(e.get("bag_id") or "").strip() == bid]
        order_journeys.append(
            build_order_journey_for_bag(
                bid,
                events_by_bag.get(bid) or [],
                bag_day,
                day_start=day_start,
                day_end=day_end,
            )
        )
    order_journeys.sort(
        key=lambda j: (
            j.get("first_activity_et") is None,
            j.get("first_activity_et") or datetime.min,
            str(j.get("bag_id") or ""),
        )
    )

    summary = build_operations_timeline_summary(timeline_rows, order_journeys, employee_rows)

    bags_detail: dict[str, Any] = {}
    for bid in bag_ids:
        bags_detail[bid] = build_bag_detail(bid, events_by_bag.get(bid) or [])

    vf = str(view_filter or "").strip().lower()
    payload: dict[str, Any] = {
        "date_et": selected_date_et.isoformat(),
        "summary": summary,
        "bags": bags_detail,
        "activity_category_mapping": {
            ACTIVITY_WEIGHING: "weight-entry",
            ACTIVITY_SORTING: "add-photos, split-load, create-workitem/issue, cleaning (prep)",
            ACTIVITY_WASHING: "start-cleaning, ready-washer, washer-settings, complete-cleaning",
            ACTIVITY_DRYING: "drying",
            ACTIVITY_FOLDING: "quality-control-completed, assembly-printed-ct, Clean rack",
            ACTIVITY_OTHER: "all other scan purposes",
        },
    }

    include_all = vf not in ALL_VIEWS
    if include_all or vf == VIEW_SHIFT_TIMELINE:
        payload["shift_timeline"] = timeline_rows
    if include_all or vf == VIEW_ORDER_JOURNEY:
        payload["order_journeys"] = order_journeys
    if include_all or vf == VIEW_EMPLOYEE_ACTIVITY:
        payload["employee_activity"] = employee_rows

    return payload
