"""Production hardening tests for Inventory v2.5."""

from __future__ import annotations

import re
import threading
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

from backend.inventory_constants import (
    LEGACY_MIGRATION_SETTING_KEY,
    ORDER_RECEIVED,
    PURCHASE_SPEND_STATUSES,
    STOCK_CHECK_DRAFT,
    STOCK_CHECK_SUBMITTED,
)
from backend.inventory_module import (
    StockCheckConflictError,
    _item_row,
    _sum_purchase_orders,
    manual_adjustment,
    migrate_legacy_inventory,
    receive_order,
    submit_stock_check,
)
from backend.inventory_ops import build_dashboard

ROOT = Path(__file__).resolve().parents[2]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


class InventoryHardeningTests(unittest.TestCase):
    def test_purchase_spend_statuses_include_received(self):
        self.assertIn(ORDER_RECEIVED, PURCHASE_SPEND_STATUSES)

    def test_sum_purchase_orders_filters_by_order_date(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = {"total": Decimal("125.50")}
        total = _sum_purchase_orders(cursor, 3, date(2026, 7, 1), date(2026, 7, 7))
        self.assertEqual(total, 125.5)
        sql = cursor.execute.call_args[0][0]
        self.assertIn("order_date IS NOT NULL", sql)
        params = cursor.execute.call_args[0][1]
        self.assertIn(ORDER_RECEIVED, params)

    def test_item_estimated_value_uses_on_hand_times_avg_cost(self):
        row = _item_row({
            "id": 1,
            "item_name": "Detergent",
            "on_hand_qty": Decimal("4"),
            "average_unit_cost": Decimal("12.50"),
            "default_unit_cost": Decimal("10"),
            "reorder_threshold": 2,
            "active": True,
            "track_weekly_check": 1,
        })
        self.assertEqual(row["estimated_value"], 50.0)
        self.assertEqual(row["current_on_hand"], 4.0)

    @patch("backend.inventory_module.ensure_inventory_tables")
    @patch("backend.inventory_module.get_org_setting", return_value="1")
    def test_legacy_migration_skips_when_flag_set(self, _setting, _ensure):
        cursor = MagicMock()
        migrate_legacy_inventory(cursor, 3)
        cursor.execute.assert_not_called()

    @patch("backend.inventory_module.save_org_setting")
    @patch("backend.inventory_module.get_org_setting", return_value=None)
    @patch("backend.inventory_module.ensure_inventory_tables")
    def test_legacy_migration_marks_complete(self, _ensure, _get, save_setting):
        cursor = MagicMock()

        def _fetchone():
            sql = cursor.execute.call_args[0][0] if cursor.execute.call_args else ""
            if "COUNT(*)" in sql:
                return {"c": 0}
            if "SELECT id FROM inventory_categories" in sql:
                return {"id": 1}
            if "SELECT id FROM inventory_vendors" in sql:
                return {"id": 2}
            return {}

        cursor.fetchone.side_effect = _fetchone
        cursor.fetchall.return_value = []
        with patch("backend.inventory_module._migrate_legacy_bag_price"):
            migrate_legacy_inventory(cursor, 3)
        save_setting.assert_called_once_with(cursor, 3, LEGACY_MIGRATION_SETTING_KEY, "1")
        executed = " ".join(str(call[0][0]) for call in cursor.execute.call_args_list)
        self.assertIn("INSERT IGNORE INTO inventory_categories", executed)

    def test_manual_adjustment_requires_reason_code(self):
        cursor = MagicMock()
        with self.assertRaises(ValueError) as ctx:
            manual_adjustment(cursor, 3, {"item_id": 1, "qty_change": 1}, 1, "Tester")
        self.assertIn("reason_code", str(ctx.exception).lower())

    @patch("backend.inventory_module.list_reorder_suggestions", return_value=[])
    @patch("backend.inventory_module.get_item")
    @patch("backend.inventory_module.get_draft_stock_check")
    @patch("backend.inventory_module.save_stock_check_draft")
    @patch("backend.inventory_module.get_variance_threshold", return_value=5)
    @patch("backend.inventory_module.ensure_inventory_tables")
    def test_stock_check_submit_blocked_when_already_submitted(
        self, _ensure, _threshold, _save_draft, get_draft, get_item, _reorder
    ):
        cursor = MagicMock()
        cursor.fetchone.return_value = {"status": STOCK_CHECK_SUBMITTED}
        get_draft.return_value = {"id": 9, "lines": {1: {"item_id": 1, "counted_qty": 5}}}
        get_item.return_value = {"id": 1, "name": "Bags", "current_on_hand": 4}
        with self.assertRaises(StockCheckConflictError) as ctx:
            submit_stock_check(cursor, 3, {"lines": [{"item_id": 1, "counted_qty": 5}], "oneshot": True}, 1, "Tester")
        self.assertIn("already submitted", str(ctx.exception).lower())

    @patch("backend.inventory_module.list_reorder_suggestions", return_value=[])
    @patch("backend.inventory_module.get_item")
    @patch("backend.inventory_module.get_draft_stock_check")
    @patch("backend.inventory_module.save_stock_check_draft")
    @patch("backend.inventory_module.get_variance_threshold", return_value=5)
    @patch("backend.inventory_module.ensure_inventory_tables")
    def test_stock_check_submit_updates_qty_once(
        self, _ensure, _threshold, _save_draft, get_draft, get_item, _reorder
    ):
        cursor = MagicMock()
        cursor.fetchone.return_value = {"status": STOCK_CHECK_DRAFT}
        cursor.rowcount = 1
        get_draft.return_value = {"id": 9, "lines": {1: {"item_id": 1, "counted_qty": 6}}}
        get_item.return_value = {"id": 1, "name": "Bags", "current_on_hand": 4}
        out = submit_stock_check(cursor, 3, {"lines": [{"item_id": 1, "counted_qty": 6}], "oneshot": True}, 1, "Tester")
        self.assertEqual(out["lines_submitted"], 1)
        update_calls = [c for c in cursor.execute.call_args_list if "UPDATE inventory_items SET on_hand_qty" in str(c[0][0])]
        self.assertEqual(len(update_calls), 1)
        adj_calls = [c for c in cursor.execute.call_args_list if "INSERT INTO inventory_adjustments" in str(c[0][0])]
        self.assertEqual(len(adj_calls), 1)

    @patch("backend.inventory_module.list_reorder_suggestions", return_value=[])
    @patch("backend.inventory_module.get_item")
    @patch("backend.inventory_module.get_draft_stock_check")
    @patch("backend.inventory_module.save_stock_check_draft")
    @patch("backend.inventory_module.get_variance_threshold", return_value=5)
    @patch("backend.inventory_module.ensure_inventory_tables")
    def test_simultaneous_submit_requests_apply_once(
        self, _ensure, _threshold, _save_draft, get_draft, get_item, _reorder
    ):
        draft = {"id": 9, "lines": {1: {"item_id": 1, "counted_qty": 5}}}
        get_draft.return_value = draft
        get_item.return_value = {"id": 1, "name": "Bags", "current_on_hand": 4}

        lock = threading.Lock()
        state = {"submitted": False}
        metrics = {"status_updates": 0, "item_updates": 0, "adjustments": 0}

        def make_cursor():
            cursor = MagicMock()

            def fetchone():
                with lock:
                    if state["submitted"]:
                        return {"status": STOCK_CHECK_SUBMITTED}
                    return {"status": STOCK_CHECK_DRAFT}

            def execute(sql, params=None):
                sql_s = str(sql)
                if "FOR UPDATE" in sql_s and "inventory_stock_checks" in sql_s:
                    return
                with lock:
                    if state["submitted"] and "UPDATE inventory_items SET on_hand_qty" in sql_s:
                        raise StockCheckConflictError("Stock check already submitted")
                    if "UPDATE inventory_items SET on_hand_qty" in sql_s:
                        metrics["item_updates"] += 1
                    elif "INSERT INTO inventory_adjustments" in sql_s:
                        metrics["adjustments"] += 1
                    elif "UPDATE inventory_stock_checks" in sql_s and "status" in sql_s:
                        metrics["status_updates"] += 1
                        state["submitted"] = True
                        cursor.rowcount = 1

            cursor.execute.side_effect = execute
            cursor.fetchone.side_effect = fetchone
            return cursor

        payload = {"lines": [{"item_id": 1, "counted_qty": 5}], "oneshot": True}
        results: list = []
        errors: list = []

        def worker():
            try:
                out = submit_stock_check(make_cursor(), 3, payload, 1, "Tester")
                results.append(out)
            except StockCheckConflictError as e:
                errors.append(str(e))

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(results), 1)
        self.assertEqual(len(errors), 1)
        self.assertIn("already submitted", errors[0].lower())
        self.assertEqual(metrics["item_updates"], 1)
        self.assertEqual(metrics["adjustments"], 1)
        self.assertEqual(metrics["status_updates"], 1)

    @patch("backend.inventory_module.list_reorder_suggestions", return_value=[])
    @patch("backend.inventory_module.get_item")
    @patch("backend.inventory_module.get_draft_stock_check")
    @patch("backend.inventory_module.save_stock_check_draft")
    @patch("backend.inventory_module.get_variance_threshold", return_value=5)
    @patch("backend.inventory_module._column_exists", return_value=True)
    @patch("backend.inventory_module.ensure_inventory_tables")
    def test_recount_flag_does_not_change_on_hand(
        self, _ensure, _col, _threshold, _save_draft, get_draft, get_item, _reorder
    ):
        cursor = MagicMock()
        cursor.fetchone.return_value = {"status": STOCK_CHECK_DRAFT}
        cursor.rowcount = 1
        get_draft.return_value = {
            "id": 9,
            "lines": {1: {"item_id": 1, "counted_qty": 0, "needs_recount": True}},
        }
        get_item.return_value = {"id": 1, "name": "Bleach", "current_on_hand": 20, "tracking_mode": "QUANTITY"}
        out = submit_stock_check(
            cursor,
            3,
            {"lines": [{"item_id": 1, "counted_qty": 0, "needs_recount": True}], "oneshot": True},
            1,
            "Jennifer",
        )
        self.assertEqual(out["recount_flagged"], 1)
        on_hand_updates = [
            c for c in cursor.execute.call_args_list
            if "UPDATE inventory_items SET on_hand_qty" in str(c[0][0])
        ]
        self.assertEqual(len(on_hand_updates), 0)
        flag_updates = [
            c for c in cursor.execute.call_args_list
            if "needs_recount = 1" in str(c[0][0])
        ]
        self.assertEqual(len(flag_updates), 1)

    @patch("backend.inventory_module.list_reorder_suggestions", return_value=[])
    @patch("backend.inventory_module.get_item")
    @patch("backend.inventory_module.get_draft_stock_check")
    @patch("backend.inventory_module.save_stock_check_draft")
    @patch("backend.inventory_module.get_variance_threshold", return_value=5)
    @patch("backend.inventory_module._column_exists", return_value=True)
    @patch("backend.inventory_module.ensure_inventory_tables")
    def test_recount_resolve_records_actor_and_timestamp(
        self, _ensure, _col, _threshold, _save_draft, get_draft, get_item, _reorder
    ):
        cursor = MagicMock()
        cursor.fetchone.return_value = {"status": STOCK_CHECK_DRAFT}
        cursor.rowcount = 1
        get_draft.return_value = {
            "id": 10,
            "lines": {1: {"item_id": 1, "counted_qty": 20, "needs_recount": False}},
        }
        get_item.return_value = {
            "id": 1,
            "name": "Bleach",
            "current_on_hand": 20,
            "tracking_mode": "QUANTITY",
            "needs_recount": True,
        }
        out = submit_stock_check(
            cursor,
            3,
            {"lines": [{"item_id": 1, "counted_qty": 20}], "oneshot": True},
            2,
            "Joshua",
        )
        self.assertEqual(out["lines_submitted"], 1)
        resolve_updates = [
            c for c in cursor.execute.call_args_list
            if "UPDATE inventory_items SET on_hand_qty" in str(c[0][0])
            and "last_counted_by" in str(c[0][0])
            and "needs_recount = 0" in str(c[0][0])
        ]
        self.assertEqual(len(resolve_updates), 1)
        params = resolve_updates[0][0][1]
        self.assertEqual(params[0], 20.0)  # counted qty
        self.assertEqual(params[1], "Joshua")  # actor
        self.assertEqual(params[2], 1)  # item id

    @patch("backend.inventory_module.list_reorder_suggestions", return_value=[])
    @patch("backend.inventory_module.get_draft_stock_check")
    @patch("backend.inventory_module.save_stock_check_draft")
    @patch("backend.inventory_module.get_variance_threshold", return_value=5)
    @patch("backend.inventory_module.ensure_inventory_tables")
    def test_oneshot_reuses_existing_draft(
        self, _ensure, _threshold, save_draft, get_draft, _reorder
    ):
        get_draft.side_effect = [
            {"id": 3, "lines": {1: {"item_id": 1, "counted_qty": 2}}},
            {"id": 3, "lines": {1: {"item_id": 1, "counted_qty": 2}}},
        ]
        cursor = MagicMock()
        cursor.fetchone.return_value = {"status": STOCK_CHECK_DRAFT}
        cursor.rowcount = 1
        with patch("backend.inventory_module.get_item", return_value={"id": 1, "name": "Bags", "current_on_hand": 2}):
            submit_stock_check(cursor, 3, {"lines": [{"item_id": 1, "counted_qty": 2}], "oneshot": True}, 1, "Tester")
        save_draft.assert_called_once()

    @patch("backend.inventory_module._refresh_item_average_cost")
    @patch("backend.inventory_module.get_item")
    @patch("backend.inventory_module.ensure_inventory_tables")
    def test_partial_receive_is_incremental_only(self, _ensure, get_item, _refresh):
        cursor = MagicMock()
        cursor.fetchone.return_value = {
            "id": 7,
            "status": "ORDERED",
            "received_date": None,
        }
        cursor.fetchall.return_value = [
            {"id": 11, "item_id": 1, "qty_ordered": Decimal("10"), "qty_received": Decimal("3")},
        ]
        get_item.return_value = {"id": 1, "current_on_hand": 5}
        out = receive_order(cursor, 3, 7, {"lines": [{"line_id": 11, "qty_received": 8}]}, 1, "Receiver")
        self.assertEqual(out["qty_received_total"], 5)
        adj_calls = [c for c in cursor.execute.call_args_list if "INSERT INTO inventory_adjustments" in str(c[0][0])]
        self.assertEqual(len(adj_calls), 1)
        self.assertEqual(adj_calls[0][0][1][3], 5)

    @patch("backend.inventory_module.ensure_inventory_tables")
    def test_double_receive_blocked(self, _ensure):
        cursor = MagicMock()
        cursor.fetchone.return_value = {"id": 7, "status": ORDER_RECEIVED}
        with self.assertRaises(ValueError) as ctx:
            receive_order(cursor, 3, 7, {"lines": []}, 1, "Receiver")
        self.assertIn("already fully received", str(ctx.exception).lower())

    @patch("backend.inventory_module._refresh_item_average_cost")
    @patch("backend.inventory_module.get_item")
    @patch("backend.inventory_module.ensure_inventory_tables")
    def test_receive_with_no_new_qty_blocked(self, _ensure, get_item, _refresh):
        cursor = MagicMock()
        cursor.fetchone.return_value = {"id": 7, "status": "PARTIALLY_RECEIVED", "received_date": date.today()}
        cursor.fetchall.return_value = [
            {"id": 11, "item_id": 1, "qty_ordered": Decimal("10"), "qty_received": Decimal("10")},
        ]
        get_item.return_value = {"id": 1, "current_on_hand": 15}
        with self.assertRaises(ValueError) as ctx:
            receive_order(cursor, 3, 7, {"lines": [{"line_id": 11, "qty_received": 10}]}, 1, "Receiver")
        self.assertIn("no new quantities", str(ctx.exception).lower())

    @patch("backend.inventory_ops.get_variance_threshold", return_value=5)
    @patch("backend.inventory_ops.get_recent_activity", return_value=[])
    @patch("backend.inventory_ops.get_latest_stock_check", return_value=None)
    @patch("backend.inventory_ops.list_reorder_suggestions", return_value=[])
    @patch("backend.inventory_ops.list_items")
    @patch("backend.inventory_ops.migrate_legacy_inventory")
    @patch("backend.inventory_ops.ensure_inventory_tables")
    def test_dashboard_kpi_inventory_value(self, _ensure, _migrate, list_items, _reorder, _latest, _activity, _threshold):
        list_items.return_value = [
            {"estimated_value": 40.0, "category_name": "Bags"},
            {"estimated_value": 10.5, "category_name": "Detergent"},
        ]
        cursor = MagicMock()
        cursor.fetchone.side_effect = [{"c": 2}, {"total": Decimal("100")}, {"total": Decimal("250")}]
        dashboard = build_dashboard(cursor, 3, include_financials=True)
        self.assertEqual(dashboard["kpis"]["inventory_value"], 50.5)
        self.assertEqual(dashboard["kpis"]["pending_purchase_orders"], 2)
        self.assertEqual(dashboard["kpis"]["this_week_purchases"], 100.0)
        self.assertEqual(dashboard["kpis"]["this_month_purchases"], 250.0)


