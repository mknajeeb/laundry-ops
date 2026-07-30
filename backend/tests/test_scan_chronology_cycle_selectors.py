"""Tests for shared STV-as-of and Sorting/Washing current-cycle selectors."""

from datetime import date, datetime, timedelta

from backend.rinse_bag_stage_bounds import lifecycle_anchor, lifecycle_anchor_as_of
from backend.rinse_ready_to_fold_chronology import (
    select_current_cycle_drying_rows,
    select_current_lifecycle_drying_row,
)
from backend.rinse_sorting_chronology import (
    select_current_cycle_sorting_sessions,
    select_current_lifecycle_sorting_session,
)
from backend.rinse_washing_chronology import (
    MAX_WASHING_START_CLEANING_ROWS_PER_BAG,
    extract_washing_rows_from_events,
    select_current_cycle_washing_rows,
    select_current_lifecycle_washing_row,
)


DAY = date(2026, 7, 30)
DAY_END = datetime(2026, 7, 30, 23, 59, 59)
PRIOR = date(2026, 7, 29)


def _ev(purpose, at, *, bag_id="BAG1", rack="R1", ev_id=1, scan_index=1, user="Alex"):
    return {
        "id": ev_id,
        "bag_id": bag_id,
        "rack": rack,
        "user_name": user,
        "purpose": purpose,
        "scanned_at_parsed": at,
        "scan_index": scan_index,
    }


def _sort_sess(bag_id, start, end=None, *, employee="Alex"):
    return {
        "bag_id": bag_id,
        "employee": employee,
        "sort_start_et": start,
        "sort_end_et": end or (start + timedelta(minutes=10)),
        "duration_seconds": 600,
        "confidence": "exact",
        "source": "test",
        "end_event_purpose": "add-photos",
    }


def _wash(bag_id, at, *, rack="W1-50-VW", ev_id=1, employee="Alex"):
    return {
        "scan_event_id": ev_id,
        "bag_id": bag_id,
        "employee": employee,
        "timestamp_et": at,
        "washer_rack": rack,
        "confidence": "exact",
        "event_purpose": "start-cleaning",
    }


def _dry(bag_id, at, *, rack="D1-50-VW", ev_id=1):
    return {
        "scan_event_id": ev_id,
        "bag_id": bag_id,
        "employee": "Alex",
        "timestamp_et": at,
        "dryer_rack": rack,
        "confidence": "exact",
        "event_purpose": "drying",
    }


class TestLifecycleAnchorAsOf:
    def test_latest_stv_as_of_selected_day_cutoff(self):
        events = [
            _ev("sent-to-vendor", datetime(2026, 7, 29, 10, 0), ev_id=1),
            _ev("sent-to-vendor", datetime(2026, 7, 30, 8, 0), ev_id=2),
            _ev("sent-to-vendor", datetime(2026, 7, 30, 20, 0), ev_id=3),
        ]
        ts, ev = lifecycle_anchor_as_of(events, as_of_end=DAY_END)
        assert ts == datetime(2026, 7, 30, 20, 0)
        assert ev["id"] == 3

    def test_later_stv_after_cutoff_ignored(self):
        events = [
            _ev("sent-to-vendor", datetime(2026, 7, 30, 8, 0), ev_id=1),
            _ev("sent-to-vendor", datetime(2026, 7, 31, 1, 0), ev_id=2),
        ]
        ts, ev = lifecycle_anchor_as_of(events, as_of_end=DAY_END)
        assert ts == datetime(2026, 7, 30, 8, 0)
        assert ev["id"] == 1

    def test_overnight_future_events_do_not_change_prior_day_result(self):
        events = [
            _ev("sent-to-vendor", datetime(2026, 7, 29, 22, 0), ev_id=1),
            _ev("sent-to-vendor", datetime(2026, 7, 30, 0, 30), ev_id=2),
        ]
        prior_end = datetime(2026, 7, 29, 23, 59, 59)
        ts, _ = lifecycle_anchor_as_of(events, as_of_end=prior_end)
        assert ts == datetime(2026, 7, 29, 22, 0)
        # Selecting again is deterministic
        ts2, _ = lifecycle_anchor_as_of(events, as_of_end=prior_end)
        assert ts2 == ts

    def test_unbounded_lifecycle_anchor_still_takes_latest_overall(self):
        events = [
            _ev("sent-to-vendor", datetime(2026, 7, 29, 10, 0), ev_id=1),
            _ev("sent-to-vendor", datetime(2026, 7, 31, 1, 0), ev_id=2),
        ]
        ts, _ = lifecycle_anchor(events)
        assert ts == datetime(2026, 7, 31, 1, 0)


