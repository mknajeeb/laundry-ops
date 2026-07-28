"""Portal system users are not payroll W-2 workers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from backend.portal_system_users import (
    is_excluded_from_kiosk_at_work,
    is_portal_system_only_user,
    is_portal_system_user,
)


def test_rinse_only_is_portal_system_user():
    assert is_portal_system_only_user(["RINSE"])
    assert is_portal_system_only_user(["SYSTEM"])
    assert not is_portal_system_only_user(["RINSE", "OPS"])
    assert not is_portal_system_only_user(["SYSTEM", "CLOCK"])
    assert not is_portal_system_only_user(["ADMIN"])
    assert not is_portal_system_only_user([])


def test_is_portal_system_user_via_employment_category():
    conn = MagicMock()
    with patch(
        "backend.portal_system_users.fetch_user_role_codes",
        return_value=["CLOCK"],
    ), patch(
        "backend.portal_system_users.user_has_system_employment_category",
        return_value=True,
    ):
        assert is_portal_system_user(conn, 23) is True


def test_kiosk_at_work_excludes_admin_roles():
    conn = MagicMock()
    with patch(
        "backend.portal_system_users.user_has_system_role_flag",
        return_value=False,
    ), patch(
        "backend.portal_system_users.user_has_system_employment_category",
        return_value=False,
    ), patch(
        "backend.portal_system_users.fetch_user_role_codes",
        return_value=["ADMIN", "OPS"],
    ):
        assert is_excluded_from_kiosk_at_work(conn, 42, display_name="Joshua Cuenca") is True


def test_kiosk_at_work_excludes_known_system_names():
    conn = MagicMock()
    with patch(
        "backend.portal_system_users.user_has_system_role_flag",
        return_value=False,
    ), patch(
        "backend.portal_system_users.user_has_system_employment_category",
        return_value=False,
    ), patch(
        "backend.portal_system_users.fetch_user_role_codes",
        return_value=[],
    ):
        assert (
            is_excluded_from_kiosk_at_work(conn, 99, display_name="New VeeWash Admin") is True
        )


def test_kiosk_at_work_excludes_is_system_role_flag():
    conn = MagicMock()
    with patch(
        "backend.portal_system_users.user_has_system_role_flag",
        return_value=True,
    ), patch(
        "backend.portal_system_users.user_has_system_employment_category",
        return_value=False,
    ), patch(
        "backend.portal_system_users.fetch_user_role_codes",
        return_value=["CUSTOM_SYS"],
    ):
        assert is_excluded_from_kiosk_at_work(conn, 55, display_name="Someone") is True


def test_kiosk_at_work_excludes_ec_system_category():
    conn = MagicMock()
    with patch(
        "backend.portal_system_users.user_has_system_role_flag",
        return_value=False,
    ), patch(
        "backend.portal_system_users.user_has_system_employment_category",
        return_value=True,
    ), patch(
        "backend.portal_system_users.fetch_user_role_codes",
        return_value=["CLOCK"],
    ):
        assert is_excluded_from_kiosk_at_work(conn, 23, display_name="VeeWash Test") is True


def test_kiosk_at_work_keeps_floor_workers():
    conn = MagicMock()
    with patch(
        "backend.portal_system_users.user_has_system_role_flag",
        return_value=False,
    ), patch(
        "backend.portal_system_users.user_has_system_employment_category",
        return_value=False,
    ), patch(
        "backend.portal_system_users.fetch_user_role_codes",
        return_value=["OPS"],
    ):
        assert is_excluded_from_kiosk_at_work(conn, 7, display_name="Ana Gonzalez") is False