class InventoryRoleEnforcementTests(unittest.TestCase):
    def test_front_desk_blocked_from_purchase_orders_api(self):
        routes = _read("backend/inventory_routes.py")
        block = routes.split("def inventory_orders_api")[1].split("def inventory_orders_receive")[0]
        self.assertIn("_supervisor(cursor)", block)

    def test_front_desk_blocked_from_reports(self):
        routes = _read("backend/inventory_routes.py")
        for fn in ("inventory_reports_bundle", "inventory_reports_weekly_orders", "inventory_report_v2"):
            block = routes.split(f"def {fn}")[1][:400]
            self.assertIn("_supervisor(cursor)", block, fn)

    def test_admin_only_settings_mutations(self):
        routes = _read("backend/inventory_routes.py")
        categories = routes.split("def inventory_categories_api")[1].split("def inventory_vendors_api")[0]
        self.assertIn('if request.method == "GET":', categories)
        self.assertIn("_me(cursor)", categories)
        self.assertIn("_admin(cursor)", categories)
        variance = routes.split("def inventory_variance_threshold")[1].split("def inventory_report_v2")[0]
        self.assertIn("_admin(cursor)", variance)

    def test_floor_blocked_from_vendor_stats(self):
        routes = _read("backend/inventory_routes.py")
        block = routes.split("def inventory_vendors_api")[1].split("def inventory_vendor_detail")[0]
        self.assertIn("_floor_only", block)
        self.assertIn("Forbidden", block)

    def test_reorder_and_low_stock_require_supervisor(self):
        routes = _read("backend/inventory_routes.py")
        for fn in ("inventory_reorder_suggestions", "inventory_low_stock_v2"):
            block = routes.split(f"def {fn}")[1][:250]
            self.assertIn("_supervisor(cursor)", block, fn)


class InventoryMigrationIdempotencyTests(unittest.TestCase):
    def test_schema_uses_column_exists_before_alter(self):
        module = _read("backend/inventory_module.py")
        self.assertIn("def _column_exists", module)
        self.assertGreaterEqual(module.count("if not _column_exists"), 3)

    def test_categories_have_unique_org_name(self):
        sql = _read("backend/sql/inventory_v2.sql")
        self.assertRegex(sql, r"UNIQUE KEY.*organization_id.*name", re.IGNORECASE | re.DOTALL)


if __name__ == "__main__":
    unittest.main()
