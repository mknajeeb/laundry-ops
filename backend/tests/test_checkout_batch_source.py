"""Checkout batch source (manual upload vs auto scrape)."""

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from backend.checkout_batch_summary import build_checkout_batch_summary
from backend.checkout_batch_source import (
    normalize_checkout_batch_source,
    upload_batch_is_auto_scrape,
)
from backend.ops_ui_flags import put_ops_ui_flags


class TestCheckoutBatchSource:
    def test_normalize_defaults_to_manual(self):
        assert normalize_checkout_batch_source(None) == "manual"
        assert normalize_checkout_batch_source("AUTO") == "auto"
        assert normalize_checkout_batch_source("bogus") == "manual"

    def test_upload_batch_is_auto_scrape_from_meta(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = {"portal_scrape_meta": '{"pages_scraped": 1}', "file_name": "a.csv"}

        with patch("backend.checkout_batch_source.table_exists", return_value=True), patch(
            "backend.checkout_batch_source.table_has_column", side_effect=lambda _c, t, col: True
        ):
            assert upload_batch_is_auto_scrape(cursor, 99, 3) is True

    def test_manual_source_skips_auto_scrape_batch(self):
        cursor = MagicMock()
        batches = [
            {"batch_id": 501, "batch_date": date(2026, 6, 2), "confirmed_at": datetime(2026, 6, 2, 8, 0, 0)},
            {"batch_id": 500, "batch_date": date(2026, 6, 1), "confirmed_at": datetime(2026, 6, 1, 8, 0, 0)},
        ]
        calls = {"n": 0}

        def execute_side_effect(sql, args=None):
            calls["n"] += 1
            calls["last"] = " ".join(str(sql).split())

        def fetchall_side_effect():
            if "FROM upload_batches" in calls.get("last", ""):
                return batches
            if "FROM upload_batch_rows" in calls.get("last", ""):
                return [
                    {
                        "ticket_id": "MANU0001",
                        "date_clean": date(2026, 6, 1),
                        "name_clean": "A",
                        "service_type": "WF",
                        "rush_type": "RUSH",
                        "row_status": "ACCEPTED",
                        "reason": "OK",
                        "weight_num": None,
                    }
                ]
            if "FROM orders_staging o" in calls.get("last", ""):
                return []
            if "FROM orders_staging" in calls.get("last", ""):
                return []
            return []

        cursor.execute.side_effect = execute_side_effect
        cursor.fetchall.side_effect = fetchall_side_effect

        with patch(
            "backend.checkout_batch_source.upload_batch_is_auto_scrape",
            side_effect=lambda _c, bid, _o: int(bid) == 501,
        ), patch("backend.checkout_batch_summary.table_exists", return_value=True), patch(
            "backend.checkout_batch_summary.table_has_column", return_value=True
        ):
            out = build_checkout_batch_summary(cursor, 1, source="manual")

        assert out["batch_id"] == 500
        assert out["checkout_batch_source"] == "manual"
        assert out["rush"]["total"] == 1

    def test_ops_ui_flags_persist_checkout_source(self):
        cursor = MagicMock()
        store: dict[tuple[int, str], str] = {}

        def execute_side_effect(sql, args=None):
            sql_s = " ".join(str(sql).split())
            if "SELECT svalue FROM system_settings" in sql_s:
                key = (args[0], args[1])
                val = store.get(key)
                cursor.fetchone.return_value = {"svalue": val} if val is not None else None
            elif "INSERT INTO system_settings" in sql_s:
                store[(args[0], args[1])] = args[2]

        cursor.execute.side_effect = execute_side_effect

        with patch("backend.ops_ui_flags.table_exists", return_value=True):
            put_ops_ui_flags(cursor, 1, {"checkout_batch_source": "auto"})
            assert store[(1, "ops_checkout_batch_source")] == "auto"
