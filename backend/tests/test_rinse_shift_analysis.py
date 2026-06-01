"""Tests for shift analysis dashboard helpers."""

from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

from backend.rinse_bag_lifecycle_status import (
    ASSIGNED_NOT_SENT_TO_VENDOR,
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


def _staging_execute_side_effect(cursor, bag_rows, scan_events=None, presence_rows=None):
    scan_events = scan_events or []
    presence_rows = presence_rows or []

    def execute_side_effect(sql, args=None):
        s = " ".join(sql.split())
        if "FROM orders_staging s" in s:
            cursor.fetchall.return_value = bag_rows
        elif "FROM rinse_bag_registry r" in s and "date_clean" in s:
            cursor.fetchall.return_value = []
        elif "FROM rinse_cleaner_ticket_presence" in s:
            cursor.fetchall.return_value = presence_rows
        elif "FROM upload_batches" in s or "FROM upload_batch_rows" in s:
            cursor.fetchall.return_value = []
        elif "orders_staging WHERE organization_id" in s and "ticket_id" in s:
            cursor.fetchone.return_value = None
        elif "rinse_bag_registry WHERE organization_id" in s and "bag_id" in s:
            cursor.fetchone.return_value = None
        elif "rinse_bag_scan_events" in s and "COUNT" in s:
            cursor.fetchone.return_value = {"cnt": 0}
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
        assert out["count_integrity"]["unreconciled_difference"] == 0
        assigned_check = out["count_integrity"]["checks"].get(ASSIGNED_NOT_SENT_TO_VENDOR)
        if assigned_check:
            assert assigned_check["match"] is True
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


class TestOperationalWorkitemDashboardStats:
    def test_workitem_stats_match_eligible_events(self):
        from backend.rinse_shift_analysis import build_operational_dashboard_data

        cursor = MagicMock()
        pending = {
            "rows": [
                {"bag_id": "EARLY", "name_clean": "Early", "rush": False},
                {"bag_id": "VALID", "name_clean": "Valid", "rush": True},
            ]
        }

        all_events = {
            "EARLY": [
                {
                    "bag_id": "EARLY",
                    "id": 1,
                    "rack": "",
                    "user_name": "Alex",
                    "purpose": "workitems-added",
                    "scanned_at_parsed": datetime(2026, 5, 28, 21, 22),
                    "scan_index": 1,
                },
                {
                    "bag_id": "EARLY",
                    "id": 2,
                    "rack": "VeeWash Dirty",
                    "user_name": "Alex",
                    "purpose": "sent-to-vendor",
                    "scanned_at_parsed": datetime(2026, 5, 29, 18, 47),
                    "scan_index": 2,
                },
                {
                    "bag_id": "EARLY",
                    "id": 3,
                    "rack": "",
                    "user_name": "Alex",
                    "purpose": "weight-entry",
                    "scanned_at_parsed": datetime(2026, 5, 30, 11, 2),
                    "scan_index": 3,
                },
            ],
            "VALID": [
                {
                    "bag_id": "VALID",
                    "id": 4,
                    "rack": "VeeWash Dirty",
                    "user_name": "Alex",
                    "purpose": "sent-to-vendor",
                    "scanned_at_parsed": datetime(2026, 5, 29, 18, 47),
                    "scan_index": 1,
                },
                {
                    "bag_id": "VALID",
                    "id": 5,
                    "rack": "",
                    "user_name": "Alex",
                    "purpose": "weight-entry",
                    "scanned_at_parsed": datetime(2026, 5, 30, 11, 2),
                    "scan_index": 2,
                },
                {
                    "bag_id": "VALID",
                    "id": 6,
                    "rack": "",
                    "user_name": "Alex",
                    "purpose": "create-workitem",
                    "scanned_at_parsed": datetime(2026, 5, 30, 11, 15),
                    "scan_index": 3,
                },
            ],
        }

        def execute_side_effect(sql, args=None):
            s = " ".join(sql.split())
            if "FROM rinse_bag_scan_events" in s and "scanned_at_parsed" in s:
                bag_ids = [str(a).strip() for a in (args or [])[1:]]
                rows = []
                for bid in bag_ids:
                    rows.extend(all_events.get(bid, []))
                cursor.fetchall.return_value = rows
            elif "FROM rinse_bag_scan_events" in s:
                cursor.fetchall.return_value = []

        cursor.execute.side_effect = execute_side_effect

        out = build_operational_dashboard_data(cursor, 1, pending_payload=pending)
        stats = out["stats"]
        by_bag = {r["bag_id"]: r for r in out["records"]}

        assert stats["bags_with_workitems"] == 1
        assert stats["total_workitem_events"] == 1
        assert by_bag["EARLY"]["workitem_stats"]["has_workitem"] is False
        assert by_bag["VALID"]["workitem_stats"]["has_workitem"] is True
        assert by_bag["VALID"]["workitem_stats"]["create_workitem_count"] == 1


class TestPresenceIncomingLifecycle:
    def test_ready_for_vendor_without_registry_appears_assigned_not_sent(self):
        cursor = MagicMock()
        _staging_execute_side_effect(
            cursor,
            [],
            presence_rows=[
                {
                    "bag_id": "READY1",
                    "portal_status": "ready_for_vendor",
                    "customer_name": "Incoming Customer",
                    "estimated_delivery_date": date(2026, 5, 31),
                    "rush_flag": "NON-RUSH",
                    "service_type": "WF",
                    "portal_status_first_seen_at": datetime(2026, 5, 30, 9, 0),
                }
            ],
        )
        with patch("backend.rinse_shift_analysis.table_exists", return_value=True), patch(
            "backend.rinse_shift_analysis.table_has_column", return_value=True
        ), patch(
            "backend.rinse_shift_analysis.get_processing_settings",
            return_value={"washing_minutes": 30, "drying_minutes": 45, "reject_after_create_issue_minutes": 45},
        ):
            out = build_lifecycle_pending_payload(cursor, 1, target_date=date(2026, 5, 31))

        assert out["portal_alignment"]["wf_ready_for_vendor_presence"] == 1
        assert out["groups"]["combined"]["by_lifecycle_status"][ASSIGNED_NOT_SENT_TO_VENDOR] == 1
        row = out["rows"][0]
        assert row["bag_id"] == "READY1"
        assert row["current_lifecycle_status"] == ASSIGNED_NOT_SENT_TO_VENDOR
        assert row["presence_source"] is True

    def test_at_vendor_presence_without_scans_is_sent_to_vendor(self):
        from backend.rinse_bag_lifecycle_status import SENT_TO_VENDOR

        cursor = MagicMock()
        _staging_execute_side_effect(
            cursor,
            [],
            presence_rows=[
                {
                    "bag_id": "ATV1",
                    "portal_status": "at_vendor",
                    "customer_name": "At Vendor",
                    "estimated_delivery_date": date(2026, 5, 31),
                    "rush_flag": "RUSH",
                    "service_type": "WF",
                    "portal_status_first_seen_at": datetime(2026, 5, 30, 10, 0),
                }
            ],
        )
        with patch("backend.rinse_shift_analysis.table_exists", return_value=True), patch(
            "backend.rinse_shift_analysis.table_has_column", return_value=True
        ), patch(
            "backend.rinse_shift_analysis.get_processing_settings",
            return_value={"washing_minutes": 30, "drying_minutes": 45, "reject_after_create_issue_minutes": 45},
        ):
            out = build_lifecycle_pending_payload(cursor, 1, target_date=date(2026, 5, 31))

        assert out["portal_alignment"]["wf_at_vendor_presence_only"] == 1
        assert out["rows"][0]["current_lifecycle_status"] == SENT_TO_VENDOR

    def test_hd_presence_excluded_from_wf_lifecycle(self):
        cursor = MagicMock()
        _staging_execute_side_effect(
            cursor,
            [],
            presence_rows=[
                {
                    "bag_id": "HD1",
                    "portal_status": "ready_for_vendor",
                    "customer_name": "HD Customer",
                    "estimated_delivery_date": date(2026, 5, 31),
                    "rush_flag": None,
                    "service_type": "HD",
                    "portal_status_first_seen_at": datetime(2026, 5, 30, 9, 0),
                }
            ],
        )
        with patch("backend.rinse_shift_analysis.table_exists", return_value=True), patch(
            "backend.rinse_shift_analysis.table_has_column", return_value=True
        ), patch(
            "backend.rinse_shift_analysis.get_processing_settings",
            return_value={"washing_minutes": 30, "drying_minutes": 45, "reject_after_create_issue_minutes": 45},
        ):
            out = build_lifecycle_pending_payload(cursor, 1, target_date=date(2026, 5, 31))

        assert out["portal_alignment"]["hd_presence_excluded"] == 1
        assert out["groups"]["combined"]["total"] == 0

    def test_assigned_count_matches_ready_for_vendor_presence(self):
        cursor = MagicMock()
        _staging_execute_side_effect(
            cursor,
            [],
            presence_rows=[
                {
                    "bag_id": "R1",
                    "portal_status": "ready_for_vendor",
                    "customer_name": "A",
                    "estimated_delivery_date": date(2026, 5, 31),
                    "rush_flag": "RUSH",
                    "service_type": "WF",
                    "portal_status_first_seen_at": datetime(2026, 5, 30, 9, 0),
                },
                {
                    "bag_id": "R2",
                    "portal_status": "ready_for_vendor",
                    "customer_name": "B",
                    "estimated_delivery_date": date(2026, 5, 31),
                    "rush_flag": "NON-RUSH",
                    "service_type": "WF",
                    "portal_status_first_seen_at": datetime(2026, 5, 30, 10, 0),
                },
            ],
        )
        with patch("backend.rinse_shift_analysis.table_exists", return_value=True), patch(
            "backend.rinse_shift_analysis.table_has_column", return_value=True
        ), patch(
            "backend.rinse_shift_analysis.get_processing_settings",
            return_value={"washing_minutes": 30, "drying_minutes": 45, "reject_after_create_issue_minutes": 45},
        ):
            out = build_lifecycle_pending_payload(cursor, 1, target_date=date(2026, 5, 31))

        assert out["portal_alignment"]["wf_ready_for_vendor_presence"] == 2
        assert out["groups"]["combined"]["by_lifecycle_status"][ASSIGNED_NOT_SENT_TO_VENDOR] == 2


class TestCompletedWithoutFinalCleanScanLifecycleSummary:
    def test_counts_as_completed_not_pending(self):
        from backend.rinse_bag_gaming_performance import gaming_events_from_records
        from backend.rinse_bag_lifecycle_status import IN_DRYING, derive_bag_lifecycle_status
        from backend.rinse_shift_operational_exceptions import (
            COMPLETED_WITHOUT_FINAL_CLEAN_SCAN,
            filter_operational_records,
        )
        from backend.rinse_shift_analysis import build_operational_dashboard_data

        events = gaming_events_from_records(
            [
                {
                    "purpose": "sent-to-vendor",
                    "scanned_at_parsed": datetime(2026, 6, 1, 8, 0),
                    "id": 1,
                    "scan_index": 1,
                },
                {
                    "purpose": "weight-entry",
                    "scanned_at_parsed": datetime(2026, 6, 1, 8, 10),
                    "id": 2,
                    "scan_index": 2,
                },
                {
                    "purpose": "start-cleaning",
                    "scanned_at_parsed": datetime(2026, 6, 1, 9, 0),
                    "id": 3,
                    "scan_index": 3,
                },
                {
                    "purpose": "drying",
                    "scanned_at_parsed": datetime(2026, 6, 1, 10, 0),
                    "id": 4,
                    "scan_index": 4,
                },
                {
                    "purpose": "processed-by-vendor",
                    "scanned_at_parsed": datetime(2026, 6, 1, 14, 0),
                    "id": 5,
                    "scan_index": 5,
                },
            ]
        )
        lifecycle = derive_bag_lifecycle_status(events, bag_id="0E0EVEA9I3")
        assert lifecycle["current_lifecycle_status"] == FOLDED_COMPLETED
        assert lifecycle["current_lifecycle_status"] != IN_DRYING
        assert COMPLETED_WITHOUT_FINAL_CLEAN_SCAN in lifecycle["exception_flags"]
        assert lifecycle["needs_review"] is True

        pending = {
            "rows": [
                {
                    "bag_id": "0E0EVEA9I3",
                    "name_clean": "Customer",
                    "rush": False,
                    "rush_label": "Non-Rush",
                    "is_completed": True,
                    **lifecycle,
                    "lifecycle_group": "folded",
                    "lifecycle_group_label": "Folded",
                    "lifecycle_status_label": "Folded / completed",
                }
            ]
        }
        cursor = MagicMock()

        def execute_side_effect(sql, args=None):
            s = " ".join(sql.split())
            if "rinse_bag_scan_events" in s:
                cursor.fetchall.return_value = [
                    {
                        "bag_id": "0E0EVEA9I3",
                        "id": i,
                        "rack": "",
                        "user_name": "Staff",
                        "purpose": ev["purpose"],
                        "scanned_at_parsed": ev["scanned_at_parsed"],
                        "scan_index": i,
                    }
                    for i, ev in enumerate(events, start=1)
                ]

        cursor.execute.side_effect = execute_side_effect
        with patch("backend.rinse_shift_analysis.table_exists", return_value=True):
            op = build_operational_dashboard_data(cursor, 1, pending_payload=pending)

        rec = op["records"][0]
        assert rec["current_lifecycle_status"] == FOLDED_COMPLETED
        assert rec["is_completed"] is True
        assert COMPLETED_WITHOUT_FINAL_CLEAN_SCAN in rec["exception_codes"]

        filtered = filter_operational_records(
            op["records"],
            drill_filter="completed_without_final_clean_scan",
        )
        assert len(filtered) == 1
        assert filtered[0]["current_lifecycle_status"] == FOLDED_COMPLETED

        rows = [
            {
                "bag_id": "0E0EVEA9I3",
                "rush": False,
                "current_lifecycle_status": FOLDED_COMPLETED,
                "lifecycle_group": "folded",
                "needs_review": True,
                "exception_flags": [COMPLETED_WITHOUT_FINAL_CLEAN_SCAN],
            }
        ]
        assert len(filter_lifecycle_pending_rows(rows, filter_kind="completed")) == 1
        assert len(filter_lifecycle_pending_rows(rows, filter_kind="pending")) == 0
