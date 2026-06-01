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
        assert evaluate_order_reject_no_start_cleaning_after_limit(timeline, window_minutes=10) is None

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

    def test_no_exception_when_clean_rack_before_processed_by_vendor(self):
        timeline = gaming_events_from_records(
            [
                _ev("move-bag", datetime(2026, 5, 28, 13, 50), ev_id=1, rack="VeeWash Clean"),
                _ev("processed-by-vendor", datetime(2026, 5, 28, 14, 0), ev_id=2, scan_index=2),
                _ev("move-bag", datetime(2026, 5, 28, 14, 10), ev_id=3, scan_index=3, rack="Folding-4-VW"),
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
        assert out["completion_evidence_kind"] == "processed-by-vendor"

    def test_exception_received_from_vendor_without_clean(self):
        timeline = gaming_events_from_records(
            [
                _ev("received-from-vendor", datetime(2026, 5, 28, 16, 0), ev_id=1),
            ]
        )
        out = evaluate_completed_without_final_clean_scan(timeline)
        assert out is not None
        assert out["completion_evidence_kind"] == "received-from-vendor"

    def test_exception_weight_after_processed_without_clean(self):
        timeline = gaming_events_from_records(
            [
                _ev("processed-by-vendor", datetime(2026, 5, 28, 14, 0), ev_id=1),
                _ev("weight-entry", datetime(2026, 5, 28, 14, 30), ev_id=2, scan_index=2),
            ]
        )
        out = evaluate_completed_without_final_clean_scan(timeline)
        assert out is not None
        assert out["completion_evidence_kind"] == "processed-by-vendor"

    def test_exception_quality_control_completed_without_clean(self):
        timeline = gaming_events_from_records(
            [
                _ev("quality-control-completed", datetime(2026, 5, 28, 15, 0), ev_id=1),
            ]
        )
        out = evaluate_completed_without_final_clean_scan(timeline)
        assert out is not None
        assert out["completion_evidence_kind"] == "quality-control-completed"

    def test_rack_match_case_insensitive_with_prefix_suffix(self):
        for rack in ("CLEAN", "CLEAN-01", "FINAL CLEAN", "RACK CLEAN A", "ABC-CLEAN-XYZ"):
            timeline = gaming_events_from_records(
                [
                    _ev("PROCESSED BY VENDOR", datetime(2026, 5, 28, 14, 0), ev_id=1),
                    _ev("", datetime(2026, 5, 28, 14, 5), ev_id=2, scan_index=2, rack=rack),
                ]
            )
            assert evaluate_completed_without_final_clean_scan(timeline) is None


class TestBag00CY9RP1K6Regression:
    """Late start-cleaning after sorting window but full wash/completion path."""

    def _timeline(self):
        return gaming_events_from_records(
            [
                _ev("sent-to-vendor", datetime(2026, 5, 31, 0, 30), ev_id=1, rack="VeeWash Dirty"),
                _ev("weight-entry", datetime(2026, 5, 31, 7, 13), ev_id=2, scan_index=2, rack=""),
                _ev("add-photos", datetime(2026, 5, 31, 8, 23), ev_id=3, scan_index=3, rack=""),
                _ev("ready-washer", datetime(2026, 5, 31, 8, 23), ev_id=4, scan_index=4, rack=""),
                _ev("start-cleaning", datetime(2026, 5, 31, 11, 51), ev_id=5, scan_index=5, rack="W26-30-VW"),
                _ev("drying", datetime(2026, 5, 31, 11, 52), ev_id=6, scan_index=6, rack="D37-50-VW"),
                _ev("complete-cleaning", datetime(2026, 5, 31, 13, 30), ev_id=7, scan_index=7, rack="Folding-5-VW"),
                _ev("garments-reviewed", datetime(2026, 5, 31, 13, 30), ev_id=8, scan_index=8, rack=""),
                _ev("assembly-printed-ct", datetime(2026, 5, 31, 14, 4), ev_id=9, scan_index=9, rack=""),
                _ev("processed-by-vendor", datetime(2026, 5, 31, 14, 11), ev_id=10, scan_index=10, rack=""),
                _ev("move-bag", datetime(2026, 5, 31, 14, 12), ev_id=11, scan_index=11, rack="VeeWash Clean"),
            ]
        )

    def test_no_reject_operational_exceptions(self):
        timeline = self._timeline()
        assert evaluate_order_reject_no_start_cleaning_after_limit(timeline, window_minutes=30) is None
        profile = evaluate_bag_operational_profile(timeline, bag_meta={"bag_id": "00CY9RP1K6"})
        assert profile["exception_codes"] == []
        assert evaluate_completed_without_final_clean_scan(timeline) is None

    def test_lifecycle_folded_completed(self):
        from backend.rinse_bag_lifecycle_status import (
            FOLDED_COMPLETED,
            ORDER_REJECTED_FULL,
            derive_bag_lifecycle_status,
        )
        from backend.rinse_shift_operational_exceptions import (
            COMPLETED_WITHOUT_FINAL_CLEAN_SCAN,
            ORDER_REJECT_NO_START_CLEANING_AFTER_LIMIT,
        )

        events = [
            {"purpose": p, "rack": r, "scanned_at_parsed": t, "user_name": "Staff", "id": i, "scan_index": i}
            for i, (p, r, t) in enumerate(
                [
                    ("sent-to-vendor", "VeeWash Dirty", datetime(2026, 5, 31, 0, 30)),
                    ("weight-entry", None, datetime(2026, 5, 31, 7, 13)),
                    ("ready-washer", None, datetime(2026, 5, 31, 8, 23)),
                    ("start-cleaning", "W26-30-VW", datetime(2026, 5, 31, 11, 51)),
                    ("drying", "D37-50-VW", datetime(2026, 5, 31, 11, 52)),
                    ("complete-cleaning", "Folding-5-VW", datetime(2026, 5, 31, 13, 30)),
                    ("processed-by-vendor", None, datetime(2026, 5, 31, 14, 11)),
                    ("move-bag", "VeeWash Clean", datetime(2026, 5, 31, 14, 12)),
                ],
                start=1,
            )
        ]
        out = derive_bag_lifecycle_status(events, bag_id="00CY9RP1K6")
        assert out["current_lifecycle_status"] == FOLDED_COMPLETED
        flags = out["exception_flags"]
        assert ORDER_REJECT_NO_START_CLEANING_AFTER_LIMIT not in flags
        assert ORDER_REJECTED_FULL not in flags
        assert COMPLETED_WITHOUT_FINAL_CLEAN_SCAN not in flags


class TestWorkitemEligibleAfterValidWeightEntry:
    """Workitem counts only after first post-anchor weight-entry."""

    def test_workitem_before_sent_to_vendor_ignored(self):
        timeline = gaming_events_from_records(
            [
                _ev("workitems-added", datetime(2026, 5, 28, 21, 22), ev_id=1),
                _ev("sent-to-vendor", datetime(2026, 5, 29, 18, 47), ev_id=2, scan_index=2),
                _ev("weight-entry", datetime(2026, 5, 30, 11, 2), ev_id=3, scan_index=3, rack=""),
            ]
        )
        stats = bag_workitem_issue_stats(timeline)
        assert stats["has_workitem"] is False
        assert stats["create_workitem_count"] == 0

    def test_workitem_after_vendor_before_weight_ignored(self):
        timeline = gaming_events_from_records(
            [
                _ev("sent-to-vendor", datetime(2026, 5, 29, 18, 47), ev_id=1),
                _ev("create-workitem", datetime(2026, 5, 29, 19, 0), ev_id=2, scan_index=2),
                _ev("weight-entry", datetime(2026, 5, 30, 11, 2), ev_id=3, scan_index=3, rack=""),
            ]
        )
        stats = bag_workitem_issue_stats(timeline)
        assert stats["has_workitem"] is False
        assert stats["create_workitem_count"] == 0

    def test_workitem_after_valid_weight_entry_counted(self):
        timeline = gaming_events_from_records(
            [
                _ev("workitems-added", datetime(2026, 5, 28, 21, 22), ev_id=1),
                _ev("sent-to-vendor", datetime(2026, 5, 29, 18, 47), ev_id=2, scan_index=2),
                _ev("weight-entry", datetime(2026, 5, 30, 11, 2), ev_id=3, scan_index=3, rack=""),
                _ev("create-workitem", datetime(2026, 5, 30, 11, 15), ev_id=4, scan_index=4),
            ]
        )
        stats = bag_workitem_issue_stats(timeline)
        assert stats["has_workitem"] is True
        assert stats["create_workitem_count"] == 1

    def test_create_bulk_workitem_after_valid_weight_entry_counted(self):
        timeline = gaming_events_from_records(
            [
                _ev("sent-to-vendor", datetime(2026, 5, 29, 18, 47), ev_id=1),
                _ev("weight-entry", datetime(2026, 5, 30, 11, 2), ev_id=2, scan_index=2, rack=""),
                _ev("create-bulk-workitem", datetime(2026, 5, 30, 11, 20), ev_id=3, scan_index=3),
            ]
        )
        stats = bag_workitem_issue_stats(timeline)
        assert stats["has_bulk_workitem"] is True
        assert stats["create_bulk_workitem_count"] == 1


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
                    _ev("sent-to-vendor", datetime(2026, 5, 28, 8, 0), ev_id=1),
                    _ev("weight-entry", datetime(2026, 5, 28, 9, 0), ev_id=2, scan_index=2),
                    _ev("create-workitem", datetime(2026, 5, 28, 9, 5), ev_id=3, scan_index=3),
                    _ev("create-issue", datetime(2026, 5, 28, 9, 6), ev_id=4, scan_index=4),
                ],
                bag_meta={"bag_id": "B1", "rush": True},
            )
        ]
        stats = aggregate_operational_stats(records)
        assert stats["bags_with_issues"] == 1
        assert stats["bags_with_workitems"] == 1
