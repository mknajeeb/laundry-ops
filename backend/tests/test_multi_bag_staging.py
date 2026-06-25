"""Ticket-ID-first staging for multi-bag same-customer uploads."""

from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import MagicMock, patch

from backend.checkout_batch_scope import reapply_checkout_batch_staging
from backend.checkout_batch_staging import upsert_staging_for_ticket_upload_row


def _row(ticket_id: str, name: str = "Margaret Baptiste 0") -> dict:
    return {
        "date_clean": date(2026, 6, 3),
        "name_clean": name,
        "weight_num": None,
        "service_type": "WF",
        "rush_type": "RUSH",
        "ticket_id": ticket_id,
    }


class TestTicketFirstStaging(unittest.TestCase):
    def setUp(self):
        self.cap = {
            "has_ticket_id": True,
            "has_logistics": True,
            "has_processing": True,
            "has_status": True,
        }
        self._log_patcher = patch(
            "backend.checkout_batch_staging.ticket_has_checkout_log",
            return_value=False,
        )
        self._log_patcher.start()

    def tearDown(self):
        self._log_patcher.stop()

    def test_same_customer_different_ticket_ids_insert_separate_rows(self):
        cursor = MagicMock()
        cursor.lastrowid = 9001

        with patch(
            "backend.checkout_batch_staging.find_staging_by_ticket_id",
            return_value=None,
        ), patch("backend.checkout_batch_staging.update_staging_from_upload_row") as upd:
            a, id_a = upsert_staging_for_ticket_upload_row(
                cursor, 1, _row("BAGAAAAAAA"), date(2026, 6, 3), self.cap
            )
            cursor.lastrowid = 9002
            b, id_b = upsert_staging_for_ticket_upload_row(
                cursor, 1, _row("BAGBBBBBBB"), date(2026, 6, 3), self.cap
            )

        self.assertEqual(a, "inserted")
        self.assertEqual(b, "inserted")
        self.assertNotEqual(id_a, id_b)
        upd.assert_not_called()
        insert_sqls = [
            str(c.args[0]) for c in cursor.execute.call_args_list if "INSERT INTO orders_staging" in str(c.args[0])
        ]
        self.assertEqual(len(insert_sqls), 2)

    def test_existing_ticket_updates_same_row_not_sibling_identity(self):
        cursor = MagicMock()
        existing = {"id": 42, "ticket_id": "BAGAAAAAAA", "logistics_status": "AT_WASHPRO"}

        with patch(
            "backend.checkout_batch_staging.find_staging_by_ticket_id",
            return_value=existing,
        ), patch("backend.checkout_batch_staging.update_staging_from_upload_row") as upd:
            action, sid = upsert_staging_for_ticket_upload_row(
                cursor, 1, _row("BAGAAAAAAA"), date(2026, 6, 3), self.cap
            )

        self.assertEqual(action, "updated")
        self.assertEqual(sid, 42)
        upd.assert_called_once()

    def test_repair_skips_sent_staging(self):
        cursor = MagicMock()
        row = _row("SENTBAG001")
        cursor.fetchone.return_value = {"batch_id": 624, "batch_date": date(2026, 6, 3)}
        cursor.fetchall.return_value = [row]

        with patch(
            "backend.checkout_batch_scope._row_batch_col", return_value="upload_batch_id"
        ), patch("backend.checkout_batch_scope.table_exists", return_value=True), patch(
            "backend.checkout_batch_scope.table_has_column", return_value=True
        ), patch(
            "backend.checkout_batch_staging.upsert_staging_for_ticket_upload_row",
            return_value=("skipped", None),
        ) as upsert:
            out = reapply_checkout_batch_staging(cursor, 1, 624, dry_run=False)

        upsert.assert_called_once()
        self.assertEqual(upsert.call_args.kwargs.get("reactivate_sent"), False)
        self.assertEqual(out["skipped"], 1)

    def test_dry_run_skips_sent_without_reactivating(self):
        cursor = MagicMock()
        row = _row("SENTBAG002")
        cursor.fetchone.return_value = {"batch_id": 624, "batch_date": date(2026, 6, 3)}
        cursor.fetchall.return_value = [row]

        with patch(
            "backend.checkout_batch_scope._row_batch_col", return_value="upload_batch_id"
        ), patch("backend.checkout_batch_scope.table_exists", return_value=True), patch(
            "backend.checkout_batch_scope.table_has_column", return_value=True
        ), patch(
            "backend.rinse_bag_upload.find_staging_by_ticket_id",
            return_value={"id": 1, "logistics_status": "SENT_TO_RINSE"},
        ):
            out = reapply_checkout_batch_staging(cursor, 1, 624, dry_run=True)

        self.assertEqual(out["skipped"], 1)
        self.assertEqual(out["inserted"], 0)

    def test_sent_staging_skipped_when_reactivate_false(self):
        cursor = MagicMock()
        existing = {"id": 99, "ticket_id": "SENT001", "logistics_status": "SENT_TO_RINSE"}

        with patch(
            "backend.checkout_batch_staging.find_staging_by_ticket_id",
            return_value=existing,
        ), patch("backend.checkout_batch_staging.update_staging_from_upload_row") as upd:
            action, sid = upsert_staging_for_ticket_upload_row(
                cursor,
                1,
                _row("SENT001"),
                date(2026, 6, 3),
                self.cap,
                reactivate_sent=False,
            )

        self.assertEqual(action, "skipped")
        self.assertIsNone(sid)
        upd.assert_not_called()

    def test_no_ticket_id_skipped_by_upsert(self):
        cursor = MagicMock()
        row = _row("BAGX")
        row.pop("ticket_id")
        action, sid = upsert_staging_for_ticket_upload_row(
            cursor, 1, row, date(2026, 6, 3), self.cap
        )
        self.assertEqual(action, "skipped")
        self.assertIsNone(sid)

    def test_skips_staging_when_ticket_already_has_checkout_log(self):
        cursor = MagicMock()
        with patch(
            "backend.checkout_batch_staging.ticket_has_checkout_log",
            return_value=True,
        ), patch(
            "backend.checkout_batch_staging.find_staging_by_ticket_id",
        ) as find_staging, patch(
            "backend.checkout_batch_staging.insert_staging_from_upload_row",
        ) as ins:
            action, sid = upsert_staging_for_ticket_upload_row(
                cursor, 3, _row("44SES6FL9A"), date(2026, 6, 4), self.cap
            )
        self.assertEqual(action, "skipped")
        self.assertIsNone(sid)
        find_staging.assert_not_called()
        ins.assert_not_called()

    def test_insert_staging_uses_credential_sourced_owner_gate(self):
        cursor = MagicMock()
        cursor.lastrowid = 9001
        canonical = MagicMock()
        canonical.owner_organization_id = 3

        with patch(
            "backend.checkout_batch_staging.find_staging_by_ticket_id",
            return_value=None,
        ), patch(
            "backend.rinse_bag_operational_owner.assert_operational_write_allowed",
            return_value=(True, None, canonical),
        ) as gate:
            action, sid = upsert_staging_for_ticket_upload_row(
                cursor, 1, _row("E9ZDC1B7MW"), date(2026, 6, 25), self.cap
            )

        self.assertEqual(action, "inserted")
        self.assertEqual(sid, 9001)
        gate.assert_called_once()
        self.assertTrue(gate.call_args.kwargs.get("credential_sourced"))


