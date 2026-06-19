"""
Read-only weighing chronology for Shift Analysis.

Builds a time-ordered timeline of weighing sessions from rinse_bag_scan_events.
Does not alter productivity calculations or bag completion logic.

Session grouping:
- One session per post-anchor weigh cycle, keyed by add-photos completion marker when present.
- Uses the first weight-entry in each cycle window (not every intermediate re-scan).
- Bounds from rinse_weighing_session (standardized weigh start/end measurement).
- Sessions are ordered globally by weigh_start_et; gap_until_next is wall time to the next session start.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping, Sequence

from backend.rinse_bag_activity_rules import is_cleaning_purpose_for_activity_start
from backend.rinse_bag_stage_bounds import (
    event_ts,
    events_on_or_after,
    gaming_events_from_records,
    lifecycle_anchor,
    ts_valid,
)
from backend.rinse_folding_et import naive_et_day_end_inclusive, naive_et_day_start, rinse_wall_calendar_date
from backend.rinse_scan_purpose import is_add_photos_purpose, is_weight_entry_purpose, normalize_scan_purpose
from backend.rinse_sorting_chronology import chronology_rows_with_gaps as _sorting_chronology_rows_with_gaps
from backend.rinse_sorting_session import same_scan_event
from backend.rinse_weighing_session import (
    compute_weighing_session,
    weighing_session_source_label,
)
from backend.ta_helpers import table_exists


def is_weighing_related_scan_purpose(raw: str | None) -> bool:
    """Scan purposes that indicate weighing workflow activity on the timeline."""
    if is_weight_entry_purpose(raw):
        return True
    return is_cleaning_purpose_for_activity_start(raw)


def _duration_seconds(start: datetime | None, end: datetime | None) -> int:
    if not ts_valid(start) or not ts_valid(end):
        return 0
    sec = int((end - start).total_seconds())
    return max(sec, 0)


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


def _first_weight_in_window(
    anchored: Sequence[Mapping[str, Any]],
    *,
    after_ts: datetime,
    before_ts: datetime | None = None,
) -> tuple[Mapping[str, Any], datetime] | None:
    """Earliest weight-entry strictly after *after_ts* and before *before_ts* (if set)."""
    first: tuple[Mapping[str, Any], datetime] | None = None
    for ev in anchored:
        if not is_weight_entry_purpose(ev.get("purpose")):
            continue
        ts = event_ts(ev)
        if not ts_valid(ts) or ts <= after_ts:
            continue
        if before_ts is not None and ts >= before_ts:
            continue
        if first is None or ts < first[1]:
            first = (ev, ts)
    return first


def _first_weight_after_ts(
    anchored: Sequence[Mapping[str, Any]],
    *,
    after_ts: datetime,
) -> tuple[Mapping[str, Any], datetime] | None:
    return _first_weight_in_window(anchored, after_ts=after_ts, before_ts=None)


def _last_weight_in_window(
    anchored: Sequence[Mapping[str, Any]],
    *,
    after_ts: datetime,
    before_ts: datetime | None = None,
) -> tuple[Mapping[str, Any], datetime] | None:
    """Most recent weight-entry strictly after *after_ts* and before *before_ts* (if set)."""
    last: tuple[Mapping[str, Any], datetime] | None = None
    for ev in anchored:
        if not is_weight_entry_purpose(ev.get("purpose")):
            continue
        ts = event_ts(ev)
        if not ts_valid(ts) or ts <= after_ts:
            continue
        if before_ts is not None and ts >= before_ts:
            continue
        if last is None or ts > last[1]:
            last = (ev, ts)
    return last


def _add_photos_strictly_between(
    anchored: Sequence[Mapping[str, Any]],
    *,
    after_ts: datetime | None,
    before_ts: datetime | None,
) -> bool:
    """True when add-photos occurs strictly between two timestamps."""
    if not ts_valid(after_ts) or not ts_valid(before_ts) or after_ts >= before_ts:
        return False
    for ev in anchored:
        if not is_add_photos_purpose(ev.get("purpose")):
            continue
        ts = event_ts(ev)
        if ts_valid(ts) and after_ts < ts < before_ts:
            return True
    return False


def _is_post_sort_weigh_end(
    anchored: Sequence[Mapping[str, Any]],
    *,
    weigh_start_et: datetime | None,
    weigh_end_et: datetime | None,
) -> bool:
    """
    Weighing closes at the first weight-entry; add-photos between start and that
    weight means the scan is a later-stage post-sort/post-clean tap, not weigh end.
    """
    return _add_photos_strictly_between(
        anchored,
        after_ts=weigh_start_et,
        before_ts=weigh_end_et,
    )


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
    seen: set[tuple[Any, ...]] = set()
    out: list[dict[str, Any]] = []
    for sess in sessions:
        key = (
            sess.get("bag_id"),
            sess.get("employee"),
            sess.get("weigh_start_et"),
            sess.get("weigh_end_et"),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(sess)
    return out


def _session_row_from_result(
    bid: str,
    session: Any,
    *,
    selected_date_et: date,
) -> dict[str, Any] | None:
    start_at = session.weigh_start_et
    end_at = session.weigh_end_et
    if not ts_valid(end_at):
        return None
    if not ts_valid(start_at):
        start_at = end_at
    if not _session_touches_date(start_at, end_at, selected_date_et):
        return None

    duration = 0 if same_scan_event(session.weigh_start_ev, session.weigh_end_ev) else _duration_seconds(
        start_at, end_at
    )
    return {
        "bag_id": bid,
        "employee": session.employee,
        "weigh_start_et": start_at,
        "weigh_end_et": end_at,
        "duration_seconds": duration,
        "confidence": session.confidence,
        "source": weighing_session_source_label(session.weigh_start_ev, session.weigh_end_ev),
        "end_event_purpose": session.end_event_purpose,
        "start_event_purpose": normalize_scan_purpose(session.weigh_start_ev.get("purpose")),
    }


def _try_append_weighing_session(
    sessions: list[dict[str, Any]],
    *,
    bid: str,
    timeline: Sequence[Mapping[str, Any]],
    anchored: Sequence[Mapping[str, Any]],
    weight_ev: Mapping[str, Any],
    weight_ts: datetime,
    selected_date_et: date,
) -> None:
    session = compute_weighing_session(timeline, weight_ev=weight_ev, weight_ts=weight_ts)
    if _is_post_sort_weigh_end(
        anchored,
        weigh_start_et=session.weigh_start_et,
        weigh_end_et=weight_ts,
    ):
        return
    row = _session_row_from_result(bid, session, selected_date_et=selected_date_et)
    if row is not None:
        sessions.append(row)


def extract_weighing_sessions_for_bag(
    bag_id: str,
    events: Sequence[Mapping[str, Any]],
    *,
    selected_date_et: date,
) -> list[dict[str, Any]]:
    """All weighing sessions for one bag that touch selected_date_et."""
    bid = str(bag_id or "").strip()
    if not bid or not events:
        return []

    tl = gaming_events_from_records(events)
    anchor_ts, _ = lifecycle_anchor(tl)
    if anchor_ts is None:
        return []
    anchored = events_on_or_after(tl, anchor_ts)
    add_photos_events = _add_photos_events_after_anchor(anchored)

    sessions: list[dict[str, Any]] = []
    prev_bound = anchor_ts

    for _add_ev, add_ts in add_photos_events:
        weight_pair = _first_weight_in_window(anchored, after_ts=prev_bound, before_ts=add_ts)
        if weight_pair is not None:
            weight_ev, weight_ts = weight_pair
            _try_append_weighing_session(
                sessions,
                bid=bid,
                timeline=tl,
                anchored=anchored,
                weight_ev=weight_ev,
                weight_ts=weight_ts,
                selected_date_et=selected_date_et,
            )
        prev_bound = add_ts

    orphan = _first_weight_after_ts(anchored, after_ts=prev_bound)
    if orphan is not None:
        weight_ev, weight_ts = orphan
        _try_append_weighing_session(
            sessions,
            bid=bid,
            timeline=tl,
            anchored=anchored,
            weight_ev=weight_ev,
            weight_ts=weight_ts,
            selected_date_et=selected_date_et,
        )

    return _dedupe_sessions_by_window(sessions)


def chronology_rows_with_gaps(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort sessions by weigh start and attach next start + gap."""
    adapted = [
        {
            **s,
            "sort_start_et": s.get("weigh_start_et"),
            "sort_end_et": s.get("weigh_end_et"),
        }
        for s in sessions
    ]
    rows = _sorting_chronology_rows_with_gaps(adapted)
    out: list[dict[str, Any]] = []
    for row in rows:
        normalized = dict(row)
        normalized["weigh_start_et"] = row.get("sort_start_et")
        normalized["weigh_end_et"] = row.get("sort_end_et")
        normalized["next_weigh_start_et"] = row.get("next_sort_start_et")
        normalized.pop("sort_start_et", None)
        normalized.pop("sort_end_et", None)
        normalized.pop("next_sort_start_et", None)
        out.append(normalized)
    return out


