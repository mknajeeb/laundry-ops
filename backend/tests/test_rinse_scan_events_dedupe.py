"""Idempotent persistent scan-events merge and deduped reads."""

from __future__ import annotations

import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

import pandas as pd

from backend.rinse_bag_completion import evaluate_bag_completion
from backend.rinse_bag_folding import evaluate_folding_performance_for_bag
from backend.rinse_bag_registry import (
    fetch_persistent_scan_events_for_bag,
    merge_scan_events_from_upload,
)
from backend.rinse_scan_event_identity import compute_scan_event_dedupe_key


class TestScanEventDedupeKey(unittest.TestCase):
    def test_same_identity_same_key(self):
        at = datetime(2026, 5, 16, 23, 10)
        k1 = compute_scan_event_dedupe_key(
            scan_index=2,
            rack="FOLDING",
            user_name="Sarah Kamran",
            purpose="",
            scanned_at_parsed=at,
        )
        k2 = compute_scan_event_dedupe_key(
            scan_index=2,
            rack="FOLDING",
            user_name="Sarah Kamran",
            purpose=None,
            scanned_at_parsed=at,
        )
        self.assertEqual(k1, k2)

    def test_different_scan_index_different_key(self):
        at = datetime(2026, 5, 16, 23, 10)
        k1 = compute_scan_event_dedupe_key(
            scan_index=1, rack="FOLDING", user_name="U", purpose="", scanned_at_parsed=at
        )
        k2 = compute_scan_event_dedupe_key(
            scan_index=2, rack="FOLDING", user_name="U", purpose="", scanned_at_parsed=at
        )
        self.assertNotEqual(k1, k2)


class InMemoryScanEventStore:
    """Minimal store mimicking upsert by (org, bag, dedupe_key)."""

    def __init__(self):
        self.rows: list[dict] = []
        self._next_id = 1

    def upsert(self, row: dict) -> str:
        for existing in self.rows:
            if (
                existing["organization_id"] == row["organization_id"]
                and existing["bag_id"] == row["bag_id"]
                and existing["dedupe_key"] == row["dedupe_key"]
            ):
                existing.update(row)
                return "updated"
        row = dict(row)
        row["id"] = self._next_id
        self._next_id += 1
        self.rows.append(row)
        return "inserted"

    def count(self, org: int, bag_id: str) -> int:
        return sum(1 for r in self.rows if r["organization_id"] == org and r["bag_id"] == bag_id)


def _events_df(bag_id: str = "30WI6KW06G", n: int = 19) -> pd.DataFrame:
    rows = []
    for i in range(1, n + 1):
        rows.append(
            {
                "Bag ID": bag_id,
                "Scan Index": str(i),
                "Rack": "FOLDING" if i < 10 else "CLEAN",
                "Time Scanned": "Friday 11:04 PM",
                "User": "Sarah Kamran",
                "Purpose": "",
                "Last Location": "",
                "Last Scan": "",
            }
        )
    return pd.DataFrame(rows)


class TestMergeScanEventsIdempotent(unittest.TestCase):
    BAG = "30WI6KW06G"

    def test_second_upload_same_events_no_row_growth(self):
        store = InMemoryScanEventStore()
        cursor = MagicMock()
        df = _events_df(self.BAG, 19)

        def _upsert_side_effect(_cursor, **kwargs):
            action = store.upsert(
                {
                    "organization_id": kwargs["organization_id"],
                    "bag_id": kwargs["bag_id"],
                    "dedupe_key": kwargs["dedupe_key"],
                    "scan_index": kwargs["scan_index"],
                    "rack": kwargs["rack"],
                    "user_name": kwargs["user_name"],
                    "purpose": kwargs["purpose"],
                    "scanned_at_parsed": kwargs["scanned_at_parsed"],
                }
            )
            return action

        with (
            patch("backend.rinse_bag_registry.ensure_rinse_bag_tables"),
            patch("backend.rinse_bag_registry.ensure_rinse_bag_scan_events_dedupe_schema"),
            patch("backend.rinse_bag_registry.upsert_scan_event_row", side_effect=_upsert_side_effect),
        ):
            from backend.rinse_bag_completion import normalize_bag_id

            merge_scan_events_from_upload(cursor, 1, 100, df, "a.csv")
            bid = normalize_bag_id(self.BAG)
            self.assertEqual(store.count(1, bid), 19)
            merge_scan_events_from_upload(cursor, 1, 200, df, "b.csv")
            self.assertEqual(store.count(1, bid), 19)

    def test_completion_stable_with_duplicated_timeline(self):
        at0 = datetime(2026, 5, 16, 10, 0)
        at1 = datetime(2026, 5, 16, 11, 0)
        at2 = datetime(2026, 5, 16, 12, 0)
        base = [
            {"id": 1, "rack": "003-NY-WF", "user_name": "A", "scanned_at_parsed": at0, "scan_index": 1},
            {"id": 2, "rack": "FOLDING", "user_name": "Folder", "scanned_at_parsed": at1, "scan_index": 2},
            {"id": 3, "rack": "CLEAN", "user_name": "Train", "scanned_at_parsed": at2, "scan_index": 3},
        ]
        duped = base + [dict(base[1]), dict(base[2])]
        r1 = evaluate_bag_completion(base)
        r2 = evaluate_bag_completion(duped)
        self.assertEqual(r1.completion_status, r2.completion_status)
        self.assertEqual(r1.completion_reason, r2.completion_reason)

    def test_folding_stable_with_duplicated_timeline(self):
        at0 = datetime(2026, 5, 16, 10, 0)
        at1 = datetime(2026, 5, 16, 11, 0)
        at2 = datetime(2026, 5, 16, 12, 0)
        base = [
            {"id": 1, "rack": "FOLDING", "user_name": "Folder", "scanned_at_parsed": at1, "scan_index": 2},
            {"id": 2, "rack": "CLEAN", "user_name": "Train", "scanned_at_parsed": at2, "scan_index": 3},
        ]
        duped = base + [dict(base[0]), dict(base[1])]
        reg = {"date_clean": datetime(2026, 5, 16).date(), "completion_status": "COMPLETED"}
        f1 = evaluate_folding_performance_for_bag(base, registry_row=reg)
        f2 = evaluate_folding_performance_for_bag(duped, registry_row=reg)
        self.assertEqual(f1.status, f2.status)
        self.assertEqual(f1.duration_seconds, f2.duration_seconds)
        self.assertEqual(f1.assigned_user_name, f2.assigned_user_name)

    def test_fetch_persistent_uses_deduped_query(self):
        cursor = MagicMock()
        with (
            patch("backend.rinse_bag_registry.ensure_rinse_bag_scan_events_dedupe_schema"),
            patch("backend.rinse_bag_registry.normalize_bag_id", return_value="BAG1"),
        ):
            fetch_persistent_scan_events_for_bag(cursor, 1, "BAG1")
        sql = cursor.execute.call_args[0][0]
        self.assertIn("GROUP BY dedupe_key", sql)
        self.assertIn("MIN(id)", sql)


if __name__ == "__main__":
    unittest.main()
