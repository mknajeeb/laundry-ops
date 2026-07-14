"""Tests for Ready to Fold chronology (selected-day drying output only)."""

from datetime import date, datetime, timedelta

from backend.rinse_ready_to_fold_chronology import (
    DEFAULT_DRYING_DURATION_MINUTES,
    INTERVALS_PER_DAY,
    build_day_interval_starts,
    build_ready_to_fold_bag_records,
    build_ready_to_fold_intervals,
    build_ready_to_fold_summary,
    clamp_drying_duration_minutes,
    filter_ready_to_fold_bags,
    floor_to_interval,
    ready_time_for_interval_bucket,
    select_current_cycle_drying_rows,
    select_current_lifecycle_drying_row,
)


SELECTED = date(2026, 7, 14)
JUL13 = date(2026, 7, 13)


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
                drying_rows=[_dry("BAG1", datetime(2026, 7, 14, 8, 5))],
                events_by_bag={},
                metadata_by_bag={},
                selected_date_et=SELECTED,
                drying_duration_minutes=mins,
            )
            assert bags[0]["ready_to_fold_et"] == datetime(2026, 7, 14, 8, 5) + timedelta(
                minutes=mins
            )

    def test_ready_time_is_drying_plus_duration(self):
        bags = build_ready_to_fold_bag_records(
            drying_rows=[_dry("BAG1", datetime(2026, 7, 14, 8, 5))],
            events_by_bag={},
            metadata_by_bag={},
            selected_date_et=SELECTED,
            drying_duration_minutes=40,
        )
        assert len(bags) == 1
        assert bags[0]["ready_to_fold_et"] == datetime(2026, 7, 14, 8, 45)

    def test_prior_day_drying_excluded_even_if_ready_on_selected_day(self):
        """Jul 13 11:30 PM dry → Jul 14 12:10 AM ready belongs to Jul 13, not Jul 14."""
        bags = build_ready_to_fold_bag_records(
            drying_rows=[_dry("BAG1", datetime(2026, 7, 13, 23, 30))],
            events_by_bag={},
            metadata_by_bag={},
            selected_date_et=SELECTED,
            drying_duration_minutes=40,
        )
        assert bags == []

        jul13 = build_ready_to_fold_bag_records(
            drying_rows=[_dry("BAG1", datetime(2026, 7, 13, 23, 30))],
            events_by_bag={},
            metadata_by_bag={},
            selected_date_et=JUL13,
            drying_duration_minutes=40,
        )
        assert len(jul13) == 1
        assert jul13[0]["ready_to_fold_et"] == datetime(2026, 7, 14, 0, 10)
        assert jul13[0]["ready_spills_next_day"] is True

    def test_late_night_dry_buckets_into_1145pm_on_dry_date(self):
        bags = build_ready_to_fold_bag_records(
            drying_rows=[_dry("BAG1", datetime(2026, 7, 13, 23, 30))],
            events_by_bag={},
            metadata_by_bag={},
            selected_date_et=JUL13,
            drying_duration_minutes=40,
        )
        intervals = build_ready_to_fold_intervals(bags, selected_date_et=JUL13)
        by_label = {i["label"]: i for i in intervals}
        assert by_label["12:00 AM"]["newly_ready_count"] == 0
        assert by_label["12:00 AM"]["cumulative_ready_count"] == 0
        assert by_label["11:45 PM"]["newly_ready_count"] == 1
        assert by_label["11:45 PM"]["cumulative_ready_count"] == 1

    def test_no_prior_day_carry_in_at_midnight(self):
        bags = [
            {
                "bag_id": "X",
                "drying_scan_et": datetime(2026, 7, 13, 22, 0),
                "ready_to_fold_et": datetime(2026, 7, 13, 22, 40),
            }
        ]
        # Population must not include prior-day dry; if it leaked, intervals still start at 0
        # because ready is before selected day and bucket returns None.
        intervals = build_ready_to_fold_intervals(bags, selected_date_et=SELECTED)
        assert intervals[0]["label"] == "12:00 AM"
        assert intervals[0]["newly_ready_count"] == 0
        assert intervals[0]["cumulative_ready_count"] == 0

    def test_folding_scans_have_zero_effect(self):
        bags_base = build_ready_to_fold_bag_records(
            drying_rows=[_dry("A", datetime(2026, 7, 14, 8, 0))],
            events_by_bag={},
            metadata_by_bag={},
            selected_date_et=SELECTED,
            drying_duration_minutes=40,
        )
        bags_fold = build_ready_to_fold_bag_records(
            drying_rows=[_dry("A", datetime(2026, 7, 14, 8, 0))],
            events_by_bag={
                "A": [_ev("A", "move-bag", datetime(2026, 7, 14, 9, 0), rack="FOLDING")],
            },
            metadata_by_bag={},
            selected_date_et=SELECTED,
            drying_duration_minutes=40,
        )
        assert bags_base[0]["ready_to_fold_et"] == bags_fold[0]["ready_to_fold_et"]
        assert "folding_start_et" not in bags_fold[0]
        assert "status" not in bags_fold[0]
        iv_base = build_ready_to_fold_intervals(bags_base, selected_date_et=SELECTED)
        iv_fold = build_ready_to_fold_intervals(bags_fold, selected_date_et=SELECTED)
        assert [i["newly_ready_count"] for i in iv_base] == [i["newly_ready_count"] for i in iv_fold]
        assert [i["cumulative_ready_count"] for i in iv_base] == [
            i["cumulative_ready_count"] for i in iv_fold
        ]

    def test_uses_most_recent_drying_cycle(self):
        drying_rows = [
            _dry("BAG1", datetime(2026, 7, 14, 7, 0), ev_id=1, rack="D1-35-VW"),
            _dry("BAG1", datetime(2026, 7, 14, 10, 0), ev_id=2, rack="D8-50-VW"),
        ]
        selected = select_current_cycle_drying_rows(drying_rows)
        assert len(selected) == 1
        assert selected[0]["timestamp_et"] == datetime(2026, 7, 14, 10, 0)

    def test_lifecycle_ignores_prior_trip_drying(self):
        drying_rows = [
            _dry("BAG1", datetime(2026, 7, 10, 9, 0), ev_id=1),
            _dry("BAG1", datetime(2026, 7, 14, 10, 0), ev_id=2, rack="D8-50-VW"),
        ]
        events = [
            _ev("BAG1", "sent-to-vendor", datetime(2026, 7, 10, 5, 0), rack="VENDOR", ev_id=1),
            _ev("BAG1", "drying", datetime(2026, 7, 10, 9, 0), rack="D4-50-VW", ev_id=2),
            _ev("BAG1", "sent-to-vendor", datetime(2026, 7, 14, 5, 0), rack="VENDOR", ev_id=3),
            _ev("BAG1", "drying", datetime(2026, 7, 14, 10, 0), rack="D8-50-VW", ev_id=4),
        ]
        bags = build_ready_to_fold_bag_records(
            drying_rows=drying_rows,
            events_by_bag={"BAG1": events},
            metadata_by_bag={},
            selected_date_et=SELECTED,
            drying_duration_minutes=40,
        )
        assert len(bags) == 1
        assert bags[0]["drying_scan_et"] == datetime(2026, 7, 14, 10, 0)


