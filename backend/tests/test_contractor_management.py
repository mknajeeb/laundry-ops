"""Contractor payment summary calculations and bag-ID-independent helpers."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from backend.contractor_management import (
    compute_payment_summary_amounts,
    sum_payments_ytd,
    user_in_contractor_management,
    user_is_contractor,
    user_is_short_term_temp,
    worker_kind_for_user,
)
from backend.payroll_operations import list_time_records


class TestContractorPaymentMath(unittest.TestCase):
    def test_compute_totals(self):
        out = compute_payment_summary_amounts(10, 25, 2, -5)
        self.assertEqual(out["service_amount"], 250.0)
        self.assertEqual(out["health_safety_credit_amount"], 50.0)
        self.assertEqual(out["total_payment"], 295.0)

    def test_zero_hours(self):
        out = compute_payment_summary_amounts(0, 30, 0, 0)
        self.assertEqual(out["total_payment"], 0.0)


class TestListTimeRecords(unittest.TestCase):
    def test_list_without_optional_columns(self):
        conn = MagicMock()
        cur = MagicMock()
        conn.cursor.return_value = cur
        cur.fetchall.return_value = [
            {
                "id": 1,
                "user_id": 2,
                "clock_in_at": "2026-05-01 09:00:00",
                "clock_out_at": "2026-05-01 17:00:00",
                "status": "completed",
                "total_break_seconds": 0,
                "net_work_seconds": 28800,
                "manual_override": 0,
                "period_adjustment_remarks": None,
                "first_name": "A",
                "last_name": "B",
            }
        ]

        def col_exists(_c, table, column):
            if table == "shift_sessions" and column == "organization_id":
                return False
            if table == "shift_sessions" and column == "period_adjustment_remarks":
                return False
            if table == "shift_sessions" and column == "manual_override":
                return False
            return False

        with patch("backend.payroll_operations.payroll_profiles_active", return_value=True):
            with patch("backend.payroll_operations.table_has_column", side_effect=col_exists):
                with patch(
                    "backend.payroll_operations.worker_category_for_user",
                    return_value="w2",
                ):
                    items = list_time_records(conn, 1)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["worker_category"], "w2")


class TestSumPaymentsYtd(unittest.TestCase):
    def test_sum_ytd(self):
        conn = MagicMock()
        cur = MagicMock()
        conn.cursor.return_value = cur
        cur.fetchone.return_value = {"total_paid": "697.00", "payment_count": 2}
        with patch("backend.contractor_management.table_exists", return_value=True):
            out = sum_payments_ytd(conn, 1, 9, year=2026)
        self.assertEqual(out["year"], 2026)
        self.assertEqual(out["total_paid_ytd"], 697.0)
        self.assertEqual(out["payment_count"], 2)


class TestUserIsContractor(unittest.TestCase):
    def test_contractor_lane(self):
        conn = MagicMock()
        with patch(
            "backend.contractor_management.infer_user_form_lanes",
            return_value=["contractor_1099"],
        ):
            self.assertTrue(user_is_contractor(conn, 1))

    def test_w2_only(self):
        conn = MagicMock()
        with patch(
            "backend.contractor_management.infer_user_form_lanes",
            return_value=["employee_w2"],
        ):
            self.assertFalse(user_is_contractor(conn, 1))
            self.assertFalse(user_in_contractor_management(conn, 1))

    def test_short_term_temp(self):
        conn = MagicMock()
        with patch(
            "backend.contractor_management.infer_user_form_lanes",
            return_value=["temp_worker"],
        ):
            self.assertTrue(user_is_short_term_temp(conn, 2))
            self.assertTrue(user_in_contractor_management(conn, 2))
            self.assertEqual(worker_kind_for_user(conn, 2), "short_term")


if __name__ == "__main__":
    unittest.main()
