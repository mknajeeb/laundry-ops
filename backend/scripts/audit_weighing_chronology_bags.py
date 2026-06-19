#!/usr/bin/env python3
"""Audit weighing chronology for bags with inflated weigh durations."""
from __future__ import annotations

import json
import sys
from datetime import date, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

ORG = 3
DEFAULT_BAGS = ("D6E0SRN9QV", "8Y75AMQ010", "9IBH0VBU07", "EZMSTPNIIG")
DEFAULT_DATE = date(2026, 6, 18)


def _fmt_ts(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _duration_minutes(seconds: int) -> float:
    return round(seconds / 60, 1)


def _buggy_last_weight_session(
    timeline,
    anchored,
    *,
    prev_bound: datetime,
    before_ts: datetime | None,
    selected_date_et: date,
):
    from backend.rinse_bag_stage_bounds import event_ts
    from backend.rinse_weighing_chronology import _last_weight_in_window, _session_row_from_result
    from backend.rinse_weighing_session import compute_weighing_session

    pair = _last_weight_in_window(anchored, after_ts=prev_bound, before_ts=before_ts)
    if pair is None:
        return None
    weight_ev, weight_ts = pair
    session = compute_weighing_session(timeline, weight_ev=weight_ev, weight_ts=weight_ts)
    row = _session_row_from_result("AUDIT", session, selected_date_et=selected_date_et)
    if row is None:
        return None
    row["selected_weight_ts"] = _fmt_ts(weight_ts)
    row["selection_rule"] = "last_weight_in_window"
    return row


def _extract_weighing_sessions_before_fix(
    bag_id: str,
    events,
    *,
    selected_date_et: date,
) -> list[dict]:
    """Pre-fix behavior: first weight in window, but orphan path kept post-add-photos weights."""
    from backend.rinse_bag_stage_bounds import (
        events_on_or_after,
        gaming_events_from_records,
        lifecycle_anchor,
    )
    from backend.rinse_weighing_chronology import (
        _add_photos_events_after_anchor,
        _dedupe_sessions_by_window,
        _first_weight_after_ts,
        _first_weight_in_window,
        _session_row_from_result,
    )
    from backend.rinse_weighing_session import compute_weighing_session

    tl = gaming_events_from_records(events)
    anchor_ts, _ = lifecycle_anchor(tl)
    if anchor_ts is None:
        return []
    anchored = events_on_or_after(tl, anchor_ts)
    add_photos_events = _add_photos_events_after_anchor(anchored)

    sessions: list[dict] = []
    prev_bound = anchor_ts
    for _add_ev, add_ts in add_photos_events:
        weight_pair = _first_weight_in_window(anchored, after_ts=prev_bound, before_ts=add_ts)
        if weight_pair is not None:
            weight_ev, weight_ts = weight_pair
            session = compute_weighing_session(tl, weight_ev=weight_ev, weight_ts=weight_ts)
            row = _session_row_from_result(bag_id, session, selected_date_et=selected_date_et)
            if row is not None:
                sessions.append(row)
        prev_bound = add_ts

    orphan = _first_weight_after_ts(anchored, after_ts=prev_bound)
    if orphan is not None:
        weight_ev, weight_ts = orphan
        session = compute_weighing_session(tl, weight_ev=weight_ev, weight_ts=weight_ts)
        row = _session_row_from_result(bag_id, session, selected_date_et=selected_date_et)
        if row is not None:
            sessions.append(row)

    return _dedupe_sessions_by_window(sessions)


def audit_bag(cursor, bag_id: str, selected_date_et: date) -> dict:
    from backend.rinse_bag_activity_rules import is_cleaning_purpose_for_activity_start
    from backend.rinse_bag_stage_bounds import (
        event_ts,
        events_on_or_after,
        gaming_events_from_records,
        lifecycle_anchor,
    )
    from backend.rinse_scan_purpose import is_add_photos_purpose, is_weight_entry_purpose
    from backend.rinse_shift_analysis import _load_scan_events_for_bags
    from backend.rinse_weighing_chronology import (
        _add_photos_events_after_anchor,
        _first_weight_in_window,
        extract_weighing_sessions_for_bag,
    )
    from backend.rinse_weighing_session import compute_weighing_session

    events = (_load_scan_events_for_bags(cursor, ORG, [bag_id]).get(bag_id)) or []
    if not events:
        return {
            "bag_id": bag_id,
            "status": "no_events",
            "selected_date_et": selected_date_et.isoformat(),
        }

    timeline = gaming_events_from_records(events)
    anchor_ts, _ = lifecycle_anchor(timeline)
    if anchor_ts is None:
        return {
            "bag_id": bag_id,
            "status": "no_anchor",
            "selected_date_et": selected_date_et.isoformat(),
        }

    anchored = events_on_or_after(timeline, anchor_ts)
    add_photos_events = _add_photos_events_after_anchor(anchored)

    cycle_reports: list[dict] = []
    prev_bound = anchor_ts
    for _add_ev, add_ts in add_photos_events:
        first_pair = _first_weight_in_window(anchored, after_ts=prev_bound, before_ts=add_ts)
        last_row = _buggy_last_weight_session(
            timeline,
            anchored,
            prev_bound=prev_bound,
            before_ts=add_ts,
            selected_date_et=selected_date_et,
        )
        if first_pair is not None:
            first_ev, first_ts = first_pair
            session = compute_weighing_session(timeline, weight_ev=first_ev, weight_ts=first_ts)
            cleaning = session.weigh_start_ev
            cycle_reports.append(
                {
                    "window_after": _fmt_ts(prev_bound),
                    "window_before_add_photos": _fmt_ts(add_ts),
                    "cleaning_used": {
                        "ts": _fmt_ts(event_ts(cleaning)),
                        "purpose": cleaning.get("purpose"),
                        "employee": cleaning.get("user_name") or cleaning.get("user"),
                    },
                    "first_weight_entry": {
                        "ts": _fmt_ts(first_ts),
                        "employee": first_ev.get("user_name") or first_ev.get("user"),
                        "event_id": first_ev.get("id"),
                    },
                    "buggy_last_weight_entry": (
                        {
                            "ts": last_row.get("selected_weight_ts"),
                            "weigh_end_et": _fmt_ts(last_row.get("weigh_end_et")),
                            "duration_minutes": _duration_minutes(int(last_row.get("duration_seconds") or 0)),
                        }
                        if last_row is not None
                        else None
                    ),
                    "buggy_duration_minutes": (
                        _duration_minutes(int(last_row.get("duration_seconds") or 0))
                        if last_row is not None
                        else None
                    ),
                }
            )
        prev_bound = add_ts

    fixed_sessions = extract_weighing_sessions_for_bag(
        bag_id,
        events,
        selected_date_et=selected_date_et,
    )
    before_sessions = _extract_weighing_sessions_before_fix(
        bag_id,
        events,
        selected_date_et=selected_date_et,
    )

    day_events = []
    for ev in anchored:
        ts = event_ts(ev)
        if ts is None or ts.date() != selected_date_et:
            continue
        purpose = ev.get("purpose")
        if (
            is_weight_entry_purpose(purpose)
            or is_add_photos_purpose(purpose)
            or is_cleaning_purpose_for_activity_start(purpose)
        ):
            day_events.append(
                {
                    "ts": _fmt_ts(ts),
                    "purpose": purpose,
                    "employee": ev.get("user_name") or ev.get("user"),
                    "event_id": ev.get("id"),
                }
            )

    inflated_before = [
        s
        for s in before_sessions
        if int(s.get("duration_seconds") or 0) >= 30 * 60
    ]

    return {
        "bag_id": bag_id,
        "status": "ok",
        "selected_date_et": selected_date_et.isoformat(),
        "day_events": day_events,
        "weigh_cycles": cycle_reports,
        "before_fix_sessions": [
            {
                "employee": s.get("employee"),
                "weigh_start_et": _fmt_ts(s.get("weigh_start_et")),
                "weigh_end_et": _fmt_ts(s.get("weigh_end_et")),
                "duration_minutes": _duration_minutes(int(s.get("duration_seconds") or 0)),
                "source": s.get("source"),
            }
            for s in before_sessions
        ],
        "after_fix_sessions": [
            {
                "employee": s.get("employee"),
                "weigh_start_et": _fmt_ts(s.get("weigh_start_et")),
                "weigh_end_et": _fmt_ts(s.get("weigh_end_et")),
                "duration_minutes": _duration_minutes(int(s.get("duration_seconds") or 0)),
                "source": s.get("source"),
            }
            for s in fixed_sessions
        ],
        "root_cause": (
            "Orphan path treated post-add-photos weight as weigh end, pairing it with "
            "earlier cleaning/start-cleaning and spanning add-photos sorting in between"
            if inflated_before
            else None
        ),
    }


def main() -> None:
    from backend.db import get_db

    selected = DEFAULT_DATE
    bags = list(DEFAULT_BAGS)
    if len(sys.argv) > 1:
        selected = date.fromisoformat(sys.argv[1])
    if len(sys.argv) > 2:
        bags = [part.strip() for part in sys.argv[2].split(",") if part.strip()]

    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    report = {
        "organization_id": ORG,
        "selected_date_et": selected.isoformat(),
        "bags": [audit_bag(cursor, bag_id, selected) for bag_id in bags],
    }
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