class TestSortingSelectors:
    def test_old_cycle_sorting_session_ignored(self):
        sessions = [
            _sort_sess("BAG1", datetime(2026, 7, 29, 12, 0)),
            _sort_sess("BAG1", datetime(2026, 7, 30, 9, 0)),
        ]
        events = [
            _ev("sent-to-vendor", datetime(2026, 7, 30, 6, 0), ev_id=10),
        ]
        chosen = select_current_lifecycle_sorting_session(
            sessions, events, as_of_end=DAY_END
        )
        assert chosen is not None
        assert chosen["sort_start_et"] == datetime(2026, 7, 30, 9, 0)

    def test_current_cycle_sorting_session_selected(self):
        sessions = [_sort_sess("BAG1", datetime(2026, 7, 30, 10, 0))]
        events = [_ev("sent-to-vendor", datetime(2026, 7, 30, 5, 0), ev_id=1)]
        chosen = select_current_lifecycle_sorting_session(
            sessions, events, as_of_end=DAY_END
        )
        assert chosen["sort_start_et"] == datetime(2026, 7, 30, 10, 0)

    def test_multiple_sorting_sessions_latest_qualifying_selected(self):
        sessions = [
            _sort_sess("BAG1", datetime(2026, 7, 30, 8, 0)),
            _sort_sess("BAG1", datetime(2026, 7, 30, 11, 0)),
            _sort_sess("BAG1", datetime(2026, 7, 30, 14, 0)),
        ]
        events = [_ev("sent-to-vendor", datetime(2026, 7, 30, 7, 0), ev_id=1)]
        chosen = select_current_lifecycle_sorting_session(
            sessions, events, as_of_end=DAY_END
        )
        assert chosen["sort_start_et"] == datetime(2026, 7, 30, 14, 0)

    def test_no_current_cycle_sorting_session_returns_null(self):
        # All sessions predate the STV anchor at/before cutoff
        sessions = [_sort_sess("BAG1", datetime(2026, 7, 29, 12, 0))]
        events = [_ev("sent-to-vendor", datetime(2026, 7, 30, 8, 0), ev_id=1)]
        chosen = select_current_lifecycle_sorting_session(
            sessions, events, as_of_end=DAY_END
        )
        assert chosen is None

    def test_session_beginning_after_as_of_end_discarded(self):
        sessions = [
            _sort_sess("BAG1", datetime(2026, 7, 30, 10, 0)),
            _sort_sess("BAG1", datetime(2026, 7, 31, 1, 0)),
        ]
        events = [_ev("sent-to-vendor", datetime(2026, 7, 30, 5, 0), ev_id=1)]
        chosen = select_current_lifecycle_sorting_session(
            sessions, events, as_of_end=DAY_END
        )
        assert chosen["sort_start_et"] == datetime(2026, 7, 30, 10, 0)

    def test_select_current_cycle_one_per_bag(self):
        sessions = [
            _sort_sess("A", datetime(2026, 7, 30, 8, 0)),
            _sort_sess("A", datetime(2026, 7, 30, 12, 0)),
            _sort_sess("B", datetime(2026, 7, 30, 9, 0)),
        ]
        events_by_bag = {
            "A": [_ev("sent-to-vendor", datetime(2026, 7, 30, 6, 0), bag_id="A", ev_id=1)],
            "B": [_ev("sent-to-vendor", datetime(2026, 7, 30, 6, 0), bag_id="B", ev_id=2)],
        }
        selected = select_current_cycle_sorting_sessions(
            sessions, events_by_bag, as_of_end=DAY_END
        )
        assert {s["bag_id"] for s in selected} == {"A", "B"}
        by_bag = {s["bag_id"]: s for s in selected}
        assert by_bag["A"]["sort_start_et"] == datetime(2026, 7, 30, 12, 0)

    def test_repeated_selection_deterministic(self):
        sessions = [
            _sort_sess("BAG1", datetime(2026, 7, 30, 8, 0)),
            _sort_sess("BAG1", datetime(2026, 7, 30, 11, 0)),
        ]
        events = [_ev("sent-to-vendor", datetime(2026, 7, 30, 7, 0), ev_id=1)]
        a = select_current_lifecycle_sorting_session(sessions, events, as_of_end=DAY_END)
        b = select_current_lifecycle_sorting_session(sessions, events, as_of_end=DAY_END)
        assert a == b


