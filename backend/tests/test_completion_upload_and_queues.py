"""
Business rules: Clean-rack completion, pre-upload ALREADY_COMPLETED, Checkout/Rush visibility.

Checkout/Rush queues use orders_staging only (no rinse_bag_registry completion filter).
"""

from __future__ import annotations

import unittest
from datetime import date, datetime
from unittest.mock import MagicMock, patch

from backend.rinse_bag_completion import (
    COMPLETION_COMPLETED,
    COMPLETION_INCOMPLETE,
    REASON_ALREADY_COMPLETED,
    REASON_CLEAN_RACK_SCANNED,
    REASON_NO_CLEAN_SCAN,
    REASON_OK,
    REASON_UPDATED_EXISTING_BAG,
    ROW_ACCEPTED,
    ROW_REJECTED,
    classify_portal_upload_row,
    evaluate_bag_completion,
)
from backend.rinse_upload_finalize import count_clean_rack_completed_bags


def _ev(rack, user, at, scan_index=1, ev_id=1):
    return {
        "id": ev_id,
        "rack": rack,
        "user_name": user,
        "scanned_at_parsed": at,
        "scan_index": scan_index,
    }


def _staging_row(*, rush_type: str, ticket_id: str, date_clean: date | None = None) -> dict:
    return {
        "id": 1,
        "date_clean": date_clean or date.today(),
        "name_clean": "Customer",
        "weight_num": 10.0,
        "service_type": "WF",
        "rush_type": rush_type,
        "ticket_id": ticket_id,
        "logistics_status": "AT_WASHPRO",
        "processing_status": "PENDING",
        "status": "PENDING",
    }


def checkout_visible_rows(rows: list[dict], *, rush_filter: str | None = None) -> list[dict]:
    """Mirror CheckoutPage / OrdersPage: staging rows filtered by rush only, not registry."""
    out = list(rows)

    def rush_of(r: dict) -> str:
        raw = str(r.get("rush_type") or "").strip().upper()
        return "RUSH" if raw == "RUSH" else "NON-RUSH"

    if rush_filter and rush_filter != "ALL":
        out = [r for r in out if rush_of(r) == rush_filter]
    return out


class TestCleanRackCompletionAndUpload(unittest.TestCase):
    def test_clean_rack_in_upload_completes_registry(self):
        r = evaluate_bag_completion(
            [_ev("VeeWash Clean", "Staff", datetime(2026, 5, 19, 10, 0), 1, 42)]
        )
        self.assertEqual(r.completion_status, COMPLETION_COMPLETED)
        self.assertEqual(r.completion_reason, REASON_CLEAN_RACK_SCANNED)

    def test_same_bag_second_upload_rejected_when_pre_completed(self):
        st, reason = classify_portal_upload_row(
            ticket_id="BAGSECOND",
            was_completed_before_upload=True,
            has_active_staging=False,
            row_date_before_batch=False,
        )
        self.assertEqual(st, ROW_REJECTED)
        self.assertEqual(reason, REASON_ALREADY_COMPLETED)

    def test_first_upload_accepted_when_not_pre_completed(self):
        st, reason = classify_portal_upload_row(
            ticket_id="BAGFIRST",
            was_completed_before_upload=False,
            has_active_staging=False,
            row_date_before_batch=False,
        )
        self.assertEqual(st, ROW_ACCEPTED)
        self.assertEqual(reason, REASON_OK)

    def test_no_clean_accepted_incomplete(self):
        r = evaluate_bag_completion(
            [_ev("003-NY-WF", "Driver", datetime(2026, 5, 19, 9, 0), 1, 1)]
        )
        self.assertEqual(r.completion_status, COMPLETION_INCOMPLETE)
        self.assertEqual(r.completion_reason, REASON_NO_CLEAN_SCAN)
        st, reason = classify_portal_upload_row(
            ticket_id="NOCLN001",
            was_completed_before_upload=False,
            has_active_staging=False,
            row_date_before_batch=False,
        )
        self.assertEqual(st, ROW_ACCEPTED)

    def test_newly_completed_clean_rack_count_on_confirm_payload(self):
        payload = {
            "bags": [
                {"bag_id": "A", "completion_status": COMPLETION_COMPLETED, "completion_reason": REASON_CLEAN_RACK_SCANNED},
                {"bag_id": "B", "completion_status": COMPLETION_INCOMPLETE, "completion_reason": REASON_NO_CLEAN_SCAN},
            ]
        }
        self.assertEqual(count_clean_rack_completed_bags(payload), 1)


class TestCheckoutRushQueuesIgnoreRegistryCompletion(unittest.TestCase):
    """Accepted staging rows appear in queues regardless of registry completion_status."""

    def test_completed_accepted_in_checkout_pool(self):
        rows = [
            _staging_row(rush_type="NON-RUSH", ticket_id="DONE0001"),
        ]
        visible = checkout_visible_rows(rows)
        self.assertEqual(len(visible), 1)

    def test_incomplete_accepted_in_checkout_pool(self):
        rows = [_staging_row(rush_type="NON-RUSH", ticket_id="INC00001")]
        self.assertEqual(len(checkout_visible_rows(rows)), 1)

    def test_completed_rush_in_rush_queue(self):
        rows = [_staging_row(rush_type="RUSH", ticket_id="RUSHDONE")]
        rush = checkout_visible_rows(rows, rush_filter="RUSH")
        self.assertEqual(len(rush), 1)
        self.assertEqual(rush[0]["ticket_id"], "RUSHDONE")

    def test_incomplete_rush_in_rush_queue(self):
        rows = [_staging_row(rush_type="RUSH", ticket_id="RUSHINC")]
        self.assertEqual(len(checkout_visible_rows(rows, rush_filter="RUSH")), 1)

    def test_completed_non_checkout_rush_tab(self):
        """Non-checkout rush = NON-RUSH classification on staging row."""
        rows = [_staging_row(rush_type="NON-RUSH", ticket_id="NCRDONE")]
        non_rush = checkout_visible_rows(rows, rush_filter="NON-RUSH")
        self.assertEqual(len(non_rush), 1)

    def test_incomplete_non_checkout_rush_tab(self):
        rows = [_staging_row(rush_type="NON-RUSH", ticket_id="NCRINC")]
        self.assertEqual(len(checkout_visible_rows(rows, rush_filter="NON-RUSH")), 1)

    def test_get_orders_sql_does_not_filter_registry_completion(self):
        app_path = (
            __import__("pathlib").Path(__file__).resolve().parents[1] / "app.py"
        )
        source = app_path.read_text(encoding="utf-8")
        start = source.index("def get_orders(")
        end = source.index("@app.route(\"/checkout\"", start)
        get_orders_block = source[start:end]
        self.assertNotIn("rinse_bag_registry", get_orders_block)
        self.assertNotIn("completion_status", get_orders_block)


if __name__ == "__main__":
    unittest.main()
