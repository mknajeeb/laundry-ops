"""
Read-only post-processing weight chronology for Shift Analysis.

One row per WF post-processing weight-entry (completion weigh after processing).
Does not alter productivity, completion, or payroll logic.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping, Sequence

from backend.rinse_bag_stage_bounds import event_ts, gaming_events_from_records, lifecycle_anchor, ts_valid
from backend.rinse_employee_completed_bags import _wf_completion_weight_event
from backend.rinse_folding_et import naive_et_day_end_inclusive, naive_et_day_start
from backend.rinse_scan_purpose import is_weight_entry_purpose
from backend.rinse_wf_weight_events import WF_POST_PROCESSING_WEIGHT_SIGNAL
from backend.ta_helpers import table_exists


def _operator(ev: Mapping[str, Any] | None) -> str | None:
    if ev is None:
        return None
    for key in ("user_name", "user", "User"):
        val = ev.get(key)
        if val:
            return str(val).strip() or None
    return None


def extract_post_processing_weight_rows_from_events(
    events: Sequence[Mapping[str, Any]],
    *,
    day_start: datetime,
    day_end: datetime,
) -> list[dict[str, Any]]:
    """One row per bag whose post-processing weight completion falls on the ET day."""
    by_bag: dict[str, list[dict[str, Any]]] = {}
    for ev in events:
        if not isinstance(ev, Mapping):
            continue
        bid = str(ev.get("bag_id") or "").strip().upper()
        if not bid:
            continue
        by_bag.setdefault(bid, []).append(dict(ev))

    rows: list[dict[str, Any]] = []
    for bid, bag_events in by_bag.items():
        timeline = gaming_events_from_records(bag_events)
        anchor, _ = lifecycle_anchor(timeline)
        if anchor is None:
            continue
        weight_ev, comp_ts = _wf_completion_weight_event(
            timeline, anchor_ts=anchor, as_of_end=day_end
        )
        if weight_ev is None or not ts_valid(comp_ts):
            continue
        if comp_ts < day_start or comp_ts > day_end:
            continue
        employee = _operator(weight_ev)
        rows.append(
            {
                "bag_id": bid,
                "employee": employee,
                "timestamp_et": comp_ts,
                "confidence": "exact" if employee else "inferred",
                "event_purpose": WF_POST_PROCESSING_WEIGHT_SIGNAL,
                "scan_event_id": weight_ev.get("id"),
            }
        )

    rows.sort(
        key=lambda r: (
            r.get("timestamp_et") is None,
            r.get("timestamp_et") or datetime.min,
            str(r.get("bag_id") or ""),
        ),
    )
    for idx, row in enumerate(rows):
        row["index"] = idx + 1
    return rows


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
        SELECT bag_id, id, rack, user_name, purpose, scanned_at_parsed, scan_index,
               last_location, last_scan, raw_json
        FROM rinse_bag_scan_events
        WHERE organization_id = %s
          AND scanned_at_parsed >= %s
          AND scanned_at_parsed <= %s
        ORDER BY scanned_at_parsed, scan_index, id
        """,
        (int(organization_id), day_start, day_end),
    )
    return [dict(r) for r in cursor.fetchall() or [] if isinstance(r, dict)]


def _load_scan_events_for_bags(
    cursor,
    organization_id: int,
    bag_ids: Sequence[str],
) -> list[dict[str, Any]]:
    if not bag_ids or not table_exists(cursor, "rinse_bag_scan_events"):
        return []
    org = int(organization_id)
    out: list[dict[str, Any]] = []
    chunk = 100
    ids = sorted({str(b).strip().upper() for b in bag_ids if str(b).strip()})
    for i in range(0, len(ids), chunk):
        part = ids[i : i + chunk]
        placeholders = ",".join(["%s"] * len(part))
        cursor.execute(
            f"""
            SELECT bag_id, id, rack, user_name, purpose, scanned_at_parsed, scan_index,
                   last_location, last_scan, raw_json
            FROM rinse_bag_scan_events
            WHERE organization_id = %s
              AND bag_id IN ({placeholders})
            ORDER BY bag_id, scanned_at_parsed, scan_index, id
            """,
            (org, *part),
        )
        out.extend(dict(r) for r in cursor.fetchall() or [] if isinstance(r, dict))
    return out


def build_post_processing_weight_chronology_payload(
    cursor,
    organization_id: int,
    *,
    selected_date_et: date,
    employee_filter: str | None = None,
    bag_id_filter: str | None = None,
    confidence_filter: str | None = None,
) -> dict[str, Any]:
    day_start = naive_et_day_start(selected_date_et)
    day_end = naive_et_day_end_inclusive(selected_date_et)
    events_on_day = _load_scan_events_on_day(cursor, organization_id, day_start, day_end)
    weight_bags = sorted(
        {
            str(ev.get("bag_id") or "").strip().upper()
            for ev in events_on_day
            if is_weight_entry_purpose(ev.get("purpose")) and str(ev.get("bag_id") or "").strip()
        }
    )
    full_events = _load_scan_events_for_bags(cursor, organization_id, weight_bags)
    rows = extract_post_processing_weight_rows_from_events(
        full_events, day_start=day_start, day_end=day_end
    )

    employees = sorted(
        {str(r.get("employee") or "").strip() for r in rows if r.get("employee")},
        key=lambda name: name.casefold(),
    )

    if bag_id_filter:
        bid = str(bag_id_filter).strip().upper()
        rows = [r for r in rows if str(r.get("bag_id") or "").strip().upper() == bid]

    if employee_filter:
        needle = str(employee_filter).strip().lower()
        rows = [
            r
            for r in rows
            if needle and str(r.get("employee") or "").strip().lower() == needle
        ]

    if confidence_filter:
        cf = str(confidence_filter).strip().lower()
        if cf in ("exact", "inferred"):
            rows = [r for r in rows if r.get("confidence") == cf]

    for idx, row in enumerate(rows):
        row["index"] = idx + 1

    timestamps = [r["timestamp_et"] for r in rows if ts_valid(r.get("timestamp_et"))]
    summary = {
        "total_post_processing_weights": len(rows),
        "unique_employees": len(employees),
        "first_weight_et": min(timestamps) if timestamps else None,
        "last_weight_et": max(timestamps) if timestamps else None,
    }

    return {
        "date_et": selected_date_et.isoformat(),
        "stage": "post_processing_weight",
        "summary": summary,
        "sessions": rows,
        "employees": employees,
        "machines": [],
        "event_purposes": [WF_POST_PROCESSING_WEIGHT_SIGNAL],
        "grouping_rules": (
            "One row per WF post-processing weight-entry scan (completion weigh after "
            "the latest processing step); uses the same post_processing_weight rule as "
            "employee bag attribution."
        ),
    }
