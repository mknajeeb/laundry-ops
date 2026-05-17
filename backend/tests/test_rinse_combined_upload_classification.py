"""Same-upload vs next-upload completion classification for combined CSV upload."""

from __future__ import annotations

import unittest
from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pandas as pd

from backend.rinse_bag_completion import (
    REASON_ALREADY_COMPLETED,
    REASON_OK,
    REASON_UPDATED_EXISTING_BAG,
    classify_portal_upload_row,
)
from backend.rinse_combined_upload import (
    commit_rinse_combined_upload,
    insert_upload_batch_rows_from_orders_df,
    snapshot_pre_upload_completed_bag_ids,
)


class TestSnapshotNoRecompute(unittest.TestCase):
    def test_snapshot_does_not_recompute_before_fetch(self):
        cursor = MagicMock()
        orders = pd.DataFrame({"ticket_id": ["BAG12345"]})
        with (
            patch(
                "backend.rinse_bag_registry.fetch_pre_existing_completed_bag_ids",
                return_value=set(),
            ) as mock_fetch,
            patch("backend.rinse_bag_registry.recompute_completion_for_bags") as mock_recompute,
        ):
            result = snapshot_pre_upload_completed_bag_ids(cursor, 1, orders)
        self.assertEqual(result, set())
        mock_fetch.assert_called_once()
        mock_recompute.assert_not_called()


class TestSameUploadCompletionClassification(unittest.TestCase):
    """Live bug: INCOMPLETE → COMPLETED in same upload must not yield ALREADY_COMPLETED."""

    BAG = "30WI6KW06G"

    def test_incomplete_before_upload_accepted_after_recompute(self):
        pre_existing: set[str] = set()
        st, reason = classify_portal_upload_row(
            ticket_id=self.BAG,
            was_completed_before_upload=self.BAG in pre_existing,
            has_active_staging=True,
            row_date_before_batch=False,
        )
        self.assertEqual(st, "ACCEPTED")
        self.assertEqual(reason, REASON_UPDATED_EXISTING_BAG)

    def test_second_upload_rejects_when_in_pre_existing(self):
        pre_existing = {self.BAG}
        st, reason = classify_portal_upload_row(
            ticket_id=self.BAG,
            was_completed_before_upload=self.BAG in pre_existing,
            has_active_staging=True,
            row_date_before_batch=False,
        )
        self.assertEqual(st, "REJECTED_DUPLICATE")
        self.assertEqual(reason, REASON_ALREADY_COMPLETED)

    def test_insert_row_uses_pre_existing_only_not_live_registry(self):
        """Even if registry is COMPLETED after recompute, row must not be ALREADY_COMPLETED."""
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        cursor.fetchall.return_value = []

        schema = MagicMock(
            row_pk="id",
            upload_batches_pk="id",
            has_ub_org=True,
            cap={"has_ticket_id": True},
        )
        orders_df = pd.DataFrame(
            {
                "Date_Clean": [date.today()],
                "Name_Clean": ["Test Customer"],
                "Weight_Num": [10.0],
                "ServiceType": ["WF"],
                "RushType": ["NON-RUSH"],
                "ticket_id": [self.BAG],
            }
        )

        def _is_completed(_c, _o, bid):
            return bid == self.BAG

        with (
            patch(
                "backend.rinse_bag_upload.find_active_staging_by_ticket_id",
                return_value={"id": 99},
            ),
            patch(
                "backend.rinse_bag_registry.is_bag_already_completed",
                side_effect=_is_completed,
            ),
            patch("backend.rinse_bag_upload.upsert_registry_from_portal_row"),
            patch(
                "backend.rinse_combined_upload.build_upload_duplicate_indexes",
                return_value=(set(), {}, 3),
            ),
            patch("backend.app.table_has_column", return_value=True),
            patch("backend.app.where_not_sent_or_forced_sql", return_value="1=1"),
        ):
            counts = insert_upload_batch_rows_from_orders_df(
                cursor,
                1,
                94,
                date.today(),
                orders_df,
                schema,
                set(),
                {},
                pre_existing_completed_bag_ids=set(),
            )

        self.assertEqual(counts["rejected_rows"], 0)
        self.assertEqual(counts["rows_inserted"], 1)
        insert_calls = [
            c
            for c in cursor.execute.call_args_list
            if c[0] and "INSERT INTO upload_batch_rows" in str(c[0][0])
        ]
        self.assertEqual(len(insert_calls), 1)
        params = insert_calls[0][0][1]
        self.assertEqual(params[6], "ACCEPTED")
        self.assertEqual(params[7], REASON_UPDATED_EXISTING_BAG)


