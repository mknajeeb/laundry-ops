"""Rinse scan timestamps (ET), dedupe identity, immutable upsert, and timeline reads."""

from __future__ import annotations

import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

import pandas as pd

from backend.rinse_bag_completion import evaluate_bag_completion
from backend.rinse_bag_folding import evaluate_folding_performance_for_bag
from backend.rinse_bag_registry import (
    fetch_persistent_scan_events_for_bag,
    list_scan_events_for_bag,
    merge_scan_events_from_upload,
)
from backend.rinse_scan_event_identity import compute_scan_event_dedupe_key
from backend.rinse_scan_time import (
    RINSE_SCAN_SOURCE_TIMEZONE,
    json_safe_rinse,
    json_safe_system,
    parse_rinse_scanned_at,
    rinse_api_json_dumps,
    serialize_rinse_datetime_for_api,
    serialize_rinse_scan_datetime_for_api,
    serialize_system_datetime_for_api,
)


class TestRinseScanTimeET(unittest.TestCase):
    def test_sunday_may_17_2026_317_pm(self):
        raw = "Sunday, May 17, 2026 3:17 PM"
        dt = parse_rinse_scanned_at(raw)
        self.assertIsNotNone(dt)
        self.assertEqual(dt, datetime(2026, 5, 17, 15, 17, 0))

    def test_may_24_525_pm_parse_and_api_serialization(self):
        raw = "Sunday, May 24, 2026 5:25 PM"
        dt = parse_rinse_scanned_at(raw)
        self.assertEqual(dt, datetime(2026, 5, 24, 17, 25, 0))
        api = serialize_rinse_datetime_for_api(dt)
        self.assertEqual(api, "2026-05-24T17:25:00-04:00")
        payload = rinse_api_json_dumps(
            {
                "time_scanned_raw": raw,
                "scanned_at_parsed": dt,
            }
        )
        self.assertIn("2026-05-24T17:25:00-04:00", payload)
        self.assertNotIn("GMT", payload)
        self.assertNotRegex(payload, r"17:25:00Z")

    def test_json_safe_rinse_nested_scan_events(self):
        out = json_safe_rinse(
            {
                "scan_events": [
                    {
                        "scanned_at_parsed": datetime(2026, 5, 24, 17, 25),
                        "time_scanned_raw": "Sunday, May 24, 2026 5:25 PM",
                    }
                ]
            }
        )
        self.assertEqual(
            out["scan_events"][0]["scanned_at_parsed"], "2026-05-24T17:25:00-04:00"
        )

    def test_late_night_et_does_not_shift_calendar_date(self):
        raw = "Saturday, May 16, 2026 11:45 PM"
        dt = parse_rinse_scanned_at(raw)
        self.assertEqual(dt, datetime(2026, 5, 16, 23, 45, 0))


class TestSystemDatetimeUTC(unittest.TestCase):
    def test_scrape_run_utc_2337_serializes_to_et_1937(self):
        utc_naive = datetime(2026, 5, 24, 23, 37, 0)
        api = serialize_system_datetime_for_api(utc_naive)
        self.assertEqual(api, "2026-05-24T19:37:00-04:00")

    def test_upload_batch_confirmed_utc_2337(self):
        api = serialize_system_datetime_for_api(datetime(2026, 5, 24, 23, 37, 0))
        self.assertEqual(api, "2026-05-24T19:37:00-04:00")

    def test_json_safe_system_does_not_tag_utc_as_et_wall(self):
        out = json_safe_system(
            {
                "finished_at": datetime(2026, 5, 24, 23, 38, 30),
                "started_at": datetime(2026, 5, 24, 23, 30, 0),
            }
        )
        self.assertEqual(out["finished_at"], "2026-05-24T19:38:30-04:00")
        self.assertEqual(out["started_at"], "2026-05-24T19:30:00-04:00")

    def test_scan_serializer_unchanged_for_1725_wall(self):
        dt = datetime(2026, 5, 24, 17, 25, 0)
        self.assertEqual(
            serialize_rinse_scan_datetime_for_api(dt), "2026-05-24T17:25:00-04:00"
        )
        self.assertEqual(serialize_rinse_datetime_for_api(dt), "2026-05-24T17:25:00-04:00")


