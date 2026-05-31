"""Tests for shift analysis dashboard helpers."""

from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

from backend.rinse_bag_lifecycle_status import (
    CHECKOUT_STATUS_CHECKED_OUT,
    CHECKOUT_STATUS_NEEDS_REVIEW,
    CHECKOUT_STATUS_NOT_CHECKED_OUT,
    FOLDED_COMPLETED,
    LIFECYCLE_UNKNOWN,
    PENDING_WEIGHING,
    SENT_TO_RINSE,
    SORTED_READY_FOR_WASH,
    WEIGHED_NOT_STARTED,
)
from backend.rinse_shift_analysis import (
    LIFECYCLE_GROUP_WASH_DRY,
    STATUS_MODEL_LIFECYCLE_V1,
    _classify_pending_bucket,
    _get_pending_bag_status_legacy_only,
    build_lifecycle_pending_payload,
    filter_lifecycle_pending_rows,
    get_pending_bag_status,
    lifecycle_group_for_status,
)


class TestPendingBucket:
    def test_not_weighed(self):
        assert _classify_pending_bucket(is_completed=False, has_weight_entry=False, has_start_cleaning=False) == "not_weighed"

    def test_weighed_not_washed(self):
        assert _classify_pending_bucket(is_completed=False, has_weight_entry=True, has_start_cleaning=False) == "weighed_not_washed"

    def test_in_washing(self):
        assert _classify_pending_bucket(is_completed=False, has_weight_entry=True, has_start_cleaning=True) == "in_washing"

    def test_completed(self):
        assert _classify_pending_bucket(is_completed=True, has_weight_entry=True, has_start_cleaning=True) is None


def _staging_execute_side_effect(cursor, bag_rows, scan_events=None):
    scan_events = scan_events or []

    def execute_side_effect(sql, args=None):
        s = " ".join(sql.split())
        if "FROM orders_staging s" in s:
            cursor.fetchall.return_value = bag_rows
        elif "FROM rinse_bag_registry r" in s and "date_clean" in s:
            cursor.fetchall.return_value = []
        elif "rinse_bag_scan_events" in s and "purpose" in s:
            cursor.fetchall.return_value = scan_events
        elif "rinse_bag_scan_events" in s:
            cursor.fetchall.return_value = scan_events
        elif "rinse_folding_user_map" in s:
            cursor.fetchall.return_value = []
        elif "system_settings" in s or "processing_settings" in s:
            cursor.fetchall.return_value = []

    cursor.execute.side_effect = execute_side_effect


class TestLegacyPendingBagStatus:
    def test_groups_rush_and_non_rush_from_active_staging(self):
        cursor = MagicMock()
        _staging_execute_side_effect(
            cursor,
            [
                {
                    "bag_id": "B1",
                    "name_clean": "A",
                    "weight_num": 10,
                    "service_type": "WF",
                    "effective_rush": "RUSH",
                    "is_completed": 0,
                    "logistics_status": "AT_WASHPRO",
                },
                {
                    "bag_id": "B2",
                    "name_clean": "B",
                    "weight_num": 8,
                    "service_type": "WF",
                    "effective_rush": "NON-RUSH",
                    "is_completed": 1,
                    "logistics_status": "AT_WASHPRO",
                },
            ],
            scan_events=[
                {"bag_id": "B1", "purpose": "weight-entry"},
                {"bag_id": "B2", "purpose": "start-cleaning"},
            ],
        )
        with patch("backend.rinse_shift_analysis.table_exists", return_value=True), patch(
            "backend.rinse_shift_analysis.table_has_column", return_value=True
        ), patch(
            "backend.rinse_shift_analysis.get_processing_settings",
            return_value={"washing_minutes": 30, "drying_minutes": 45, "reject_after_create_issue_minutes": 45},
        ):
            out = _get_pending_bag_status_legacy_only(cursor, 1, target_date=date(2026, 5, 27))

        assert out["groups"]["rush"]["pending"] == 1
        assert out["groups"]["rush"]["weighed_not_washed"] == 1
        assert out["groups"]["non_rush"]["completed"] == 1
        assert out["groups"]["combined"]["total"] == 2