class TestWashingSelectors:
    def test_old_cycle_washing_row_ignored(self):
        rows = [
            _wash("BAG1", datetime(2026, 7, 29, 14, 0), ev_id=1),
            _wash("BAG1", datetime(2026, 7, 30, 10, 0), ev_id=2),
        ]
        events = [_ev("sent-to-vendor", datetime(2026, 7, 30, 6, 0), ev_id=10)]
        chosen = select_current_lifecycle_washing_row(rows, events, as_of_end=DAY_END)
        assert chosen["timestamp_et"] == datetime(2026, 7, 30, 10, 0)
        assert chosen["scan_event_id"] == 2

    def test_current_cycle_washing_row_selected(self):
        rows = [_wash("BAG1", datetime(2026, 7, 30, 11, 0), ev_id=5)]
        events = [_ev("sent-to-vendor", datetime(2026, 7, 30, 5, 0), ev_id=1)]
        chosen = select_current_lifecycle_washing_row(rows, events, as_of_end=DAY_END)
        assert chosen["scan_event_id"] == 5

    def test_multiple_washing_rows_canonical_latest_selected(self):
        rows = [
            _wash("BAG1", datetime(2026, 7, 30, 9, 0), ev_id=1),
            _wash("BAG1", datetime(2026, 7, 30, 12, 0), ev_id=2),
        ]
        events = [_ev("sent-to-vendor", datetime(2026, 7, 30, 7, 0), ev_id=10)]
        chosen = select_current_lifecycle_washing_row(rows, events, as_of_end=DAY_END)
        assert chosen["scan_event_id"] == 2

    def test_full_multi_row_washing_extraction_unchanged(self):
        events = [
            _ev(
                "start-cleaning",
                datetime(2026, 7, 30, 9, 0),
                rack="W1-50-VW",
                ev_id=1,
                scan_index=1,
            ),
            _ev(
                "start-cleaning",
                datetime(2026, 7, 30, 10, 0),
                rack="W2-50-VW",
                ev_id=2,
                scan_index=2,
            ),
            _ev(
                "start-cleaning",
                datetime(2026, 7, 30, 11, 0),
                rack="W3-50-VW",
                ev_id=3,
                scan_index=3,
            ),
        ]
        rows = extract_washing_rows_from_events(events)
        # Cap remains 2 — chronology multi-row behavior unchanged
        assert MAX_WASHING_START_CLEANING_ROWS_PER_BAG == 2
        assert len(rows) == 2
        assert [r["scan_event_id"] for r in rows] == [1, 2]

    def test_no_current_cycle_washing_row_returns_null(self):
        rows = [_wash("BAG1", datetime(2026, 7, 29, 14, 0), ev_id=1)]
        events = [_ev("sent-to-vendor", datetime(2026, 7, 30, 8, 0), ev_id=10)]
        chosen = select_current_lifecycle_washing_row(rows, events, as_of_end=DAY_END)
        assert chosen is None

    def test_select_current_cycle_one_per_bag(self):
        rows = [
            _wash("A", datetime(2026, 7, 30, 9, 0), ev_id=1),
            _wash("A", datetime(2026, 7, 30, 12, 0), ev_id=2),
            _wash("B", datetime(2026, 7, 30, 10, 0), ev_id=3),
        ]
        events_by_bag = {
            "A": [_ev("sent-to-vendor", datetime(2026, 7, 30, 6, 0), bag_id="A", ev_id=10)],
            "B": [_ev("sent-to-vendor", datetime(2026, 7, 30, 6, 0), bag_id="B", ev_id=11)],
        }
        selected = select_current_cycle_washing_rows(
            rows, events_by_bag, as_of_end=DAY_END
        )
        assert {r["bag_id"] for r in selected} == {"A", "B"}
        by_bag = {r["bag_id"]: r for r in selected}
        assert by_bag["A"]["scan_event_id"] == 2