class TestDedupeKeyDistinctScans(unittest.TestCase):
    ORG = 3
    BAG = "5LCZ5RJ60E"

    def _key(self, *, scan_index=1, rack="CLEAN", user="U", purpose="", raw="", parsed=None):
        return compute_scan_event_dedupe_key(
            organization_id=self.ORG,
            bag_id=self.BAG,
            scan_index=scan_index,
            rack=rack,
            user_name=user,
            purpose=purpose,
            time_scanned_raw=raw,
            scanned_at_parsed=parsed,
        )

    def test_may_15_and_may_17_never_share_key(self):
        k15 = self._key(
            raw="Thursday, May 15, 2026 2:00 PM",
            parsed=datetime(2026, 5, 15, 14, 0, 0),
        )
        k17 = self._key(
            raw="Sunday, May 17, 2026 3:17 PM",
            parsed=datetime(2026, 5, 17, 15, 17, 0),
        )
        self.assertNotEqual(k15, k17)

    def test_same_rack_user_purpose_different_timestamp_different_key(self):
        base = dict(rack="FOLDING", user="Sarah", purpose="weight-entry", scan_index=2)
        k1 = self._key(
            **base,
            raw="Sunday, May 17, 2026 3:04 PM",
            parsed=datetime(2026, 5, 17, 15, 4, 0),
        )
        k2 = self._key(
            **base,
            raw="Sunday, May 17, 2026 3:17 PM",
            parsed=datetime(2026, 5, 17, 15, 17, 0),
        )
        self.assertNotEqual(k1, k2)

    def test_same_scan_index_different_rack_different_key(self):
        base = dict(
            raw="Sunday, May 17, 2026 3:04 PM",
            parsed=datetime(2026, 5, 17, 15, 4, 0),
            scan_index=2,
        )
        k1 = self._key(**base, rack="FOLDING", user="Sarah", purpose="weight-entry")
        k2 = self._key(**base, rack="CLEAN", user="Sarah", purpose="weight-entry")
        self.assertNotEqual(k1, k2)

    def test_renumbered_scan_index_same_key(self):
        base = dict(
            rack="FOLDING",
            user="Sarah",
            purpose="weight-entry",
            raw="Sunday, May 17, 2026 3:04 PM",
            parsed=datetime(2026, 5, 17, 15, 4, 0),
        )
        k1 = self._key(**base, scan_index=2)
        k2 = self._key(**base, scan_index=99)
        self.assertEqual(k1, k2)

    def test_blank_parsed_without_raw_raises(self):
        with self.assertRaises(ValueError):
            compute_scan_event_dedupe_key(
                organization_id=1,
                bag_id="B",
                scan_index=1,
                rack="CLEAN",
                user_name="U",
                purpose="",
                time_scanned_raw="",
                scanned_at_parsed=None,
            )


class ImmutableScanEventStore:
    """Mimics metadata-only upsert on dedupe_key match."""

    def __init__(self):
        self.rows: list[dict] = []
        self._next_id = 1

    def upsert(self, kwargs: dict) -> str:
        dk = kwargs["dedupe_key"]
        for existing in self.rows:
            if (
                existing["organization_id"] == kwargs["organization_id"]
                and existing["bag_id"] == kwargs["bag_id"]
                and existing["dedupe_key"] == dk
            ):
                existing["source_upload_batch_id"] = kwargs["source_upload_batch_id"]
                existing["source_filename"] = kwargs.get("source_filename")
                return "metadata_updated"
        row = {
            "id": self._next_id,
            "organization_id": kwargs["organization_id"],
            "bag_id": kwargs["bag_id"],
            "dedupe_key": dk,
            "scan_index": kwargs["scan_index"],
            "rack": kwargs["rack"],
            "time_scanned_raw": kwargs["time_scanned_raw"],
            "scanned_at_parsed": kwargs["scanned_at_parsed"],
            "source_timezone": RINSE_SCAN_SOURCE_TIMEZONE,
            "user_name": kwargs["user_name"],
            "purpose": kwargs["purpose"],
            "source_upload_batch_id": kwargs["source_upload_batch_id"],
        }
        self._next_id += 1
        self.rows.append(row)
        return "inserted"

    def by_bag(self, org: int, bag_id: str) -> list[dict]:
        return [r for r in self.rows if r["organization_id"] == org and r["bag_id"] == bag_id]


