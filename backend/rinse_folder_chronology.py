"""
Read-only Folder chronology for Scan Chronology.

One session per bag per current vendor cycle:
  START = earliest Folder-start marker after lifecycle anchor
  END   = first Clean-rack scan after that start

Does not alter productivity, completion, PRE/POST, or import/merge.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping, Sequence

from backend.rinse_bag_completion import rack_contains_clean
from backend.rinse_bag_folding import rack_contains_folding
from backend.rinse_bag_stage_bounds import (
    event_ts,
    events_on_or_after,
    gaming_events_from_records,
    lifecycle_anchor_as_of,
    sort_key_ev,
    ts_valid,
)
from backend.rinse_folding_et import (
    naive_et_day_end_inclusive,
    naive_et_day_start,
    rinse_wall_calendar_date,
)
from backend.rinse_scan_purpose import (
    is_assembly_printed_ct_purpose,
    is_complete_cleaning_purpose,
    is_drying_purpose,
    is_quality_control_completed_purpose,
    is_weight_entry_purpose,
    normalize_scan_purpose,
)
from backend.ta_helpers import table_exists

STATUS_COMPLETE = "complete"
STATUS_INCOMPLETE_OPEN = "incomplete_open"
STATUS_INCOMPLETE_MISSING_START = "incomplete_missing_start"

FOLDER_EVENT_PURPOSES = [
    "complete-cleaning (Folding rack)",
    "garments-reviewed",
    "quality-control-completed",
    "folding rack activity",
    "Clean rack (end)",
]


def _operator(ev: Mapping[str, Any] | None) -> str | None:
    if ev is None:
        return None
    for key in ("user_name", "user", "User"):
        val = ev.get(key)
        if val:
            return str(val).strip() or None
    return None


def _duration_seconds(start: datetime | None, end: datetime | None) -> int | None:
    if not ts_valid(start) or not ts_valid(end):
        return None
    return max(int((end - start).total_seconds()), 0)


def _session_touches_date(
    start_at: datetime | None,
    end_at: datetime | None,
    selected: date,
) -> bool:
    if rinse_wall_calendar_date(start_at) == selected or rinse_wall_calendar_date(end_at) == selected:
        return True
    if start_at and end_at and ts_valid(start_at) and ts_valid(end_at):
        day_start = naive_et_day_start(selected)
        day_end = naive_et_day_end_inclusive(selected)
        return start_at <= day_end and end_at >= day_start
    return False


def is_folder_start_event(ev: Mapping[str, Any]) -> bool:
    """
    Canonical Folder START evidence.

    - complete-cleaning on a Folding rack (not dryer/other racks)
    - garments-reviewed
    - quality-control-completed
    - Folding-rack activity that is not a drying-purpose mis-tag
    """
    purpose = ev.get("purpose")
    rack = ev.get("rack")
    p = normalize_scan_purpose(purpose)

    if is_quality_control_completed_purpose(purpose):
        return True
    if "garments-reviewed" in p:
        return True
    if is_complete_cleaning_purpose(purpose) and rack_contains_folding(rack):
        return True
    if rack_contains_folding(rack) or p == "folding":
        # Drying stamped on a Folding rack is not Folder start by itself.
        if is_drying_purpose(purpose):
            return False
        return True
    return False


def is_folder_end_event(ev: Mapping[str, Any]) -> bool:
    """Canonical Folder END evidence: Clean rack scan."""
    return rack_contains_clean(ev.get("rack"))


def is_folder_day_activity_purpose_or_rack(purpose: str | None, rack: Any) -> bool:
    """Day-candidate filter for bags that may have Folder chronology on an ET day."""
    if is_folder_end_event({"rack": rack}):
        return True
    if is_folder_start_event({"purpose": purpose, "rack": rack}):
        return True
    if is_assembly_printed_ct_purpose(purpose):
        return True
    return False


def _weight_after_start(
    anchored: Sequence[Mapping[str, Any]],
    *,
    start_ts: datetime | None,
    end_ts: datetime | None,
) -> float | None:
    """Prefer weight-entry at/after start and at/before end (POST finish weight)."""
    best: tuple[datetime, float] | None = None
    for ev in anchored:
        if not is_weight_entry_purpose(ev.get("purpose")):
            continue
        ts = event_ts(ev)
        if not ts_valid(ts):
            continue
        if start_ts and ts_valid(start_ts) and ts < start_ts:
            continue
        if end_ts and ts_valid(end_ts) and ts > end_ts:
            continue
        raw = ev.get("weight_lbs")
        if raw is None:
            continue
        try:
            lbs = float(raw)
        except (TypeError, ValueError):
            continue
        if best is None or ts >= best[0]:
            best = (ts, lbs)
    return best[1] if best else None


def extract_folder_session_for_bag(
    bag_id: str,
    events: Sequence[Mapping[str, Any]],
    *,
    selected_date_et: date,
) -> dict[str, Any] | None:
    """
    Build at most one Folder session for the bag's current cycle relative to the
    selected ET day end.
    """
    bid = str(bag_id or "").strip()
    if not bid:
        return None

    timeline = gaming_events_from_records(events)
    if not timeline:
        return None

    day_end = naive_et_day_end_inclusive(selected_date_et)
    # Ignore scans after the selected day when choosing the cycle anchor.
    as_of_timeline = [
        ev
        for ev in timeline
        if ts_valid(event_ts(ev)) and event_ts(ev) <= day_end
    ]
    anchor_ts, _ = lifecycle_anchor_as_of(as_of_timeline or timeline, as_of_end=day_end)
    anchored = events_on_or_after(as_of_timeline or timeline, anchor_ts)
    if not anchored:
        return None

    start_candidates = [ev for ev in anchored if is_folder_start_event(ev)]
    start_ev = min(start_candidates, key=sort_key_ev) if start_candidates else None
    start_ts = event_ts(start_ev) if start_ev else None

    end_ev = None
    end_ts = None
    if start_ev and ts_valid(start_ts):
        for ev in anchored:
            if not is_folder_end_event(ev):
                continue
            ts = event_ts(ev)
            if not ts_valid(ts) or ts < start_ts:
                continue
            end_ev = ev
            end_ts = ts
            break
    else:
        # Missing start: still surface Clean-rack evidence on the selected day.
        clean_on_day = []
        for ev in anchored:
            if not is_folder_end_event(ev):
                continue
            ts = event_ts(ev)
            if ts_valid(ts) and rinse_wall_calendar_date(ts) == selected_date_et:
                clean_on_day.append(ev)
        if clean_on_day:
            end_ev = min(clean_on_day, key=sort_key_ev)
            end_ts = event_ts(end_ev)

    if not start_ev and not end_ev:
        return None
    if not _session_touches_date(start_ts, end_ts, selected_date_et):
        return None

    if start_ev and end_ev:
        status = STATUS_COMPLETE
        confidence = "exact"
    elif start_ev and not end_ev:
        status = STATUS_INCOMPLETE_OPEN
        confidence = "inferred"
    else:
        status = STATUS_INCOMPLETE_MISSING_START
        confidence = "inferred"

    employee = _operator(end_ev) or _operator(start_ev)
    start_purpose = normalize_scan_purpose(start_ev.get("purpose")) if start_ev else None
    end_purpose = normalize_scan_purpose(end_ev.get("purpose")) if end_ev else None
    start_rack = str(start_ev.get("rack") or "").strip() or None if start_ev else None
    end_rack = str(end_ev.get("rack") or "").strip() or None if end_ev else None

    source_bits = []
    if start_purpose:
        source_bits.append(start_purpose + (f"@{start_rack}" if start_rack else ""))
    else:
        source_bits.append("missing-start")
    if end_purpose:
        source_bits.append(end_purpose + (f"@{end_rack}" if end_rack else ""))
    else:
        source_bits.append("open")
    source = " → ".join(source_bits)

    weight_lbs = _weight_after_start(anchored, start_ts=start_ts, end_ts=end_ts)

    return {
        "bag_id": bid,
        "employee": employee,
        "folder_start_et": start_ts,
        "folder_end_et": end_ts,
        "duration_seconds": _duration_seconds(start_ts, end_ts),
        "status": status,
        "confidence": confidence,
        "source": source,
        "start_event_purpose": start_purpose,
        "end_event_purpose": end_purpose,
        "start_rack": start_rack,
        "end_rack": end_rack,
        "start_scan_event_id": start_ev.get("id") if start_ev else None,
        "end_scan_event_id": end_ev.get("id") if end_ev else None,
        "weight_lbs": weight_lbs,
        "cycle_anchor_et": anchor_ts,
    }


def chronology_rows_with_gaps(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(
        sessions,
        key=lambda s: (
            s.get("folder_start_et") is None and s.get("folder_end_et") is None,
            s.get("folder_start_et") or s.get("folder_end_et") or datetime.min,
            str(s.get("bag_id") or ""),
        ),
    )
    rows: list[dict[str, Any]] = []
    for idx, sess in enumerate(ordered):
        row = dict(sess)
        row["index"] = idx + 1
        next_start = None
        gap_seconds = None
        if idx + 1 < len(ordered):
            next_sess = ordered[idx + 1]
            next_start = next_sess.get("folder_start_et") or next_sess.get("folder_end_et")
            end_at = row.get("folder_end_et") or row.get("folder_start_et")
            if ts_valid(end_at) and ts_valid(next_start):
                gap_seconds = max(int((next_start - end_at).total_seconds()), 0)
        row["next_folder_start_et"] = next_start
        row["gap_until_next_seconds"] = gap_seconds
        rows.append(row)
    return rows


def build_folder_chronology_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "first_folder_start_et": None,
            "last_folder_end_et": None,
            "total_sessions": 0,
            "complete_sessions": 0,
            "incomplete_sessions": 0,
            "total_folder_seconds": 0,
            "total_gap_seconds": 0,
            "average_folder_duration_seconds": None,
        }

    starts = [r["folder_start_et"] for r in rows if ts_valid(r.get("folder_start_et"))]
    ends = [r["folder_end_et"] for r in rows if ts_valid(r.get("folder_end_et"))]
    complete = sum(1 for r in rows if r.get("status") == STATUS_COMPLETE)
    incomplete = len(rows) - complete
    durations = [
        int(r["duration_seconds"])
        for r in rows
        if r.get("duration_seconds") is not None and r.get("status") == STATUS_COMPLETE
    ]
    total_dur = sum(durations)
    gaps = [
        r.get("gap_until_next_seconds")
        for r in rows
        if r.get("gap_until_next_seconds") is not None
    ]
    total_gap = sum(int(g) for g in gaps)
    avg_dur = round(total_dur / len(durations), 2) if durations else None
    return {
        "first_folder_start_et": min(starts) if starts else None,
        "last_folder_end_et": max(ends) if ends else None,
        "total_sessions": len(rows),
        "complete_sessions": complete,
        "incomplete_sessions": incomplete,
        "total_folder_seconds": total_dur,
        "total_gap_seconds": total_gap,
        "average_folder_duration_seconds": avg_dur,
    }


def _load_bag_ids_with_folder_activity_on_day(
    cursor,
    organization_id: int,
    day_start: datetime,
    day_end: datetime,
) -> list[str]:
    if not table_exists(cursor, "rinse_bag_scan_events"):
        return []
    cursor.execute(
        """
        SELECT bag_id, purpose, rack
        FROM rinse_bag_scan_events
        WHERE organization_id = %s
          AND scanned_at_parsed >= %s
          AND scanned_at_parsed <= %s
        """,
        (int(organization_id), day_start, day_end),
    )
    bag_ids: set[str] = set()
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            continue
        if is_folder_day_activity_purpose_or_rack(row.get("purpose"), row.get("rack")):
            bid = str(row.get("bag_id") or "").strip()
            if bid:
                bag_ids.add(bid)
    return sorted(bag_ids)


def _load_scan_events_for_folder_bags(
    cursor,
    organization_id: int,
    bag_ids: list[str],
) -> dict[str, list[dict[str, Any]]]:
    """Full bag timelines (incl. weight) for cycle-safe Folder session building."""
    org = int(organization_id)
    out: dict[str, list[dict[str, Any]]] = {bid: [] for bid in bag_ids if bid}
    if not bag_ids or not table_exists(cursor, "rinse_bag_scan_events"):
        return out
    chunk = 100
    for i in range(0, len(bag_ids), chunk):
        part = [b for b in bag_ids[i : i + chunk] if b]
        if not part:
            continue
        placeholders = ",".join(["%s"] * len(part))
        cursor.execute(
            f"""
            SELECT bag_id, id, rack, user_name, purpose, scanned_at_parsed, scan_index,
                   weight_lbs, weight_role
            FROM rinse_bag_scan_events
            WHERE organization_id = %s AND bag_id IN ({placeholders})
            ORDER BY bag_id, scanned_at_parsed, scan_index, id
            """,
            (org, *part),
        )
        for row in cursor.fetchall() or []:
            if not isinstance(row, dict):
                continue
            bid = str(row.get("bag_id") or "").strip()
            if bid:
                out.setdefault(bid, []).append(row)
    return out

def build_folder_chronology_payload(
    cursor,
    organization_id: int,
    *,
    selected_date_et: date,
    employee_filter: str | None = None,
    bag_id_filter: str | None = None,
    confidence_filter: str | None = None,
    machine_filter: str | None = None,
) -> dict[str, Any]:
    del machine_filter  # Folder sessions are bag/employee scoped, not machine util.

    day_start = naive_et_day_start(selected_date_et)
    day_end = naive_et_day_end_inclusive(selected_date_et)

    bag_ids = _load_bag_ids_with_folder_activity_on_day(
        cursor, organization_id, day_start, day_end
    )
    if bag_id_filter:
        bid = str(bag_id_filter).strip()
        bag_ids = [bid] if bid in bag_ids else ([bid] if bid else [])

    events_by_bag = _load_scan_events_for_folder_bags(
        cursor, int(organization_id), bag_ids
    )

    sessions: list[dict[str, Any]] = []
    for bid in bag_ids:
        sess = extract_folder_session_for_bag(
            bid,
            events_by_bag.get(bid) or [],
            selected_date_et=selected_date_et,
        )
        if sess:
            sessions.append(sess)

    if employee_filter:
        needle = str(employee_filter).strip().lower()
        sessions = [
            s
            for s in sessions
            if needle and str(s.get("employee") or "").strip().lower() == needle
        ]

    if confidence_filter:
        cf = str(confidence_filter).strip().lower()
        if cf in ("exact", "inferred"):
            sessions = [s for s in sessions if s.get("confidence") == cf]

    rows = chronology_rows_with_gaps(sessions)
    summary = build_folder_chronology_summary(rows)
    employees = sorted(
        {str(s.get("employee") or "").strip() for s in rows if s.get("employee")},
        key=lambda name: name.casefold(),
    )

    return {
        "date_et": selected_date_et.isoformat(),
        "stage": "folder",
        "summary": summary,
        "sessions": rows,
        "employees": employees,
        "machines": [],
        "event_purposes": FOLDER_EVENT_PURPOSES,
        "grouping_rules": (
            "One Folder session per bag per current sent-to-vendor cycle. "
            "Start = earliest garments-reviewed, quality-control-completed, "
            "complete-cleaning on a Folding rack, or other Folding-rack activity "
            "(excluding drying-only mis-tags). "
            "End = first Clean-rack scan after start. "
            "Intermediate assembly-printed-ct / add-photos are not separate sessions. "
            "Open sessions keep start without inventing an end; Clean without start "
            "is incomplete_missing_start."
        ),
    }
