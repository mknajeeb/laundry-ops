"""
Read-only sorting chronology for Shift Analysis.

Builds a time-ordered timeline of sorting sessions from rinse_bag_scan_events.
Does not alter productivity calculations or bag completion logic.

Session grouping:
- One session per post-anchor sort cycle, keyed by each add-photos completion marker.
- Uses the last weight-entry before that add-photos (not every intermediate weight scan).
- Bounds reuse sorting_bounds_v2 (same as activity credits / performance sorting stage).
- Sort start is attributed to the add-photos employee's cleaning/weight, not another employee's weight.
- Sessions overlapping other bags sorted by the same employee push sort_start forward.
- Sessions are ordered globally by sort_start_et; gap_until_next is wall time to the next session start.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping, Sequence

from backend.rinse_bag_activity_rules import sorting_bounds_v2
from backend.rinse_bag_stage_bounds import (
    event_ts,
    events_on_or_after,
    first_start_cleaning_after,
    gaming_events_from_records,
    is_cleaning_purpose_for_activity_start,
    lifecycle_anchor,
    sort_key_ev,
    ts_valid,
)
from backend.rinse_folding_et import naive_et_day_end_inclusive, naive_et_day_start, rinse_wall_calendar_date
from backend.rinse_scan_purpose import (
    is_add_photos_purpose,
    is_lifecycle_sorting_progress_marker_purpose,
    is_weight_entry_purpose,
    normalize_scan_purpose,
)
from backend.ta_helpers import table_exists


def is_sorting_related_scan_purpose(raw: str | None) -> bool:
    """Scan purposes that indicate sorting workflow activity on the timeline."""
    if is_lifecycle_sorting_progress_marker_purpose(raw):
        return True
    if is_cleaning_purpose_for_activity_start(raw):
        return True
    return is_weight_entry_purpose(raw)


def _operator(ev: Mapping[str, Any] | None) -> str | None:
    if ev is None:
        return None
    for key in ("user_name", "user", "User"):
        val = ev.get(key)
        if val:
            return str(val).strip() or None
    return None


def _operators_match(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    return a.casefold() == b.casefold()


def _duration_seconds(start: datetime | None, end: datetime | None) -> int:
    if not ts_valid(start) or not ts_valid(end):
        return 0
    sec = int((end - start).total_seconds())
    return max(sec, 0)


def _session_confidence(
    sort_start_ev: Mapping[str, Any] | None,
    sort_end_ev: Mapping[str, Any] | None,
    *,
    start_cleaning_after_weight: bool,
) -> str:
    """exact when both bounds come from explicit sorting markers; otherwise inferred."""
    start_exact = sort_start_ev is not None and is_cleaning_purpose_for_activity_start(
        sort_start_ev.get("purpose")
    )
    end_exact = (
        start_cleaning_after_weight
        and sort_end_ev is not None
        and is_lifecycle_sorting_progress_marker_purpose(sort_end_ev.get("purpose"))
    )
    if start_exact and end_exact:
        return "exact"
    return "inferred"


def _session_source_label(
    sort_start_ev: Mapping[str, Any] | None,
    sort_end_ev: Mapping[str, Any] | None,
) -> str:
    start_p = normalize_scan_purpose(sort_start_ev.get("purpose")) if sort_start_ev else ""
    end_p = normalize_scan_purpose(sort_end_ev.get("purpose")) if sort_end_ev else ""
    if start_p and end_p:
        return f"{start_p} → {end_p}"
    return end_p or start_p or "unknown"


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


def _last_weight_before_ts(
    anchored: Sequence[Mapping[str, Any]],
    *,
    before_ts: datetime,
    employee: str | None = None,
) -> tuple[Mapping[str, Any], datetime] | None:
    """Most recent weight-entry strictly before *before_ts* (optionally same employee)."""
    last: tuple[Mapping[str, Any], datetime] | None = None
    for ev in anchored:
        if not is_weight_entry_purpose(ev.get("purpose")):
            continue
        ts = event_ts(ev)
        if not ts_valid(ts) or ts >= before_ts:
            continue
        if employee and not _operators_match(_operator(ev), employee):
            continue
        last = (ev, ts)
    return last


def _last_cleaning_before_ts_by_employee(
    timeline: Sequence[Mapping[str, Any]],
    *,
    before_ts: datetime,
    employee: str | None,
) -> tuple[Mapping[str, Any], datetime] | None:
    """Most recent cleaning/start-cleaning by *employee* strictly before *before_ts*."""
    if not employee:
        return None
    last: tuple[Mapping[str, Any], datetime] | None = None
    for ev in timeline:
        if not is_cleaning_purpose_for_activity_start(ev.get("purpose")):
            continue
        ts = event_ts(ev)
        if not ts_valid(ts) or ts >= before_ts:
            continue
        if not _operators_match(_operator(ev), employee):
            continue
        last = (ev, ts)
    return last


def _chronology_sort_start_for_employee(
    anchored: Sequence[Mapping[str, Any]],
    timeline: Sequence[Mapping[str, Any]],
    *,
    before_ts: datetime,
    sort_employee: str | None,
    bounds_start_ev: Mapping[str, Any] | None,
    bounds_start_ts: datetime | None,
) -> tuple[datetime, Mapping[str, Any] | None]:
    """
    Sort start for chronology mirrors productivity attribution: bound by the
    add-photos employee's own cleaning/weight before add-photos, not another
    employee's earlier weight on the same bag.
    """
    if not sort_employee:
        if ts_valid(bounds_start_ts):
            return bounds_start_ts, bounds_start_ev
        return before_ts, None

    emp_cleaning = _last_cleaning_before_ts_by_employee(
        timeline, before_ts=before_ts, employee=sort_employee
    )
    if emp_cleaning is not None:
        return emp_cleaning[1], emp_cleaning[0]

    emp_weight = _last_weight_before_ts(
        anchored, before_ts=before_ts, employee=sort_employee
    )
    if emp_weight is not None:
        return emp_weight[1], emp_weight[0]

    if bounds_start_ev is not None and _operators_match(
        _operator(bounds_start_ev), sort_employee
    ):
        return bounds_start_ts or before_ts, bounds_start_ev

    return before_ts, None


def _cap_sessions_by_employee_busy_periods(
    sessions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Push sort_start forward when the session employee was actively sorting other
    bags during the current window (inter-session overlap).
    """
    capped: list[dict[str, Any]] = []
    for sess in sessions:
        row = dict(sess)
        employee = str(row.get("employee") or "").strip()
        start_at = row.get("sort_start_et")
        end_at = row.get("sort_end_et")
        if not employee or not ts_valid(end_at):
            capped.append(row)
            continue
        if not ts_valid(start_at):
            capped.append(row)
            continue

        peer_busy_ends: list[datetime] = []
        peer_ends_before: list[datetime] = []
        for other in sessions:
            if other.get("bag_id") == row.get("bag_id"):
                continue
            if not _operators_match(str(other.get("employee") or "").strip(), employee):
                continue
            o_start = other.get("sort_start_et")
            o_end = other.get("sort_end_et")
            if not ts_valid(o_start) or not ts_valid(o_end):
                continue
            if o_end <= end_at:
                peer_ends_before.append(o_end)
            if o_start < end_at and o_end > start_at:
                if o_end <= end_at:
                    peer_busy_ends.append(o_end)

        capped_start = start_at
        if start_at >= end_at and peer_ends_before:
            capped_start = max(peer_ends_before)
        elif peer_busy_ends:
            capped_start = max(start_at, max(peer_busy_ends))

        if capped_start < end_at:
            row["sort_start_et"] = capped_start
            row["duration_seconds"] = _duration_seconds(capped_start, end_at)
        capped.append(row)
    return capped


