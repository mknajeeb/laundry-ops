"""Tests for standardized sorting session measurement (rinse_sorting_session)."""

from datetime import datetime

from backend.rinse_bag_stage_bounds import (
    events_on_or_after,
    first_weight_after_anchor,
    gaming_events_from_records,
    lifecycle_anchor,
)
from backend.rinse_sorting_session import (
    compute_sorting_session,
    same_scan_event,
    session_source_label,
    sorting_session_bounds,
)


def _ev(purpose, at, *, scan_index=1, ev_id=1, user="Maria"):
    return {
        "id": ev_id,
        "rack": "Scale",
        "user_name": user,
        "purpose": purpose,
        "scanned_at_parsed": at,
        "scan_index": scan_index,
    }


def _timeline(*events):
    return gaming_events_from_records(
        [_ev("sent-to-vendor", datetime(2026, 6, 17, 6, 0), ev_id=1)] + list(events)
    )


def _anchored(tl):
    anchor_ts, _ = lifecycle_anchor(tl)
    return events_on_or_after(tl, anchor_ts)


def _weight_pair(tl):
    return first_weight_after_anchor(_anchored(tl))


class TestSortingSessionStart:
    def test_start_at_same_employee_cleaning_before_add_photos(self):
        tl = _timeline(
            _ev("cleaning", datetime(2026, 6, 18, 8, 21), ev_id=2, scan_index=2),
            _ev("weight-entry", datetime(2026, 6, 18, 8, 22), ev_id=3, scan_index=3),
            _ev("add-photos", datetime(2026, 6, 18, 8, 24), ev_id=4, scan_index=4),
        )
        weight_ev, weight_ts = _weight_pair(tl)
        session = compute_sorting_session(
            _anchored(tl), tl, weight_ev=weight_ev, weight_ts=weight_ts
        )
        assert session is not None
        assert session.sort_start_et == datetime(2026, 6, 18, 8, 21)
        assert session.sort_end_et == datetime(2026, 6, 18, 8, 24)
        assert session.employee == "Maria"
        assert session.confidence == "exact"

    def test_start_fallback_same_employee_weight_without_cleaning(self):
        tl = _timeline(
            _ev("weight-entry", datetime(2026, 6, 18, 9, 0), ev_id=2, scan_index=2),
            _ev("add-photos", datetime(2026, 6, 18, 9, 10), ev_id=3, scan_index=3),
        )
        weight_ev, weight_ts = _weight_pair(tl)
        session = compute_sorting_session(
            _anchored(tl), tl, weight_ev=weight_ev, weight_ts=weight_ts
        )
        assert session.sort_start_et == datetime(2026, 6, 18, 9, 0)
        assert session.confidence == "inferred"

    def test_cross_employee_weight_not_sort_start(self):
        """86CK96LI6E: Jennifer weight must not anchor Maria's sort start."""
        tl = _timeline(
            _ev(
                "weight-entry",
                datetime(2026, 6, 18, 7, 47),
                ev_id=2,
                scan_index=2,
                user="Jennifer",
            ),
            _ev(
                "add-photos",
                datetime(2026, 6, 18, 9, 19),
                ev_id=3,
                scan_index=3,
                user="Maria",
            ),
        )
        weight_ev, weight_ts = _weight_pair(tl)
        session = compute_sorting_session(
            _anchored(tl), tl, weight_ev=weight_ev, weight_ts=weight_ts
        )
        assert session.employee == "Maria"
        assert session.sort_start_et == datetime(2026, 6, 18, 9, 19)
        assert session.sort_end_et == datetime(2026, 6, 18, 9, 19)


