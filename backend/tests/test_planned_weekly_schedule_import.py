"""Tests for planned weekly schedule import parsing and name matching."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

from backend.planned_weekly_schedule_import import (
    VEEWASH_WEEK_2026_06_14,
    import_planned_weekly_schedule,
    match_worker_name,
    normalize_import_rows,
    parse_shift_label,
    sheet_role_to_planned_role,
)


def test_parse_shift_label_common_formats():
    assert parse_shift_label("Tue 6am-3pm") == (2, "06:00", "15:00")
    assert parse_shift_label("Mon 2pm-10pm") == (1, "14:00", "22:00")
    assert parse_shift_label("Sun 4pm-10pm") == (0, "16:00", "22:00")
    assert parse_shift_label("Thu 8am-4pm") == (4, "08:00", "16:00")
    assert parse_shift_label("Sat 7am-3pm") == (6, "07:00", "15:00")


def test_sheet_role_defaults_to_folder():
    assert sheet_role_to_planned_role("Wash & Fold") == "folder"
    assert sheet_role_to_planned_role("Fold") == "folder"


def test_match_worker_name_fuzzy_variants():
    workers = [
        {"user_id": 19, "display_name": "Jennifer Farfan"},
        {"user_id": 28, "display_name": "Jaspreet Singh"},
        {"user_id": 35, "display_name": "Tarannum Mithala"},
        {"user_id": 27, "display_name": "Guiying  Lin"},
    ]
    uid, name, score = match_worker_name("Jeniffer Farfan", workers)
    assert uid == 19
    assert score >= 0.84
    uid, _, _ = match_worker_name("Singh", workers)
    assert uid == 28
    uid, _, _ = match_worker_name("Tarranum Mithala", workers)
    assert uid == 35
    uid, _, _ = match_worker_name("Guiying Lin", workers)
    assert uid == 27


def test_veewash_seed_expands_to_42_shifts():
    flat = normalize_import_rows(VEEWASH_WEEK_2026_06_14)
    assert len(flat) == 42
    assert all(item.get("role") == "folder" for item in flat)


def test_import_dry_run_reports_mappings():
    workers = [
        {"user_id": 16, "display_name": "Francis Arita", "active": True},
        {"user_id": 19, "display_name": "Jennifer Farfan", "active": True},
    ]
    conn = MagicMock()
    cursor = MagicMock()
    rows = [
        {"name": "Francis Arita", "shifts": ["Tue 6am-3pm"]},
        {"name": "Jennifer Farfan", "shifts": ["Sun 8am-4pm"]},
    ]
    with patch("backend.planned_weekly_schedule_import._bulk_insert_entries") as mock_bulk:
        result = import_planned_weekly_schedule(
            conn,
            cursor,
            3,
            week_start="2026-06-14",
            rows=rows,
            workers=workers,
            dry_run=True,
        )
    mock_bulk.assert_not_called()
    assert result["created_count"] == 2
    assert result["week_start"] == "2026-06-14"
    assert result["name_failures"] == []
    assert result["name_mappings"]["Francis Arita"]["user_id"] == 16


def test_import_apply_creates_entries():
    workers = [{"user_id": 16, "display_name": "Francis Arita", "active": True}]
    conn = MagicMock()
    cursor = MagicMock()
    rows = [{"name": "Francis Arita", "shifts": ["Tue 6am-3pm"]}]
    fake_entries = [{"id": 1, "user_id": 16, "day_of_week": 2}]
    with patch(
        "backend.planned_weekly_schedule_import._bulk_insert_entries",
        return_value=fake_entries,
    ):
        result = import_planned_weekly_schedule(
            conn,
            cursor,
            3,
            week_start=date(2026, 6, 14),
            rows=rows,
            workers=workers,
            dry_run=False,
        )
    assert result["created_count"] == 1
    assert result["created"][0]["id"] == 1
