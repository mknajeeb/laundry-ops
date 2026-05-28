"""Tests for Wash & Fold bag gaming / performance stage timings."""

from datetime import datetime
from unittest.mock import patch

from backend.rinse_bag_folding import STATUS_CALCULATED, FoldingResult
from backend.rinse_bag_gaming_performance import (
    DRYING_PURPOSE_MISSING,
    SORTING_INTERRUPTED_BY_ISSUE,
    SORTING_INTERRUPTED_BY_WORKITEM,
    STAGE_COMPLETED,
    STAGE_EXCEPTION,
    WEIGHING_START_SCAN_MISSING,
    WEIGHT_ENTRY_MISSING,
    WashLoadLimits,
    aggregate_daily_workitem_issue_indicators,
    evaluate_bag_gaming_performance,
    evaluate_sorting_stage,
    evaluate_wash_load_stage,
    evaluate_weighing_stage,
    gaming_events_from_records,
)


def _ev(purpose, at, *, scan_index=1, ev_id=1, rack="Scale"):
    return {
        "id": ev_id,
        "rack": rack,
        "user_name": "Alex",
        "purpose": purpose,
        "scanned_at_parsed": at,
        "scan_index": scan_index,
    }


class TestWeighingStage:
    def test_weighing_starts_at_last_cleaning_purpose_before_weight_entry(self):
        events = [
            _ev("pre-cleaning", datetime(2026, 5, 27, 8, 50), ev_id=1, rack="Scale"),
            _ev("pre-cleaning", datetime(2026, 5, 27, 8, 55), ev_id=2, rack="Scale"),
            _ev("weight-entry", datetime(2026, 5, 27, 9, 0), ev_id=3),
        ]
        timeline = gaming_events_from_records(events)
        weighing = evaluate_weighing_stage(timeline)
        assert weighing.status == STAGE_COMPLETED
        assert weighing.start_time == datetime(2026, 5, 27, 8, 55)
        assert weighing.end_time == datetime(2026, 5, 27, 9, 0)
        assert weighing.end_event_purpose == "weight-entry"
        assert weighing.duration_seconds == 300

    def test_weighing_ignores_rack_without_cleaning_purpose(self):
        events = [
            _ev("move-bag", datetime(2026, 5, 27, 8, 55), rack="VeeWash Clean"),
            _ev("weight-entry", datetime(2026, 5, 27, 9, 0)),
        ]
        weighing = evaluate_weighing_stage(gaming_events_from_records(events))
        assert weighing.status == STAGE_EXCEPTION
        assert WEIGHING_START_SCAN_MISSING in weighing.exception_codes

    def test_weighing_ends_at_weight_entry(self):
        events = [
            _ev("pre-cleaning", datetime(2026, 5, 27, 9, 0)),
            _ev("weight-entry", datetime(2026, 5, 27, 9, 2)),
        ]
        weighing = evaluate_weighing_stage(gaming_events_from_records(events))
        assert weighing.end_time == datetime(2026, 5, 27, 9, 2)
        assert weighing.end_event_purpose == "weight-entry"

    def test_weighing_missing_cleaning_purpose_before_weight(self):
        events = [_ev("weight-entry", datetime(2026, 5, 27, 9, 0))]
        weighing = evaluate_weighing_stage(gaming_events_from_records(events))
        assert weighing.status == STAGE_EXCEPTION
        assert WEIGHING_START_SCAN_MISSING in weighing.exception_codes

    def test_weighing_missing_weight_entry(self):
        events = [_ev("pre-cleaning", datetime(2026, 5, 27, 9, 0))]
        weighing = evaluate_weighing_stage(gaming_events_from_records(events))
        assert WEIGHT_ENTRY_MISSING in weighing.exception_codes


class TestWashLoadStage:
    def test_wash_load_starts_at_start_cleaning(self):
        events = [
            _ev("start-cleaning", datetime(2026, 5, 27, 10, 0), ev_id=1),
            _ev("drying", datetime(2026, 5, 27, 10, 45), ev_id=2),
        ]
        wl = evaluate_wash_load_stage(gaming_events_from_records(events))
        assert wl.start_time == datetime(2026, 5, 27, 10, 0)
        assert wl.end_event_purpose == "drying"

    def test_wash_load_ends_at_drying(self):
        events = [
            _ev("start-cleaning", datetime(2026, 5, 27, 10, 0), ev_id=1),
            _ev("drying", datetime(2026, 5, 27, 11, 0), ev_id=2),
        ]
        wl = evaluate_wash_load_stage(gaming_events_from_records(events))
        assert wl.end_time == datetime(2026, 5, 27, 11, 0)
        assert wl.duration_seconds == 3600
        assert wl.status == STAGE_COMPLETED

    def test_wash_load_drying_missing_is_exception(self):
        events = [_ev("start-cleaning", datetime(2026, 5, 27, 10, 0))]
        wl = evaluate_wash_load_stage(gaming_events_from_records(events))
        assert wl.status == STAGE_EXCEPTION
        assert DRYING_PURPOSE_MISSING in wl.exception_codes

    def test_wash_load_too_short_when_limits_configured(self):
        events = [
            _ev("start-cleaning", datetime(2026, 5, 27, 10, 0)),
            _ev("drying", datetime(2026, 5, 27, 10, 5)),
        ]
        wl = evaluate_wash_load_stage(
            gaming_events_from_records(events),
            limits=WashLoadLimits(min_seconds=600),
        )
        assert wl.status == STAGE_EXCEPTION
        assert "WASH_LOAD_DURATION_TOO_SHORT" in wl.exception_codes