class TestBatchSummaryNotStaged(unittest.TestCase):
    def test_accepted_ticket_not_excluded_when_staged_by_ticket(self):
        from datetime import date as dt_date
        from backend.checkout_batch_summary import build_checkout_batch_summary

        batch_rows = [
            {
                "ticket_id": "BAGAAAAAAA",
                "date_clean": dt_date(2026, 6, 3),
                "name_clean": "Margaret Baptiste 0",
                "service_type": "WF",
                "rush_type": "RUSH",
                "row_status": "ACCEPTED",
                "reason": "OK",
                "weight_num": None,
            },
            {
                "ticket_id": "BAGBBBBBBB",
                "date_clean": dt_date(2026, 6, 3),
                "name_clean": "Margaret Baptiste 0",
                "service_type": "WF",
                "rush_type": "RUSH",
                "row_status": "ACCEPTED",
                "reason": "OK",
                "weight_num": None,
            },
        ]
        active_staging = [
            {
                "id": 1,
                "ticket_id": "BAGAAAAAAA",
                "name_clean": "Margaret Baptiste 0",
                "date_clean": dt_date(2026, 6, 3),
                "service_type": "WF",
                "effective_rush": "RUSH",
                "status": "PENDING",
                "logistics_status": "AT_WASHPRO",
                "weight_num": None,
            },
            {
                "id": 2,
                "ticket_id": "BAGBBBBBBB",
                "name_clean": "Margaret Baptiste 0",
                "date_clean": dt_date(2026, 6, 3),
                "service_type": "WF",
                "effective_rush": "RUSH",
                "status": "PENDING",
                "logistics_status": "AT_WASHPRO",
                "weight_num": None,
            },
        ]

        from backend.tests.test_checkout_batch_summary import _mock_summary_cursor

        cursor, mod, orig_te, orig_thc, auto_patch, override_patch = _mock_summary_cursor(
            batch_rows=batch_rows,
            active_staging=active_staging,
        )
        try:
            out = build_checkout_batch_summary(cursor, 1, source="manual")
        finally:
            override_patch.stop()
            auto_patch.stop()
            mod.table_exists = orig_te
            mod.table_has_column = orig_thc

        self.assertEqual(out["rush"]["total"], 2)
        self.assertEqual(out["rush"]["remaining"], 2)
        self.assertEqual(out["rush"]["excluded_not_staged"], 0)


if __name__ == "__main__":
    unittest.main()