class TestLifecyclePendingPayload:
    def test_status_model_and_combined_equals_rush_plus_non_rush(self):
        cursor = MagicMock()
        _staging_execute_side_effect(
            cursor,
            [
                {
                    "bag_id": "R1",
                    "name_clean": "Rush A",
                    "weight_num": 10,
                    "service_type": "WF",
                    "effective_rush": "RUSH",
                    "is_completed": 0,
                    "logistics_status": "AT_WASHPRO",
                },
                {
                    "bag_id": "N1",
                    "name_clean": "Non A",
                    "weight_num": 8,
                    "service_type": "WF",
                    "effective_rush": "NON-RUSH",
                    "is_completed": 0,
                    "logistics_status": "AT_WASHPRO",
                },
            ],
        )

        def fake_derive(events, *, bag_id, **kwargs):
            if bag_id == "R1":
                return {
                    "current_lifecycle_status": PENDING_WEIGHING,
                    "checkout_status": CHECKOUT_STATUS_NOT_CHECKED_OUT,
                    "status_timestamp": datetime(2026, 5, 28, 8, 0),
                    "status_source_event": None,
                    "operational_flags": {},
                    "exception_flags": [],
                    "needs_review": False,
                    "stage_detail": {},
                }
            return {
                "current_lifecycle_status": FOLDED_COMPLETED,
                "checkout_status": CHECKOUT_STATUS_CHECKED_OUT,
                "status_timestamp": datetime(2026, 5, 28, 12, 0),
                "status_source_event": None,
                "operational_flags": {},
                "exception_flags": [],
                "needs_review": False,
                "stage_detail": {},
            }

        with patch("backend.rinse_shift_analysis.table_exists", return_value=True), patch(
            "backend.rinse_shift_analysis.table_has_column", return_value=True
        ), patch(
            "backend.rinse_shift_analysis.get_processing_settings",
            return_value={"washing_minutes": 30, "drying_minutes": 45, "reject_after_create_issue_minutes": 45},
        ), patch(
            "backend.rinse_shift_analysis.derive_bag_lifecycle_status",
            side_effect=fake_derive,
        ):
            out = build_lifecycle_pending_payload(cursor, 1, target_date=date(2026, 5, 28))

        assert out["status_model"] == STATUS_MODEL_LIFECYCLE_V1
        rush = out["groups"]["rush"]
        non_rush = out["groups"]["non_rush"]
        combined = out["groups"]["combined"]
        assert rush["pending"] == 1
        assert non_rush["completed"] == 1
        assert combined["total"] == rush["total"] + non_rush["total"]
        assert combined["pending"] == rush["pending"] + non_rush["pending"]
        assert combined["completed"] == rush["completed"] + non_rush["completed"]
        assert combined["by_lifecycle_group"]["pending_weighing"] == 1
        assert combined["by_lifecycle_group"]["folded"] == 1
        assert out["legacy_buckets"]["combined"]["total"] == 2

    def test_grouped_counts_and_needs_review_exceptions(self):
        cursor = MagicMock()
        _staging_execute_side_effect(
            cursor,
            [
                {
                    "bag_id": "W1",
                    "name_clean": "Wash",
                    "weight_num": 10,
                    "service_type": "WF",
                    "effective_rush": "RUSH",
                    "is_completed": 0,
                    "logistics_status": "AT_WASHPRO",
                },
                {
                    "bag_id": "E1",
                    "name_clean": "Ex",
                    "weight_num": 8,
                    "service_type": "WF",
                    "effective_rush": "RUSH",
                    "is_completed": 0,
                    "logistics_status": "SENT_TO_RINSE",
                },
            ],
        )

        def fake_derive(events, *, bag_id, **kwargs):
            if bag_id == "W1":
                return {
                    "current_lifecycle_status": "IN_WASHING",
                    "checkout_status": CHECKOUT_STATUS_NOT_CHECKED_OUT,
                    "status_timestamp": datetime(2026, 5, 28, 9, 0),
                    "status_source_event": None,
                    "operational_flags": {},
                    "exception_flags": [],
                    "needs_review": False,
                    "stage_detail": {},
                }
            return {
                "current_lifecycle_status": PENDING_WEIGHING,
                "checkout_status": CHECKOUT_STATUS_NEEDS_REVIEW,
                "status_timestamp": None,
                "status_source_event": None,
                "operational_flags": {},
                "exception_flags": ["CHECKOUT_WITHOUT_CLEAN_RACK"],
                "needs_review": True,
                "stage_detail": {},
            }

        with patch("backend.rinse_shift_analysis.table_exists", return_value=True), patch(
            "backend.rinse_shift_analysis.table_has_column", return_value=True
        ), patch(
            "backend.rinse_shift_analysis.get_processing_settings",
            return_value={"washing_minutes": 30, "drying_minutes": 45, "reject_after_create_issue_minutes": 45},
        ), patch(
            "backend.rinse_shift_analysis.derive_bag_lifecycle_status",
            side_effect=fake_derive,
        ):
            out = build_lifecycle_pending_payload(cursor, 1, target_date=date(2026, 5, 28))

        rush = out["groups"]["rush"]
        assert rush["by_lifecycle_group"][LIFECYCLE_GROUP_WASH_DRY] == 1
        assert rush["needs_review"] == 1
        assert rush["with_exceptions"] == 1
        assert out["checkout_summary"]["rush"]["checkout_pending"] == 1
        assert out["checkout_summary"]["rush"]["checkout_needs_review"] == 1

    def test_checkout_does_not_change_lifecycle_status(self):
        cursor = MagicMock()
        _staging_execute_side_effect(
            cursor,
            [
                {
                    "bag_id": "C1",
                    "name_clean": "Checked",
                    "weight_num": 10,
                    "service_type": "WF",
                    "effective_rush": "RUSH",
                    "is_completed": 0,
                    "logistics_status": "SENT_TO_RINSE",
                },
            ],
        )
        with patch("backend.rinse_shift_analysis.table_exists", return_value=True), patch(
            "backend.rinse_shift_analysis.table_has_column", return_value=True
        ), patch(
            "backend.rinse_shift_analysis.get_processing_settings",
            return_value={"washing_minutes": 30, "drying_minutes": 45, "reject_after_create_issue_minutes": 45},
        ):
            out = get_pending_bag_status(cursor, 1, target_date=date(2026, 5, 28))

        row = out["rows"][0]
        assert row["current_lifecycle_status"] != SENT_TO_RINSE
        assert row["checkout_status"] == CHECKOUT_STATUS_NEEDS_REVIEW

    def test_evaluation_time_gates_order_rejected_full(self):
        cursor = MagicMock()
        issue_at = datetime(2026, 5, 28, 8, 20)
        _staging_execute_side_effect(
            cursor,
            [
                {
                    "bag_id": "RJ1",
                    "name_clean": "Reject",
                    "weight_num": 10,
                    "service_type": "WF",
                    "effective_rush": "RUSH",
                    "is_completed": 0,
                    "logistics_status": "AT_WASHPRO",
                },
            ],
            scan_events=[
                {
                    "bag_id": "RJ1",
                    "id": 1,
                    "rack": "Scale",
                    "user_name": "Alex",
                    "purpose": "sent-to-vendor",
                    "scanned_at_parsed": datetime(2026, 5, 28, 8, 0),
                    "scan_index": 1,
                },
                {
                    "bag_id": "RJ1",
                    "id": 2,
                    "rack": "Scale",
                    "user_name": "Alex",
                    "purpose": "weight-entry",
                    "scanned_at_parsed": datetime(2026, 5, 28, 8, 10),
                    "scan_index": 2,
                },
                {
                    "bag_id": "RJ1",
                    "id": 3,
                    "rack": "Scale",
                    "user_name": "Alex",
                    "purpose": "create-issue",
                    "scanned_at_parsed": issue_at,
                    "scan_index": 3,
                },
            ],
        )
        with patch("backend.rinse_shift_analysis.table_exists", return_value=True), patch(
            "backend.rinse_shift_analysis.table_has_column", return_value=True
        ), patch(
            "backend.rinse_shift_analysis.get_processing_settings",
            return_value={"washing_minutes": 30, "drying_minutes": 45, "reject_after_create_issue_minutes": 45},
        ):
            before = get_pending_bag_status(
                cursor,
                1,
                target_date=date(2026, 5, 28),
                evaluation_time=datetime(2026, 5, 28, 8, 30),
            )
            after = get_pending_bag_status(
                cursor,
                1,
                target_date=date(2026, 5, 28),
                evaluation_time=datetime(2026, 5, 28, 9, 10),
            )

        assert "ORDER_REJECTED_FULL" not in (before["rows"][0].get("exception_flags") or [])
        assert "ORDER_REJECTED_FULL" in (after["rows"][0].get("exception_flags") or [])

    def test_unknown_lifecycle_on_derivation_failure(self):
        cursor = MagicMock()
        _staging_execute_side_effect(
            cursor,
            [
                {
                    "bag_id": "U1",
                    "name_clean": "Unknown",
                    "weight_num": 10,
                    "service_type": "WF",
                    "effective_rush": "RUSH",
                    "is_completed": 0,
                    "logistics_status": "AT_WASHPRO",
                },
            ],
        )
        with patch("backend.rinse_shift_analysis.table_exists", return_value=True), patch(
            "backend.rinse_shift_analysis.table_has_column", return_value=True
        ), patch(
            "backend.rinse_shift_analysis.get_processing_settings",
            return_value={"washing_minutes": 30, "drying_minutes": 45, "reject_after_create_issue_minutes": 45},
        ), patch(
            "backend.rinse_shift_analysis.derive_bag_lifecycle_status",
            side_effect=RuntimeError("boom"),
        ):
            out = get_pending_bag_status(cursor, 1, target_date=date(2026, 5, 28))

        assert out["groups"]["combined"]["by_lifecycle_group"]["unknown"] == 1
        assert out["rows"][0]["lifecycle_fallback"] is True
        assert out["rows"][0]["needs_review"] is True


