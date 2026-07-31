"""Process Flow inter-stage queue calculator tests."""

from datetime import date, datetime, timedelta

import pytest

from backend.rinse_folding_settings import DEFAULT_LBS_PER_HOUR
from backend.rinse_process_flow_chronology import (
    DEFAULT_DRY_ASSUMPTION_MINUTES,
    ProcessFlowValidationError,
    clamp_dry_assumption_minutes,
)
from backend.rinse_process_flow_queue import (
    FOLDING_COMPLETION_RESOLVER,
    FOLDING_COMPLETION_SOURCE,
    build_queue_slot,
    classify_excess_deficit,
    compose_queue_bags_from_process_flow_rows,
    effective_departure,
    folder_capacity_recommendation,
    newly_available_in_interval,
    parse_interval_start,
    processed_in_interval,
    reconcile_waiting_end,
    replay_peak_and_starved,
    waiting_at_checkpoint,
)
from backend.rinse_processing_settings import DEFAULT_DRYING_MINUTES as SETTINGS_DRYING_MINUTES

SELECTED = date(2026, 7, 30)


def _bag(
    bag_id,
    *,
    arrival,
    departure=None,
    pre_lbs=None,
    seq="Valid",
    codes=None,
):
    return {
        "bag_id": bag_id,
        "arrival": arrival,
        "departure": departure,
        "pre_weight_lbs": pre_lbs,
        "sequence_status": seq,
        "sequence_codes": codes or [],
        "arrival_employee": "Up",
        "arrival_machine": "M1",
        "departure_employee": "Down",
        "departure_machine": "M2",
    }


class TestDefaultsAndFoldingResolver:
    def test_dry_default_40_not_45(self):
        assert DEFAULT_DRY_ASSUMPTION_MINUTES == 40
        assert SETTINGS_DRYING_MINUTES == 45
        assert clamp_dry_assumption_minutes(None) == 40
        assert clamp_dry_assumption_minutes("") == 40

    def test_folding_completion_resolver_identity(self):
        assert FOLDING_COMPLETION_RESOLVER == "evaluate_folding_performance_for_bag"
        assert "folding_end_at" in FOLDING_COMPLETION_SOURCE

    def test_start_time_required(self):
        with pytest.raises(ProcessFlowValidationError, match="Start Time"):
            parse_interval_start(None, selected_date_et=SELECTED)
        assert parse_interval_start("08:00", selected_date_et=SELECTED) == datetime(
            2026, 7, 30, 8, 0
        )


class TestReadyTimesAreActual:
    def test_washing_arrival_is_sort_time(self):
        rows = [
            {
                "bag_id": "A",
                "sort_scan_et": datetime(2026, 7, 30, 8, 0),
                "wash_scan_et": datetime(2026, 7, 30, 9, 0),
                "dry_scan_et": datetime(2026, 7, 30, 10, 0),
                "sort_employee": "S",
                "wash_employee": "W",
                "dry_employee": "D",
                "sequence_status": "Valid",
                "sequence_codes": [],
            }
        ]
        bags = compose_queue_bags_from_process_flow_rows(
            rows,
            dry_minutes=40,
            fold_completions={},
            pre_pounds={},
        )
        assert bags[0]["wash_arrival"] == datetime(2026, 7, 30, 8, 0)
        assert bags[0]["wash_departure"] == datetime(2026, 7, 30, 9, 0)

    def test_drying_arrival_is_wash_time(self):
        rows = [
            {
                "bag_id": "A",
                "sort_scan_et": datetime(2026, 7, 30, 8, 0),
                "wash_scan_et": datetime(2026, 7, 30, 9, 0),
                "dry_scan_et": datetime(2026, 7, 30, 10, 0),
                "sequence_status": "Valid",
                "sequence_codes": [],
            }
        ]
        bags = compose_queue_bags_from_process_flow_rows(
            rows, dry_minutes=40, fold_completions={}, pre_pounds={}
        )
        assert bags[0]["dry_arrival"] == datetime(2026, 7, 30, 9, 0)
        assert bags[0]["dry_departure"] == datetime(2026, 7, 30, 10, 0)

    def test_folding_arrival_is_dry_plus_40(self):
        rows = [
            {
                "bag_id": "A",
                "sort_scan_et": datetime(2026, 7, 30, 8, 0),
                "wash_scan_et": datetime(2026, 7, 30, 9, 0),
                "dry_scan_et": datetime(2026, 7, 30, 10, 0),
                "sequence_status": "Valid",
                "sequence_codes": [],
            }
        ]
        bags = compose_queue_bags_from_process_flow_rows(
            rows, dry_minutes=40, fold_completions={}, pre_pounds={}
        )
        assert bags[0]["fold_arrival"] == datetime(2026, 7, 30, 10, 40)

    def test_folded_uses_folding_end_at(self):
        rows = [
            {
                "bag_id": "A",
                "sort_scan_et": datetime(2026, 7, 30, 8, 0),
                "wash_scan_et": datetime(2026, 7, 30, 9, 0),
                "dry_scan_et": datetime(2026, 7, 30, 10, 0),
                "sequence_status": "Valid",
                "sequence_codes": [],
            }
        ]
        bags = compose_queue_bags_from_process_flow_rows(
            rows,
            dry_minutes=40,
            fold_completions={"A": datetime(2026, 7, 30, 11, 30)},
            pre_pounds={},
        )
        assert bags[0]["fold_departure"] == datetime(2026, 7, 30, 11, 30)

    def test_no_sort_wash_duration_assumptions_in_compose(self):
        rows = [
            {
                "bag_id": "A",
                "sort_scan_et": datetime(2026, 7, 30, 8, 0),
                "wash_scan_et": datetime(2026, 7, 30, 9, 0),
                "dry_scan_et": None,
                "sequence_status": "Missing Dry",
                "sequence_codes": ["Missing Dry"],
            }
        ]
        bags = compose_queue_bags_from_process_flow_rows(
            rows, dry_minutes=40, fold_completions={}, pre_pounds={}
        )
        # Wash arrival is raw sort time — not sort+assumption
        assert bags[0]["wash_arrival"] == datetime(2026, 7, 30, 8, 0)
        assert bags[0]["fold_arrival"] is None


