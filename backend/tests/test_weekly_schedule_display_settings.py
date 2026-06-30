"""Tests for weekly schedule display / sharing settings."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

from backend.weekly_schedule_display_settings import (
    apply_rinse_viewer_scope,
    effective_weekly_schedule_view,
    get_weekly_schedule_display_settings,
    is_rinse_schedule_viewer,
    save_weekly_schedule_display_settings,
    validate_schedule_week_access,
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


def test_display_settings_defaults():
    cursor = _FakeCursor()
    with patch("backend.weekly_schedule_display_settings.table_exists", return_value=True):
        settings = get_weekly_schedule_display_settings(cursor, 3)
    assert settings["show_estimated_cost_default"] is False
    assert settings["show_employee_rates_default"] is False
    assert settings["schedule_end_time_enabled"] is True
    assert settings["share_cost_with_external"] is False


def test_effective_view_hides_cost_for_external():
    cursor = _FakeCursor()
    with patch("backend.weekly_schedule_display_settings.table_exists", return_value=True):
        view = effective_weekly_schedule_view(cursor, 3, ["EMPLOYEE"])
    assert view["is_privileged"] is False
    assert view["show_estimated_cost"] is False
    assert view["can_edit_schedule"] is False


def test_effective_view_admin_sees_cost_by_default():
    cursor = _FakeCursor()
    with patch("backend.weekly_schedule_display_settings.table_exists", return_value=True):
        view = effective_weekly_schedule_view(cursor, 3, ["ADMIN"])
    assert view["is_privileged"] is True
    assert view["show_estimated_cost"] is False
    assert view["show_employee_rates"] is False
    assert view["schedule_end_time_enabled"] is True


def test_save_display_settings_round_trip():
    cursor = _FakeCursor()
    with patch("backend.weekly_schedule_display_settings.table_exists", return_value=True):
        saved = save_weekly_schedule_display_settings(
            cursor,
            3,
            {"share_cost_with_external": True, "share_role_labels_with_external": False},
        )
        assert saved["share_cost_with_external"] is True
        assert saved["share_role_labels_with_external"] is False
        loaded = get_weekly_schedule_display_settings(cursor, 3)
    assert loaded["share_cost_with_external"] is True
    assert loaded["share_role_labels_with_external"] is False


def test_is_rinse_schedule_viewer():
    assert is_rinse_schedule_viewer(["RINSE"])
    assert not is_rinse_schedule_viewer(["ADMIN"])
    assert not is_rinse_schedule_viewer(["ADMIN", "RINSE"])


def test_effective_view_rinse_viewer_locked_tab():
    cursor = _FakeCursor()
    with patch("backend.weekly_schedule_display_settings.table_exists", return_value=True), patch(
        "backend.weekly_schedule_display_settings.current_schedule_week_start",
        return_value=date(2026, 6, 21),
    ):
        view = effective_weekly_schedule_view(cursor, 3, ["RINSE"])
    assert view["is_privileged"] is False
    assert view["lock_employer_tab"] is True
    assert view["hide_employer_tabs"] is True
    assert view["employer_tab"] == "rinse_exclusive"
    assert view["min_week_start"] == "2026-06-21"
    assert view["can_view_past_weeks"] is False
    assert view["can_edit_schedule"] is False
    assert view["hidden_schedule_roles"] == ["non_rinse_folder", "attendant"]


def test_apply_rinse_viewer_scope_filters_hidden_roles():
    payload = {
        "employees": [
            {"user_id": 1, "employer_affiliation": "rinse_exclusive", "default_hourly_rate": 18},
            {"user_id": 2, "employer_affiliation": "rinse_exclusive", "default_hourly_rate": 19},
        ],
        "entries": [
            {"user_id": 1, "day_of_week": 0, "hours": 7, "role": "fold", "employer_affiliation": "rinse_exclusive"},
            {"user_id": 2, "day_of_week": 1, "hours": 6, "role": "attendant", "employer_affiliation": "rinse_exclusive"},
        ],
        "excluded_user_ids": [],
        "totals": {},
    }
    scoped = apply_rinse_viewer_scope(payload, hidden_roles=["attendant"])
    assert {entry["user_id"] for entry in scoped["entries"]} == {1}
    assert {row["user_id"] for row in scoped["employees"]} == {1}


def test_save_hidden_roles_for_rinse_viewers():
    cursor = _FakeCursor()
    with patch("backend.weekly_schedule_display_settings.table_exists", return_value=True):
        saved = save_weekly_schedule_display_settings(
            cursor,
            3,
            {"hidden_roles_for_rinse_viewers": ["attendant", "invalid", "wash"]},
        )
        assert saved["hidden_roles_for_rinse_viewers"] == ["attendant", "wash"]
        loaded = get_weekly_schedule_display_settings(cursor, 3)
    assert loaded["hidden_roles_for_rinse_viewers"] == ["attendant", "wash"]


def test_validate_schedule_week_access_blocks_past_week():
    with patch(
        "backend.weekly_schedule_display_settings.current_schedule_week_start",
        return_value=date(2026, 6, 21),
    ):
        err = validate_schedule_week_access(date(2026, 6, 14), ["RINSE"])
    assert err
    assert "2026-06-21" in err


def test_validate_schedule_week_access_allows_current_week():
    with patch(
        "backend.weekly_schedule_display_settings.current_schedule_week_start",
        return_value=date(2026, 6, 21),
    ):
        assert validate_schedule_week_access(date(2026, 6, 21), ["RINSE"]) is None
        assert validate_schedule_week_access(date(2026, 6, 28), ["RINSE"]) is None


def test_apply_rinse_viewer_scope_filters_employees_and_entries():
    payload = {
        "employees": [
            {"user_id": 1, "employer_affiliation": "rinse_exclusive", "default_hourly_rate": 18},
            {"user_id": 2, "employer_affiliation": "veewash", "default_hourly_rate": 20},
            {"user_id": 3, "employer_affiliation": "both", "default_hourly_rate": 19},
        ],
        "entries": [
            {"user_id": 1, "day_of_week": 0, "hours": 7, "role": "fold", "employer_affiliation": "rinse_exclusive"},
            {"user_id": 2, "day_of_week": 0, "hours": 8, "role": "wash", "employer_affiliation": "veewash"},
            {"user_id": 3, "day_of_week": 1, "hours": 6, "role": "sort", "employer_affiliation": "rinse_exclusive"},
        ],
        "excluded_user_ids": [1, 2],
        "totals": {},
    }
    scoped = apply_rinse_viewer_scope(payload)
    assert {row["user_id"] for row in scoped["employees"]} == {1, 3}
    assert {entry["user_id"] for entry in scoped["entries"]} == {1, 3}
    assert scoped["excluded_user_ids"] == [1]
    assert scoped["totals"]["employee_totals"][3]["total_hours"] == 6.0