class TestReadyToFoldIntervals:
    def test_has_96_intervals(self):
        starts = build_day_interval_starts(SELECTED)
        assert len(starts) == INTERVALS_PER_DAY
        assert starts[0] == datetime(2026, 7, 14, 0, 0)
        assert starts[-1] == datetime(2026, 7, 14, 23, 45)

    def test_half_open_and_once_each(self):
        assert floor_to_interval(datetime(2026, 7, 14, 8, 7)) == datetime(2026, 7, 14, 8, 0)
        bags = build_ready_to_fold_bag_records(
            drying_rows=[
                _dry("A", datetime(2026, 7, 14, 7, 20), ev_id=1),  # ready 8:00
                _dry("B", datetime(2026, 7, 14, 7, 27), ev_id=2),  # ready 8:07
                _dry("C", datetime(2026, 7, 14, 7, 35), ev_id=3),  # ready 8:15
            ],
            events_by_bag={},
            metadata_by_bag={},
            selected_date_et=SELECTED,
            drying_duration_minutes=40,
        )
        intervals = build_ready_to_fold_intervals(bags, selected_date_et=SELECTED)
        by_label = {i["label"]: i for i in intervals}
        assert by_label["8:00 AM"]["newly_ready_count"] == 2
        assert by_label["8:15 AM"]["newly_ready_count"] == 1
        newly_ids = [b["bag_id"] for i in intervals for b in i["newly_ready_bags"]]
        assert len(newly_ids) == len(set(newly_ids)) == 3

    def test_cumulative_starts_zero_and_running_sum(self):
        bags = [
            {"bag_id": "A", "ready_to_fold_et": datetime(2026, 7, 14, 7, 50)},
            *[{"bag_id": f"B{i}", "ready_to_fold_et": datetime(2026, 7, 14, 8, 1 + i)} for i in range(4)],
            *[{"bag_id": f"C{i}", "ready_to_fold_et": datetime(2026, 7, 14, 8, 16 + i)} for i in range(3)],
        ]
        intervals = build_ready_to_fold_intervals(bags, selected_date_et=SELECTED)
        by_label = {i["label"]: i for i in intervals}
        assert by_label["12:00 AM"]["newly_ready_count"] == 0
        assert by_label["12:00 AM"]["cumulative_ready_count"] == 0
        assert by_label["7:45 AM"]["newly_ready_count"] == 1
        assert by_label["7:45 AM"]["cumulative_ready_count"] == 1
        assert by_label["8:00 AM"]["newly_ready_count"] == 4
        assert by_label["8:00 AM"]["cumulative_ready_count"] == 5
        assert by_label["8:15 AM"]["newly_ready_count"] == 3
        assert by_label["8:15 AM"]["cumulative_ready_count"] == 8
        assert by_label["8:30 AM"]["newly_ready_count"] == 0
        assert by_label["8:30 AM"]["cumulative_ready_count"] == 8

        prev = None
        for iv in intervals:
            if prev is not None:
                assert iv["cumulative_ready_count"] == prev + iv["newly_ready_count"]
                assert iv["cumulative_ready_count"] >= prev
            prev = iv["cumulative_ready_count"]

    def test_summary_final_cum_equals_total_ready(self):
        bags = build_ready_to_fold_bag_records(
            drying_rows=[
                _dry("A", datetime(2026, 7, 14, 7, 20), ev_id=1),
                _dry("B", datetime(2026, 7, 14, 7, 25), ev_id=2),
                _dry("C", datetime(2026, 7, 14, 7, 40), ev_id=3),
            ],
            events_by_bag={},
            metadata_by_bag={},
            selected_date_et=SELECTED,
            drying_duration_minutes=40,
        )
        intervals = build_ready_to_fold_intervals(bags, selected_date_et=SELECTED)
        summary = build_ready_to_fold_summary(bags, intervals, selected_date_et=SELECTED)
        assert summary["total_bags_dried"] == 3
        assert summary["total_bags_ready"] == 3
        assert summary["peak_cumulative_ready_count"] == 3
        assert intervals[-1]["cumulative_ready_count"] == summary["total_bags_ready"]
        assert summary["peak_15min_ready_count"] == 2
        assert "currently_waiting_to_fold" not in summary

    def test_duration_change_same_population(self):
        drying_rows = [
            _dry("A", datetime(2026, 7, 14, 8, 0), ev_id=1),
            _dry("B", datetime(2026, 7, 14, 9, 0), ev_id=2),
        ]
        ids40 = {
            b["bag_id"]
            for b in build_ready_to_fold_bag_records(
                drying_rows=drying_rows,
                events_by_bag={},
                metadata_by_bag={},
                selected_date_et=SELECTED,
                drying_duration_minutes=40,
            )
        }
        ids60 = {
            b["bag_id"]
            for b in build_ready_to_fold_bag_records(
                drying_rows=drying_rows,
                events_by_bag={},
                metadata_by_bag={},
                selected_date_et=SELECTED,
                drying_duration_minutes=60,
            )
        }
        assert ids40 == ids60 == {"A", "B"}

    def test_post_midnight_bucket_helper(self):
        spill = ready_time_for_interval_bucket(datetime(2026, 7, 14, 0, 10), JUL13)
        assert spill == datetime(2026, 7, 14, 0, 0) - timedelta(microseconds=1)
        assert floor_to_interval(spill) == datetime(2026, 7, 13, 23, 45)

    def test_filters_order_and_machine(self):
        bags = [
            {
                "bag_id": "A",
                "service_type": "WF",
                "dryer_rack": "D1",
                "drying_scan_et": datetime(2026, 7, 14, 8, 0),
                "ready_to_fold_et": datetime(2026, 7, 14, 8, 40),
            },
            {
                "bag_id": "B",
                "service_type": "HD",
                "dryer_rack": "D2",
                "drying_scan_et": datetime(2026, 7, 14, 9, 0),
                "ready_to_fold_et": datetime(2026, 7, 14, 9, 40),
            },
        ]
        assert [b["bag_id"] for b in filter_ready_to_fold_bags(bags, order_type_filter="WF")] == ["A"]
        assert [b["bag_id"] for b in filter_ready_to_fold_bags(bags, machine_filter="D2")] == ["B"]