class TestPointInTimeWaiting:
    def test_waiting_for_wash(self):
        bags = [
            _bag("A", arrival=datetime(2026, 7, 30, 8, 0), departure=datetime(2026, 7, 30, 9, 0)),
            _bag("B", arrival=datetime(2026, 7, 30, 8, 30), departure=None),
            _bag("C", arrival=datetime(2026, 7, 30, 10, 0), departure=None),
        ]
        cp = datetime(2026, 7, 30, 9, 30)
        waiting = waiting_at_checkpoint(bags, cp, arrival_key="arrival", departure_key="departure")
        assert {b["bag_id"] for b in waiting} == {"B"}

    def test_waiting_for_dry_and_fold(self):
        bags = [
            _bag("A", arrival=datetime(2026, 7, 30, 8, 0), departure=datetime(2026, 7, 30, 8, 45)),
            _bag("B", arrival=datetime(2026, 7, 30, 8, 10), departure=None),
        ]
        waiting = waiting_at_checkpoint(
            bags, datetime(2026, 7, 30, 9, 0), arrival_key="arrival", departure_key="departure"
        )
        assert [b["bag_id"] for b in waiting] == ["B"]

    def test_waiting_never_negative(self):
        bags = [
            _bag("A", arrival=datetime(2026, 7, 30, 9, 0), departure=datetime(2026, 7, 30, 8, 0)),
        ]
        waiting = waiting_at_checkpoint(
            bags, datetime(2026, 7, 30, 9, 30), arrival_key="arrival", departure_key="departure"
        )
        # OOS departure ignored → still waiting
        assert len(waiting) == 1


