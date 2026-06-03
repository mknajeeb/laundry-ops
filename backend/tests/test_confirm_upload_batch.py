"""Confirm upload batch route — no confirm-time registry blocking."""

from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import MagicMock, patch

def _accepted_row(*, ticket_id: str | None = "5LCZ5RJ60E") -> dict:
    return {
        "id": 1,
        "date_clean": date.today(),
        "name_clean": "Customer A",
        "weight_num": 10.0,
        "service_type": "WF",
        "rush_type": "NON-RUSH",
        "ticket_id": ticket_id,
    }


def _confirm_post(client, batch_id: int = 1):
    return client.post(
        f"/upload_batches/{batch_id}/confirm",
        json={},
        content_type="application/json",
    )


class TestConfirmUploadBatch(unittest.TestCase):
    def setUp(self):
        from backend.app import app

        self.client = app.test_client()
        self.me = {"user_id": 1, "organization_id": 1, "roles": []}

    def _run_confirm(
        self,
        *,
        accepted_rows: list[dict],
        staging_hit: dict | None = None,
    ):
        cursor = MagicMock()
        cursor.lastrowid = 501

        def _fetchone():
            calls = getattr(_fetchone, "n", 0)
            _fetchone.n = calls + 1
            if calls == 0:
                return {"id": 1, "batch_date": date.today(), "state": "DRAFT"}
            if calls == 1:
                return {"attention_count": 0}
            return None

        _fetchone.n = 0

        def _fetchall():
            calls = getattr(_fetchall, "n", 0)
            _fetchall.n = calls + 1
            if calls == 0:
                return list(accepted_rows)
            return []

        _fetchall.n = 0
        cursor.fetchone.side_effect = _fetchone
        cursor.fetchall.side_effect = _fetchall

        conn = MagicMock()
        conn.cursor.return_value = cursor

        cap = {
            "has_ticket_id": True,
            "has_logistics": False,
            "has_processing": False,
            "has_status": True,
        }

        patches = [
            patch("backend.app.get_db", return_value=conn),
            patch("backend.app.require_user", return_value=(self.me, None, None)),
            patch("backend.app.get_upload_batches_pk", return_value="id"),
            patch("backend.app.get_upload_batch_rows_pk", return_value="id"),
            patch("backend.app.ensure_ticket_id_columns"),
            patch("backend.app.ensure_upload_batch_rows_ticket_id"),
            patch("backend.app.orders_status_capabilities", return_value=cap),
            patch("backend.app.table_has_column", return_value=False),
            patch("backend.app.table_exists", return_value=False),
            patch(
                "backend.upload_batch_requirements.validate_batch_confirm_dual_csv",
                return_value=None,
            ),
            patch("backend.app.where_not_sent_or_forced_sql", return_value="1=1"),
            patch("backend.app.orders_logistics_select_sql", return_value="NULL AS logistics_status"),
            patch("backend.app.orders_processing_select_sql", return_value="NULL AS processing_status"),
            patch(
                "backend.checkout_batch_source.upload_batch_is_auto_scrape",
                return_value=False,
            ),
            patch(
                "backend.rinse_bag_upload.find_staging_by_ticket_id",
                return_value=staging_hit,
            ),
            patch(
                "backend.rinse_bag_upload.find_active_staging_for_portal_upload",
                return_value=staging_hit,
            ),
            patch(
                "backend.rinse_bag_upload.find_active_staging_by_ticket_id",
                return_value=staging_hit,
            ),
            patch("backend.rinse_bag_upload.update_staging_from_upload_row"),
        ]

        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])

        return _confirm_post(self.client), conn, cursor

    def test_confirm_accepted_ok_inserts_staging(self):
        row = _accepted_row(ticket_id=None)
        resp, _conn, cursor = self._run_confirm(accepted_rows=[row], staging_hit=None)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "batch_confirmed")
        self.assertEqual(data["inserted_to_staging"], 1)
        self.assertEqual(data["staging_updated_by_bag_id"], 0)
        self.assertNotIn("blocked_at_confirm_count", data)
        self.assertNotIn("blocked_bag_ids", data)
        insert_sql = " ".join(
            str(c[0][0]) for c in cursor.execute.call_args_list if c[0]
        )
        self.assertIn("INSERT INTO orders_staging", insert_sql)

    def test_confirm_updated_existing_bag_updates_staging(self):
        row = _accepted_row()
        resp, _conn, cursor = self._run_confirm(
            accepted_rows=[row],
            staging_hit={"id": 99, "ticket_id": row["ticket_id"]},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "batch_confirmed")
        self.assertEqual(data["inserted_to_staging"], 0)
        self.assertEqual(data["staging_updated_by_bag_id"], 1)
        from backend.rinse_bag_upload import update_staging_from_upload_row

        update_staging_from_upload_row.assert_called_once()

    def test_confirm_registry_completed_does_not_block(self):
        """Accepted draft rows confirm even when registry is COMPLETED (same-upload case)."""
        row = _accepted_row()
        with patch(
            "backend.rinse_bag_registry.is_bag_already_completed",
            return_value=True,
        ):
            resp, _conn, _cursor = self._run_confirm(
                accepted_rows=[row],
                staging_hit={"id": 88},
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["status"], "batch_confirmed")
        self.assertEqual(resp.get_json()["staging_updated_by_bag_id"], 1)

    def test_confirm_staging_action_paths(self):
        from backend.rinse_bag_completion import confirm_staging_action

        self.assertEqual(
            confirm_staging_action(
                ticket_id="5LCZ5RJ60E",
                was_completed_before_upload=False,
                has_active_staging=True,
            ),
            "UPDATE_STAGING",
        )
        self.assertEqual(
            confirm_staging_action(
                ticket_id="5LCZ5RJ60E",
                was_completed_before_upload=False,
                has_active_staging=False,
            ),
            "INSERT_STAGING",
        )
        self.assertEqual(
            confirm_staging_action(
                ticket_id="5LCZ5RJ60E",
                was_completed_before_upload=True,
                has_active_staging=True,
            ),
            "BLOCK",
        )
        self.assertEqual(
            confirm_staging_action(
                ticket_id="5LCZ5RJ60E",
                was_completed_before_upload=True,
                has_active_staging=False,
            ),
            "INSERT_STAGING",
        )


if __name__ == "__main__":
    unittest.main()
