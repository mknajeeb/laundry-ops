"""Tests for Wash & Fold bag gaming / performance stage timings."""

from datetime import datetime
from unittest.mock import patch

from backend.rinse_bag_folding import STATUS_CALCULATED, FoldingResult
from backend.rinse_bag_gaming_performance import (
    DRYING_PURPOSE_MISSING,
    STAGE_COMPLETED,
    STAGE_EXCEPTION,
    WEIGHING_START_CLEANING_MISSING,
    WEIGHING_START_SCAN_MISSING,
    WEIGHT_ENTRY_MISSING,
    WashLoadLimits,
    aggregate_daily_workitem_issue_indicators,
    evaluate_bag_gaming_performance,
    evaluate_load_dryer_stage,
    evaluate_load_washer_stage,
    evaluate_sorting_stage,
    evaluate_wash_load_stage,
    evaluate_weighing_stage,
    gaming_events_from_records,
)
from backend.rinse_processing_settings import DEFAULT_DRYING_MINUTES, DEFAULT_WASHING_MINUTES


def _ev(purpose, at, *, scan_index=1, ev_id=1, rack="Scale"):
    return {
        "id": ev_id,
        "rack": rack,
        "user_name": "Alex",
        "purpose": purpose,
        "scanned_at_parsed": at,
        "scan_index": scan_index,
    }


def _anchored_weight_events(*extra):
    base = [
        _ev("sent-to-vendor", datetime(2026, 5, 27, 8, 0), ev_id=1),
    ]
    base.extend(extra)
    return base


class TestWeighingStage:
    def test_weighing_starts_at_exact_cleaning_before_post_anchor_weight(self):
        events = _anchored_weight_events(
            _ev("cleaning", datetime(2026, 5, 27, 8, 50), ev_id=2, scan_index=2),
            _ev("cleaning", datetime(2026, 5, 27, 8, 55), ev_id=3, scan_index=3),
            _ev("weight-entry", datetime(2026, 5, 27, 9, 0), ev_id=4, scan_index=4),
        )
        weighing = evaluate_weighing_stage(gaming_events_from_records(events))
        assert weighing.status == STAGE_COMPLETED
        assert weighing.start_time == datetime(2026, 5, 27, 8, 55)
        assert weighing.end_time == datetime(2026, 5, 27, 9, 0)
        assert weighing.duration_seconds == 300

    def test_weighing_does_not_use_broad_cleaning_related_purpose(self):
        events = _anchored_weight_events(
            _ev("pre-cleaning", datetime(2026, 5, 27, 8, 55), ev_id=2, scan_index=2),
            _ev("weight-entry", datetime(2026, 5, 27, 9, 0), ev_id=3, scan_index=3),
        )
        weighing = evaluate_weighing_stage(gaming_events_from_records(events))
        assert weighing.status == STAGE_EXCEPTION
        assert WEIGHING_START_CLEANING_MISSING in weighing.exception_codes

    def test_pre_anchor_weight_ignored(self):
        events = [
            _ev("weight-entry", datetime(2026, 5, 27, 7, 50), ev_id=1),
            _ev("sent-to-vendor", datetime(2026, 5, 27, 8, 0), ev_id=2, scan_index=2),
            _ev("cleaning", datetime(2026, 5, 27, 8, 55), ev_id=3, scan_index=3),
            _ev("weight-entry", datetime(2026, 5, 27, 9, 0), ev_id=4, scan_index=4),
        ]
        weighing = evaluate_weighing_stage(gaming_events_from_records(events))
        assert weighing.status == STAGE_COMPLETED
        assert weighing.end_time == datetime(2026, 5, 27, 9, 0)

    def test_weighing_missing_exact_cleaning(self):
        events = _anchored_weight_events(
            _ev("weight-entry", datetime(2026, 5, 27, 9, 0), ev_id=2, scan_index=2),
        )
        weighing = evaluate_weighing_stage(gaming_events_from_records(events))
        assert WEIGHING_START_SCAN_MISSING in weighing.exception_codes

    def test_weighing_missing_weight_entry(self):
        events = _anchored_weight_events(
            _ev("cleaning", datetime(2026, 5, 27, 9, 0), ev_id=2, scan_index=2),
        )
        weighing = evaluate_weighing_stage(gaming_events_from_records(events))
        assert WEIGHT_ENTRY_MISSING in weighing.exception_codes


class TestSortingStage:
    def test_sorting_uses_lifecycle_boundary(self):
        events = _anchored_weight_events(
            _ev("cleaning", datetime(2026, 5, 27, 8, 55), ev_id=2, scan_index=2),
            _ev("weight-entry", datetime(2026, 5, 27, 9, 0), ev_id=3, scan_index=3),
            _ev("add-photos", datetime(2026, 5, 27, 9, 3), ev_id=4, scan_index=4),
            _ev("create-issue", datetime(2026, 5, 27, 9, 4, 30), ev_id=5, scan_index=5),
            _ev("start-cleaning", datetime(2026, 5, 27, 9, 10), ev_id=6, scan_index=6),
        )
        sorting = evaluate_sorting_stage(gaming_events_from_records(events))
        assert sorting.status == STAGE_COMPLETED
        assert sorting.start_time == datetime(2026, 5, 27, 8, 55)
        assert sorting.end_time == datetime(2026, 5, 27, 9, 4, 30)
        assert sorting.end_event_purpose == "create-issue"

    def test_sorting_start_uses_cleaning_before_add_photos(self):
        events = _anchored_weight_events(
            _ev("cleaning", datetime(2026, 5, 27, 8, 55), ev_id=2, scan_index=2),
            _ev("weight-entry", datetime(2026, 5, 27, 9, 0), ev_id=3, scan_index=3),
            _ev("add-photos", datetime(2026, 5, 27, 9, 5), ev_id=4, scan_index=4),
            _ev("start-cleaning", datetime(2026, 5, 27, 9, 10), ev_id=5, scan_index=5),
        )
        sorting = evaluate_sorting_stage(gaming_events_from_records(events))
        assert sorting.start_time == datetime(2026, 5, 27, 8, 55)
        assert sorting.end_time == datetime(2026, 5, 27, 9, 5)
        assert sorting.end_event_purpose == "add-photos"


