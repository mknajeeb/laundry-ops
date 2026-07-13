"""Tests for Ready to Fold chronology calculations."""

from datetime import date, datetime, timedelta

from backend.rinse_ready_to_fold_chronology import (
    DEFAULT_DRYING_DURATION_MINUTES,
    INTERVALS_PER_DAY,
    STATUS_FOLDING_STARTED,
    STATUS_NOT_YET_READY,
    STATUS_WAITING,
    build_day_interval_starts,
    build_ready_to_fold_bag_records,
    build_ready_to_fold_intervals,
    build_ready_to_fold_summary,
    clamp_drying_duration_minutes,
    filter_ready_to_fold_bags,
    find_folding_start_after,
    floor_to_interval,
    select_current_cycle_drying_rows,
    select_current_lifecycle_drying_row,
)


SELECTED = date(2026, 7, 13)


def _dry(bag_id, at, *, rack="D4-50-VW", ev_id=1):
    return {
        "scan_event_id": ev_id,
        "bag_id": bag_id,
        "employee": "Alex",
        "timestamp_et": at,
        "dryer_rack": rack,
        "confidence": "exact",
        "event_purpose": "drying",
    }


def _ev(bag_id, purpose, at, *, rack="FOLDING", ev_id=10, scan_index=1):
    return {
        "id": ev_id,
        "bag_id": bag_id,
        "rack": rack,
        "user_name": "Folder",
        "purpose": purpose,
        "scanned_at_parsed": at,
        "scan_index": scan_index,
    }


