"""Tests for weekly schedule display / sharing settings."""

from __future__ import annotations

from unittest.mock import patch

from backend.weekly_schedule_display_settings import (
    effective_weekly_schedule_view,
    get_weekly_schedule_display_settings,
    save_weekly_schedule_display_settings,
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
    assert settings["show_estimated_cost_default"] is True
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
    assert view["show_estimated_cost"] is True


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
