"""Tests for inventory v2 module."""

from __future__ import annotations

import unittest
from decimal import Decimal

from backend.inventory_module import _calc_order_totals, _money, _item_row


class InventoryModuleTests(unittest.TestCase):
    def test_money_rounding(self):
        self.assertEqual(_money("10.005"), 10.01)
        self.assertEqual(_money(None), 0.0)

    def test_calc_order_totals(self):
        lines = [
            {"qty_ordered": 3, "unit_cost": 10.0},
            {"qty_ordered": 2, "unit_cost": 5.5},
        ]
        totals = _calc_order_totals(lines, {"tax": 1, "shipping_charge": 2, "discount": 0.5})
        self.assertEqual(totals["subtotal"], 41.0)
        self.assertEqual(totals["grand_total"], 43.5)
        self.assertEqual(lines[0]["line_total"], 30.0)

    def test_item_row_mapping(self):
        row = _item_row({
            "id": 1,
            "item_name": "Poly Bags",
            "category_id": 2,
            "category_name": "Poly Bags",
            "unit_label": "case",
            "reorder_threshold": Decimal("2"),
            "on_hand_qty": Decimal("3"),
            "active": True,
            "track_weekly_check": 1,
        })
        self.assertEqual(row["name"], "Poly Bags")
        self.assertEqual(row["reorder_level"], 2.0)
        self.assertEqual(row["current_on_hand"], 3.0)
        self.assertTrue(row["track_weekly_check"])
        self.assertEqual(row["tracking_mode"], "QUANTITY")
        self.assertIsNone(row["status_level"])

    def test_item_row_status_tracking(self):
        row = _item_row({
            "id": 3,
            "item_name": "Hand Soap",
            "on_hand_qty": Decimal("0"),
            "tracking_mode": "STATUS",
            "status_level": "LOW",
            "reorder_threshold": 0,
            "active": True,
            "track_weekly_check": 1,
        })
        self.assertEqual(row["tracking_mode"], "STATUS")
        self.assertEqual(row["status_level"], "LOW")

    def test_item_estimated_value_prefers_average_cost(self):
        row = _item_row({
            "id": 2,
            "item_name": "Softener",
            "on_hand_qty": Decimal("2"),
            "average_unit_cost": Decimal("7.25"),
            "default_unit_cost": Decimal("5"),
            "reorder_threshold": 1,
            "active": True,
            "track_weekly_check": 1,
        })
        self.assertEqual(row["estimated_value"], 14.5)


if __name__ == "__main__":
    unittest.main()