class TestReadyToFoldCore:
    def test_default_duration_is_40(self):
        assert clamp_drying_duration_minutes(None) == 40
        assert clamp_drying_duration_minutes("abc") == DEFAULT_DRYING_DURATION_MINUTES
        assert clamp_drying_duration_minutes(35) == 35

    def test_duration_matrix_including_zero(self):
        assert clamp_drying_duration_minutes(0) == 0
        assert clamp_drying_duration_minutes(-5) == 0
        assert clamp_drying_duration_minutes(1440) == 1440
        assert clamp_drying_duration_minutes(1441) == 1440
        for mins in (0, 35, 40, 45, 60, 120):
            bags = build_ready_to_fold_bag_records(
                drying_rows=[_dry("BAG1", datetime(2026, 7, 13, 8, 5))],
                events_by_bag={},
                metadata_by_bag={},
                selected_date_et=SELECTED,
                drying_duration_minutes=mins,
                as_of=datetime(2026, 7, 13, 23, 59, 59),
            )
            assert bags[0]["ready_to_fold_et"] == datetime(2026, 7, 13, 8, 5) + timedelta(
                minutes=mins
            )

    def test_ready_time_is_drying_plus_duration(self):
        drying_rows = [_dry("BAG1", datetime(2026, 7, 13, 8, 5))]
        bags = build_ready_to_fold_bag_records(
            drying_rows=drying_rows,
            events_by_bag={},
            metadata_by_bag={},
            selected_date_et=SELECTED,
            drying_duration_minutes=40,
            as_of=datetime(2026, 7, 13, 23, 59, 59),
        )
        assert len(bags) == 1
        assert bags[0]["ready_to_fold_et"] == datetime(2026, 7, 13, 8, 45)
        assert bags[0]["status"] == STATUS_WAITING

    def test_duration_change_recalculates(self):
        drying_rows = [_dry("BAG1", datetime(2026, 7, 13, 8, 5))]
        bags = build_ready_to_fold_bag_records(
            drying_rows=drying_rows,
            events_by_bag={},
            metadata_by_bag={},
            selected_date_et=SELECTED,
            drying_duration_minutes=35,
            as_of=datetime(2026, 7, 13, 23, 59, 59),
        )
        assert bags[0]["ready_to_fold_et"] == datetime(2026, 7, 13, 8, 40)

    def test_prior_day_drying_ready_on_selected_day(self):
        drying_rows = [_dry("BAG1", datetime(2026, 7, 12, 23, 30))]
        bags = build_ready_to_fold_bag_records(
            drying_rows=drying_rows,
            events_by_bag={},
            metadata_by_bag={},
            selected_date_et=SELECTED,
            drying_duration_minutes=40,
            as_of=datetime(2026, 7, 13, 23, 59, 59),
        )
        assert len(bags) == 1
        assert bags[0]["ready_to_fold_et"] == datetime(2026, 7, 13, 0, 10)

    def test_cross_day_1140pm_plus_40(self):
        drying_rows = [_dry("BAG1", datetime(2026, 7, 12, 23, 40))]
        bags = build_ready_to_fold_bag_records(
            drying_rows=drying_rows,
            events_by_bag={},
            metadata_by_bag={},
            selected_date_et=SELECTED,
            drying_duration_minutes=40,
            as_of=datetime(2026, 7, 13, 23, 59, 59),
        )
        assert bags[0]["ready_to_fold_et"] == datetime(2026, 7, 13, 0, 20)
        assert bags[0]["is_carryover"] is False
        intervals = build_ready_to_fold_intervals(bags, selected_date_et=SELECTED)
        by_label = {i["label"]: i for i in intervals}
        assert by_label["12:15 AM"]["newly_ready_count"] == 1
        assert by_label["12:00 AM"]["newly_ready_count"] == 0
        # Still waiting at 12:00 AM before ready → not yet in cumulative until 12:15 end
        assert by_label["12:00 AM"]["available_count"] == 0
        assert by_label["12:15 AM"]["available_count"] == 1

    def test_carryover_waiting_not_newly_ready(self):
        drying_rows = [_dry("BAG1", datetime(2026, 7, 12, 22, 0))]
        bags = build_ready_to_fold_bag_records(
            drying_rows=drying_rows,
            events_by_bag={},
            metadata_by_bag={},
            selected_date_et=SELECTED,
            drying_duration_minutes=40,
            as_of=datetime(2026, 7, 13, 23, 59, 59),
        )
        assert bags[0]["ready_to_fold_et"] == datetime(2026, 7, 12, 22, 40)
        assert bags[0]["is_carryover"] is True
        intervals = build_ready_to_fold_intervals(bags, selected_date_et=SELECTED)
        newly_total = sum(i["newly_ready_count"] for i in intervals)
        assert newly_total == 0
        assert intervals[0]["available_count"] == 1
        assert intervals[0]["label"] == "12:00 AM"

    def test_uses_most_recent_drying_cycle(self):
        drying_rows = [
            _dry("BAG1", datetime(2026, 7, 13, 7, 0), ev_id=1, rack="D1-35-VW"),
            _dry("BAG1", datetime(2026, 7, 13, 10, 0), ev_id=2, rack="D8-50-VW"),
        ]
        selected = select_current_cycle_drying_rows(drying_rows)
        assert len(selected) == 1
        assert selected[0]["timestamp_et"] == datetime(2026, 7, 13, 10, 0)
        assert selected[0]["dryer_rack"] == "D8-50-VW"

    def test_redry_replaces_earlier_cycle_no_double_count(self):
        drying_rows = [
            _dry("BAG1", datetime(2026, 7, 13, 8, 0), ev_id=1),
            _dry("BAG1", datetime(2026, 7, 13, 11, 0), ev_id=2, rack="D9-50-VW"),
        ]
        events = {
            "BAG1": [
                _ev("BAG1", "sent-to-vendor", datetime(2026, 7, 13, 5, 0), rack="VENDOR", ev_id=1),
                _ev("BAG1", "drying", datetime(2026, 7, 13, 8, 0), rack="D4-50-VW", ev_id=2),
                _ev("BAG1", "drying", datetime(2026, 7, 13, 11, 0), rack="D9-50-VW", ev_id=3),
            ]
        }
        bags = build_ready_to_fold_bag_records(
            drying_rows=drying_rows,
            events_by_bag=events,
            metadata_by_bag={},
            selected_date_et=SELECTED,
            drying_duration_minutes=40,
            as_of=datetime(2026, 7, 13, 23, 59, 59),
        )
        assert len(bags) == 1
        assert bags[0]["drying_scan_et"] == datetime(2026, 7, 13, 11, 0)
        assert bags[0]["ready_to_fold_et"] == datetime(2026, 7, 13, 11, 40)
        intervals = build_ready_to_fold_intervals(bags, selected_date_et=SELECTED)
        assert sum(i["newly_ready_count"] for i in intervals) == 1

    def test_lifecycle_ignores_prior_trip_drying(self):
        drying_rows = [
            _dry("BAG1", datetime(2026, 7, 10, 9, 0), ev_id=1),
            _dry("BAG1", datetime(2026, 7, 13, 10, 0), ev_id=2, rack="D8-50-VW"),
        ]
        events = [
            _ev("BAG1", "sent-to-vendor", datetime(2026, 7, 10, 5, 0), rack="VENDOR", ev_id=1),
            _ev("BAG1", "drying", datetime(2026, 7, 10, 9, 0), rack="D4-50-VW", ev_id=2),
            _ev("BAG1", "sent-to-vendor", datetime(2026, 7, 13, 5, 0), rack="VENDOR", ev_id=3),
            _ev("BAG1", "drying", datetime(2026, 7, 13, 10, 0), rack="D8-50-VW", ev_id=4),
        ]
        chosen = select_current_lifecycle_drying_row(
            drying_rows,
            events,
            as_of_end=datetime(2026, 7, 13, 23, 59, 59),
        )
        assert chosen["timestamp_et"] == datetime(2026, 7, 13, 10, 0)
        assert chosen["dryer_rack"] == "D8-50-VW"

        # Historical day before re-intake must keep the prior trip dry.
        chosen_prior = select_current_lifecycle_drying_row(
            drying_rows,
            events,
            as_of_end=datetime(2026, 7, 10, 23, 59, 59),
        )
        assert chosen_prior["timestamp_et"] == datetime(2026, 7, 10, 9, 0)

    def test_folding_start_after_drying_marks_status(self):
        dry_ts = datetime(2026, 7, 13, 8, 5)
        fold_ts = datetime(2026, 7, 13, 9, 0)
        bags = build_ready_to_fold_bag_records(
            drying_rows=[_dry("BAG1", dry_ts)],
            events_by_bag={
                "BAG1": [
                    _ev("BAG1", "move-bag", fold_ts, rack="FOLDING"),
                ]
            },
            metadata_by_bag={"BAG1": {"service_type": "WF", "weight_num": 21.0}},
            selected_date_et=SELECTED,
            drying_duration_minutes=40,
            as_of=datetime(2026, 7, 13, 23, 59, 59),
        )
        assert bags[0]["folding_start_et"] == fold_ts
        assert bags[0]["status"] == STATUS_FOLDING_STARTED
        assert bags[0]["service_type"] == "WF"
        assert bags[0]["weight"] == 21.0

    def test_folding_before_current_drying_ignored(self):
        fold_ts = datetime(2026, 7, 13, 7, 0)
        dry_ts = datetime(2026, 7, 13, 8, 5)
        assert (
            find_folding_start_after(
                [_ev("BAG1", "move-bag", fold_ts, rack="FOLDING")],
                after_ts=dry_ts,
            )
            is None
        )

    def test_fold_before_ready_never_negative_waiting(self):
        bags = build_ready_to_fold_bag_records(
            drying_rows=[_dry("BAG1", datetime(2026, 7, 13, 12, 16))],
            events_by_bag={
                "BAG1": [
                    _ev(
                        "BAG1",
                        "move-bag",
                        datetime(2026, 7, 13, 12, 17),
                        rack="FOLDING",
                    )
                ]
            },
            metadata_by_bag={},
            selected_date_et=SELECTED,
            drying_duration_minutes=40,
            as_of=datetime(2026, 7, 13, 23, 59, 59),
        )
        intervals = build_ready_to_fold_intervals(bags, selected_date_et=SELECTED)
        assert all(i["available_count"] >= 0 for i in intervals)
        ready_iv = next(
            i for i in intervals if i["interval_start_et"] == datetime(2026, 7, 13, 12, 45)
        )
        assert ready_iv["newly_ready_count"] == 1
        assert ready_iv["available_count"] == 0

    def test_not_yet_ready_when_as_of_before_ready(self):
        bags = build_ready_to_fold_bag_records(
            drying_rows=[_dry("BAG1", datetime(2026, 7, 13, 8, 5))],
            events_by_bag={},
            metadata_by_bag={},
            selected_date_et=SELECTED,
            drying_duration_minutes=40,
            as_of=datetime(2026, 7, 13, 8, 20),
        )
        assert bags[0]["status"] == STATUS_NOT_YET_READY


