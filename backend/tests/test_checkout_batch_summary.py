"""Tests for checkout batch summary (upload batch vs staging queue)."""

from datetime import date
from unittest.mock import MagicMock, patch

from backend.checkout_batch_summary import build_checkout_batch_summary


def _mock_summary_cursor(*, batch_rows, active_staging, batch_meta=None, checked_out_staging=None):
    cursor = MagicMock()
    batch_meta = batch_meta or {
        "batch_id": 500,
        "batch_date": date(2026, 6, 1),
        "confirmed_at": None,
    }
    checked_out_staging = checked_out_staging or []

    def table_exists_side_effect(_c, name):
        return name in (
            "upload_batches",
            "upload_batch_rows",
            "orders_staging",
            "checkout_log",
            "rinse_scrape_runs",
        )

    def table_has_column_side_effect(_c, table, col):
        cols = {
            "upload_batches": {
                "batch_id",
                "organization_id",
                "confirmed_at",
                "batch_date",
                "portal_scrape_meta",
                "file_name",
            },
            "upload_batch_rows": {
                "upload_batch_id",
                "ticket_id",
                "date_clean",
                "name_clean",
                "service_type",
                "rush_type",
                "row_status",
                "reason",
                "weight_num",
            },
            "orders_staging": {
                "organization_id",
                "ticket_id",
                "rush_type",
                "logistics_status",
                "status",
                "date_clean",
                "service_type",
                "name_clean",
                "weight_num",
            },
            "checkout_log": {"order_id"},
            "rinse_scrape_runs": {"imported_batch_id", "organization_id"},
        }
        return col in cols.get(table, set())

    calls = {"n": 0}

    def execute_side_effect(sql, args=None):
        calls["n"] += 1
        calls["last"] = " ".join(str(sql).split())

    def fetchall_side_effect():
        sql = calls.get("last", "")
        if "FROM upload_batches" in sql and "upload_batch_rows" not in sql:
            return [batch_meta]
        if "FROM upload_batch_rows" in sql:
            return batch_rows
        if "FROM orders_staging o" in sql:
            return active_staging
        if "FROM orders_staging" in sql and "ticket_id" in sql:
            return checked_out_staging
        if "FROM checkout_log" in sql:
            return []
        return []

    cursor.execute.side_effect = execute_side_effect
    cursor.fetchall.side_effect = fetchall_side_effect

    import backend.checkout_batch_summary as mod

    orig_te = mod.table_exists
    orig_thc = mod.table_has_column
    mod.table_exists = table_exists_side_effect
    mod.table_has_column = table_has_column_side_effect
    auto_patch = patch(
        "backend.checkout_batch_source.upload_batch_is_auto_scrape",
        return_value=False,
    )
    auto_patch.start()
    return cursor, mod, orig_te, orig_thc, auto_patch