class TestImmutableUpsertAndMerge(unittest.TestCase):
    BAG = "TESTBAG01"
    ORG = 1

    def _row_df(self, bag_id: str, scan_index: int, time_scanned: str, rack: str = "CLEAN") -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "Bag ID": bag_id,
                    "Scan Index": str(scan_index),
                    "Rack": rack,
                    "Time Scanned": time_scanned,
                    "User": "Operator",
                    "Purpose": "",
                    "Last Location": "",
                    "Last Scan": "",
                }
            ]
        )

    def test_exact_duplicate_upload_metadata_only(self):
        store = ImmutableScanEventStore()
        cursor = MagicMock()
        df = self._row_df(self.BAG, 1, "Sunday, May 17, 2026 3:17 PM")

        def _side(_cursor, **kwargs):
            return store.upsert(kwargs)

        with (
            patch("backend.rinse_bag_registry.ensure_rinse_bag_tables"),
            patch("backend.rinse_bag_registry.ensure_rinse_bag_scan_events_dedupe_schema"),
            patch(
                "backend.rinse_bag_operational_owner.filter_bag_ids_for_operational_write",
                side_effect=lambda _c, _o, ids, **kw: (list(ids), []),
            ),
            patch("backend.rinse_bag_registry.upsert_scan_event_row", side_effect=_side),
        ):
            from backend.rinse_bag_completion import normalize_bag_id

            merge_scan_events_from_upload(cursor, self.ORG, 100, df, "a.csv")
            bid = normalize_bag_id(self.BAG)
            self.assertEqual(len(store.by_bag(self.ORG, bid)), 1)
            first = store.by_bag(self.ORG, bid)[0]
            merge_scan_events_from_upload(cursor, self.ORG, 200, df, "b.csv")
            self.assertEqual(len(store.by_bag(self.ORG, bid)), 1)
            second = store.by_bag(self.ORG, bid)[0]
            self.assertEqual(first["scanned_at_parsed"], second["scanned_at_parsed"])
            self.assertEqual(first["rack"], second["rack"])
            self.assertEqual(second["source_upload_batch_id"], 200)

    def test_second_upload_replaces_prior_cycle_scans(self):
        store = ImmutableScanEventStore()
        cursor = MagicMock()
        df15 = self._row_df(self.BAG, 1, "Thursday, May 15, 2026 2:00 PM", rack="FOLDING")
        df17 = self._row_df(self.BAG, 2, "Sunday, May 17, 2026 3:17 PM", rack="CLEAN")

        def _side(_cursor, **kwargs):
            return store.upsert(kwargs)

        def _delete(_cursor, org, bag_ids):
            bids = set(bag_ids)
            store.rows = [
                r
                for r in store.rows
                if not (r["organization_id"] == org and r["bag_id"] in bids)
            ]
            return len(bag_ids)

        with (
            patch("backend.rinse_bag_registry.ensure_rinse_bag_tables"),
            patch("backend.rinse_bag_registry.ensure_rinse_bag_scan_events_dedupe_schema"),
            patch(
                "backend.rinse_bag_operational_owner.filter_bag_ids_for_operational_write",
                side_effect=lambda _c, _o, ids, **kw: (list(ids), []),
            ),
            patch("backend.rinse_bag_registry.upsert_scan_event_row", side_effect=_side),
            patch(
                "backend.rinse_bag_registry.delete_persistent_scan_events_for_bags",
                side_effect=_delete,
            ),
        ):
            from backend.rinse_bag_completion import normalize_bag_id

            merge_scan_events_from_upload(cursor, self.ORG, 1, df15, "may15.csv")
            merge_scan_events_from_upload(cursor, self.ORG, 2, df17, "may17.csv")
            bid = normalize_bag_id(self.BAG)
            rows = sorted(store.by_bag(self.ORG, bid), key=lambda r: r["scanned_at_parsed"])
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["scanned_at_parsed"], datetime(2026, 5, 17, 15, 17))
            self.assertEqual(rows[0]["rack"], "CLEAN")