class TestReadyToFoldIntervals:
    def test_has_96_intervals(self):
        starts = build_day_interval_starts(SELECTED)
        assert len(starts) == INTERVALS_PER_DAY
        assert starts[0] == datetime(2026, 7, 13, 0, 0)
        assert starts[-1] == datetime(2026, 7, 13, 23, 45)

    def test_half_open_allocation_807_and_boundaries(self):
        # Ready 8:07 → floor to 8:00 interval [8:00, 8:15)
        assert floor_to_interval(datetime(2026, 7, 13, 8, 7)) == datetime(2026, 7, 13, 8, 0)
        bags = build_ready_to_fold_bag_records(
            drying_rows=[
                _dry("A", datetime(2026, 7, 13, 7, 20), ev_id=1),  # ready 8:00
                _dry("B", datetime(2026, 7, 13, 7, 27), ev_id=2),  # ready 8:07
                _dry("C", datetime(2026, 7, 13, 7, 35), ev_id=3),  # ready 8:15
                _dry("D", datetime(2026, 7, 13, 7, 50), ev_id=4),  # ready 8:30
                _dry("E", datetime(2026, 7, 13, 23, 19), ev_id=5),  # ready 23:59
            ],
            events_by_bag={},
            metadata_by_bag={},
            selected_date_et=SELECTED,
            drying_duration_minutes=40,
            as_of=datetime(2026, 7, 13, 23, 59, 59),
        )
        intervals = build_ready_to_fold_intervals(bags, selected_date_et=SELECTED)
        by_label = {i["label"]: i for i in intervals}
        assert sorted(b["bag_id"] for b in by_label["8:00 AM"]["newly_ready_bags"]) == ["A", "B"]
        assert [b["bag_id"] for b in by_label["8:15 AM"]["newly_ready_bags"]] == ["C"]
        assert [b["bag_id"] for b in by_label["8:30 AM"]["newly_ready_bags"]] == ["D"]
        assert [b["bag_id"] for b in by_label["11:45 PM"]["newly_ready_bags"]] == ["E"]

        newly_ids = [b["bag_id"] for i in intervals for b in i["newly_ready_bags"]]
        assert len(newly_ids) == len(set(newly_ids)) == 5

    def test_newly_ready_and_cumulative(self):
        bags = build_ready_to_fold_bag_records(
            drying_rows=[
                _dry("A", datetime(2026, 7, 13, 7, 20), ev_id=1),  # ready 8:00
                _dry("B", datetime(2026, 7, 13, 7, 25), ev_id=2),  # ready 8:05
                _dry("C", datetime(2026, 7, 13, 7, 40), ev_id=3),  # ready 8:20
            ],
            events_by_bag={},
            metadata_by_bag={},
            selected_date_et=SELECTED,
            drying_duration_minutes=40,
            as_of=datetime(2026, 7, 13, 23, 59, 59),
        )
        intervals = build_ready_to_fold_intervals(bags, selected_date_et=SELECTED)
        by_label = {i["label"]: i for i in intervals}

        assert by_label["8:00 AM"]["newly_ready_count"] == 2
        assert by_label["8:00 AM"]["available_count"] == 2
        assert by_label["8:15 AM"]["newly_ready_count"] == 1
        assert by_label["8:15 AM"]["available_count"] == 3

    def test_cumulative_drops_after_folding_start(self):
        bags = build_ready_to_fold_bag_records(
            drying_rows=[_dry("A", datetime(2026, 7, 13, 7, 20), ev_id=1)],
            events_by_bag={
                "A": [_ev("A", "move-bag", datetime(2026, 7, 13, 8, 10), rack="FOLDING")],
            },
            metadata_by_bag={},
            selected_date_et=SELECTED,
            drying_duration_minutes=40,
            as_of=datetime(2026, 7, 13, 23, 59, 59),
        )
        intervals = build_ready_to_fold_intervals(bags, selected_date_et=SELECTED)
        by_label = {i["label"]: i for i in intervals}
        # Ready at 8:00, folded at 8:10 → available at end of 8:00 bucket is False
        assert by_label["8:00 AM"]["newly_ready_count"] == 1
        assert by_label["8:00 AM"]["available_count"] == 0
        assert by_label["8:15 AM"]["available_count"] == 0

    def test_summary_peak(self):
        bags = build_ready_to_fold_bag_records(
            drying_rows=[
                _dry("A", datetime(2026, 7, 13, 7, 20), ev_id=1),
                _dry("B", datetime(2026, 7, 13, 7, 25), ev_id=2),
                _dry("C", datetime(2026, 7, 13, 7, 40), ev_id=3),
            ],
            events_by_bag={},
            metadata_by_bag={},
            selected_date_et=SELECTED,
            drying_duration_minutes=40,
            as_of=datetime(2026, 7, 13, 23, 59, 59),
        )
        intervals = build_ready_to_fold_intervals(bags, selected_date_et=SELECTED)
        summary = build_ready_to_fold_summary(
            bags, intervals, selected_date_et=SELECTED
        )
        assert summary["total_bags_dried"] == 3
        assert summary["total_bags_ready_to_fold"] == 3
        assert summary["currently_waiting_to_fold"] == 3
        assert summary["first_bag_ready_et"] == datetime(2026, 7, 13, 8, 0)
        assert summary["max_bags_waiting"] == 3

    def test_filters_update_summary_scope(self):
        bags = [
            {
                "bag_id": "A",
                "service_type": "WF",
                "status": STATUS_WAITING,
                "dryer_rack": "D1",
                "drying_scan_et": datetime(2026, 7, 13, 8, 0),
                "ready_to_fold_et": datetime(2026, 7, 13, 8, 40),
            },
            {
                "bag_id": "B",
                "service_type": "HD",
                "status": STATUS_FOLDING_STARTED,
                "dryer_rack": "D2",
                "drying_scan_et": datetime(2026, 7, 13, 9, 0),
                "ready_to_fold_et": datetime(2026, 7, 13, 9, 40),
            },
        ]
        filtered = filter_ready_to_fold_bags(bags, order_type_filter="WF")
        assert [b["bag_id"] for b in filtered] == ["A"]
        intervals = build_ready_to_fold_intervals(filtered, selected_date_et=SELECTED)
        summary = build_ready_to_fold_summary(
            filtered, intervals, selected_date_et=SELECTED
        )
        assert summary["total_bags_dried"] == 1
        assert summary["currently_waiting_to_fold"] == 1

        waiting = filter_ready_to_fold_bags(bags, status_filter=STATUS_WAITING)
        assert [b["bag_id"] for b in waiting] == ["A"]
        machine = filter_ready_to_fold_bags(bags, machine_filter="D2")
        assert [b["bag_id"] for b in machine] == ["B"]
