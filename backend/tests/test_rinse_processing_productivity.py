"""Processing productivity (start-cleaning scans)."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pytest

from backend.rinse_processing_productivity import (
    build_clocked_processing_summary,
    build_processing_productivity,
    build_processing_record_rows,
    dedupe_processing_scans,
    load_start_cleaning_scan_rows,
)
from backend.rinse_processing_settings import (
    DEFAULT_DRY,
    DEFAULT_SORT,
    DEFAULT_WASH,
    DEFAULT_WEIGH,
    get_processing_settings,
    put_processing_settings,
)
from backend.rinse_scan_purpose import is_start_cleaning_purpose, normalize_scan_purpose


class TestScanPurpose:
    def test_start_cleaning_normalized(self):
        assert is_start_cleaning_purpose("Start-Cleaning last scan")
        assert normalize_scan_purpose("Start  Cleaning") == "start-cleaning"

    def test_not_start_cleaning(self):
        assert not is_start_cleaning_purpose("move-bag")


class TestDedupeAndSettings:
    def test_duplicate_start_cleaning_deduped(self):
        rows = [
            {
                "user_name": "U1",
                "bag_id": "B1",
                "scanned_at_parsed": datetime(2026, 5, 16, 9, 0),
                "scan_index": 2,
            },
            {
                "user_name": "U1",
                "bag_id": "B1",
                "scanned_at_parsed": datetime(2026, 5, 16, 8, 0),
                "scan_index": 1,
            },
        ]
        out = dedupe_processing_scans(rows)
        assert len(out) == 1
        assert out[0]["scanned_at_parsed"] == datetime(2026, 5, 16, 8, 0)

    def test_estimated_time_uses_settings(self):
        settings = {
            "total_seconds_per_bag": DEFAULT_WEIGH + DEFAULT_SORT + DEFAULT_WASH + DEFAULT_DRY,
            "total_minutes_per_bag": 7.5,
        }
        recs = build_processing_record_rows(
            [
                {
                    "bag_id": "B1",
                    "user_name": "U",
                    "name_clean": "Cust",
                    "weight_num": 10.0,
                    "scanned_at_parsed": datetime(2026, 5, 16, 10, 0),
                    "scan_event_id": 1,
                }
            ],
            settings=settings,
        )
        assert recs[0]["estimated_processing_seconds"] == 450
        assert recs[0]["estimated_processing_minutes"] == 7.5

    def test_settings_update_changes_total(self, monkeypatch):
        sets: dict[tuple[int, str], str] = {}

        def _get(cursor, org, key):
            return sets.get((org, key))

        def _set(cursor, org, key, val):
            sets[(org, key)] = str(val)

        monkeypatch.setattr("backend.rinse_processing_settings.table_exists", lambda c: True)
        monkeypatch.setattr("backend.rinse_processing_settings._get_setting", _get)
        monkeypatch.setattr("backend.rinse_processing_settings._set_setting", _set)
        cursor = MagicMock()
        put_processing_settings(cursor, 3, {"processing_sort_seconds_per_bag": 60})
        out = get_processing_settings(cursor, 3)
        assert out["processing_sort_seconds_per_bag"] == 60
        assert out["total_seconds_per_bag"] == DEFAULT_WEIGH + 60 + DEFAULT_WASH + DEFAULT_DRY


class TestLoadScans:
    def test_et_range_filter_in_sql(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = [
            {
                "scan_event_id": 1,
                "bag_id": "B1",
                "user_name": "U",
                "purpose": "start-cleaning",
                "scanned_at_parsed": datetime(2026, 5, 16, 12, 0),
                "scan_index": 1,
                "name_clean": None,
                "weight_num": None,
            }
        ]
        with patch(
            "backend.rinse_processing_productivity.ensure_rinse_bag_scan_events_dedupe_schema"
        ):
            load_start_cleaning_scan_rows(
                cursor,
                3,
                period_start=date(2026, 5, 16),
                period_end=date(2026, 5, 16),
            )
        sql = cursor.execute.call_args[0][0]
        assert "scanned_at_parsed >=" in sql
        assert "scanned_at_parsed <" in sql
        args = cursor.execute.call_args[0][1]
        assert args[1] == datetime(2026, 5, 16, 0, 0, 0)
        assert args[2] == datetime(2026, 5, 17, 0, 0, 0)

    def test_prior_day_excluded_by_range(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        with patch(
            "backend.rinse_processing_productivity.ensure_rinse_bag_scan_events_dedupe_schema"
        ):
            rows = load_start_cleaning_scan_rows(
                cursor,
                3,
                period_start=date(2026, 5, 16),
                period_end=date(2026, 5, 16),
            )
        assert rows == []
        args = cursor.execute.call_args[0][1]
        assert args[2] == datetime(2026, 5, 17, 0, 0, 0)


class TestClockMapping:
    def test_clock_hour_uses_shift_sessions(self, monkeypatch):
        monkeypatch.setattr(
            "backend.ta_helpers.table_exists",
            lambda c, t: True,
        )
        monkeypatch.setattr(
            "backend.rinse_processing_productivity._load_shift_sessions",
            lambda *a, **k: [
                {
                    "id": 9,
                    "clock_in_at": datetime(2026, 5, 16, 8, 0),
                    "clock_out_at": datetime(2026, 5, 16, 16, 0),
                    "status": "completed",
                }
            ],
        )
        monkeypatch.setattr(
            "backend.rinse_processing_productivity._last_rinse_sync_naive",
            lambda *a, **k: None,
        )
        cursor = MagicMock()
        records = [
            {
                "bag_id": "B1",
                "weight_lbs": 5.0,
                "start_cleaning_at": datetime(2026, 5, 16, 10, 0),
            }
        ]
        out = build_clocked_processing_summary(
            cursor,
            3,
            user_id=1,
            records=records,
            period_start=date(2026, 5, 16),
            period_end=date(2026, 5, 16),
        )
        assert out["available"] is True
        assert out["summary"]["total_bags"] == 1
        assert out["summary"]["clocked_hours"] == 8.0

    def test_unmapped_no_clock_summary(self, monkeypatch):
        monkeypatch.setattr(
            "backend.rinse_folding_user_productivity.get_user_map",
            lambda *a, **k: None,
        )
        monkeypatch.setattr(
            "backend.rinse_processing_productivity.load_start_cleaning_scan_rows",
            lambda *a, **k: [
                {
                    "user_name": "RinseOnly",
                    "bag_id": "B1",
                    "purpose": "start-cleaning",
                    "scanned_at_parsed": datetime(2026, 5, 16, 9, 0),
                    "scan_index": 1,
                    "name_clean": "C",
                    "weight_num": 3.0,
                    "scan_event_id": 1,
                }
            ],
        )
        monkeypatch.setattr(
            "backend.rinse_processing_productivity.get_processing_settings",
            lambda *a, **k: {"total_seconds_per_bag": 450, "total_minutes_per_bag": 7.5},
        )
        cursor = MagicMock()
        payload = build_processing_productivity(
            cursor,
            3,
            period_start=date(2026, 5, 16),
            period_end=date(2026, 5, 16),
            user_name="RinseOnly",
        )
        clocked = payload["users"][0]["clocked_productivity"]
        assert clocked["available"] is False
        assert payload["users"][0]["bag_level"]["total_bags"] == 1

    def test_mapped_has_clock_summary(self, monkeypatch):
        monkeypatch.setattr(
            "backend.rinse_folding_user_productivity.get_user_map",
            lambda *a, **k: {"user_id": 5, "display_name": "Emp"},
        )
        monkeypatch.setattr(
            "backend.rinse_processing_productivity.load_start_cleaning_scan_rows",
            lambda *a, **k: [
                {
                    "user_name": "Alex",
                    "bag_id": "B1",
                    "purpose": "start-cleaning",
                    "scanned_at_parsed": datetime(2026, 5, 16, 9, 0),
                    "scan_index": 1,
                    "weight_num": 2.0,
                    "scan_event_id": 2,
                }
            ],
        )
        monkeypatch.setattr(
            "backend.rinse_processing_settings.get_processing_settings",
            lambda *a, **k: {"total_seconds_per_bag": 450, "total_minutes_per_bag": 7.5},
        )
        monkeypatch.setattr(
            "backend.rinse_processing_productivity.build_clocked_processing_summary",
            lambda *a, **k: {
                "available": True,
                "summary": {"clocked_hours": 7.5, "total_bags": 1, "total_lbs": 2.0},
                "shifts": [],
            },
        )
        cursor = MagicMock()
        payload = build_processing_productivity(
            cursor,
            3,
            period_start=date(2026, 5, 16),
            period_end=date(2026, 5, 16),
            user_name="Alex",
        )
        assert payload["users"][0]["clocked_productivity"]["available"] is True


class TestRecordsAndRoutes:
    def test_record_table_has_order_and_timeline_ids(self):
        settings = {"total_seconds_per_bag": 450, "total_minutes_per_bag": 7.5}
        recs = build_processing_record_rows(
            [
                {
                    "bag_id": "BAG99",
                    "user_name": "U",
                    "scanned_at_parsed": datetime(2026, 5, 16, 11, 0),
                    "scan_event_id": 42,
                }
            ],
            settings=settings,
        )
        assert recs[0]["bag_id"] == "BAG99"
        assert recs[0]["scan_event_id"] == 42

    def test_start_cleaning_counts_as_processing_bag(self, monkeypatch):
        monkeypatch.setattr(
            "backend.rinse_processing_productivity.load_start_cleaning_scan_rows",
            lambda *a, **k: [
                {
                    "user_name": "U",
                    "bag_id": "B1",
                    "purpose": "start-cleaning",
                    "scanned_at_parsed": datetime(2026, 5, 16, 9, 0),
                    "scan_index": 1,
                    "weight_num": 1.0,
                    "scan_event_id": 1,
                }
            ],
        )
        monkeypatch.setattr(
            "backend.rinse_folding_user_productivity.get_user_map",
            lambda *a, **k: None,
        )
        monkeypatch.setattr(
            "backend.rinse_processing_productivity.get_processing_settings",
            lambda *a, **k: {"total_seconds_per_bag": 450, "total_minutes_per_bag": 7.5},
        )
        cursor = MagicMock()
        payload = build_processing_productivity(
            cursor,
            3,
            period_start=date(2026, 5, 16),
            period_end=date(2026, 5, 16),
            user_name="U",
        )
        assert payload["summary_all_users"]["total_bags"] == 1