class TestTimelineReadPath(unittest.TestCase):
    def test_fetch_persistent_no_group_by_dedupe_key(self):
        cursor = MagicMock()
        with (
            patch("backend.rinse_bag_registry.ensure_rinse_bag_scan_events_dedupe_schema"),
            patch("backend.rinse_bag_registry.normalize_bag_id", return_value="BAG1"),
        ):
            fetch_persistent_scan_events_for_bag(cursor, 1, "BAG1")
        sql = cursor.execute.call_args[0][0]
        self.assertNotIn("GROUP BY dedupe_key", sql.upper())
        self.assertNotIn("MIN(ID)", sql.upper())
        self.assertIn("ORDER BY scanned_at_parsed ASC", sql)

    def test_list_scan_events_returns_audit_columns(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        with (
            patch("backend.rinse_bag_registry.ensure_rinse_bag_scan_events_dedupe_schema"),
            patch("backend.rinse_bag_registry.normalize_bag_id", return_value="BAG1"),
        ):
            list_scan_events_for_bag(cursor, 1, "BAG1")
        sql = cursor.execute.call_args[0][0]
        self.assertIn("source_timezone", sql)
        self.assertIn("dedupe_key", sql)
        self.assertIn("time_scanned_raw", sql)
        self.assertNotIn("GROUP BY", sql.upper())


class TestFoldingWorkDateFromETTimeline(unittest.TestCase):
    def test_folding_may_17_before_clean_same_work_date(self):
        at_fold = datetime(2026, 5, 17, 15, 4)
        at_clean = datetime(2026, 5, 17, 15, 17)
        events = [
            {"id": 1, "rack": "FOLDING", "user_name": "Sarah", "scanned_at_parsed": at_fold, "scan_index": 1},
            {"id": 2, "rack": "CLEAN", "user_name": "Train", "scanned_at_parsed": at_clean, "scan_index": 2},
        ]
        reg = {"date_clean": datetime(2026, 5, 19).date(), "completion_status": "COMPLETED"}
        perf = evaluate_folding_performance_for_bag(events, registry_row=reg)
        self.assertEqual(perf.work_date, datetime(2026, 5, 17).date())

    def test_portal_date_clean_does_not_change_work_date(self):
        at_fold = datetime(2026, 5, 17, 16, 18)
        at_clean = datetime(2026, 5, 17, 16, 20)
        events = [
            {"id": 1, "rack": "FOLDING", "user_name": "Sarah", "scanned_at_parsed": at_fold, "scan_index": 1},
            {"id": 2, "rack": "CLEAN", "user_name": "Train", "scanned_at_parsed": at_clean, "scan_index": 2},
        ]
        reg_bad = {"date_clean": datetime(2026, 5, 19).date(), "completion_status": "COMPLETED"}
        perf = evaluate_folding_performance_for_bag(events, registry_row=reg_bad)
        self.assertEqual(perf.work_date, datetime(2026, 5, 17).date())


class TestCompletionUsesETTimeline(unittest.TestCase):
    def test_clean_rack_completes_on_first_clean_scan(self):
        at_clean = datetime(2026, 5, 17, 15, 17)
        at_later = datetime(2026, 5, 17, 15, 30)
        events = [
            {"id": 1, "rack": "CLEAN", "user_name": "Train", "scanned_at_parsed": at_clean, "scan_index": 1},
            {"id": 2, "rack": "003-NY-WF", "user_name": "Driver", "scanned_at_parsed": at_later, "scan_index": 2},
        ]
        result = evaluate_bag_completion(events)
        self.assertEqual(result.completion_status, "COMPLETED")
        self.assertEqual(result.trigger_scan_event_id, 1)


if __name__ == "__main__":
    unittest.main()