class TestSortingEndWorkitemIssue:
    def test_create_issue_ends_sorting_without_exception(self):
        events = [
            _ev("weight-entry", datetime(2026, 5, 27, 9, 0), scan_index=1, ev_id=1),
            _ev("create-issue", datetime(2026, 5, 27, 9, 4, 30), scan_index=2, ev_id=2),
        ]
        sorting = evaluate_sorting_stage(gaming_events_from_records(events))
        assert sorting.status == STAGE_COMPLETED
        assert sorting.exception_codes == ()
        assert sorting.end_event_purpose == "create-issue"
        assert sorting.duration_seconds == 270

    def test_last_workitem_or_issue_wins_not_first(self):
        events = [
            _ev("weight-entry", datetime(2026, 5, 27, 9, 0), scan_index=1, ev_id=1),
            _ev("create-workitem", datetime(2026, 5, 27, 9, 2), scan_index=2, ev_id=2),
            _ev("create-issue", datetime(2026, 5, 27, 9, 5), scan_index=3, ev_id=3),
            _ev("create-workitem", datetime(2026, 5, 27, 9, 6), scan_index=4, ev_id=4),
        ]
        sorting = evaluate_sorting_stage(gaming_events_from_records(events))
        assert sorting.end_event_purpose == "create-workitem"
        assert sorting.end_time == datetime(2026, 5, 27, 9, 6)

    def test_no_sorting_interrupted_exception_codes(self):
        events = [
            _ev("weight-entry", datetime(2026, 5, 27, 9, 0)),
            _ev("create-workitem", datetime(2026, 5, 27, 9, 1)),
        ]
        sorting = evaluate_sorting_stage(gaming_events_from_records(events))
        codes = set(sorting.exception_codes)
        assert SORTING_INTERRUPTED_BY_WORKITEM not in codes
        assert SORTING_INTERRUPTED_BY_ISSUE not in codes


class TestSortingEndPriority:
    def test_workitem_beats_split_load(self):
        events = [
            _ev("weight-entry", datetime(2026, 5, 27, 9, 0), ev_id=1),
            _ev("split-load", datetime(2026, 5, 27, 9, 10), ev_id=2),
            _ev("create-issue", datetime(2026, 5, 27, 9, 12), ev_id=3),
        ]
        sorting = evaluate_sorting_stage(gaming_events_from_records(events))
        assert sorting.end_event_purpose == "create-issue"

    def test_late_clean_purpose_does_not_change_sorting_start(self):
        events = [
            _ev("weight-entry", datetime(2026, 5, 27, 9, 0), ev_id=1),
            _ev("start-cleaning", datetime(2026, 5, 27, 9, 10), ev_id=2),
            _ev("post-clean", datetime(2026, 5, 27, 10, 20), ev_id=3, rack="CLEAN"),
        ]
        sorting = evaluate_sorting_stage(gaming_events_from_records(events))
        assert sorting.start_time == datetime(2026, 5, 27, 9, 0)
        assert sorting.end_event_purpose == "start-cleaning"

    def test_sorting_start_from_cleaning_purpose_after_weight(self):
        events = [
            _ev("weight-entry", datetime(2026, 5, 27, 9, 0), ev_id=1),
            _ev("pre-cleaning", datetime(2026, 5, 27, 9, 1), ev_id=2),
            _ev("add-photos", datetime(2026, 5, 27, 9, 10), ev_id=3),
        ]
        sorting = evaluate_sorting_stage(gaming_events_from_records(events))
        assert sorting.start_time == datetime(2026, 5, 27, 9, 1)
        assert sorting.end_event_purpose == "add-photos"


class TestDailyIndicators:
    def test_aggregate_workitem_issue_counts(self):
        bag1 = [
            _ev("weight-entry", datetime(2026, 5, 27, 9, 0)),
            _ev("create-workitem", datetime(2026, 5, 27, 9, 2)),
            _ev("create-issue", datetime(2026, 5, 27, 9, 3)),
        ]
        bag2 = [
            _ev("weight-entry", datetime(2026, 5, 27, 10, 0)),
            _ev("create-issue", datetime(2026, 5, 27, 10, 1)),
        ]
        agg = aggregate_daily_workitem_issue_indicators(
            [gaming_events_from_records(bag1), gaming_events_from_records(bag2)]
        )
        assert agg["total_create_workitems"] == 1
        assert agg["total_create_issues"] == 2
        assert agg["bags_with_workitems"] == 1
        assert agg["bags_with_issues"] == 2


class TestFoldingIntegration:
    def test_uses_existing_folding_logic_unchanged(self):
        events = [
            _ev("pre-cleaning", datetime(2026, 5, 27, 8, 55)),
            _ev("weight-entry", datetime(2026, 5, 27, 9, 0)),
            _ev("start-cleaning", datetime(2026, 5, 27, 9, 10)),
            _ev("drying", datetime(2026, 5, 27, 9, 50)),
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
        ]
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
        assert out["weighing"]["end_time"] == datetime(2026, 5, 27, 9, 0)
        assert out["wash_load"]["start_time"] == datetime(2026, 5, 27, 9, 10)
        assert out["wash_load"]["end_time"] == datetime(2026, 5, 27, 9, 50)
        assert out["wash_load"]["duration_seconds"] == 40 * 60
        assert out["folding"]["duration_seconds"] == 1200
        assert out["folding"]["status"] == STATUS_CALCULATED
        assert out["sorting"]["status"] == STAGE_COMPLETED
