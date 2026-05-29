"""Tests for rinse_bag_lifecycle_status engine."""

from datetime import datetime

from backend.rinse_bag_completion import COMPLETION_COMPLETED
from backend.rinse_bag_gaming_performance import evaluate_sorting_stage, gaming_events_from_records
from backend.rinse_bag_lifecycle_status import (
    ASSIGNED_NOT_SENT_TO_VENDOR,
    FOLDED_COMPLETED,
    IN_DRYING,
    IN_WASHING,
    PENDING_WEIGHING,
    RETURNED_TO_RINSE,
    SENT_TO_VENDOR,
    SORTED_READY_FOR_WASH,
    WEIGHED_NOT_STARTED,
    derive_bag_lifecycle_status,
    operational_flags_from_timeline,
)
from backend.rinse_shift_operational_exceptions import (
    COMPLETED_WITHOUT_FINAL_CLEAN_SCAN,
    ORDER_REJECT_NO_START_CLEANING_AFTER_LIMIT,
    evaluate_order_reject_no_start_cleaning_after_limit,
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


class TestLifecycleStatuses:
    def test_assigned_not_sent_with_ready_for_vendor_presence(self):
        out = derive_bag_lifecycle_status(
            [],
            bag_id="BAG1",
            ready_for_vendor_presence=True,
        )
        assert out["current_lifecycle_status"] == ASSIGNED_NOT_SENT_TO_VENDOR

    def test_sent_to_vendor_via_at_vendor_presence(self):
        out = derive_bag_lifecycle_status(
            [],
            bag_id="BAG2",
            at_vendor_presence=True,
        )
        assert out["current_lifecycle_status"] == SENT_TO_VENDOR

    def test_pending_weighing_with_sent_to_vendor_scan(self):
        events = [_ev("sent-to-vendor", datetime(2026, 5, 28, 8, 0), ev_id=1)]
        out = derive_bag_lifecycle_status(events, bag_id="BAG3", at_vendor_presence=True)
        assert out["current_lifecycle_status"] == PENDING_WEIGHING

    def test_weighed_not_started(self):
        events = [
            _ev("sent-to-vendor", datetime(2026, 5, 28, 8, 0), ev_id=1),
            _ev("weight-entry", datetime(2026, 5, 28, 8, 10), ev_id=2, scan_index=2),
        ]
        out = derive_bag_lifecycle_status(events, bag_id="BAG4", at_vendor_presence=True)
        assert out["current_lifecycle_status"] == WEIGHED_NOT_STARTED

    def test_sorted_ready_for_wash_with_create_issue_flag(self):
        events = [
            _ev("sent-to-vendor", datetime(2026, 5, 28, 8, 0), ev_id=1),
            _ev("weight-entry", datetime(2026, 5, 28, 8, 10), ev_id=2, scan_index=2),
            _ev("create-issue", datetime(2026, 5, 28, 8, 20), ev_id=3, scan_index=3),
        ]
        out = derive_bag_lifecycle_status(events, bag_id="BAG5", at_vendor_presence=True)
        assert out["current_lifecycle_status"] == SORTED_READY_FOR_WASH
        assert out["operational_flags"]["has_create_issue"] is True
        assert ORDER_REJECT_NO_START_CLEANING_AFTER_LIMIT not in out["exception_flags"]

    def test_sorted_ready_for_wash_with_bulk_workitem(self):
        events = [
            _ev("weight-entry", datetime(2026, 5, 28, 9, 0), ev_id=1),
            _ev("create-bulk-workitem", datetime(2026, 5, 28, 9, 5), ev_id=2, scan_index=2),
        ]
        out = derive_bag_lifecycle_status(
            events, bag_id="BAG5B", at_vendor_presence=True
        )
        assert out["current_lifecycle_status"] == SORTED_READY_FOR_WASH
        assert out["operational_flags"]["has_create_bulk_workitem"] is True

    def test_in_washing(self):
        events = [
            _ev("weight-entry", datetime(2026, 5, 28, 9, 0), ev_id=1),
            _ev("start-cleaning", datetime(2026, 5, 28, 9, 30), ev_id=2, scan_index=2),
        ]
        out = derive_bag_lifecycle_status(events, bag_id="BAG6", at_vendor_presence=True)
        assert out["current_lifecycle_status"] == IN_WASHING

    def test_in_drying(self):
        events = [
            _ev("start-cleaning", datetime(2026, 5, 28, 9, 0), ev_id=1),
            _ev("drying", datetime(2026, 5, 28, 10, 0), ev_id=2, scan_index=2),
        ]
        out = derive_bag_lifecycle_status(events, bag_id="BAG7", at_vendor_presence=True)
        assert out["current_lifecycle_status"] == IN_DRYING

    def test_folded_completed_from_registry(self):
        events = [
            _ev("", datetime(2026, 5, 28, 12, 0), ev_id=1, rack="FINAL CLEAN"),
        ]
        out = derive_bag_lifecycle_status(
            events,
            bag_id="BAG8",
            registry_row={
                "completion_status": COMPLETION_COMPLETED,
                "completed_at": datetime(2026, 5, 28, 12, 0),
            },
        )
        assert out["current_lifecycle_status"] == FOLDED_COMPLETED

    def test_returned_to_rinse_via_logistics(self):
        out = derive_bag_lifecycle_status(
            [],
            bag_id="BAG9",
            logistics_status="SENT_TO_RINSE",
            registry_row={"completion_status": COMPLETION_COMPLETED},
        )
        assert out["current_lifecycle_status"] == RETURNED_TO_RINSE

    def test_returned_to_rinse_via_received_from_vendor(self):
        events = [_ev("received-from-vendor", datetime(2026, 5, 28, 15, 0), ev_id=1)]
        out = derive_bag_lifecycle_status(
            events,
            bag_id="BAG10",
            registry_row={"completion_status": COMPLETION_COMPLETED},
        )
        assert out["current_lifecycle_status"] == RETURNED_TO_RINSE


class TestOperationalAndExceptionSeparation:
    def test_operational_flags_not_exceptions(self):
        events = [
            _ev("weight-entry", datetime(2026, 5, 28, 9, 0), ev_id=1),
            _ev("create-workitem", datetime(2026, 5, 28, 9, 5), ev_id=2, scan_index=2),
        ]
        timeline = gaming_events_from_records(events)
        flags = operational_flags_from_timeline(timeline)
        assert flags["has_create_workitem"] is True
        out = derive_bag_lifecycle_status(events, bag_id="BAGW", at_vendor_presence=True)
        assert out["current_lifecycle_status"] == SORTED_READY_FOR_WASH
        assert out["operational_flags"]["has_create_workitem"] is True
        assert out["operational_flags"]["has_create_issue"] is False

    def test_reject_exception_separate_from_lifecycle(self):
        events = [
            _ev("weight-entry", datetime(2026, 5, 28, 9, 0), ev_id=1),
            _ev("create-bulk-workitem", datetime(2026, 5, 28, 9, 5), ev_id=2, scan_index=2),
        ]
        out = derive_bag_lifecycle_status(events, bag_id="BAGR", at_vendor_presence=True)
        assert out["current_lifecycle_status"] == SORTED_READY_FOR_WASH
        assert ORDER_REJECT_NO_START_CLEANING_AFTER_LIMIT in out["exception_flags"]
        timeline = gaming_events_from_records(events)
        assert evaluate_order_reject_no_start_cleaning_after_limit(timeline) is not None

    def test_processed_by_vendor_exception_not_completion(self):
        events = [
            _ev("processed by vendor", datetime(2026, 5, 28, 14, 0), ev_id=1),
            _ev("", datetime(2026, 5, 28, 14, 5), ev_id=2, scan_index=2, rack="FOLDING"),
        ]
        out = derive_bag_lifecycle_status(events, bag_id="BAGP", at_vendor_presence=True)
        assert out["current_lifecycle_status"] != FOLDED_COMPLETED
        assert COMPLETED_WITHOUT_FINAL_CLEAN_SCAN in out["exception_flags"]


class TestSortingEndBulkWorkitem:
    def test_bulk_workitem_is_sorting_end_marker_in_lifecycle(self):
        events = [
            _ev("weight-entry", datetime(2026, 5, 28, 9, 0), ev_id=1),
            _ev("create-bulk-workitem", datetime(2026, 5, 28, 9, 4), ev_id=2, scan_index=2),
        ]
        sorting = evaluate_sorting_stage(gaming_events_from_records(events))
        assert sorting.end_event_purpose == "create-bulk-workitem"
