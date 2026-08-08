"""Tests for org-scoped Shift Capacity Planner parameter persistence."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from backend.shift_capacity_planner_settings import (
    DEFAULT_PLANNER_PARAMS,
    KEY_PLANNER_PARAMS,
    get_shift_capacity_planner_settings,
    save_shift_capacity_planner_settings,
    validate_planner_params,
)


class _FakeCursor:
    def __init__(self):
        self.store: dict[tuple[int, str], str] = {}

    def execute(self, sql, params=None):
        sql_norm = " ".join(sql.split()).lower()
        params = params or ()
        if "select svalue from system_settings" in sql_norm:
            org_id, key = params
            val = self.store.get((org_id, key))
            self._last = [{"svalue": val}] if val is not None else []
            return
        if "insert into system_settings" in sql_norm:
            org_id, key, value = params
            self.store[(org_id, key)] = value
            return

    def fetchone(self):
        rows = getattr(self, "_last", [])
        return rows[0] if rows else None


def test_defaults_when_unset():
    cursor = _FakeCursor()
    with patch("backend.shift_capacity_planner_settings.table_exists", return_value=True):
        settings = get_shift_capacity_planner_settings(cursor, 3)
    assert settings == DEFAULT_PLANNER_PARAMS


def test_save_round_trip_and_org_scope():
    cursor = _FakeCursor()
    payload = {
        **DEFAULT_PLANNER_PARAMS,
        "bag_count": 80,
        "start_time": "8:30 AM",
        "target_time": "2:00 PM",
        "planning_block_size_min": 45,
        "washer_count": 6,
        "dryer_count": 5,
        "weigh_sec_per_bag": 40,
        "sort_min_per_bag": 4,
        "fold_min_per_bag": 7,
    }
    with patch("backend.shift_capacity_planner_settings.table_exists", return_value=True):
        saved = save_shift_capacity_planner_settings(cursor, 3, payload)
        assert saved["bag_count"] == 80
        assert saved["planning_block_size_min"] == 45
        loaded = get_shift_capacity_planner_settings(cursor, 3)
        other = get_shift_capacity_planner_settings(cursor, 9)
    assert loaded["bag_count"] == 80
    assert loaded["start_time"] == "8:30 AM"
    assert loaded["fold_min_per_bag"] == 7
    # Org 9 has no row → defaults
    assert other == DEFAULT_PLANNER_PARAMS
    raw = json.loads(cursor.store[(3, KEY_PLANNER_PARAMS)])
    assert "staffing_intervals" not in raw
    assert set(raw.keys()) == set(DEFAULT_PLANNER_PARAMS.keys())


def test_invalid_save_does_not_overwrite():
    cursor = _FakeCursor()
    with patch("backend.shift_capacity_planner_settings.table_exists", return_value=True):
        save_shift_capacity_planner_settings(
            cursor,
            3,
            {**DEFAULT_PLANNER_PARAMS, "bag_count": 60},
        )
        with pytest.raises(ValueError, match="bag_count"):
            save_shift_capacity_planner_settings(
                cursor,
                3,
                {**DEFAULT_PLANNER_PARAMS, "bag_count": -1},
            )
        loaded = get_shift_capacity_planner_settings(cursor, 3)
    assert loaded["bag_count"] == 60


@pytest.mark.parametrize(
    "patch_fields,match",
    [
        ({"bag_count": 0}, "bag_count"),
        ({"start_time": "not-a-time"}, "start_time"),
        ({"target_time": "8:00 AM", "start_time": "9:00 AM"}, "after start"),
        ({"planning_block_size_min": 15}, "30, 45, or 60"),
        ({"washer_count": 0}, "washer_count"),
        ({"dryer_count": -2}, "dryer_count"),
        ({"weigh_sec_per_bag": 0}, "weigh_sec"),
        ({"wash_cycle_min": 0}, "wash_cycle"),
        ({"dry_cycle_min": -1}, "dry_cycle"),
        ({"sort_min_per_bag": -1}, "sort_min"),
    ],
)
def test_validate_rejects_invalid(patch_fields, match):
    with pytest.raises(ValueError, match=match):
        validate_planner_params({**DEFAULT_PLANNER_PARAMS, **patch_fields})


def test_validate_accepts_defaults():
    out = validate_planner_params(DEFAULT_PLANNER_PARAMS)
    assert out["bag_count"] == 50
    assert out["planning_block_size_min"] == 60
