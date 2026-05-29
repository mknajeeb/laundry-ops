"""Tests for revised rinse_bag_lifecycle_status engine."""

from datetime import datetime, timedelta

from backend.rinse_bag_lifecycle_status import (
    ASSIGNED_NOT_SENT_TO_VENDOR,
    FOLDED_COMPLETED,
    IN_DRYING,
    IN_WASHING,
    LOAD_WASHER,
    PENDING_WEIGHING,
    SENT_TO_RINSE,
    SENT_TO_RINSE_CHECKOUT,
    SENT_TO_RINSE_EXTERNAL_USER_AFTER_CLEAN,
    SENT_TO_RINSE_MISSING_FROM_NEXT_PORTAL_SCRAPE,
    SENT_TO_VENDOR,
    SORTED_READY_FOR_WASH,
    WEIGHED_NOT_STARTED,
    derive_bag_lifecycle_status,
    operational_flags_from_timeline,
)
from backend.rinse_bag_gaming_performance import gaming_events_from_records
from backend.rinse_processing_settings import (
    DEFAULT_DRYING_MINUTES,
    DEFAULT_REJECT_AFTER_CREATE_ISSUE,
    DEFAULT_WASHING_MINUTES,
    get_processing_settings,
    put_processing_settings,
)
from backend.rinse_scan_purpose import is_ghost_cleaning_purpose
from backend.rinse_shift_operational_exceptions import (
    COMPLETED_WITHOUT_FINAL_CLEAN_SCAN,
    NEEDS_REVIEW_EXTERNAL_SCAN_AFTER_CLEAN,
    ORDER_REJECTED_FULL,
    SENT_TO_RINSE_WITHOUT_CLEAN_RACK,
    evaluate_order_rejected_full,
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


class TestGhostCleaningPurpose:
    def test_only_exact_cleaning_is_ghost(self):
        assert is_ghost_cleaning_purpose("cleaning") is True
        assert is_ghost_cleaning_purpose("start-cleaning") is False
        assert is_ghost_cleaning_purpose("pre-cleaning") is False

    def test_cleaning_ignored_in_lifecycle(self):
        events = [
            _ev("sent-to-vendor", datetime(2026, 5, 28, 8, 0), ev_id=1),
            _ev("cleaning", datetime(2026, 5, 28, 8, 5), ev_id=2, scan_index=2),
            _ev("weight-entry", datetime(2026, 5, 28, 8, 10), ev_id=3, scan_index=3),
        ]
        out = derive_bag_lifecycle_status(events, bag_id="GHOST1")
        assert out["current_lifecycle_status"] == WEIGHED_NOT_STARTED


class TestSentToVendorAnchor:
    def test_weight_before_sent_ignored(self):
        events = [
            _ev("weight-entry", datetime(2026, 5, 28, 7, 50), ev_id=1),
            _ev("sent-to-vendor", datetime(2026, 5, 28, 8, 0), ev_id=2, scan_index=2),
        ]
        out = derive_bag_lifecycle_status(events, bag_id="ANCHOR1")
        assert out["current_lifecycle_status"] == PENDING_WEIGHING

    def test_weight_after_sent_counts(self):
        events = [
            _ev("weight-entry", datetime(2026, 5, 28, 7, 50), ev_id=1),
            _ev("sent-to-vendor", datetime(2026, 5, 28, 8, 0), ev_id=2, scan_index=2),
            _ev("weight-entry", datetime(2026, 5, 28, 8, 10), ev_id=3, scan_index=3),
        ]
        out = derive_bag_lifecycle_status(events, bag_id="ANCHOR2")
        assert out["current_lifecycle_status"] == WEIGHED_NOT_STARTED


class TestEarlyLifecycleStatuses:
    def test_assigned_not_sent(self):
        out = derive_bag_lifecycle_status([], bag_id="A1", ready_for_vendor_presence=True)
        assert out["current_lifecycle_status"] == ASSIGNED_NOT_SENT_TO_VENDOR

    def test_sent_to_vendor_at_vendor_only(self):
        out = derive_bag_lifecycle_status([], bag_id="A2", at_vendor_presence=True)
        assert out["current_lifecycle_status"] == SENT_TO_VENDOR

    def test_pending_weighing(self):
        events = [_ev("sent-to-vendor", datetime(2026, 5, 28, 8, 0), ev_id=1)]
        out = derive_bag_lifecycle_status(events, bag_id="A3")
        assert out["current_lifecycle_status"] == PENDING_WEIGHING

    def test_weighed_not_started(self):
        events = [
            _ev("sent-to-vendor", datetime(2026, 5, 28, 8, 0), ev_id=1),
            _ev("weight-entry", datetime(2026, 5, 28, 8, 10), ev_id=2, scan_index=2),
        ]
        out = derive_bag_lifecycle_status(events, bag_id="A4")
        assert out["current_lifecycle_status"] == WEIGHED_NOT_STARTED


class TestSortingLifecycle:
    def test_sorted_ready_for_wash(self):
        events = [
            _ev("sent-to-vendor", datetime(2026, 5, 28, 8, 0), ev_id=1),
            _ev("weight-entry", datetime(2026, 5, 28, 8, 10), ev_id=2, scan_index=2),
            _ev("create-issue", datetime(2026, 5, 28, 8, 20), ev_id=3, scan_index=3),
        ]
        out = derive_bag_lifecycle_status(events, bag_id="S1")
        assert out["current_lifecycle_status"] == SORTED_READY_FOR_WASH
        assert out["operational_flags"]["has_create_issue"] is True

    def test_workitem_detected_by_contains(self):
        events = [
            _ev("sent-to-vendor", datetime(2026, 5, 28, 8, 0), ev_id=1),
            _ev("weight-entry", datetime(2026, 5, 28, 8, 10), ev_id=2, scan_index=2),
            _ev("custom-workitem-step", datetime(2026, 5, 28, 8, 15), ev_id=3, scan_index=3),
        ]
        flags = operational_flags_from_timeline(gaming_events_from_records(events))
        assert flags["has_workitem"] is True
        assert flags["workitem_count"] == 1


class TestWashDryStages:
    def test_load_washer_before_ready_washer(self):
        events = [
            _ev("sent-to-vendor", datetime(2026, 5, 28, 8, 0), ev_id=1),
            _ev("weight-entry", datetime(2026, 5, 28, 8, 10), ev_id=2, scan_index=2),
            _ev("start-cleaning", datetime(2026, 5, 28, 9, 0), ev_id=3, scan_index=3),
        ]
        out = derive_bag_lifecycle_status(events, bag_id="W1")
        assert out["current_lifecycle_status"] == LOAD_WASHER

    def test_in_washing_after_ready_washer(self):
        events = [
            _ev("sent-to-vendor", datetime(2026, 5, 28, 8, 0), ev_id=1),
            _ev("weight-entry", datetime(2026, 5, 28, 8, 10), ev_id=2, scan_index=2),
            _ev("start-cleaning", datetime(2026, 5, 28, 9, 0), ev_id=3, scan_index=3),
            _ev("ready-washer", datetime(2026, 5, 28, 9, 15), ev_id=4, scan_index=4),
        ]
        out = derive_bag_lifecycle_status(
            events, bag_id="W2", washing_minutes=30
        )
        assert out["current_lifecycle_status"] == IN_WASHING
        expected_end = datetime(2026, 5, 28, 9, 15) + timedelta(minutes=30)
        assert out["stage_detail"]["in_washing"]["expected_end_time"] == expected_end

    def test_in_drying_uses_configurable_minutes(self):
        events = [
            _ev("sent-to-vendor", datetime(2026, 5, 28, 8, 0), ev_id=1),
            _ev("start-cleaning", datetime(2026, 5, 28, 9, 0), ev_id=2, scan_index=2),
            _ev("drying", datetime(2026, 5, 28, 10, 0), ev_id=3, scan_index=3),
        ]
        out = derive_bag_lifecycle_status(events, bag_id="D1", drying_minutes=40)
        assert out["current_lifecycle_status"] == IN_DRYING
        assert out["stage_detail"]["in_drying"]["expected_end_time"] == datetime(
            2026, 5, 28, 10, 40
        )


class TestFoldedAndSentToRinse:
    def test_folded_completed_on_clean_rack(self):
        events = [
            _ev("", datetime(2026, 5, 28, 12, 0), ev_id=1, rack="FINAL CLEAN"),
        ]
        out = derive_bag_lifecycle_status(events, bag_id="F1")
        assert out["current_lifecycle_status"] == FOLDED_COMPLETED

    def test_sent_to_rinse_missing_from_next_scrape(self):
        events = [_ev("", datetime(2026, 5, 28, 12, 0), ev_id=1, rack="CLEAN")]
        out = derive_bag_lifecycle_status(
            events,
            bag_id="F2",
            missing_from_next_portal_scrape=True,
        )
        assert out["current_lifecycle_status"] == SENT_TO_RINSE
        assert out["stage_detail"]["sent_to_rinse_reason"] == SENT_TO_RINSE_MISSING_FROM_NEXT_PORTAL_SCRAPE

    def test_sent_to_rinse_external_user_after_clean(self):
        events = [
            _ev("", datetime(2026, 5, 28, 12, 0), ev_id=1, rack="CLEAN", user="Alex"),
            _ev("move-bag", datetime(2026, 5, 28, 12, 10), ev_id=2, scan_index=2, user="Rinse Driver"),
        ]
        out = derive_bag_lifecycle_status(events, bag_id="F3", mapped_internal_users=["Alex"])
        assert out["current_lifecycle_status"] == SENT_TO_RINSE
        assert out["stage_detail"]["sent_to_rinse_reason"] == SENT_TO_RINSE_EXTERNAL_USER_AFTER_CLEAN
        assert NEEDS_REVIEW_EXTERNAL_SCAN_AFTER_CLEAN in out["exception_flags"]

    def test_sent_to_rinse_checkout_without_clean_rack(self):
        out = derive_bag_lifecycle_status(
            [],
            bag_id="F4",
            logistics_status="SENT_TO_RINSE",
        )
        assert out["current_lifecycle_status"] == SENT_TO_RINSE
        assert out["stage_detail"]["sent_to_rinse_reason"] == SENT_TO_RINSE_CHECKOUT
        assert out["needs_review"] is True
        assert SENT_TO_RINSE_WITHOUT_CLEAN_RACK in out["exception_flags"]

    def test_sent_to_rinse_checkout_with_clean_rack(self):
        events = [_ev("", datetime(2026, 5, 28, 12, 0), ev_id=1, rack="CLEAN")]
        out = derive_bag_lifecycle_status(
            events,
            bag_id="F5",
            logistics_status="SENT_TO_RINSE",
        )
        assert out["current_lifecycle_status"] == SENT_TO_RINSE
        assert out["stage_detail"]["sent_to_rinse_reason"] == SENT_TO_RINSE_CHECKOUT
        assert out["needs_review"] is False
        assert SENT_TO_RINSE_WITHOUT_CLEAN_RACK not in out["exception_flags"]


class TestOrderRejectedFullTiming:
    ISSUE_AT = datetime(2026, 5, 28, 8, 20)
    DEADLINE = ISSUE_AT + timedelta(minutes=45)

    def _base_events(self, *, start_cleaning_at: datetime | None = None):
        events = [
            _ev("sent-to-vendor", datetime(2026, 5, 28, 8, 0), ev_id=1),
            _ev("weight-entry", datetime(2026, 5, 28, 8, 10), ev_id=2, scan_index=2),
            _ev("create-issue", self.ISSUE_AT, ev_id=3, scan_index=3),
        ]
        if start_cleaning_at is not None:
            events.append(
                _ev("start-cleaning", start_cleaning_at, ev_id=4, scan_index=4)
            )
        return events

    def test_before_deadline_no_reject(self):
        out = derive_bag_lifecycle_status(
            self._base_events(),
            bag_id="RT1",
            reject_after_create_issue_minutes=45,
            evaluation_time=datetime(2026, 5, 28, 8, 30),
        )
        assert ORDER_REJECTED_FULL not in out["exception_flags"]
        detail = out["stage_detail"]["reject_after_create_issue"]
        assert detail["order_rejected_full"] is False
        assert detail["reject_deadline"] == self.DEADLINE
        assert detail["evaluation_time"] == datetime(2026, 5, 28, 8, 30)

    def test_after_deadline_no_start_cleaning_rejects(self):
        out = derive_bag_lifecycle_status(
            self._base_events(),
            bag_id="RT2",
            reject_after_create_issue_minutes=45,
            evaluation_time=datetime(2026, 5, 28, 9, 10),
        )
        assert ORDER_REJECTED_FULL in out["exception_flags"]
        detail = out["stage_detail"]["reject_after_create_issue"]
        assert detail["order_rejected_full"] is True
        assert detail["actual_start_cleaning_after_issue"] is None

    def test_start_cleaning_within_deadline_no_reject(self):
        out = derive_bag_lifecycle_status(
            self._base_events(start_cleaning_at=datetime(2026, 5, 28, 8, 30)),
            bag_id="RT3",
            reject_after_create_issue_minutes=45,
            evaluation_time=datetime(2026, 5, 28, 9, 10),
        )
        assert ORDER_REJECTED_FULL not in out["exception_flags"]
        detail = out["stage_detail"]["reject_after_create_issue"]
        assert detail["order_rejected_full"] is False
        assert detail["actual_start_cleaning_after_issue"] == datetime(2026, 5, 28, 8, 30)

    def test_start_cleaning_after_deadline_rejects(self):
        out = derive_bag_lifecycle_status(
            self._base_events(start_cleaning_at=datetime(2026, 5, 28, 9, 10)),
            bag_id="RT4",
            reject_after_create_issue_minutes=45,
            evaluation_time=datetime(2026, 5, 28, 9, 15),
        )
        assert ORDER_REJECTED_FULL in out["exception_flags"]
        detail = out["stage_detail"]["reject_after_create_issue"]
        assert detail["order_rejected_full"] is True
        assert detail["actual_start_cleaning_after_issue"] == datetime(2026, 5, 28, 9, 10)


class TestRejectAndSeparation:
    def test_order_rejected_full(self):
        events = [
            _ev("sent-to-vendor", datetime(2026, 5, 28, 8, 0), ev_id=1),
            _ev("weight-entry", datetime(2026, 5, 28, 8, 10), ev_id=2, scan_index=2),
            _ev("create-issue", datetime(2026, 5, 28, 8, 20), ev_id=3, scan_index=3),
        ]
        out = derive_bag_lifecycle_status(
            events,
            bag_id="R1",
            reject_after_create_issue_minutes=45,
            evaluation_time=datetime(2026, 5, 28, 9, 10),
        )
        assert out["current_lifecycle_status"] == SORTED_READY_FOR_WASH
        assert ORDER_REJECTED_FULL in out["exception_flags"]

    def test_create_issue_does_not_change_status_to_exception(self):
        events = [
            _ev("sent-to-vendor", datetime(2026, 5, 28, 8, 0), ev_id=1),
            _ev("weight-entry", datetime(2026, 5, 28, 8, 10), ev_id=2, scan_index=2),
            _ev("create-issue", datetime(2026, 5, 28, 8, 20), ev_id=3, scan_index=3),
            _ev("start-cleaning", datetime(2026, 5, 28, 8, 30), ev_id=4, scan_index=4),
        ]
        out = derive_bag_lifecycle_status(events, bag_id="R2", reject_after_create_issue_minutes=45)
        assert ORDER_REJECTED_FULL not in out["exception_flags"]

    def test_processed_by_vendor_not_completion(self):
        events = [
            _ev("processed by vendor", datetime(2026, 5, 28, 14, 0), ev_id=1),
            _ev("", datetime(2026, 5, 28, 14, 5), ev_id=2, scan_index=2, rack="FOLDING"),
        ]
        out = derive_bag_lifecycle_status(events, bag_id="R3")
        assert out["current_lifecycle_status"] != FOLDED_COMPLETED
        assert COMPLETED_WITHOUT_FINAL_CLEAN_SCAN in out["exception_flags"]


class TestProcessingSettings:
    def test_lifecycle_settings_from_db(self, monkeypatch):
        store: dict[str, str] = {}

        def _get(_cursor, _org, key):
            return store.get(key)

        def _set(_cursor, _org, key, value):
            store[key] = value

        monkeypatch.setattr("backend.rinse_processing_settings.table_exists", lambda c: True)
        monkeypatch.setattr("backend.rinse_processing_settings._get_setting", _get)
        monkeypatch.setattr("backend.rinse_processing_settings._set_setting", _set)

        cursor = None
        put_processing_settings(
            cursor,
            1,
            {
                "washing_minutes": 25,
                "drying_minutes": 35,
                "reject_after_create_issue_minutes": 50,
            },
        )
        out = get_processing_settings(cursor, 1)
        assert out["washing_minutes"] == 25
        assert out["drying_minutes"] == 35
        assert out["reject_after_create_issue_minutes"] == 50

    def test_reject_after_issue_uses_config_not_hardcoded(self):
        timeline = gaming_events_from_records(
            [
                _ev("sent-to-vendor", datetime(2026, 5, 28, 8, 0), ev_id=1),
                _ev("create-issue", datetime(2026, 5, 28, 8, 10), ev_id=2, scan_index=2),
                _ev("start-cleaning", datetime(2026, 5, 28, 8, 50), ev_id=3, scan_index=3),
            ]
        )
        eval_after = datetime(2026, 5, 28, 9, 0)
        within = evaluate_order_rejected_full(
            timeline, window_minutes=45, evaluation_time=eval_after
        )
        assert within is not None
        assert within["order_rejected_full"] is False

        after_window = evaluate_order_rejected_full(
            timeline, window_minutes=30, evaluation_time=eval_after
        )
        assert after_window is not None
        assert after_window["order_rejected_full"] is True


class TestDefaults:
    def test_default_washing_and_drying_minutes(self):
        events = [
            _ev("sent-to-vendor", datetime(2026, 5, 28, 8, 0), ev_id=1),
            _ev("start-cleaning", datetime(2026, 5, 28, 9, 0), ev_id=2, scan_index=2),
            _ev("ready-washer", datetime(2026, 5, 28, 9, 10), ev_id=3, scan_index=3),
        ]
        out = derive_bag_lifecycle_status(events, bag_id="DEF1")
        assert out["stage_detail"]["washing_minutes"] == DEFAULT_WASHING_MINUTES

        events2 = [
            _ev("sent-to-vendor", datetime(2026, 5, 28, 8, 0), ev_id=1),
            _ev("drying", datetime(2026, 5, 28, 10, 0), ev_id=2, scan_index=2),
        ]
        out2 = derive_bag_lifecycle_status(events2, bag_id="DEF2")
        assert out2["stage_detail"]["drying_minutes"] == DEFAULT_DRYING_MINUTES
        assert DEFAULT_REJECT_AFTER_CREATE_ISSUE == 45
