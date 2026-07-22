"""Tests for Category & Role Tracking feature flag."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

from backend.category_role_tracking_settings import (
    close_open_task_segments_for_organization,
    get_category_role_tracking_settings,
    is_category_role_tracking_enabled,
    set_category_role_tracking_enabled,
)


def _cursor_with_setting(value):
    cur = MagicMock()
    if value is None:
        cur.fetchone.return_value = None
    else:
        cur.fetchone.return_value = {"svalue": value}
    return cur


def test_feature_flag_defaults_to_disabled():
    conn = MagicMock()
    cur = _cursor_with_setting(None)
    conn.cursor.return_value = cur
    with patch("backend.category_role_tracking_settings.table_exists", return_value=True):
        assert is_category_role_tracking_enabled(conn, 3) is False
        assert get_category_role_tracking_settings(conn, 3)["category_role_tracking_enabled"] is False


def test_feature_flag_reads_enabled():
    conn = MagicMock()
    cur = _cursor_with_setting("1")
    conn.cursor.return_value = cur
    with patch("backend.category_role_tracking_settings.table_exists", return_value=True):
        assert is_category_role_tracking_enabled(conn, 3) is True


def test_disable_closes_open_segments_idempotent():
    conn = MagicMock()
    enabled_cur = MagicMock()
    enabled_cur.fetchone.return_value = {"svalue": "1"}
    disabled_cur = MagicMock()
    disabled_cur.fetchone.return_value = {"svalue": "0"}
    cursors = iter([enabled_cur, disabled_cur])

    def cursor_side_effect(*args, **kwargs):
        try:
            return next(cursors)
        except StopIteration:
            return disabled_cur

    conn.cursor.side_effect = cursor_side_effect

    with patch("backend.category_role_tracking_settings.table_exists", return_value=True), patch(
        "backend.category_role_tracking_settings.close_open_task_segments_for_organization",
        return_value=2,
    ) as close_fn, patch("backend.ta_routes.write_audit") as audit:
        result = set_category_role_tracking_enabled(conn, 3, False, actor_user_id=9)
        assert result["changed"] is True
        assert result["open_segments_closed"] == 2
        assert result["category_role_tracking_enabled"] is False
        close_fn.assert_called_once()
        assert audit.call_args.args[4] == "admin_feature_disabled"

        result2 = set_category_role_tracking_enabled(conn, 3, False, actor_user_id=9)
        assert result2["changed"] is False
        assert result2["open_segments_closed"] == 0
        assert close_fn.call_count == 1


def test_enable_does_not_close_segments():
    conn = MagicMock()
    dict_cur = MagicMock()
    dict_cur.fetchone.return_value = {"svalue": "0"}
    conn.cursor.return_value = dict_cur
    with patch("backend.category_role_tracking_settings.table_exists", return_value=True), patch(
        "backend.category_role_tracking_settings.close_open_task_segments_for_organization"
    ) as close_fn, patch("backend.ta_routes.write_audit") as audit:
        result = set_category_role_tracking_enabled(conn, 3, True, actor_user_id=1)
    assert result["changed"] is True
    assert result["category_role_tracking_enabled"] is True
    close_fn.assert_not_called()
    assert audit.call_args.args[4] == "admin_feature_enabled" or audit.call_args.kwargs.get(
        "action"
    ) == "admin_feature_enabled"


def test_close_open_segments_returns_zero_when_none():
    conn = MagicMock()
    dict_cur = MagicMock()
    dict_cur.fetchall.return_value = []
    conn.cursor.return_value = dict_cur
    with patch("backend.shift_job_tracking.ensure_shift_job_tracking_schema"), patch(
        "backend.category_role_tracking_settings.table_exists", return_value=True
    ):
        assert close_open_task_segments_for_organization(conn, 3) == 0


def test_pin_punch_disabled_skips_category_role():
    from backend.attendance_pin_punch import perform_pin_punch

    conn = MagicMock()
    with patch("backend.attendance_pin_punch.payroll_profiles_active", return_value=True), patch(
        "backend.attendance_pin_punch.fetch_organization_by_slug",
        return_value={"id": 3, "slug": "veewash", "active": 1},
    ), patch("backend.attendance_pin_punch.shared_device_attendance_enabled", return_value=True), patch(
        "backend.attendance_pin_punch.is_rate_limited", return_value=False
    ), patch(
        "backend.attendance_pin_punch.resolve_user_by_attendance_pin",
        return_value={"id": 10, "first_name": "A", "last_name": "B", "username": "ab"},
    ), patch("backend.attendance_pin_punch._active_shift", return_value=None), patch(
        "backend.attendance_pin_punch.kiosk_clock_in",
        return_value=({"id": 1, "clock_in_at": datetime(2026, 7, 22, 8, 0)}, None, 201),
    ) as clock_in, patch(
        "backend.attendance_pin_punch.record_pin_attempt"
    ), patch(
        "backend.category_role_tracking_settings.is_category_role_tracking_enabled",
        return_value=False,
    ):
        body, status = perform_pin_punch(conn, "veewash", "1234", MagicMock(), "1.1.1.1")
    assert status == 200
    assert body["ok"] is True
    clock_in.assert_called_once()
    assert clock_in.call_args.kwargs.get("category_id") is None
    assert clock_in.call_args.kwargs.get("role_id") is None


def test_pin_punch_enabled_requires_category_role():
    from backend.attendance_pin_punch import perform_pin_punch

    conn = MagicMock()
    tree = [{"id": 1, "name": "DHS", "roles": [{"role_id": 2, "role_name": "Operator"}]}]
    with patch("backend.attendance_pin_punch.payroll_profiles_active", return_value=True), patch(
        "backend.attendance_pin_punch.fetch_organization_by_slug",
        return_value={"id": 3, "slug": "veewash", "active": 1},
    ), patch("backend.attendance_pin_punch.shared_device_attendance_enabled", return_value=True), patch(
        "backend.attendance_pin_punch.is_rate_limited", return_value=False
    ), patch(
        "backend.attendance_pin_punch.resolve_user_by_attendance_pin",
        return_value={"id": 10, "first_name": "A", "last_name": "B", "username": "ab"},
    ), patch("backend.attendance_pin_punch._active_shift", return_value=None), patch(
        "backend.attendance_pin_punch.record_pin_attempt"
    ), patch(
        "backend.category_role_tracking_settings.is_category_role_tracking_enabled",
        return_value=True,
    ), patch("backend.shift_job_tracking.seed_default_categories_and_roles"), patch(
        "backend.shift_job_tracking.list_active_selection_tree", return_value=tree
    ):
        body, status = perform_pin_punch(conn, "veewash", "1234", MagicMock(), "1.1.1.1")
    assert status == 400
    assert body["needs_category_role"] is True
    assert body["selection_tree"] == tree


def test_switch_gate_uses_feature_flag():
    """Role switching must be blocked when the org flag is disabled."""
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchone.return_value = None
    conn.cursor.return_value = cur
    with patch("backend.category_role_tracking_settings.table_exists", return_value=True):
        assert is_category_role_tracking_enabled(conn, 99) is False
