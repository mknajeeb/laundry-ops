"""Tests for shift analysis operational exceptions."""

from datetime import datetime

from backend.rinse_bag_gaming_performance import gaming_events_from_records
from backend.rinse_shift_operational_exceptions import (
    COMPLETED_WITHOUT_FINAL_CLEAN_SCAN,
    ORDER_REJECT_NO_START_CLEANING_AFTER_LIMIT,
    aggregate_operational_stats,
    bag_workitem_issue_stats,
    evaluate_bag_operational_profile,
    evaluate_completed_without_final_clean_scan,
    evaluate_order_reject_no_start_cleaning_after_limit,
    filter_operational_records,
)


def _ev(
    purpose: str,
    at: datetime,
    *,
    user: str = "Alex",
    scan_index: int = 1,
    ev_id: int = 1,
    rack: str = "Scale",
) -> dict:
    return {
        "id": ev_id,
        "rack": rack,
        "user_name": user,
        "purpose": purpose,
        "scanned_at_parsed": at,
        "scan_index": scan_index,
    }


class TestOrderRejectAfterLimit:
    def test_triggers_when_no_start_cleaning_within_limit(self):
        timeline = gaming_events_from_records(
            [
                _ev("weight-entry", datetime(2026, 5, 28, 9, 0), ev_id=1),
                _ev("create-workitem", datetime(2026, 5, 28, 9, 5), ev_id=2, scan_index=2),
            ]
        )
        out = evaluate_order_reject_no_start_cleaning_after_limit(timeline, window_minutes=30)
        assert out is not None
        assert out["exception_code"] == ORDER_REJECT_NO_START_CLEANING_AFTER_LIMIT
        assert out["configured_limit_minutes"] == 30

    def test_respects_custom_limit(self):
        timeline = gaming_events_from_records(
            [
                _ev("weight-entry", datetime(2026, 5, 28, 9, 0), ev_id=1),
                _ev("create-workitem", datetime(2026, 5, 28, 9, 5), ev_id=2, scan_index=2),
                _ev("start-cleaning", datetime(2026, 5, 28, 9, 20), ev_id=3, scan_index=3),
            ]
        )
        assert evaluate_order_reject_no_start_cleaning_after_limit(timeline, window_minutes=30) is None
        assert evaluate_order_reject_no_start_cleaning_after_limit(timeline, window_minutes=10) is not None

    def test_does_not_trigger_when_create_issue_present(self):
        timeline = gaming_events_from_records(
            [
                _ev("weight-entry", datetime(2026, 5, 28, 9, 0), ev_id=1),
                _ev("create-issue", datetime(2026, 5, 28, 9, 5), ev_id=2, scan_index=2),
            ]
        )
        assert evaluate_order_reject_no_start_cleaning_after_limit(timeline) is None

    def test_create_bulk_workitem_does_not_suppress_reject(self):
        timeline = gaming_events_from_records(
            [
                _ev("weight-entry", datetime(2026, 5, 28, 9, 0), ev_id=1),
                _ev("create-bulk-workitem", datetime(2026, 5, 28, 9, 5), ev_id=2, scan_index=2),
            ]
        )
        out = evaluate_order_reject_no_start_cleaning_after_limit(timeline, window_minutes=30)
        assert out is not None
        assert out["exception_code"] == ORDER_REJECT_NO_START_CLEANING_AFTER_LIMIT


class TestCompletedWithoutFinalCleanScan:
    def test_no_exception_when_clean_rack_after_processed_by_vendor(self):
        timeline = gaming_events_from_records(
            [
                _ev("processed by vendor", datetime(2026, 5, 28, 14, 0), ev_id=1),
                _ev("", datetime(2026, 5, 28, 14, 10), ev_id=2, scan_index=2, rack="FINAL CLEAN"),
            ]
        )
        assert evaluate_completed_without_final_clean_scan(timeline) is None

    def test_exception_when_no_clean_rack_after_processed_by_vendor(self):
        timeline = gaming_events_from_records(
            [
                _ev("processed by vendor", datetime(2026, 5, 28, 14, 0), ev_id=1),
                _ev("", datetime(2026, 5, 28, 14, 10), ev_id=2, scan_index=2, rack="FOLDING"),
            ]
        )
        out = evaluate_completed_without_final_clean_scan(timeline)
        assert out is not None
        assert out["exception_code"] == COMPLETED_WITHOUT_FINAL_CLEAN_SCAN

    def test_rack_match_case_insensitive_with_prefix_suffix(self):
        for rack in ("CLEAN", "CLEAN-01", "FINAL CLEAN", "RACK CLEAN A", "ABC-CLEAN-XYZ"):
            timeline = gaming_events_from_records(
                [
                    _ev("PROCESSED BY VENDOR", datetime(2026, 5, 28, 14, 0), ev_id=1),
                    _ev("", datetime(2026, 5, 28, 14, 5), ev_id=2, scan_index=2, rack=rack),
                ]
            )
            assert evaluate_completed_without_final_clean_scan(timeline) is None


class TestOperationalDrilldownFilter:
    def test_filter_by_exception_code(self):
        records = [
            {
                "bag_id": "A",
                "exception_codes": [ORDER_REJECT_NO_START_CLEANING_AFTER_LIMIT],
                "workitem_stats": {},
            },
        ]
        out = filter_operational_records(
            records, drill_filter="order_reject_no_start_cleaning_after_limit"
        )
        assert [r["bag_id"] for r in out] == ["A"]


class TestAggregateOperationalStats:
    def test_aggregate_counts(self):
        records = [
            evaluate_bag_operational_profile(
                [
                    _ev("weight-entry", datetime(2026, 5, 28, 9, 0), ev_id=1),
                    _ev("create-workitem", datetime(2026, 5, 28, 9, 5), ev_id=2, scan_index=2),
                    _ev("create-issue", datetime(2026, 5, 28, 9, 6), ev_id=3, scan_index=3),
                ],
                bag_meta={"bag_id": "B1", "rush": True},
            )
        ]
        stats = aggregate_operational_stats(records)
        assert stats["bags_with_issues"] == 1
        assert stats["bags_with_workitems"] == 1