class TestLoadWasherAndDryerPerformance:
    def test_load_washer_performance_stage(self):
        events = _anchored_weight_events(
            _ev("start-cleaning", datetime(2026, 5, 27, 10, 0), ev_id=2, scan_index=2),
            _ev("ready-washer", datetime(2026, 5, 27, 10, 10), ev_id=3, scan_index=3),
            _ev("washer-settings", datetime(2026, 5, 27, 10, 15), ev_id=4, scan_index=4),
        )
        stage = evaluate_load_washer_stage(gaming_events_from_records(events))
        assert stage.status == STAGE_COMPLETED
        assert stage.start_time == datetime(2026, 5, 27, 10, 0)
        assert stage.end_time == datetime(2026, 5, 27, 10, 15)

    def test_load_dryer_is_instant(self):
        events = _anchored_weight_events(
            _ev("start-cleaning", datetime(2026, 5, 27, 10, 0), ev_id=2, scan_index=2),
            _ev("drying", datetime(2026, 5, 27, 11, 0), ev_id=3, scan_index=3),
        )
        stage = evaluate_load_dryer_stage(gaming_events_from_records(events))
        assert stage.status == STAGE_COMPLETED
        assert stage.duration_seconds == 0
        assert stage.start_time == stage.end_time


class TestWashLoadStage:
    def test_wash_load_on_anchored_timeline(self):
        events = _anchored_weight_events(
            _ev("start-cleaning", datetime(2026, 5, 27, 10, 0), ev_id=2, scan_index=2),
            _ev("drying", datetime(2026, 5, 27, 11, 0), ev_id=3, scan_index=3),
        )
        wl = evaluate_wash_load_stage(gaming_events_from_records(events))
        assert wl.status == STAGE_COMPLETED
        assert wl.duration_seconds == 3600

    def test_wash_load_drying_missing_is_exception(self):
        events = _anchored_weight_events(
            _ev("start-cleaning", datetime(2026, 5, 27, 10, 0), ev_id=2, scan_index=2),
        )
        wl = evaluate_wash_load_stage(gaming_events_from_records(events))
        assert DRYING_PURPOSE_MISSING in wl.exception_codes


class TestDefaults:
    def test_processing_settings_defaults(self):
        assert DEFAULT_WASHING_MINUTES == 30
        assert DEFAULT_DRYING_MINUTES == 45


class TestDailyIndicators:
    def test_aggregate_workitem_issue_counts(self):
        bag1 = _anchored_weight_events(
            _ev("weight-entry", datetime(2026, 5, 27, 9, 0), ev_id=2, scan_index=2),
            _ev("create-workitem", datetime(2026, 5, 27, 9, 2), ev_id=3, scan_index=3),
            _ev("create-issue", datetime(2026, 5, 27, 9, 3), ev_id=4, scan_index=4),
        )
        agg = aggregate_daily_workitem_issue_indicators(
            [gaming_events_from_records(bag1)]
        )
        assert agg["total_create_workitems"] == 1
        assert agg["total_create_issues"] == 1


class TestFoldingIntegration:
    def test_uses_existing_folding_logic_unchanged(self):
        events = _anchored_weight_events(
            _ev("cleaning", datetime(2026, 5, 27, 8, 55), ev_id=2, scan_index=2),
            _ev("weight-entry", datetime(2026, 5, 27, 9, 0), ev_id=3, scan_index=3),
            _ev("start-cleaning", datetime(2026, 5, 27, 9, 10), ev_id=4, scan_index=4),
            _ev("drying", datetime(2026, 5, 27, 9, 50), ev_id=5, scan_index=5),
            {
                "id": 10,
                "rack": "FOLDING",
                "user_name": "Alex",
                "purpose": "fold",
                "scanned_at_parsed": datetime(2026, 5, 27, 10, 0),
                "scan_index": 10,
            },
            {
                "id": 11,
                "rack": "CLEAN",
                "user_name": "Alex",
                "purpose": "clean",
                "scanned_at_parsed": datetime(2026, 5, 27, 10, 20),
                "scan_index": 11,
            },
        )
        mock_fold = FoldingResult(
            status=STATUS_CALCULATED,
            exception_code=None,
            folding_start_at=datetime(2026, 5, 27, 10, 0),
            folding_end_at=datetime(2026, 5, 27, 10, 20),
            duration_seconds=1200,
            folding_start_event_id=10,
            folding_end_event_id=11,
            folding_start_rack="FOLDING",
            folding_end_rack="CLEAN",
            assigned_user_name="Alex",
            assigned_user_name_source="FOLDING_SCAN",
            folding_scan_count=1,
            clean_scan_count=1,
            work_date=datetime(2026, 5, 27).date(),
        )
        with patch(
            "backend.rinse_bag_gaming_performance.evaluate_folding_performance_for_bag",
            return_value=mock_fold,
        ) as fold_fn:
            out = evaluate_bag_gaming_performance(events)
            fold_fn.assert_called_once_with(events, registry_row=None, rules=None)

        assert out["weighing"]["start_time"] == datetime(2026, 5, 27, 8, 55)
        assert out["load_washer"]["status"] == STAGE_EXCEPTION
        assert out["folding"]["duration_seconds"] == 1200