class TestCheckoutBatchSummary:
    def test_rush_total_from_batch_remaining_from_staging(self):
        batch_rows = [
            {
                "ticket_id": f"BAG{i}",
                "date_clean": date(2026, 6, 1),
                "name_clean": f"C{i}",
                "service_type": "WF",
                "rush_type": "RUSH",
                "row_status": "ACCEPTED",
                "reason": "OK",
                "weight_num": None,
            }
            for i in range(49)
        ] + [
            {
                "ticket_id": "DONE1",
                "date_clean": date(2026, 6, 1),
                "name_clean": "Done",
                "service_type": "WF",
                "rush_type": "RUSH",
                "row_status": "REJECTED_DUPLICATE",
                "reason": "ALREADY_COMPLETED",
                "weight_num": None,
            }
        ]
        active_staging = [
            {
                "id": i,
                "ticket_id": f"BAG{i}",
                "name_clean": f"C{i}",
                "date_clean": date(2026, 6, 1),
                "service_type": "WF",
                "effective_rush": "RUSH",
                "status": "PENDING",
                "logistics_status": "AT_WASHPRO",
                "weight_num": None,
            }
            for i in range(40)
        ]
        checked_out_staging = [
            {"ticket_id": f"BAG{i}"}
            for i in range(40, 49)
        ]
        cursor, mod, orig_te, orig_thc, auto_patch = _mock_summary_cursor(
            batch_rows=batch_rows,
            active_staging=active_staging,
            checked_out_staging=checked_out_staging,
        )
        try:
            out = build_checkout_batch_summary(cursor, 1, source="manual")
        finally:
            auto_patch.stop()
            mod.table_exists = orig_te
            mod.table_has_column = orig_thc

        assert out["rush"]["total"] == 50
        assert out["rush"]["remaining"] == 40
        assert out["rush"]["checked_out"] == 9
        assert out["rush"]["excluded_already_completed"] == 1
        assert out["rush"]["excluded_rack_scan_after_clean"] == 0
        assert out["rush"]["excluded_not_staged"] == 0
        assert len(out["missing_rush_rows"]) == 1

    def test_hd_counts_as_non_rush_batch_total(self):
        batch_rows = [
            {
                "ticket_id": "HD12BAG001",
                "date_clean": date(2026, 6, 1),
                "name_clean": "HD",
                "service_type": "HD",
                "rush_type": "NON-RUSH",
                "row_status": "ACCEPTED",
                "reason": "OK",
                "weight_num": 3,
            }
        ]
        active_staging = [
            {
                "id": 1,
                "ticket_id": "HD12BAG001",
                "name_clean": "HD",
                "date_clean": date(2026, 6, 1),
                "service_type": "HD",
                "effective_rush": "NON-RUSH",
                "status": "PENDING",
                "logistics_status": "AT_WASHPRO",
                "weight_num": 3,
            }
        ]
        cursor, mod, orig_te, orig_thc, auto_patch = _mock_summary_cursor(
            batch_rows=batch_rows, active_staging=active_staging
        )
        try:
            out = build_checkout_batch_summary(cursor, 1, source="manual")
        finally:
            auto_patch.stop()
            mod.table_exists = orig_te
            mod.table_has_column = orig_thc

        assert out["non_rush"]["total"] == 1
        assert out["non_rush"]["remaining"] == 1

    def test_hd_rush_counts_in_rush_bucket(self):
        batch_rows = [
            {
                "ticket_id": "HD12RUSH01",
                "date_clean": date(2026, 6, 2),
                "name_clean": "BlueBottle",
                "service_type": "HD",
                "rush_type": "RUSH",
                "row_status": "ACCEPTED",
                "reason": "OK",
                "weight_num": 0,
            }
        ]
        active_staging = [
            {
                "id": 1,
                "ticket_id": "HD12RUSH01",
                "name_clean": "BlueBottle",
                "date_clean": date(2026, 6, 2),
                "service_type": "HD",
                "effective_rush": "RUSH",
                "status": "PENDING",
                "logistics_status": "AT_WASHPRO",
                "weight_num": 0,
            }
        ]
        cursor, mod, orig_te, orig_thc, auto_patch = _mock_summary_cursor(
            batch_rows=batch_rows, active_staging=active_staging
        )
        try:
            out = build_checkout_batch_summary(cursor, 1, source="manual")
        finally:
            auto_patch.stop()
            mod.table_exists = orig_te
            mod.table_has_column = orig_thc

        assert out["rush"]["total"] == 1
        assert out["rush"]["remaining"] == 1
        assert out["non_rush"]["total"] == 0

    def test_accepted_not_in_queue_counts_as_not_staged_when_not_sent(self):
        batch_rows = [
            {
                "ticket_id": "SKIP1",
                "date_clean": date(2026, 6, 1),
                "name_clean": "Skip",
                "service_type": "WF",
                "rush_type": "RUSH",
                "row_status": "ACCEPTED",
                "reason": "OK",
                "weight_num": None,
            }
        ]
        cursor, mod, orig_te, orig_thc, auto_patch = _mock_summary_cursor(
            batch_rows=batch_rows, active_staging=[], checked_out_staging=[]
        )
        try:
            out = build_checkout_batch_summary(cursor, 1, source="manual")
        finally:
            auto_patch.stop()
            mod.table_exists = orig_te
            mod.table_has_column = orig_thc

        assert out["rush"]["total"] == 1
        assert out["rush"]["remaining"] == 0
        assert out["rush"]["checked_out"] == 0
        assert out["rush"]["excluded_not_staged"] == 1
        assert len(out["missing_rush_rows"]) == 1

    def test_manual_rack_scan_after_clean_counts_excluded_not_already_completed(self):
        from unittest.mock import patch

        batch_rows = [
            {
                "ticket_id": "MOVED1",
                "date_clean": date(2026, 6, 2),
                "name_clean": "Moved Bag",
                "service_type": "WF",
                "rush_type": "RUSH",
                "row_status": "REJECTED_DUPLICATE",
                "reason": "RACK_SCAN_AFTER_CLEAN",
                "weight_num": None,
            }
        ]

        def _eff(_cursor, _org, row, **kwargs):
            return ("REJECTED_DUPLICATE", "RACK_SCAN_AFTER_CLEAN")

        cursor, mod, orig_te, orig_thc, auto_patch = _mock_summary_cursor(
            batch_rows=batch_rows, active_staging=[]
        )
        with patch(
            "backend.manual_checkout_settings.washpro_manual_checkout_override_active",
            return_value=True,
        ), patch(
            "backend.manual_checkout_eligibility.effective_washpro_manual_checkout_row_status",
            side_effect=_eff,
        ):
            try:
                out = build_checkout_batch_summary(cursor, 1, source="manual")
            finally:
                auto_patch.stop()
                mod.table_exists = orig_te
                mod.table_has_column = orig_thc

        assert out["rush"]["excluded_rack_scan_after_clean"] == 1
        assert out["rush"]["excluded_already_completed"] == 0