def _orders_df_for_bag(bag_id: str) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Date_Clean": [date.today()],
            "Name_Clean": ["Test Customer"],
            "Weight_Num": [10.0],
            "ServiceType": ["WF"],
            "RushType": ["NON-RUSH"],
            "ticket_id": [bag_id],
        }
    )


def _insert_bag_row(
    cursor,
    *,
    bag_id: str,
    pre_existing: set[str],
    registry_completed_now: bool,
    staging_hit: dict | None,
) -> tuple[dict, list]:
    schema = MagicMock(
        row_pk="id",
        upload_batches_pk="id",
        has_ub_org=True,
        cap={"has_ticket_id": True},
    )
    with (
        patch(
            "backend.rinse_bag_upload.find_active_staging_by_ticket_id",
            return_value=staging_hit,
        ),
        patch(
            "backend.rinse_bag_registry.is_bag_already_completed",
            return_value=registry_completed_now,
        ),
        patch("backend.rinse_bag_upload.upsert_registry_from_portal_row"),
        patch(
            "backend.rinse_combined_upload.build_upload_duplicate_indexes",
            return_value=(set(), {}, 3),
        ),
        patch("backend.app.table_has_column", return_value=True),
        patch("backend.app.where_not_sent_or_forced_sql", return_value="1=1"),
    ):
        counts = insert_upload_batch_rows_from_orders_df(
            cursor,
            1,
            94,
            date.today(),
            _orders_df_for_bag(bag_id),
            schema,
            set(),
            {},
            pre_existing_completed_bag_ids=pre_existing,
        )
    insert_calls = [
        c
        for c in cursor.execute.call_args_list
        if c[0] and "INSERT INTO upload_batch_rows" in str(c[0][0])
    ]
    return counts, insert_calls