def build_weighing_chronology_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "first_weigh_start_et": None,
            "last_weigh_end_et": None,
            "total_sessions": 0,
            "total_weighing_seconds": 0,
            "total_gap_seconds": 0,
            "average_weigh_duration_seconds": None,
        }

    starts = [r["weigh_start_et"] for r in rows if ts_valid(r.get("weigh_start_et"))]
    ends = [r["weigh_end_et"] for r in rows if ts_valid(r.get("weigh_end_et"))]
    total_dur = sum(int(r.get("duration_seconds") or 0) for r in rows)
    gaps = [r.get("gap_until_next_seconds") for r in rows if r.get("gap_until_next_seconds") is not None]
    total_gap = sum(int(g) for g in gaps)
    avg_dur = round(total_dur / len(rows), 2) if rows else None
    return {
        "first_weigh_start_et": min(starts) if starts else None,
        "last_weigh_end_et": max(ends) if ends else None,
        "total_sessions": len(rows),
        "total_weighing_seconds": total_dur,
        "total_gap_seconds": total_gap,
        "average_weigh_duration_seconds": avg_dur,
    }


def _load_bag_ids_with_weighing_activity_on_day(
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
        if is_weighing_related_scan_purpose(row.get("purpose")):
            bid = str(row.get("bag_id") or "").strip()
            if bid:
                bag_ids.add(bid)
    return sorted(bag_ids)


def build_weighing_chronology_payload(
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

    bag_ids = _load_bag_ids_with_weighing_activity_on_day(
        cursor, organization_id, day_start, day_end
    )
    if bag_id_filter:
        bid = str(bag_id_filter).strip()
        bag_ids = [bid] if bid in bag_ids else ([bid] if bid else [])

    events_by_bag = _load_scan_events_for_bags(cursor, int(organization_id), bag_ids)

    all_sessions: list[dict[str, Any]] = []
    for bid in bag_ids:
        all_sessions.extend(
            extract_weighing_sessions_for_bag(
                bid,
                events_by_bag.get(bid) or [],
                selected_date_et=selected_date_et,
            )
        )

    employees = sorted(
        {str(s.get("employee") or "").strip() for s in all_sessions if s.get("employee")},
        key=lambda name: name.casefold(),
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

    rows = chronology_rows_with_gaps(all_sessions)
    summary = build_weighing_chronology_summary(rows)

    return {
        "date_et": selected_date_et.isoformat(),
        "stage": "weighing",
        "summary": summary,
        "sessions": rows,
        "employees": employees,
        "weighing_event_purposes": sorted(
            {
                normalize_scan_purpose(p)
                for p in ("cleaning", "start-cleaning", "weight-entry")
            }
        ),
        "grouping_rules": (
            "One session per post-sent-to-vendor weigh cycle; "
            "bounds from rinse_weighing_session (same-employee cleaning/start-cleaning before "
            "first weight-entry in cycle; weight-entry is weigh end; "
            "sorting/washing/drying/folding scans do not extend weighing); "
            "global chronological order; gap_until_next = next session weigh_start minus current weigh_end."
        ),
    }