class TestSharedAnchorSemantics:
    def test_sorting_washing_drying_share_identical_anchor_semantics(self):
        stv = datetime(2026, 7, 30, 6, 0)
        old = datetime(2026, 7, 29, 12, 0)
        cur = datetime(2026, 7, 30, 10, 0)
        events = [_ev("sent-to-vendor", stv, ev_id=1)]

        sort_chosen = select_current_lifecycle_sorting_session(
            [_sort_sess("BAG1", old), _sort_sess("BAG1", cur)],
            events,
            as_of_end=DAY_END,
        )
        wash_chosen = select_current_lifecycle_washing_row(
            [_wash("BAG1", old, ev_id=1), _wash("BAG1", cur, ev_id=2)],
            events,
            as_of_end=DAY_END,
        )
        dry_chosen = select_current_lifecycle_drying_row(
            [_dry("BAG1", old, ev_id=1), _dry("BAG1", cur, ev_id=2)],
            events,
            as_of_end=DAY_END,
        )
        assert sort_chosen["sort_start_et"] == cur
        assert wash_chosen["timestamp_et"] == cur
        assert dry_chosen["timestamp_et"] == cur

        # Same as_of_end STV after midnight ignored for all three
        events_future = events + [
            _ev("sent-to-vendor", datetime(2026, 7, 31, 2, 0), ev_id=99)
        ]
        assert (
            select_current_lifecycle_sorting_session(
                [_sort_sess("BAG1", cur)], events_future, as_of_end=DAY_END
            )["sort_start_et"]
            == cur
        )
        assert (
            select_current_lifecycle_washing_row(
                [_wash("BAG1", cur, ev_id=2)], events_future, as_of_end=DAY_END
            )["timestamp_et"]
            == cur
        )
        assert (
            select_current_lifecycle_drying_row(
                [_dry("BAG1", cur, ev_id=2)], events_future, as_of_end=DAY_END
            )["timestamp_et"]
            == cur
        )

    def test_select_current_cycle_drying_still_one_per_bag(self):
        rows = [
            _dry("A", datetime(2026, 7, 30, 9, 0), ev_id=1),
            _dry("A", datetime(2026, 7, 30, 12, 0), ev_id=2),
        ]
        events_by_bag = {
            "A": [_ev("sent-to-vendor", datetime(2026, 7, 30, 6, 0), bag_id="A", ev_id=10)]
        }
        selected = select_current_cycle_drying_rows(
            rows, events_by_bag, as_of_end=DAY_END
        )
        assert len(selected) == 1
        assert selected[0]["scan_event_id"] == 2


class TestExistingChronologyUnchanged:
    """Selectors are additive — extractors keep prior behavior."""

    def test_washing_extract_still_returns_capped_multi_rows(self):
        events = [
            _ev("start-cleaning", datetime(2026, 7, 30, 9, 0) + timedelta(minutes=i),
                rack=f"W{i}-50-VW", ev_id=i + 1, scan_index=i + 1)
            for i in range(4)
        ]
        before = extract_washing_rows_from_events(events)
        # Calling selectors must not mutate extractor output contract
        _ = select_current_cycle_washing_rows(
            before,
            {"BAG1": [_ev("sent-to-vendor", datetime(2026, 7, 30, 5, 0), ev_id=99)]},
            as_of_end=DAY_END,
        )
        after = extract_washing_rows_from_events(events)
        assert [r["scan_event_id"] for r in before] == [r["scan_event_id"] for r in after]
        assert len(after) == 2

    def test_ready_to_fold_default_duration_still_40(self):
        from backend.rinse_ready_to_fold_chronology import DEFAULT_DRYING_DURATION_MINUTES
        from backend.rinse_processing_settings import DEFAULT_DRYING_MINUTES

        assert DEFAULT_DRYING_DURATION_MINUTES == 40
        assert DEFAULT_DRYING_MINUTES == 45
        # Documented discrepancy — extraction does not reconcile them