class TestSortingSessionEnd:
    def test_end_at_add_photos_by_default(self):
        tl = _timeline(
            _ev("cleaning", datetime(2026, 6, 18, 8, 21), ev_id=2, scan_index=2),
            _ev("weight-entry", datetime(2026, 6, 18, 8, 22), ev_id=3, scan_index=3),
            _ev("add-photos", datetime(2026, 6, 18, 8, 24), ev_id=4, scan_index=4),
            _ev("start-cleaning", datetime(2026, 6, 18, 8, 30), ev_id=5, scan_index=5),
        )
        weight_ev, weight_ts = _weight_pair(tl)
        session = compute_sorting_session(
            _anchored(tl), tl, weight_ev=weight_ev, weight_ts=weight_ts
        )
        assert session.end_event_purpose == "add-photos"
        assert session.sort_end_et == datetime(2026, 6, 18, 8, 24)

    def test_ready_washer_does_not_extend_sorting(self):
        """COXWJMCCPH: ready-washer after add-photos must not extend sort end."""
        tl = _timeline(
            _ev("cleaning", datetime(2026, 6, 18, 8, 21), ev_id=2, scan_index=2),
            _ev("weight-entry", datetime(2026, 6, 18, 8, 22), ev_id=3, scan_index=3),
            _ev("add-photos", datetime(2026, 6, 18, 8, 24), ev_id=4, scan_index=4),
            _ev("split-load", datetime(2026, 6, 18, 8, 25), ev_id=5, scan_index=5),
            _ev("ready-washer", datetime(2026, 6, 18, 8, 47), ev_id=6, scan_index=6),
            _ev("start-cleaning", datetime(2026, 6, 18, 8, 50), ev_id=7, scan_index=7),
        )
        weight_ev, weight_ts = _weight_pair(tl)
        session = compute_sorting_session(
            _anchored(tl), tl, weight_ev=weight_ev, weight_ts=weight_ts
        )
        assert session.sort_start_et == datetime(2026, 6, 18, 8, 21)
        assert session.sort_end_et == datetime(2026, 6, 18, 8, 25)
        assert session.end_event_purpose == "split-load"
        assert session_source_label(session.sort_start_ev, session.sort_end_ev) == (
            "cleaning → split-load"
        )

    def test_create_issue_extends_after_add_photos(self):
        tl = _timeline(
            _ev("cleaning", datetime(2026, 6, 18, 8, 21), ev_id=2, scan_index=2),
            _ev("weight-entry", datetime(2026, 6, 18, 8, 22), ev_id=3, scan_index=3),
            _ev("add-photos", datetime(2026, 6, 18, 8, 24), ev_id=4, scan_index=4),
            _ev("create-issue", datetime(2026, 6, 18, 8, 26), ev_id=5, scan_index=5),
            _ev("ready-washer", datetime(2026, 6, 18, 8, 47), ev_id=6, scan_index=6),
        )
        weight_ev, weight_ts = _weight_pair(tl)
        session = compute_sorting_session(
            _anchored(tl), tl, weight_ev=weight_ev, weight_ts=weight_ts
        )
        assert session.sort_end_et == datetime(2026, 6, 18, 8, 26)
        assert session.end_event_purpose == "create-issue"

    def test_latest_create_issue_wins(self):
        tl = _timeline(
            _ev("weight-entry", datetime(2026, 6, 18, 9, 0), ev_id=2, scan_index=2),
            _ev("add-photos", datetime(2026, 6, 18, 9, 5), ev_id=3, scan_index=3),
            _ev("create-issue", datetime(2026, 6, 18, 9, 8), ev_id=4, scan_index=4),
            _ev("create-issue", datetime(2026, 6, 18, 9, 12), ev_id=5, scan_index=5),
        )
        weight_ev, weight_ts = _weight_pair(tl)
        session = compute_sorting_session(
            _anchored(tl), tl, weight_ev=weight_ev, weight_ts=weight_ts
        )
        assert session.sort_end_et == datetime(2026, 6, 18, 9, 12)

    def test_split_load_then_create_issue(self):
        tl = _timeline(
            _ev("weight-entry", datetime(2026, 6, 18, 9, 0), ev_id=2, scan_index=2),
            _ev("add-photos", datetime(2026, 6, 18, 9, 5), ev_id=3, scan_index=3),
            _ev("split-load", datetime(2026, 6, 18, 9, 7), ev_id=4, scan_index=4),
            _ev("create-issue", datetime(2026, 6, 18, 9, 10), ev_id=5, scan_index=5),
        )
        weight_ev, weight_ts = _weight_pair(tl)
        session = compute_sorting_session(
            _anchored(tl), tl, weight_ev=weight_ev, weight_ts=weight_ts
        )
        assert session.end_event_purpose == "create-issue"
        assert session.sort_end_et == datetime(2026, 6, 18, 9, 10)


class TestSortingSessionHelpers:
    def test_same_scan_event_by_id(self):
        a = _ev("add-photos", datetime(2026, 6, 18, 9, 0), ev_id=10)
        b = _ev("add-photos", datetime(2026, 6, 18, 9, 0), ev_id=11)
        assert not same_scan_event(a, b)
        assert same_scan_event(a, a)

    def test_sorting_session_bounds_tuple(self):
        tl = _timeline(
            _ev("cleaning", datetime(2026, 6, 18, 8, 50), ev_id=2, scan_index=2),
            _ev("weight-entry", datetime(2026, 6, 18, 9, 0), ev_id=3, scan_index=3),
            _ev("add-photos", datetime(2026, 6, 18, 9, 10), ev_id=4, scan_index=4),
        )
        weight_ev, weight_ts = _weight_pair(tl)
        start, end = sorting_session_bounds(
            _anchored(tl), tl, weight_ev=weight_ev, weight_ts=weight_ts
        )
        assert start.get("purpose") == "cleaning"
        assert end.get("purpose") == "add-photos"

    def test_no_add_photos_returns_none(self):
        tl = _timeline(
            _ev("weight-entry", datetime(2026, 6, 18, 9, 0), ev_id=2, scan_index=2),
        )
        weight_ev, weight_ts = _weight_pair(tl)
        assert (
            compute_sorting_session(
                _anchored(tl),
                tl,
                weight_ev=weight_ev,
                weight_ts=weight_ts,
            )
            is None
        )
