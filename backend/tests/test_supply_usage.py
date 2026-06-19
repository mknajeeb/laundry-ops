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
    _load_split_load_bag_ids,
    _order_row_from_staging,
)
from backend.supply_usage_settings import (
    DEFAULT_DOSAGES,
    DEFAULT_MAPPING_RULES,
    KEY_SUPPLY_USAGE_MAPPING_RULES,
    get_supply_usage_dosages,
    get_supply_usage_mapping_rules,
    save_supply_usage_mapping_rules,
)


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

    def test_custom_substring_rule(self):
        rules = [
            {
                "instructions": "VIP customer",
                "supplies": ["Tide", "Downy", "OxiClean"],
            },
            {"instructions": "None / default", "supplies": ["Tide"], "default": True},
        ]
        out = supplies_for_usage("VIP customer special handling", rules)
        assert out["supplies_used"] == ["Tide", "Downy", "OxiClean"]


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

    def test_split_load_scan_primary(self):
        assert detect_split_order(has_split_load_scan=True) is True
        assert split_order_multiplier(has_split_load_scan=True) == 2

    def test_split_load_scan_without_portal_label(self):
        assert detect_split_order("USE OXICLEAN", has_split_load_scan=True) is True
        assert split_order_multiplier("USE OXICLEAN", has_split_load_scan=True) == 2


class TestSplitLoadScanIntegration:
    def test_order_row_split_load_scan_sets_multiplier(self):
        row = _order_row_from_staging(
            {
                "ticket_id": "ABC12345",
                "name_clean": "Test Customer",
                "special_instructions_raw": "USE OXICLEAN",
            },
            split_load_bags={"ABC12345"},
            mapping_rules=DEFAULT_MAPPING_RULES,
        )
        assert row["split_order"] is True
        assert row["split_load_scan"] is True
        assert row["multiplier"] == 2
        assert row["doses_by_supply"]["Tide"] == 2
        assert row["doses_by_supply"]["OxiClean"] == 2

    def test_load_split_load_bag_ids_from_scan_events(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = [
            {"bag_id": "ABC12345", "purpose": "split-load"},
            {"bag_id": "OTHER123", "purpose": "cleaning"},
        ]

        from backend import supply_usage as su

        original_te = su.table_exists
        su.table_exists = lambda _c, table: table == "rinse_bag_scan_events"
        try:
            out = _load_split_load_bag_ids(cursor, 3, ["ABC12345", "OTHER123"])
        finally:
            su.table_exists = original_te

        assert out == {"ABC12345"}

    def test_load_orders_applies_split_load_scans(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        cursor.fetchall.return_value = [{"bag_id": "SPLITBAG1", "purpose": "split-load"}]

        from backend import supply_usage as su

        staging_row = {
            "ticket_id": "SPLITBAG1",
            "name_clean": "Split Customer",
            "special_instructions_raw": None,
            "_source": "orders_staging",
        }

        original_load_staging = su._load_staging_orders
        original_load_upload = su._load_upload_batch_orders
        original_te = su.table_exists
        su._load_staging_orders = lambda *a, **k: [staging_row]
        su._load_upload_batch_orders = lambda *a, **k: []
        su.table_exists = lambda _c, table: table == "rinse_bag_scan_events"
        try:
            orders = load_orders_for_supply_usage(cursor, 3, date(2026, 6, 18))
        finally:
            su._load_staging_orders = original_load_staging
            su._load_upload_batch_orders = original_load_upload
            su.table_exists = original_te

        assert len(orders) == 1
        assert orders[0]["split_order"] is True
        assert orders[0]["multiplier"] == 2


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

    def test_default_mapping_rules(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        rules = get_supply_usage_mapping_rules(cursor, 1)
        assert len(rules) == len(DEFAULT_MAPPING_RULES)
        assert rules[-1]["default"] is True
        assert rules[-1]["supplies"] == ["Tide"]

    def test_mapping_rules_persist_and_reload(self):
        cursor = MagicMock()
        stored: dict[str, str] = {}

        def fake_get_setting(_c, _oid, key):
            return stored.get(key)

        def fake_set_setting(_c, _oid, key, value):
            stored[key] = value

        from backend import supply_usage_settings as sus

        original_get = sus._get_setting
        original_set = sus._set_setting
        sus._get_setting = fake_get_setting
        sus._set_setting = fake_set_setting
        try:
            custom = [
                {"instructions": "VIP", "supplies": ["Tide", "Downy"]},
                {"instructions": "None / default", "supplies": ["Tide"], "default": True},
            ]
            saved = save_supply_usage_mapping_rules(cursor, 3, custom)
            assert saved[0]["supplies"] == ["Tide", "Downy"]
            reloaded = get_supply_usage_mapping_rules(cursor, 3)
            assert reloaded[0]["instructions"] == "VIP"
            assert KEY_SUPPLY_USAGE_MAPPING_RULES in stored
        finally:
            sus._get_setting = original_get
            sus._set_setting = original_set


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