class TestWaitingStartEndAndPeak:
    def test_waiting_start_end_and_reconciliation(self):
        bags = [
            _bag("A", arrival=datetime(2026, 7, 30, 7, 30), departure=datetime(2026, 7, 30, 8, 20)),
            _bag("B", arrival=datetime(2026, 7, 30, 8, 10), departure=None),
            _bag("C", arrival=datetime(2026, 7, 30, 8, 40), departure=None),
        ]
        start = datetime(2026, 7, 30, 8, 0)
        end = datetime(2026, 7, 30, 9, 0)
        w_start = waiting_at_checkpoint(bags, start, arrival_key="arrival", departure_key="departure")
        w_end = waiting_at_checkpoint(bags, end, arrival_key="arrival", departure_key="departure")
        newly = newly_available_in_interval(
            bags, interval_start=start, interval_end=end, arrival_key="arrival"
        )
        processed, excluded = processed_in_interval(
            bags, interval_start=start, interval_end=end, arrival_key="arrival", departure_key="departure"
        )
        assert len(w_start) == 1  # A
        assert {b["bag_id"] for b in newly} == {"B", "C"}
        assert [b["bag_id"] for b in processed] == ["A"]
        assert len(excluded) == 0
        assert {b["bag_id"] for b in w_end} == {"B", "C"}
        recon = reconcile_waiting_end(
            waiting_at_start=len(w_start),
            newly_available=len(newly),
            processed=len(processed),
            waiting_at_end=len(w_end),
        )
        assert recon["reconciles"] is True

    def test_peak_from_chronological_replay(self):
        bags = [
            _bag("A", arrival=datetime(2026, 7, 30, 7, 50), departure=datetime(2026, 7, 30, 8, 30)),
            _bag("B", arrival=datetime(2026, 7, 30, 8, 10), departure=None),
            _bag("C", arrival=datetime(2026, 7, 30, 8, 15), departure=None),
        ]
        start = datetime(2026, 7, 30, 8, 0)
        end = datetime(2026, 7, 30, 9, 0)
        # waiting at start = 1 (A)
        replay = replay_peak_and_starved(
            bags,
            interval_start=start,
            interval_end=end,
            waiting_at_start_count=1,
            arrival_key="arrival",
            departure_key="departure",
        )
        # 8:10 +B → 2; 8:15 +C → 3; 8:30 -A → 2; peak 3
        assert replay["peak_waiting"] == 3

    def test_departure_only_reduces_existing_queue(self):
        bags = [
            _bag("X", arrival=None, departure=datetime(2026, 7, 30, 8, 30)),
        ]
        replay = replay_peak_and_starved(
            bags,
            interval_start=datetime(2026, 7, 30, 8, 0),
            interval_end=datetime(2026, 7, 30, 9, 0),
            waiting_at_start_count=0,
            arrival_key="arrival",
            departure_key="departure",
        )
        assert replay["peak_waiting"] == 0
        assert replay["excluded_departures"] == 1

    def test_oos_departure_excluded(self):
        dep, oos = effective_departure(
            datetime(2026, 7, 30, 9, 0), datetime(2026, 7, 30, 8, 0)
        )
        assert dep is None and oos is True


class TestWorkStarved:
    def test_starved_begins_at_zero_and_stops_on_arrival(self):
        bags = [
            _bag("A", arrival=datetime(2026, 7, 30, 8, 0), departure=datetime(2026, 7, 30, 8, 42)),
            _bag("B", arrival=datetime(2026, 7, 30, 8, 55), departure=None),
        ]
        replay = replay_peak_and_starved(
            bags,
            interval_start=datetime(2026, 7, 30, 8, 0),
            interval_end=datetime(2026, 7, 30, 9, 0),
            waiting_at_start_count=1,
            arrival_key="arrival",
            departure_key="departure",
        )
        # starved 8:42–8:55 = 13 minutes
        assert replay["work_starved_minutes"] == 13

    def test_multiple_empty_periods_summed(self):
        bags = [
            _bag("A", arrival=datetime(2026, 7, 30, 8, 0), departure=datetime(2026, 7, 30, 8, 10)),
            _bag("B", arrival=datetime(2026, 7, 30, 8, 20), departure=datetime(2026, 7, 30, 8, 30)),
            _bag("C", arrival=datetime(2026, 7, 30, 8, 50), departure=None),
        ]
        replay = replay_peak_and_starved(
            bags,
            interval_start=datetime(2026, 7, 30, 8, 0),
            interval_end=datetime(2026, 7, 30, 9, 0),
            waiting_at_start_count=1,
            arrival_key="arrival",
            departure_key="departure",
        )
        # 8:10–8:20 (10) + 8:30–8:50 (20) = 30
        assert replay["work_starved_minutes"] == 30

    def test_continuously_nonempty_zero_starved(self):
        bags = [
            _bag("A", arrival=datetime(2026, 7, 30, 7, 50), departure=None),
            _bag("B", arrival=datetime(2026, 7, 30, 8, 10), departure=None),
        ]
        replay = replay_peak_and_starved(
            bags,
            interval_start=datetime(2026, 7, 30, 8, 0),
            interval_end=datetime(2026, 7, 30, 9, 0),
            waiting_at_start_count=1,
            arrival_key="arrival",
            departure_key="departure",
        )
        assert replay["work_starved_minutes"] == 0

    def test_empty_entire_interval(self):
        replay = replay_peak_and_starved(
            [],
            interval_start=datetime(2026, 7, 30, 8, 0),
            interval_end=datetime(2026, 7, 30, 9, 0),
            waiting_at_start_count=0,
            arrival_key="arrival",
            departure_key="departure",
        )
        assert replay["work_starved_minutes"] == 60


