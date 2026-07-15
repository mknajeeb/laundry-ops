"""
Read-only washing chronology for Shift Analysis.

One row per start-cleaning scan (split orders may produce multiple rows).
W-prefix washer racks on the start-cleaning scan are exact; otherwise the row
is still shown (inferred), including facility locations like VeeWash Clean.
Optional same-bag washer-settings inference may fill a W rack for display only.
Does not alter productivity, completion, or payroll logic.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta
from typing import Any, Mapping, Sequence

from backend.rinse_bag_stage_bounds import event_ts, ts_valid
from backend.rinse_folding_et import naive_et_day_end_inclusive, naive_et_day_start
from backend.rinse_machine_rack import (
    cap_machine_load_rows_per_bag,
    dedupe_machine_load_rows,
    dedupe_scan_events_by_id,
    extract_washer_rack,
    is_washer_rack_code,
    normalize_rack_code,
)
from backend.rinse_scan_purpose import (
    is_start_cleaning_purpose,
    is_washer_settings_purpose,
    normalize_scan_purpose,
)
from backend.ta_helpers import table_exists


MAX_WASHING_START_CLEANING_ROWS_PER_BAG = 2
# Display-only: fill a W rack from same-bag washer-settings shortly after start-cleaning.
WASHER_SETTINGS_INFER_WINDOW = timedelta(minutes=15)


def _operator(ev: Mapping[str, Any] | None) -> str | None:
    if ev is None:
        return None
    for key in ("user_name", "user", "User"):
        val = ev.get(key)
        if val:
            return str(val).strip() or None
    return None


def _event_confidence(ev: Mapping[str, Any], *, rack: str | None) -> str:
    employee = _operator(ev)
    if (
        employee
        and rack
        and is_washer_rack_code(rack)
        and is_start_cleaning_purpose(ev.get("purpose"))
    ):
        return "exact"
    return "inferred"


def _next_start_cleaning_ts(
    start_ev: Mapping[str, Any],
    all_events: Sequence[Mapping[str, Any]],
) -> datetime | None:
    bag = str(start_ev.get("bag_id") or "").strip()
    start_ts = event_ts(start_ev)
    if not bag or not ts_valid(start_ts):
        return None
    next_ts: datetime | None = None
    for ev in all_events:
        if str(ev.get("bag_id") or "").strip() != bag:
            continue
        if not is_start_cleaning_purpose(ev.get("purpose")):
            continue
        ts = event_ts(ev)
        if not ts_valid(ts) or ts <= start_ts:
            continue
        if next_ts is None or ts < next_ts:
            next_ts = ts
    return next_ts


def _infer_washer_rack_from_nearby(
    start_ev: Mapping[str, Any],
    all_events: Sequence[Mapping[str, Any]],
) -> str | None:
    """
    Same-bag washer-settings with a W-prefix rack shortly after this start-cleaning.

    Never borrows a W rack from a later separate start-cleaning load.
    """
    bag = str(start_ev.get("bag_id") or "").strip()
    start_ts = event_ts(start_ev)
    if not bag or not ts_valid(start_ts):
        return None
    window_end = start_ts + WASHER_SETTINGS_INFER_WINDOW
    next_start = _next_start_cleaning_ts(start_ev, all_events)
    if next_start is not None and next_start < window_end:
        window_end = next_start
    best: tuple[datetime, str] | None = None
    for ev in all_events:
        if str(ev.get("bag_id") or "").strip() != bag:
            continue
        if not is_washer_settings_purpose(ev.get("purpose")):
            continue
        rack = extract_washer_rack(ev)
        if not rack:
            continue
        ts = event_ts(ev)
        if not ts_valid(ts) or ts < start_ts or ts >= window_end:
            continue
        if best is None or ts < best[0]:
            best = (ts, rack)
    return best[1] if best else None


def washing_rows_with_washer_rack(
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """
    Physical W-prefix washer loads only.

    Inferred chronology rows (VeeWash Clean / borrowed washer-settings) are
    display-only and must not feed Supply Usage or Washer Utilization.
    """
    out: list[dict[str, Any]] = []
    for row in rows:
        rack = row.get("washer_rack")
        if is_washer_rack_code(rack) and row.get("confidence") == "exact":
            out.append(dict(row))
    return out


def extract_washing_rows_from_events(
    events: Sequence[Mapping[str, Any]],
    *,
    require_direct_washer_rack: bool = False,
) -> list[dict[str, Any]]:
    """
    Build washing chronology rows from start-cleaning scans.

    By default every start-cleaning is kept. Pass
    ``require_direct_washer_rack=True`` for Supply Usage (W-prefix on the
    start-cleaning scan only — legacy physical-load counting).
    """
    rows: list[dict[str, Any]] = []
    cleaning_events = [
        ev for ev in events if is_start_cleaning_purpose(ev.get("purpose"))
    ]
    for ev in dedupe_scan_events_by_id(cleaning_events):
        ts = event_ts(ev)
        if not ts_valid(ts):
            continue
        direct_washer = extract_washer_rack(ev)
        if direct_washer:
            rack = direct_washer
            confidence = _event_confidence(ev, rack=rack)
        elif require_direct_washer_rack:
            continue
        else:
            rack = (
                _infer_washer_rack_from_nearby(ev, events)
                or normalize_rack_code(ev.get("rack"))
            )
            confidence = "inferred"
        rows.append(
            {
                "scan_event_id": ev.get("id"),
                "bag_id": str(ev.get("bag_id") or "").strip(),
                "employee": _operator(ev),
                "timestamp_et": ts,
                "washer_rack": rack,
                "confidence": confidence,
                "event_purpose": normalize_scan_purpose(ev.get("purpose")),
            }
        )
    rows = dedupe_machine_load_rows(rows)
    rows = cap_machine_load_rows_per_bag(
        rows,
        max_per_bag=MAX_WASHING_START_CLEANING_ROWS_PER_BAG,
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


def build_washing_chronology_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "total_washer_loads": 0,
            "unique_bags_washed": 0,
            "split_bags_washed": 0,
            "single_bags_washed": 0,
            "unique_bag_ids": 0,
            "unique_washers_used": 0,
            "most_used_washer": None,
            "first_washer_load_et": None,
            "last_washer_load_et": None,
        }
    # Physical washer stats exclude inferred display-only machine fills.
    racks = [
        r.get("washer_rack")
        for r in rows
        if is_washer_rack_code(r.get("washer_rack")) and r.get("confidence") == "exact"
    ]
    bag_load_counts = Counter(
        str(r.get("bag_id") or "").strip()
        for r in rows
        if str(r.get("bag_id") or "").strip()
    )
    unique_bags_washed = len(bag_load_counts)
    split_bags_washed = sum(1 for count in bag_load_counts.values() if count > 1)
    single_bags_washed = sum(1 for count in bag_load_counts.values() if count == 1)
    counts = Counter(racks)
    timestamps = [r["timestamp_et"] for r in rows if ts_valid(r.get("timestamp_et"))]
    return {
        "total_washer_loads": len(rows),
        "unique_bags_washed": unique_bags_washed,
        "split_bags_washed": split_bags_washed,
        "single_bags_washed": single_bags_washed,
        "unique_bag_ids": unique_bags_washed,
        "unique_washers_used": len(set(racks)),
        "most_used_washer": counts.most_common(1)[0][0] if counts else None,
        "first_washer_load_et": min(timestamps) if timestamps else None,
        "last_washer_load_et": max(timestamps) if timestamps else None,
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


def build_washing_chronology_payload(
    cursor,
    organization_id: int,
    *,
    selected_date_et: date,
    employee_filter: str | None = None,
    bag_id_filter: str | None = None,
    confidence_filter: str | None = None,
    machine_filter: str | None = None,
) -> dict[str, Any]:
    day_start = naive_et_day_start(selected_date_et)
    day_end = naive_et_day_end_inclusive(selected_date_et)
    events = _load_scan_events_on_day(cursor, organization_id, day_start, day_end)

    rows = extract_washing_rows_from_events(events)

    employees = sorted(
        {str(r.get("employee") or "").strip() for r in rows if r.get("employee")},
        key=lambda name: name.casefold(),
    )
    machines = sorted(
        {
            str(r.get("washer_rack") or "").strip()
            for r in rows
            if is_washer_rack_code(r.get("washer_rack"))
            and r.get("confidence") == "exact"
        },
        key=lambda name: name.casefold(),
    )

    if bag_id_filter:
        bid = str(bag_id_filter).strip()
        rows = [r for r in rows if str(r.get("bag_id") or "").strip() == bid]

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

    if machine_filter:
        mf = str(machine_filter).strip()
        rows = [r for r in rows if str(r.get("washer_rack") or "").strip() == mf]

    # Re-index after filters.
    for idx, row in enumerate(rows):
        row["index"] = idx + 1

    summary = build_washing_chronology_summary(rows)

    return {
        "date_et": selected_date_et.isoformat(),
        "stage": "washing",
        "summary": summary,
        "sessions": rows,
        "employees": employees,
        "machines": machines,
        "event_purposes": ["start-cleaning"],
        "grouping_rules": (
            "One row per start-cleaning scan; W-prefix on the start-cleaning scan is "
            "exact; otherwise the row is kept as inferred (facility location such as "
            "VeeWash Clean, or a same-bag washer-settings W rack within 15 minutes "
            "before the next start-cleaning on that bag); duplicate ingest with the "
            "same event id or same bag, employee, timestamp, and rack collapse to one "
            "row; split loads at the same timestamp with different washer racks "
            "produce separate rows; at most two start-cleaning loads per bag per day "
            "(earliest two by time)."
        ),
    }


def build_washer_utilization_payload(
    cursor,
    organization_id: int,
    *,
    selected_date_et: date,
    employee_filter: str | None = None,
    bag_id_filter: str | None = None,
    confidence_filter: str | None = None,
    machine_filter: str | None = None,
) -> dict[str, Any]:
    washing = build_washing_chronology_payload(
        cursor,
        organization_id,
        selected_date_et=selected_date_et,
        employee_filter=employee_filter,
        bag_id_filter=bag_id_filter,
        confidence_filter=confidence_filter,
        machine_filter=machine_filter,
    )
    # Utilization is unchanged: exact W-prefix assignments only (inferred display-only).
    util_source = washing_rows_with_washer_rack(washing.get("sessions") or [])
    util_rows: list[dict[str, Any]] = []
    for idx, row in enumerate(util_source):
        util_rows.append(
            {
                "index": idx + 1,
                "timestamp_et": row.get("timestamp_et"),
                "machine": row.get("washer_rack"),
                "employee": row.get("employee"),
                "bag_id": row.get("bag_id"),
            }
        )
    util_employees = sorted(
        {
            str(r.get("employee") or "").strip()
            for r in util_rows
            if r.get("employee")
        },
        key=lambda name: name.casefold(),
    )
    util_machines = sorted(
        {
            str(r.get("machine") or "").strip()
            for r in util_rows
            if r.get("machine")
        },
        key=lambda name: name.casefold(),
    )
    util_summary = {
        "total_loads": len(util_rows),
        "unique_machines_used": len(util_machines),
        "most_used_machine": (
            Counter(
                str(r.get("machine") or "").strip()
                for r in util_rows
                if r.get("machine")
            ).most_common(1)[0][0]
            if util_rows
            else None
        ),
        "first_load_et": min(
            (r["timestamp_et"] for r in util_rows if ts_valid(r.get("timestamp_et"))),
            default=None,
        ),
        "last_load_et": max(
            (r["timestamp_et"] for r in util_rows if ts_valid(r.get("timestamp_et"))),
            default=None,
        ),
    }
    return {
        "date_et": washing.get("date_et"),
        "stage": "washer_utilization",
        "summary": util_summary,
        "sessions": util_rows,
        "employees": util_employees,
        "machines": util_machines,
        "grouping_rules": (
            "Chronological washer utilization from start-cleaning scans at washer rack codes; "
            "one utilization row per washer load scan."
        ),
    }