class TestLifecycleDrilldownFilter:
    def test_filter_by_group_and_wash_dry(self):
        rows = [
            {
                "bag_id": "A",
                "rush": True,
                "current_lifecycle_status": "IN_WASHING",
                "lifecycle_group": LIFECYCLE_GROUP_WASH_DRY,
                "needs_review": False,
                "exception_flags": [],
            },
            {
                "bag_id": "B",
                "rush": True,
                "current_lifecycle_status": PENDING_WEIGHING,
                "lifecycle_group": "pending_weighing",
                "needs_review": False,
                "exception_flags": [],
            },
            {
                "bag_id": "C",
                "rush": False,
                "current_lifecycle_status": "IN_WASHING",
                "lifecycle_group": LIFECYCLE_GROUP_WASH_DRY,
                "needs_review": False,
                "exception_flags": [],
            },
        ]
        filtered = filter_lifecycle_pending_rows(
            rows,
            rush_group="rush",
            lifecycle_group=LIFECYCLE_GROUP_WASH_DRY,
        )
        assert [r["bag_id"] for r in filtered] == ["A"]

    def test_filter_needs_review_and_exceptions(self):
        rows = [
            {"bag_id": "A", "rush": True, "current_lifecycle_status": PENDING_WEIGHING, "needs_review": True, "exception_flags": []},
            {"bag_id": "B", "rush": True, "current_lifecycle_status": WEIGHED_NOT_STARTED, "needs_review": False, "exception_flags": ["X"]},
        ]
        assert len(filter_lifecycle_pending_rows(rows, filter_kind="needs_review")) == 1
        assert len(filter_lifecycle_pending_rows(rows, filter_kind="exceptions")) == 1


