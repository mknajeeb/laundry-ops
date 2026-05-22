"""Contractor payment summary calculations and bag-ID-independent helpers."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from backend.contractor_management import (
    compute_payment_summary_amounts,
    user_in_contractor_management,
    user_is_contractor,
    user_is_short_term_temp,
    worker_kind_for_user,
)


class TestContractorPaymentMath(unittest.TestCase):
    def test_compute_totals(self):
        out = compute_payment_summary_amounts(10, 25, 2, -5)
        self.assertEqual(out["service_amount"], 250.0)
        self.assertEqual(out["health_safety_credit_amount"], 50.0)
        self.assertEqual(out["total_payment"], 295.0)

    def test_zero_hours(self):
        out = compute_payment_summary_amounts(0, 30, 0, 0)
        self.assertEqual(out["total_payment"], 0.0)


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