class TestTodayTruncationAndFuture:
    def test_slot_truncates_at_analysis_end(self):
        bags = [
            _bag("A", arrival=datetime(2026, 7, 30, 8, 0), departure=None),
        ]
        slot = build_queue_slot(
            bags,
            slot_index=1,
            interval_start=datetime(2026, 7, 30, 8, 0),
            interval_end=datetime(2026, 7, 30, 10, 0),
            analysis_end=datetime(2026, 7, 30, 9, 0),
            arrival_key="arrival",
            departure_key="departure",
            stage_id="washing_queue",
            labels={"newly_available": "Newly Sorted", "processed": "Washed", "waiting": "Waiting"},
            incomplete=True,
        )
        assert slot["interval_end_et"] == datetime(2026, 7, 30, 9, 0)
        assert slot["incomplete_interval"] is True
        assert slot["waiting_at_end"] == 1


class TestDetailReconcileAndStatus:
    def test_detail_counts_reconcile(self):
        bags = [
            _bag("A", arrival=datetime(2026, 7, 30, 7, 50), departure=datetime(2026, 7, 30, 8, 20)),
            _bag("B", arrival=datetime(2026, 7, 30, 8, 15), departure=None),
        ]
        slot = build_queue_slot(
            bags,
            slot_index=1,
            interval_start=datetime(2026, 7, 30, 8, 0),
            interval_end=datetime(2026, 7, 30, 9, 0),
            analysis_end=datetime(2026, 7, 30, 23, 59, 59),
            arrival_key="arrival",
            departure_key="departure",
            stage_id="drying_queue",
            labels={},
            incomplete=False,
        )
        assert len(slot["bags_available"]) == slot["newly_available_count"]
        assert len(slot["bags_processed"]) == slot["processed_count"]
        assert len(slot["bags_waiting"]) == slot["waiting_at_end"]
        assert slot["reconciliation"]["reconciles"] is True

    def test_deficit_and_capacity_labels(self):
        d = classify_excess_deficit(
            stage_id="washing_queue", waiting_at_end=3, work_starved_minutes=0
        )
        assert d["status"] == "deficit"
        assert "Wash deficit — 3" in d["label"]
        c = classify_excess_deficit(
            stage_id="folding_queue", waiting_at_end=0, work_starved_minutes=15
        )
        assert c["status"] == "capacity_available"
        assert "Folder capacity" in c["label"]
        b = classify_excess_deficit(
            stage_id="drying_queue", waiting_at_end=0, work_starved_minutes=0
        )
        assert b["label"] == "Balanced"


class TestFoldingCapacity:
    def test_target_unit_is_pounds_per_hour(self):
        assert DEFAULT_LBS_PER_HOUR == 40.0
        rec = folder_capacity_recommendation(
            available_bags=2,
            available_pounds=80.0,
            pounds_complete=True,
            interval_hours=1.0,
            lbs_per_hour_target=40.0,
        )
        assert rec["target_unit"] == "pounds_per_hour"
        assert rec["full_additional_folders"] == 2  # floor(80/40)
        assert rec["recommendation_code"] == "add_2"

    def test_uses_pounds_not_bag_count(self):
        rec = folder_capacity_recommendation(
            available_bags=10,
            available_pounds=30.0,
            pounds_complete=True,
            interval_hours=1.0,
            lbs_per_hour_target=40.0,
        )
        # 30 lbs < 40 → floor 0 despite 10 bags
        assert rec["full_additional_folders"] == 0
        assert rec["recommendation_code"] in ("none", "partial")

    def test_incomplete_pounds_no_guessed_conversion(self):
        rec = folder_capacity_recommendation(
            available_bags=5,
            available_pounds=20.0,
            pounds_complete=False,
            interval_hours=1.0,
            lbs_per_hour_target=40.0,
        )
        assert rec["full_additional_folders"] is None
        assert rec["recommendation_code"] == "insufficient_pounds"
        assert "no bag-count conversion" in (rec["note"] or "").lower()

    def test_floor_additional_folders(self):
        rec = folder_capacity_recommendation(
            available_bags=3,
            available_pounds=99.0,
            pounds_complete=True,
            interval_hours=1.0,
            lbs_per_hour_target=40.0,
        )
        assert rec["full_additional_folders"] == 2  # floor(99/40)=2
        assert rec["recommendation_code"] == "add_2"


class TestReadOnlyFlags:
    def test_queue_slot_non_negative(self):
        slot = build_queue_slot(
            [],
            slot_index=1,
            interval_start=datetime(2026, 7, 30, 8, 0),
            interval_end=datetime(2026, 7, 30, 9, 0),
            analysis_end=datetime(2026, 7, 30, 23, 59, 59),
            arrival_key="arrival",
            departure_key="departure",
            stage_id="washing_queue",
            labels={},
            incomplete=False,
        )
        for k in (
            "newly_available_count",
            "processed_count",
            "waiting_at_start",
            "waiting_at_end",
            "peak_waiting",
            "work_starved_minutes",
        ):
            assert slot[k] >= 0
