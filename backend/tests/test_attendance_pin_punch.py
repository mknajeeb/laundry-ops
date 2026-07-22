"""Attendance kiosk PIN punch — unit tests with mocked DB."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from backend.attendance_pin_punch import (
    ADMIN_ROLE_CODES,
    COMPLIANCE_BLOCK_MESSAGE,
    INVALID_PIN_MESSAGE,
    KIOSK_DISABLED_MESSAGE,
    OPEN_BREAK_MESSAGE,
    PIN_LEN_KIOSK,
    RATE_LIMIT_MAX_FAILURES,
    build_success_payload,
    is_rate_limited,
    perform_pin_punch,
    pin_already_used_in_org,
    resolve_user_by_attendance_pin,
    shared_device_attendance_enabled,
)
from backend.ta_helpers import hash_password, verify_password


def _mock_roles(cursor, user_id):
    return ["OPS"]


def _mock_roles_admin(cursor, user_id):
    return ["ADMIN"]


class TestAttendancePinPunchHelpers(unittest.TestCase):
    def test_pin_length_constant(self):
        self.assertEqual(PIN_LEN_KIOSK, 4)

    def test_admin_roles_frozen(self):
        self.assertIn("ADMIN", ADMIN_ROLE_CODES)

    def test_build_success_clock_in(self):
        user = {"first_name": "Sarah", "last_name": "Kamran", "username": "sk"}
        sess = {"id": 9, "clock_in_at": datetime(2026, 5, 19, 9, 0, 0)}
        out = build_success_payload(user, "CLOCK_IN", sess)
        self.assertTrue(out["ok"])
        self.assertEqual(out["action"], "CLOCK_IN")
        self.assertIn("Sarah", out["message"])
        self.assertIn("clocked in", out["message"].lower())

    def test_build_success_clock_out(self):
        user = {"first_name": "Sarah", "last_name": "K", "username": "sk"}
        sess = {"id": 9, "clock_out_at": datetime(2026, 5, 19, 17, 42, 0)}
        out = build_success_payload(user, "CLOCK_OUT", sess)
        self.assertEqual(out["action"], "CLOCK_OUT")
        self.assertIn("clocked out", out["message"].lower())

    def test_pin_duplicate_detection(self):
        pin = "1234"
        h = hash_password(pin)
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor

        def fetchall_side_effect():
            # Mimic SQL `user_id != exclude`: only return other users.
            args = cursor.execute.call_args[0][1]
            exclude_uid = int(args[1])
            rows = [{"user_id": 2, "attendance_pin_hash": h}]
            return [r for r in rows if int(r["user_id"]) != exclude_uid]

        cursor.fetchall.side_effect = fetchall_side_effect
        self.assertTrue(pin_already_used_in_org(conn, 1, pin, exclude_user_id=1))
        self.assertFalse(pin_already_used_in_org(conn, 1, pin, exclude_user_id=2))

    def test_verify_password_roundtrip(self):
        h = hash_password("5678")
        self.assertTrue(verify_password(h, "5678"))
        self.assertFalse(verify_password(h, "1234"))


class TestResolveUserByPin(unittest.TestCase):
    def test_excludes_admin_role(self):
        pin = "1234"
        h = hash_password(pin)
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchall.return_value = [
            {
                "id": 5,
                "username": "boss",
                "display_name": "Boss",
                "active": 1,
                "organization_id": 1,
                "attendance_pin_hash": h,
                "first_name": "A",
                "last_name": "B",
                "payroll_active": 1,
                "termination_date": None,
            }
        ]

        def roles_admin(c, uid):
            return ["ADMIN"]

        matched = resolve_user_by_attendance_pin(conn, 1, pin, roles_admin)
        self.assertIsNone(matched)

    def test_matches_floor_user(self):
        pin = "4321"
        h = hash_password(pin)
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchall.return_value = [
            {
                "id": 7,
                "username": "floor1",
                "display_name": "Floor One",
                "active": 1,
                "organization_id": 3,
                "attendance_pin_hash": h,
                "first_name": "Floor",
                "last_name": "One",
                "payroll_active": 1,
                "termination_date": None,
            }
        ]
        matched = resolve_user_by_attendance_pin(conn, 3, pin, _mock_roles)
        self.assertIsNotNone(matched)
        self.assertEqual(matched["id"], 7)


class TestPerformPinPunchFlow(unittest.TestCase):
    @patch("backend.attendance_pin_punch.record_pin_attempt")
    @patch("backend.attendance_pin_punch.kiosk_clock_in")
    @patch("backend.attendance_pin_punch._active_shift")
    @patch("backend.attendance_pin_punch.resolve_user_by_attendance_pin")
    @patch("backend.attendance_pin_punch.is_rate_limited", return_value=False)
    @patch("backend.attendance_pin_punch.shared_device_attendance_enabled", return_value=True)
    @patch("backend.attendance_pin_punch.fetch_organization_by_slug")
    @patch("backend.attendance_pin_punch.payroll_profiles_active", return_value=True)
    def test_clock_in_success(
        self,
        _ppa,
        fetch_org,
        _sda,
        _rl,
        resolve,
        active_shift,
        clock_in,
        _rec,
    ):
        fetch_org.return_value = {"id": 3, "slug": "veewash", "display_name": "VeeWash", "active": 1}
        resolve.return_value = {
            "id": 10,
            "first_name": "Sam",
            "last_name": "Lee",
            "username": "sam",
        }
        active_shift.return_value = None
        clock_in.return_value = ({"id": 99, "clock_in_at": datetime.utcnow()}, None, 201)

        conn = MagicMock()
        with patch(
            "backend.category_role_tracking_settings.is_category_role_tracking_enabled",
            return_value=False,
        ):
            body, status = perform_pin_punch(conn, "veewash", "1234", _mock_roles, "127.0.0.1")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["action"], "CLOCK_IN")
        self.assertNotIn("token", body)
        clock_in.assert_called_once()
        conn.commit.assert_called()

    @patch("backend.attendance_pin_punch.record_pin_attempt")
    @patch("backend.attendance_pin_punch._active_shift")
    @patch("backend.attendance_pin_punch.resolve_user_by_attendance_pin")
    @patch("backend.attendance_pin_punch.is_rate_limited", return_value=False)
    @patch("backend.attendance_pin_punch.shared_device_attendance_enabled", return_value=True)
    @patch("backend.attendance_pin_punch.fetch_organization_by_slug")
    @patch("backend.attendance_pin_punch.payroll_profiles_active", return_value=True)
    def test_clock_in_requires_category_role_when_enabled(
        self,
        _ppa,
        fetch_org,
        _sda,
        _rl,
        resolve,
        active_shift,
        _rec,
    ):
        fetch_org.return_value = {"id": 3, "slug": "veewash", "display_name": "VeeWash", "active": 1}
        resolve.return_value = {
            "id": 10,
            "first_name": "Sam",
            "last_name": "Lee",
            "username": "sam",
        }
        active_shift.return_value = None
        tree = [{"id": 1, "name": "DHS", "roles": [{"id": 2, "name": "Operator"}]}]

        conn = MagicMock()
        with patch(
            "backend.category_role_tracking_settings.is_category_role_tracking_enabled",
            return_value=True,
        ), patch(
            "backend.shift_job_tracking.seed_default_categories_and_roles"
        ), patch(
            "backend.shift_job_tracking.list_active_selection_tree", return_value=tree
        ):
            body, status = perform_pin_punch(conn, "veewash", "1234", _mock_roles, "127.0.0.1")
        self.assertEqual(status, 400)
        self.assertFalse(body["ok"])
        self.assertTrue(body["needs_category_role"])
        self.assertEqual(body["selection_tree"], tree)

    @patch("backend.attendance_pin_punch.record_pin_attempt")
    @patch("backend.attendance_pin_punch.kiosk_clock_out")
    @patch("backend.attendance_pin_punch._active_shift")
    @patch("backend.attendance_pin_punch.resolve_user_by_attendance_pin")
    @patch("backend.attendance_pin_punch.is_rate_limited", return_value=False)
    @patch("backend.attendance_pin_punch.shared_device_attendance_enabled", return_value=True)
    @patch("backend.attendance_pin_punch.fetch_organization_by_slug")
    @patch("backend.attendance_pin_punch.payroll_profiles_active", return_value=True)
    def test_clock_out_success(
        self,
        _ppa,
        fetch_org,
        _sda,
        _rl,
        resolve,
        active_shift,
        clock_out,
        _rec,
    ):
        fetch_org.return_value = {"id": 3, "slug": "washpro", "active": 1}
        resolve.return_value = {"id": 10, "first_name": "Sam", "last_name": "Lee", "username": "sam"}
        active_shift.return_value = {"id": 50, "status": "active"}
        clock_out.return_value = (
            {"id": 50, "clock_out_at": datetime(2026, 5, 19, 17, 30, 0)},
            None,
            200,
        )

        conn = MagicMock()
        body, status = perform_pin_punch(conn, "washpro", "1234", _mock_roles, "10.0.0.1")
        self.assertEqual(status, 200)
        self.assertEqual(body["action"], "CLOCK_OUT")

    @patch("backend.attendance_pin_punch.record_pin_attempt")
    @patch("backend.attendance_pin_punch.resolve_user_by_attendance_pin", return_value=None)
    @patch("backend.attendance_pin_punch.is_rate_limited", return_value=False)
    @patch("backend.attendance_pin_punch.shared_device_attendance_enabled", return_value=True)
    @patch("backend.attendance_pin_punch.fetch_organization_by_slug")
    @patch("backend.attendance_pin_punch.payroll_profiles_active", return_value=True)
    def test_invalid_pin_generic(self, _ppa, fetch_org, _sda, _rl, _res, _rec):
        fetch_org.return_value = {"id": 1, "slug": "veewash", "active": 1}
        conn = MagicMock()
        body, status = perform_pin_punch(conn, "veewash", "9999", _mock_roles, "1.2.3.4")
        self.assertEqual(status, 401)
        self.assertEqual(body["error"], INVALID_PIN_MESSAGE)
        self.assertNotIn("employee_name", body)

    @patch("backend.attendance_pin_punch.shared_device_attendance_enabled", return_value=False)
    @patch("backend.attendance_pin_punch.fetch_organization_by_slug")
    @patch("backend.attendance_pin_punch.payroll_profiles_active", return_value=True)
    def test_kiosk_disabled(self, _ppa, fetch_org, _sda):
        fetch_org.return_value = {"id": 1, "slug": "veewash", "active": 1}
        conn = MagicMock()
        body, status = perform_pin_punch(conn, "veewash", "1234", _mock_roles, "1.2.3.4")
        self.assertEqual(status, 503)
        self.assertEqual(body["error"], KIOSK_DISABLED_MESSAGE)

    @patch("backend.attendance_pin_punch.record_pin_attempt")
    @patch("backend.attendance_pin_punch.kiosk_clock_out")
    @patch("backend.attendance_pin_punch._active_shift")
    @patch("backend.attendance_pin_punch.resolve_user_by_attendance_pin")
    @patch("backend.attendance_pin_punch.is_rate_limited", return_value=False)
    @patch("backend.attendance_pin_punch.shared_device_attendance_enabled", return_value=True)
    @patch("backend.attendance_pin_punch.fetch_organization_by_slug")
    @patch("backend.attendance_pin_punch.payroll_profiles_active", return_value=True)
    def test_open_break_blocks_clock_out(
        self,
        _ppa,
        fetch_org,
        _sda,
        _rl,
        resolve,
        active_shift,
        clock_out,
        _rec,
    ):
        fetch_org.return_value = {"id": 1, "slug": "veewash", "active": 1}
        resolve.return_value = {"id": 10, "first_name": "A", "last_name": "B", "username": "ab"}
        active_shift.return_value = {"id": 1}
        clock_out.return_value = (None, OPEN_BREAK_MESSAGE, 403)

        conn = MagicMock()
        body, status = perform_pin_punch(conn, "veewash", "1234", _mock_roles, "9.9.9.9")
        self.assertEqual(status, 403)
        self.assertEqual(body["error"], OPEN_BREAK_MESSAGE)

    @patch("backend.attendance_pin_punch.record_pin_attempt")
    @patch("backend.attendance_pin_punch.kiosk_clock_in")
    @patch("backend.attendance_pin_punch._active_shift", return_value=None)
    @patch("backend.attendance_pin_punch.resolve_user_by_attendance_pin")
    @patch("backend.attendance_pin_punch.is_rate_limited", return_value=False)
    @patch("backend.attendance_pin_punch.shared_device_attendance_enabled", return_value=True)
    @patch("backend.attendance_pin_punch.fetch_organization_by_slug")
    @patch("backend.attendance_pin_punch.payroll_profiles_active", return_value=True)
    def test_compliance_blocks_clock_in(
        self,
        _ppa,
        fetch_org,
        _sda,
        _rl,
        resolve,
        _active,
        clock_in,
        _rec,
    ):
        fetch_org.return_value = {"id": 1, "slug": "veewash", "active": 1}
        resolve.return_value = {"id": 10, "first_name": "X", "last_name": "Y", "username": "xy"}
        clock_in.return_value = (None, COMPLIANCE_BLOCK_MESSAGE, 403)

        conn = MagicMock()
        with patch(
            "backend.category_role_tracking_settings.is_category_role_tracking_enabled",
            return_value=True,
        ):
            body, status = perform_pin_punch(
                conn, "veewash", "1234", _mock_roles, "8.8.8.8", category_id=1, role_id=2
            )
        self.assertEqual(status, 403)
        self.assertEqual(body["error"], COMPLIANCE_BLOCK_MESSAGE)

    @patch("backend.attendance_pin_punch.is_rate_limited", return_value=True)
    @patch("backend.attendance_pin_punch.shared_device_attendance_enabled", return_value=True)
    @patch("backend.attendance_pin_punch.fetch_organization_by_slug")
    @patch("backend.attendance_pin_punch.payroll_profiles_active", return_value=True)
    def test_rate_limited_returns_generic(self, _ppa, fetch_org, _sda, _rl):
        fetch_org.return_value = {"id": 1, "slug": "veewash", "active": 1}
        conn = MagicMock()
        body, status = perform_pin_punch(conn, "veewash", "1234", _mock_roles, "1.1.1.1")
        self.assertEqual(status, 429)
        self.assertEqual(body["error"], INVALID_PIN_MESSAGE)

    def test_wrong_pin_length(self):
        conn = MagicMock()
        body, status = perform_pin_punch(conn, "veewash", "12", _mock_roles, "1.1.1.1")
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], INVALID_PIN_MESSAGE)


class TestRateLimitCount(unittest.TestCase):
    @patch("backend.attendance_pin_punch.ensure_auth_pin_attempts_table", return_value=True)
    def test_rate_limit_threshold(self, _ensure):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchone.return_value = (RATE_LIMIT_MAX_FAILURES,)
        self.assertTrue(is_rate_limited(conn, 1, "192.168.1.1"))
        cursor.fetchone.return_value = (RATE_LIMIT_MAX_FAILURES - 1,)
        self.assertFalse(is_rate_limited(conn, 1, "192.168.1.1"))


class TestSharedDeviceFlag(unittest.TestCase):
    @patch("backend.ta_routes.load_clock_payroll_ui")
    def test_reads_setting(self, load_ui):
        load_ui.return_value = {"clock": {"shared_device_attendance": True}}
        conn = MagicMock()
        self.assertTrue(shared_device_attendance_enabled(conn, 5))

    @patch("backend.ta_routes.load_clock_payroll_ui")
    def test_default_false(self, load_ui):
        load_ui.return_value = {"clock": {}}
        conn = MagicMock()
        self.assertFalse(shared_device_attendance_enabled(conn, 5))


class TestNoAuthSessionInResponse(unittest.TestCase):
    """Success payload must never include session token fields."""

    def test_success_body_shape(self):
        user = {"first_name": "A", "last_name": "B", "username": "ab"}
        sess = {"id": 1, "clock_in_at": datetime.utcnow()}
        body = build_success_payload(user, "CLOCK_IN", sess)
        self.assertNotIn("token", body)
        self.assertNotIn("user", body)


if __name__ == "__main__":
    unittest.main()
