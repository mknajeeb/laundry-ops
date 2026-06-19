"""Tests for supply usage mapping, split multiplier, and dose/oz math."""

from datetime import date
from unittest.mock import MagicMock

import pytest

from backend.supply_usage import (
    build_supply_usage_report,
    detect_split_order,
    load_orders_for_supply_usage,
    split_order_multiplier,
    supplies_for_usage,
)
from backend.supply_usage_settings import DEFAULT_DOSAGES, get_supply_usage_dosages


class TestSuppliesForUsage:
    def test_default_tide(self):
        out = supplies_for_usage(None)
        assert out["supplies_used"] == ["Tide"]

    def test_fabric_softener(self):
        out = supplies_for_usage("USE FABRIC SOFTENER")
        assert out["supplies_used"] == ["Tide", "Downy"]

    def test_fab_and_oxic(self):
        out = supplies_for_usage("USE FABRIC SOFTENER; USE OXICLEAN")
        assert out["supplies_used"] == ["Tide", "Downy", "OxiClean"]

    def test_oxic_only(self):
        out = supplies_for_usage("use oxiclean")
        assert out["supplies_used"] == ["Tide", "OxiClean"]

    def test_hypo_only_maps_all_free_clear(self):
        out = supplies_for_usage("Use Hypoallergenic Soap")
        assert out["supplies_used"] == ["All Free & Clear"]

    def test_hypo_oxic(self):
        out = supplies_for_usage("Use Hypoallergenic Soap; USE OXICLEAN")
        assert out["supplies_used"] == ["All Free & Clear", "OxiClean"]

    def test_hypo_variations(self):
        for raw in ("Hypo-allergenic", "Hypo Allergenic", "HYPOALLERGENIC"):
            out = supplies_for_usage(raw)
            assert out["supplies_used"] == ["All Free & Clear"], raw

    def test_softener_variation(self):
        out = supplies_for_usage("Fabric Softener")
        assert "Downy" in out["supplies_used"]

    def test_oxiclean_variations(self):
        for raw in ("Oxi Clean", "Oxiclean"):
            out = supplies_for_usage(raw)
            assert "OxiClean" in out["supplies_used"], raw


class TestSplitOrder:
    def test_split_order_label(self):
        assert detect_split_order("Customer requested Split Order") is True
        assert split_order_multiplier("Split-Order tag") == 2

    def test_split_ticket_portal_noise_not_split(self):
        assert detect_split_order(
            "Vendor Notes Vendor Price Add New Item Split Ticket Processed Save"
        ) is False
        assert split_order_multiplier(
            "Vendor Notes Vendor Price Add New Item Split Ticket Processed Save"
        ) == 1

    def test_split_order_in_instructions(self):
        assert detect_split_order("Split Order; USE OXICLEAN") is True


class TestDoseOzMath:
    def _report_from_orders(self, orders):
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        dosages = dict(DEFAULT_DOSAGES)

        from backend import supply_usage as su

        original_load = su.load_orders_for_supply_usage
        su.load_orders_for_supply_usage = lambda *a, **k: orders
        try:
            report = build_supply_usage_report(cursor, 3, date(2026, 6, 18))
        finally:
            su.load_orders_for_supply_usage = original_load

        report["dosage_settings"] = dosages
        report["usage_by_supply"] = su._usage_by_supply(orders, dosages)
        return report

    def test_single_order_doses_and_ounces(self):
        orders = [
            {
                "supplies_used": ["Tide", "Downy"],
                "doses_by_supply": {"Tide": 1, "Downy": 1},
                "multiplier": 1,
                "split_order": False,
            }
        ]
        report = self._report_from_orders(orders)
        assert report["usage_by_supply"]["Tide"]["doses"] == 1
        assert report["usage_by_supply"]["Tide"]["ounces"] == 2.0
        assert report["usage_by_supply"]["Downy"]["doses"] == 1
        assert report["usage_by_supply"]["Downy"]["ounces"] == 1.0

    def test_split_order_doubles_doses(self):
        orders = [
            {
                "supplies_used": ["Tide"],
                "doses_by_supply": {"Tide": 2},
                "multiplier": 2,
                "split_order": True,
            }
        ]
        report = self._report_from_orders(orders)
        assert report["summary"]["split_orders"] == 1
        assert report["usage_by_supply"]["Tide"]["doses"] == 2
        assert report["usage_by_supply"]["Tide"]["ounces"] == 4.0


class TestSupplyUsageSettings:
    def test_default_dosages(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        out = get_supply_usage_dosages(cursor, 1)
        assert out == DEFAULT_DOSAGES


class TestLoadUploadBatchOrders:
    def test_upload_batches_batch_id_pk_join(self):
        """Production schema uses upload_batches.batch_id, not id."""
        from backend import supply_usage as su

        executed: list[tuple[str, tuple]] = []

        def fake_table_exists(cursor, table):
            return table in ("upload_batch_rows", "upload_batches")

        def fake_table_has_column(cursor, table, col):
            if table == "upload_batches" and col == "id":
                return False
            if table == "upload_batches" and col == "batch_id":
                return True
            if table == "upload_batches" and col == "organization_id":
                return True
            if table == "upload_batch_rows" and col in ("ticket_id", "date_clean", "special_instructions_raw"):
                return True
            return False

        cursor = MagicMock()
        cursor.fetchall.return_value = []

        def capture_execute(sql, args=()):
            executed.append((sql, args))

        cursor.execute = capture_execute

        original_te = su.table_exists
        original_thc = su.table_has_column
        su.table_exists = fake_table_exists
        su.table_has_column = fake_table_has_column
        try:
            su._load_upload_batch_orders(cursor, 3, date(2026, 6, 19))
        finally:
            su.table_exists = original_te
            su.table_has_column = original_thc

        assert executed, "expected SQL query"
        sql = executed[0][0]
        assert "ub.batch_id = ubr.upload_batch_id" in sql
        assert "ub.id" not in sql


class TestBuildSupplyUsageReportEmptyDay:
    def test_empty_orders_no_error(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = None

        from backend import supply_usage as su

        original_load = su.load_orders_for_supply_usage
        su.load_orders_for_supply_usage = lambda *a, **k: []
        try:
            report = build_supply_usage_report(cursor, 3, date(2026, 6, 19))
        finally:
            su.load_orders_for_supply_usage = original_load

        assert report["date_et"] == "2026-06-19"
        assert report["summary"]["orders_analyzed"] == 0
        assert report["orders"] == []