def _same_scan_event(
    left: Mapping[str, Any] | None,
    right: Mapping[str, Any] | None,
) -> bool:
    """True when *left* and *right* refer to the same scan row (not just the same timestamp)."""
    if left is None or right is None:
        return False
    if left is right:
        return True
    left_id, right_id = left.get("id"), right.get("id")
    if left_id is not None and right_id is not None:
        return left_id == right_id
    return sort_key_ev(left) == sort_key_ev(right)


def _add_photos_events_after_anchor(
    anchored: Sequence[Mapping[str, Any]],
) -> list[tuple[Mapping[str, Any], datetime]]:
    out: list[tuple[Mapping[str, Any], datetime]] = []
    for ev in anchored:
        if not is_add_photos_purpose(ev.get("purpose")):
            continue
        ts = event_ts(ev)
        if ts_valid(ts):
            out.append((ev, ts))
    return out


def _dedupe_sessions_by_window(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per employee + bag + sort start/end window."""
    seen: set[tuple[Any, ...]] = set()
    out: list[dict[str, Any]] = []
    for sess in sessions:
        key = (
            sess.get("bag_id"),
            sess.get("employee"),
            sess.get("sort_start_et"),
            sess.get("sort_end_et"),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(sess)
    return out


def extract_sorting_sessions_for_bag(
    bag_id: str,
    events: Sequence[Mapping[str, Any]],
    *,
    selected_date_et: date,
) -> list[dict[str, Any]]:
    """All sorting sessions for one bag that touch selected_date_et."""
    bid = str(bag_id or "").strip()
    if not bid or not events:
        return []

    tl = gaming_events_from_records(events)
    anchor_ts, _ = lifecycle_anchor(tl)
    if anchor_ts is None:
        return []
    anchored = events_on_or_after(tl, anchor_ts)
    add_photos_events = _add_photos_events_after_anchor(anchored)
    if not add_photos_events:
        return []

    sessions: list[dict[str, Any]] = []
    for add_ev_iter, add_ts in add_photos_events:
        sort_employee = _operator(add_ev_iter)
        weight_pair = _last_weight_before_ts(anchored, before_ts=add_ts)
        if weight_pair is None:
            continue
        weight_ev, weight_ts = weight_pair

        add_ev, bounds_start_ev, sort_end_ev = sorting_bounds_v2(
            anchored, weight_ts, weight_ev, full_timeline=tl
        )
        if add_ev is None:
            continue
        # One session per sort cycle: only the canonical add-photos for this weight window.
        if not _same_scan_event(add_ev, add_ev_iter):
            continue

        bounds_start_ts = event_ts(bounds_start_ev) if bounds_start_ev else weight_ts
        start_at, sort_start_ev = _chronology_sort_start_for_employee(
            anchored,
            tl,
            before_ts=add_ts,
            sort_employee=sort_employee,
            bounds_start_ev=bounds_start_ev,
            bounds_start_ts=bounds_start_ts,
        )
        end_at = event_ts(sort_end_ev) if sort_end_ev else add_ts
        if not ts_valid(start_at):
            continue
        if not ts_valid(end_at):
            end_at = start_at

        if not _session_touches_date(start_at, end_at, selected_date_et):
            continue

        sc_after = first_start_cleaning_after(anchored, after_ts=weight_ts) is not None
        confidence = _session_confidence(sort_start_ev, sort_end_ev, start_cleaning_after_weight=sc_after)
        employee = sort_employee or _operator(add_ev) or _operator(sort_end_ev) or _operator(sort_start_ev)

        sessions.append(
            {
                "bag_id": bid,
                "employee": employee,
                "sort_start_et": start_at,
                "sort_end_et": end_at,
                "duration_seconds": _duration_seconds(start_at, end_at),
                "confidence": confidence,
                "source": _session_source_label(sort_start_ev, sort_end_ev),
                "end_event_purpose": normalize_scan_purpose(sort_end_ev.get("purpose")) if sort_end_ev else None,
            }
        )
    return _dedupe_sessions_by_window(sessions)


def chronology_rows_with_gaps(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort sessions by start time and attach next_sort_start + gap_until_next."""
    ordered = sorted(
        sessions,
        key=lambda s: (
            s.get("sort_start_et") is None,
            s.get("sort_start_et") or datetime.min,
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
            next_start = next_sess.get("sort_start_et")
            end_at = row.get("sort_end_et")
            if ts_valid(end_at) and ts_valid(next_start):
                gap_seconds = max(int((next_start - end_at).total_seconds()), 0)
        row["next_sort_start_et"] = next_start
        row["gap_until_next_seconds"] = gap_seconds
        rows.append(row)
    return rows


def build_sorting_chronology_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "first_sort_start_et": None,
            "last_sort_end_et": None,
            "total_sessions": 0,
            "total_sorting_seconds": 0,
            "total_gap_seconds": 0,
            "average_sort_duration_seconds": None,
        }

    starts = [r["sort_start_et"] for r in rows if ts_valid(r.get("sort_start_et"))]
    ends = [r["sort_end_et"] for r in rows if ts_valid(r.get("sort_end_et"))]
    total_dur = sum(int(r.get("duration_seconds") or 0) for r in rows)
    gaps = [r.get("gap_until_next_seconds") for r in rows if r.get("gap_until_next_seconds") is not None]
    total_gap = sum(int(g) for g in gaps)

    avg_dur = round(total_dur / len(rows), 2) if rows else None
    return {
        "first_sort_start_et": min(starts) if starts else None,
        "last_sort_end_et": max(ends) if ends else None,
        "total_sessions": len(rows),
        "total_sorting_seconds": total_dur,
        "total_gap_seconds": total_gap,
        "average_sort_duration_seconds": avg_dur,
    }


def _load_bag_ids_with_sorting_activity_on_day(
    cursor,
    organization_id: int,
    day_start: datetime,
    day_end: datetime,
) -> list[str]:
    if not table_exists(cursor, "rinse_bag_scan_events"):
        return []
    cursor.execute(
        """
        SELECT DISTINCT bag_id
        FROM rinse_bag_scan_events
        WHERE organization_id = %s
          AND scanned_at_parsed >= %s
          AND scanned_at_parsed <= %s
        """,
        (int(organization_id), day_start, day_end),
    )
    candidate_ids = [
        str(r.get("bag_id") or "").strip()
        for r in cursor.fetchall() or []
        if isinstance(r, dict) and r.get("bag_id")
    ]
    if not candidate_ids:
        return []

    # Narrow to bags with sorting-related purposes on that day (Python filter for normalized purposes).
    placeholders = ",".join(["%s"] * len(candidate_ids))
    cursor.execute(
        f"""
        SELECT bag_id, purpose
        FROM rinse_bag_scan_events
        WHERE organization_id = %s
          AND bag_id IN ({placeholders})
          AND scanned_at_parsed >= %s
          AND scanned_at_parsed <= %s
        """,
        (int(organization_id), *candidate_ids, day_start, day_end),
    )
    bag_ids: set[str] = set()
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            continue
        if is_sorting_related_scan_purpose(row.get("purpose")):
            bid = str(row.get("bag_id") or "").strip()
            if bid:
                bag_ids.add(bid)
    return sorted(bag_ids)


def build_sorting_chronology_payload(
    cursor,
    organization_id: int,
    *,
    selected_date_et: date,
    employee_filter: str | None = None,
    bag_id_filter: str | None = None,
    confidence_filter: str | None = None,
) -> dict[str, Any]:
    from backend.rinse_shift_analysis import _load_scan_events_for_bags

    day_start = naive_et_day_start(selected_date_et)
    day_end = naive_et_day_end_inclusive(selected_date_et)

    bag_ids = _load_bag_ids_with_sorting_activity_on_day(
        cursor, organization_id, day_start, day_end
    )
    if bag_id_filter:
        bid = str(bag_id_filter).strip()
        bag_ids = [bid] if bid in bag_ids else ([bid] if bid else [])

    events_by_bag = _load_scan_events_for_bags(cursor, int(organization_id), bag_ids)

    all_sessions: list[dict[str, Any]] = []
    for bid in bag_ids:
        all_sessions.extend(
            extract_sorting_sessions_for_bag(
                bid,
                events_by_bag.get(bid) or [],
                selected_date_et=selected_date_et,
            )
        )

    if employee_filter:
        needle = str(employee_filter).strip().lower()
        all_sessions = [
            s
            for s in all_sessions
            if needle and str(s.get("employee") or "").strip().lower() == needle
        ]

    if confidence_filter:
        cf = str(confidence_filter).strip().lower()
        if cf in ("exact", "inferred"):
            all_sessions = [s for s in all_sessions if s.get("confidence") == cf]

    all_sessions = _cap_sessions_by_employee_busy_periods(all_sessions)
    rows = chronology_rows_with_gaps(all_sessions)
    summary = build_sorting_chronology_summary(rows)

    return {
        "date_et": selected_date_et.isoformat(),
        "summary": summary,
        "sessions": rows,
        "sorting_event_purposes": sorted(
            {
                normalize_scan_purpose(p)
                for p in (
                    "add-photos",
                    "split-load",
                    "create-workitem",
                    "create-issue",
                    "create-bulk-workitem",
                    "cleaning",
                    "start-cleaning",
                    "weight-entry",
                )
            }
        ),
        "grouping_rules": (
            "One session per post-sent-to-vendor sort cycle (add-photos completion marker); "
            "bounds from sorting_bounds_v2 using last weight before that add-photos; "
            "sort start attributed to add-photos employee cleaning/weight (not another employee's weight); "
            "sort_start capped forward when employee sorted other bags during the window; "
            "global chronological order; gap_until_next = next session sort_start minus current sort_end."
        ),
    }