class TestRecordsPayloadShape:
    def test_list_return_normalized(self):
        rows = [{"bag_id": "B1", "status": "CALCULATED", "included_in_scoring": 1}]
        payload = {"rows": rows, "total": len(rows)}
        assert payload.get("rows")

    def test_lifecycle_group_mapping(self):
        assert lifecycle_group_for_status(SORTED_READY_FOR_WASH) == "sorted_ready"
        assert lifecycle_group_for_status(LIFECYCLE_UNKNOWN) == "unknown"


class TestOperationalRecordsLifecycleMapping:
    def test_operational_records_use_lifecycle_fields_from_pending(self):
        from backend.rinse_shift_analysis import build_operational_dashboard_data

        cursor = MagicMock()
        pending = {
            "rows": [
                {
                    "bag_id": "00CY9RP1K6",
                    "name_clean": "Customer",
                    "rush": True,
                    "rush_label": "Rush",
                    "current_lifecycle_status": FOLDED_COMPLETED,
                    "lifecycle_group": "folded",
                    "lifecycle_group_label": "Folded",
                    "lifecycle_status_label": "Folded / completed",
                    "exception_flags": [],
                }
            ]
        }

        def execute_side_effect(sql, args=None):
            s = " ".join(sql.split())
            if "rinse_bag_scan_events" in s and "purpose" in s:
                cursor.fetchall.return_value = []
            elif "rinse_bag_scan_events" in s:
                cursor.fetchall.return_value = [
                    {
                        "bag_id": "00CY9RP1K6",
                        "id": 1,
                        "rack": "W26-30-VW",
                        "user_name": "Alex",
                        "purpose": "start-cleaning",
                        "scanned_at_parsed": datetime(2026, 5, 31, 11, 51),
                        "scan_index": 1,
                    },
                    {
                        "bag_id": "00CY9RP1K6",
                        "id": 2,
                        "rack": "D37-50-VW",
                        "user_name": "Alex",
                        "purpose": "drying",
                        "scanned_at_parsed": datetime(2026, 5, 31, 11, 52),
                        "scan_index": 2,
                    },
                    {
                        "bag_id": "00CY9RP1K6",
                        "id": 3,
                        "rack": "VeeWash Clean",
                        "user_name": "Alex",
                        "purpose": "move-bag",
                        "scanned_at_parsed": datetime(2026, 5, 31, 14, 12),
                        "scan_index": 3,
                    },
                ]

        cursor.execute.side_effect = execute_side_effect

        out = build_operational_dashboard_data(cursor, 1, pending_payload=pending)
        rec = out["records"][0]
        assert rec["activity"] == "lifecycle"
        assert rec["current_lifecycle_status"] == FOLDED_COMPLETED
        assert rec["lifecycle_group"] == "folded"
        assert rec["exception_codes"] == []