class TestIncompleteRegistryUploadAcceptance(unittest.TestCase):
    """Registry INCOMPLETE must not reject portal rows; only pre-upload COMPLETED snapshot."""

    BAG = "30WI6KW06G"

    def test_clean_without_qualifying_later_scan_accepted_with_staging(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        cursor.fetchall.return_value = []
        counts, inserts = _insert_bag_row(
            cursor,
            bag_id=self.BAG,
            pre_existing=set(),
            registry_completed_now=False,
            staging_hit={"id": 42},
        )
        self.assertEqual(counts["rejected_rows"], 0)
        self.assertEqual(counts["rows_inserted"], 1)
        params = inserts[0][0][1]
        self.assertEqual(params[6], "ACCEPTED")
        self.assertEqual(params[7], REASON_UPDATED_EXISTING_BAG)
        self.assertNotEqual(params[7], "CLEAN_WITHOUT_QUALIFYING_LATER_SCAN")

    def test_no_clean_scan_accepted_ok_without_staging(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        cursor.fetchall.return_value = []
        counts, inserts = _insert_bag_row(
            cursor,
            bag_id=self.BAG,
            pre_existing=set(),
            registry_completed_now=False,
            staging_hit=None,
        )
        self.assertEqual(counts["rejected_rows"], 0)
        params = inserts[0][0][1]
        self.assertEqual(params[6], "ACCEPTED")
        self.assertEqual(params[7], REASON_OK)
        self.assertNotEqual(params[7], "NO_CLEAN_SCAN")

    def test_completed_during_same_upload_accepted_not_already_completed(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        cursor.fetchall.return_value = []
        counts, inserts = _insert_bag_row(
            cursor,
            bag_id=self.BAG,
            pre_existing=set(),
            registry_completed_now=True,
            staging_hit={"id": 7},
        )
        self.assertEqual(counts["rejected_rows"], 0)
        params = inserts[0][0][1]
        self.assertEqual(params[6], "ACCEPTED")
        self.assertEqual(params[7], REASON_UPDATED_EXISTING_BAG)
        self.assertNotEqual(params[7], REASON_ALREADY_COMPLETED)

    def test_pre_upload_completed_snapshot_rejects(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        cursor.fetchall.return_value = []
        counts, inserts = _insert_bag_row(
            cursor,
            bag_id=self.BAG,
            pre_existing={self.BAG},
            registry_completed_now=True,
            staging_hit={"id": 7},
        )
        self.assertEqual(counts["rejected_rows"], 1)
        params = inserts[0][0][1]
        self.assertEqual(params[6], "REJECTED_DUPLICATE")
        self.assertEqual(params[7], REASON_ALREADY_COMPLETED)

    def test_pre_upload_completed_but_recomputed_incomplete_accepted(self):
        """Stale COMPLETED in snapshot demoted to INCOMPLETE after recompute → accept."""
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        cursor.fetchall.return_value = []
        counts, inserts = _insert_bag_row(
            cursor,
            bag_id=self.BAG,
            pre_existing={self.BAG},
            registry_completed_now=False,
            staging_hit={"id": 7},
        )
        self.assertEqual(counts["rejected_rows"], 0)
        params = inserts[0][0][1]
        self.assertEqual(params[6], "ACCEPTED")
        self.assertEqual(params[7], REASON_UPDATED_EXISTING_BAG)


class TestCommitCombinedUploadFlow(unittest.TestCase):
    BAG = "5LCZ5RJ60E"

    def test_combined_upload_accepts_row_completed_in_same_transaction(self):
        orders_df = pd.DataFrame(
            {
                "Date_Clean": [date.today()],
                "Name_Clean": ["Customer"],
                "Weight_Num": [5.0],
                "ServiceType": ["WF"],
                "RushType": ["NON-RUSH"],
                "ticket_id": [self.BAG],
            }
        )
        events_df = pd.DataFrame(
            {
                "Bag ID": [self.BAG],
                "Scan Index": ["1"],
                "Rack": ["003-NY-WF"],
                "Time Scanned": ["Friday 11:04 PM"],
                "User": ["Mahmoudou Nduwayo"],
                "Purpose": [""],
                "Last Location": [""],
                "Last Scan": [""],
            }
        )

        conn = MagicMock()
        cursor = MagicMock()
        schema = MagicMock(
            row_pk="id",
            upload_batches_pk="id",
            has_ub_org=True,
            has_state=True,
            has_closed_at=True,
            has_updated_at=True,
            has_rows_inserted=True,
            time_col="created_at",
            cap={"has_ticket_id": True},
        )

        captured_pre_existing: list[set] = []
        insert_counts = {"rows_inserted": 1, "rejected_rows": 0, "needs_attention_rows": 0}

        def _snapshot(_c, _o, _df):
            captured_pre_existing.append(set())
            return set()

        def _insert(*args, **kwargs):
            captured_pre_existing.append(kwargs.get("pre_existing_completed_bag_ids", set()))
            return insert_counts

        with (
            patch("backend.rinse_combined_upload.get_upload_batch_schema", return_value=schema),
            patch("backend.rinse_combined_upload.prepare_orders_df", side_effect=lambda df: df),
            patch(
                "backend.rinse_combined_upload.snapshot_pre_upload_completed_bag_ids",
                side_effect=_snapshot,
            ),
            patch(
                "backend.rinse_combined_upload.create_draft_upload_batch_shell",
                return_value=94,
            ),
            patch(
                "backend.rinse_bag_registry.merge_scan_events_from_upload",
                return_value={"bag_ids": [self.BAG]},
            ),
            patch(
                "backend.rinse_bag_registry.recompute_completion_for_bags",
                return_value={"bags_completed": 1},
            ),
            patch(
                "backend.rinse_combined_upload.build_upload_duplicate_indexes",
                return_value=(set(), {}, 3),
            ),
            patch(
                "backend.rinse_combined_upload.insert_upload_batch_rows_from_orders_df",
                side_effect=_insert,
            ),
            patch(
                "backend.rinse_scan_events_upload.commit_scan_events_for_batch",
                return_value={"rows_inserted": 1},
            ),
            patch("backend.rinse_combined_upload.finalize_upload_batch_row_counts"),
            patch("backend.app.summarize_batch_rows", return_value={}),
            patch(
                "backend.upload_batch_requirements.batch_upload_files_status",
                return_value={"confirm_ready": True, "has_scan_events": True},
            ),
        ):
            payload = commit_rinse_combined_upload(
                conn,
                cursor,
                tenant_oid=1,
                batch_date=date.today(),
                portal_filename="portal.csv",
                orders_df=orders_df,
                events_filename="events.csv",
                events_df=events_df,
            )

        self.assertEqual(payload["batch_id"], 94)
        self.assertEqual(payload["rejected_rows"], 0)
        self.assertEqual(captured_pre_existing[0], set())
        self.assertEqual(captured_pre_existing[1], set())


if __name__ == "__main__":
    unittest.main()
