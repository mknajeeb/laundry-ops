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
    _display_special_instructions,
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

    def test_christian_portal_pollution_defaults_tide(self):
        from backend.tests.test_rinse_special_instructions import CHRISTIAN_CATALOG_ONLY

        out = supplies_for_usage(CHRISTIAN_CATALOG_ONLY)
        assert out["supplies_used"] == ["Tide"]
        assert out["supply_interpretation"] == "Standard soap"

    def test_polluted_catalog_trailing_supply_tokens_default_tide(self):
        from backend.tests.test_rinse_special_instructions import CHRISTIAN_POLLUTED_RAW

        out = supplies_for_usage(CHRISTIAN_POLLUTED_RAW)
        assert out["supplies_used"] == ["Tide"]
        assert out["supply_interpretation"] == "Standard soap"

    def test_ryan_tiffany_polluted_row_defaults_tide(self):
        from backend.tests.test_rinse_special_instructions import RYAN_TIFFANY_POLLUTED_RAW

        out = supplies_for_usage(RYAN_TIFFANY_POLLUTED_RAW)
        assert out["supplies_used"] == ["Tide"]
        assert _display_special_instructions(RYAN_TIFFANY_POLLUTED_RAW) is None

    def test_ryan_tiffany_labeled_si_hypo_oxic(self):
        from backend.tests.test_rinse_special_instructions import RYAN_TIFFANY_LABELED_SI

        out = supplies_for_usage(RYAN_TIFFANY_LABELED_SI)
        assert out["supplies_used"] == ["All Free & Clear", "OxiClean"]
        assert _display_special_instructions(RYAN_TIFFANY_LABELED_SI) == (
            "Hypoallergenic + OxiClean"
        )

    def test_labeled_special_instructions_fabric_softener_maps_downy(self):
        out = supplies_for_usage("Special Instructions: USE FABRIC SOFTENER")
        assert out["supplies_used"] == ["Tide", "Downy"]

    def test_portal_menu_pollution_defaults_tide_only(self):
        from backend.tests.test_rinse_special_instructions import CHRISTIAN_CATALOG_ONLY

        out = supplies_for_usage(CHRISTIAN_CATALOG_ONLY)
        assert out["supplies_used"] == ["Tide"]

    def test_polluted_catalog_hypo_trailing_token_defaults_tide(self):
        raw = (
            "Vendor Notes Vendor Price Collateral Dry Clean Hang Dry Launder & Press Leather Cleaning "
            "Press Only Repair Shine Special Services Specialty Items Wash and Fold Apron Baby Clothing "
            "Bag Bathing Suit Bathing Suit (Bottom) Bathing Suit (Top) Bath Mat Bath Rug Belt Blanket "
            "Blanket (Large) Blanket (Small) Blouse Boots Boxers Bra Button (Repair) Cloth Mask "
            "Cloth Mask (Kids) Coat Coat (Down) Comforter Comforter (Down) Couch Cover Cover Cummerbund "
            "Curtain Door Hanger Dress (Casual) Dress (Formal) Duvet D; Use Hypoallergenic Soap"
        )
        out = supplies_for_usage(raw)
        assert out["supplies_used"] == ["Tide"]

    def test_empty_instructions_default_tide(self):
        out = supplies_for_usage("")
        assert out["supplies_used"] == ["Tide"]


class TestDisplaySpecialInstructions:
    def test_empty_si_display_not_standard_soap(self):
        row = _order_row_from_staging(
            {
                "ticket_id": "EMPTY001",
                "name_clean": "Curtis Teegardin",
                "special_instructions_raw": None,
            },
            split_load_bags=set(),
            mapping_rules=DEFAULT_MAPPING_RULES,
        )
        assert row["special_instructions"] is None
        assert row["special_instructions"] != "Standard soap"
        assert row["supply_interpretation"] == "Standard soap"
        assert row["supplies_used"] == ["Tide"]

    def test_standard_tide_only_display_empty_supplies_tide(self):
        from backend.tests.test_rinse_special_instructions import CHRISTIAN_CATALOG_ONLY

        row = _order_row_from_staging(
            {
                "ticket_id": "STD001",
                "name_clean": "Standard Customer",
                "special_instructions_raw": CHRISTIAN_CATALOG_ONLY,
            },
            split_load_bags=set(),
            mapping_rules=DEFAULT_MAPPING_RULES,
        )
        assert row["special_instructions"] is None
        assert row["supply_interpretation"] == "Standard soap"
        assert row["supplies_used"] == ["Tide"]

    def test_fab_oxic_display(self):
        row = _order_row_from_staging(
            {
                "ticket_id": "FABOX001",
                "name_clean": "Fab Oxi Customer",
                "special_instructions_raw": "USE FABRIC SOFTENER; USE OXICLEAN",
            },
            split_load_bags=set(),
            mapping_rules=DEFAULT_MAPPING_RULES,
        )
        assert row["special_instructions"] == "Fabric Softener + OxiClean"
        assert row["supplies_used"] == ["Tide", "Downy", "OxiClean"]

    def test_polluted_row_display_is_none(self):
        from backend.tests.test_rinse_special_instructions import CHRISTIAN_POLLUTED_RAW

        assert _display_special_instructions(CHRISTIAN_POLLUTED_RAW) is None

    def test_eldar_polluted_row_defaults_tide(self):
        from backend.tests.test_rinse_special_instructions import CHRISTIAN_CATALOG_ONLY

        raw = f"{CHRISTIAN_CATALOG_ONLY}; USE FABRIC SOFTENER; Use Hypoallergenic Soap"
        row = _order_row_from_staging(
            {
                "ticket_id": "5DGG7KT7CW",
                "name_clean": "Eldar Hadad 0",
                "special_instructions_raw": raw,
            },
            split_load_bags=set(),
            mapping_rules=DEFAULT_MAPPING_RULES,
        )
        assert row["special_instructions"] is None
        assert row["supplies_used"] == ["Tide"]

    def test_curtis_empty_labeled_si_display_none(self):
        from backend.tests.test_rinse_special_instructions import CURTIS_EMPTY_SI_PORTAL

        row = _order_row_from_staging(
            {
                "ticket_id": "CURTIS001",
                "name_clean": "Curtis Teegardin",
                "special_instructions_raw": CURTIS_EMPTY_SI_PORTAL,
            },
            split_load_bags=set(),
            mapping_rules=DEFAULT_MAPPING_RULES,
        )
        assert row["special_instructions"] is None
        assert row["supplies_used"] == ["Tide"]

    def test_display_never_returns_standard_soap_literal(self):
        assert _display_special_instructions(None) is None
        assert _display_special_instructions("") is None
        for raw in ("Standard soap", "standard soap"):
            assert _display_special_instructions(raw) is None

    def test_hypo_only_display(self):
        assert _display_special_instructions("Use Hypoallergenic Soap") == "Hypoallergenic"

    def test_order_row_labeled_si_display_matches_mapping(self):
        from backend.tests.test_rinse_special_instructions import RYAN_TIFFANY_LABELED_SI

        row = _order_row_from_staging(
            {
                "ticket_id": "TEST1234",
                "name_clean": "Test Customer",
                "special_instructions_raw": RYAN_TIFFANY_LABELED_SI,
            },
            split_load_bags=set(),
            mapping_rules=DEFAULT_MAPPING_RULES,
        )
        assert row["special_instructions"] == "Hypoallergenic + OxiClean"
        assert row["supplies_used"] == ["All Free & Clear", "OxiClean"]
        assert "Downy" not in row["supplies_used"]


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
            if table == "upload_batch_rows" and col in (
                "ticket_id",
                "date_clean",
                "special_instructions_raw",
                "row_status",
            ):
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
        assert "ubr.row_status IN ('ACCEPTED', 'OVERRIDDEN')" in sql
        assert executed[0][1] == (date(2026, 6, 19), 3)


class TestUploadRowStatusSupplyUsage:
    """Rejected/deleted/unresolved upload rows must not consume supplies."""

    TARGET = date(2026, 7, 14)
    FAB_OXIC = "USE FABRIC SOFTENER; USE OXICLEAN"
    HYPO = "Use Hypoallergenic Soap"

    def _patch_schema(self, su):
        def fake_table_exists(cursor, table):
            return table in ("upload_batch_rows", "upload_batches")

        def fake_table_has_column(cursor, table, col):
            if table == "upload_batches" and col == "id":
                return True
            if table == "upload_batches" and col == "organization_id":
                return True
            if table == "upload_batch_rows" and col in (
                "ticket_id",
                "date_clean",
                "special_instructions_raw",
                "row_status",
            ):
                return True
            return False

        original_te = su.table_exists
        original_thc = su.table_has_column
        su.table_exists = fake_table_exists
        su.table_has_column = fake_table_has_column
        return original_te, original_thc

    def _cursor_for_upload_rows(self, rows):
        """Simulate SQL date/org/ticket/row_status filters against in-memory rows."""
        executed: list[tuple[str, tuple]] = []
        result: list[dict] = []

        cursor = MagicMock()

        def capture_execute(sql, args=()):
            executed.append((sql, args))
            sql_norm = " ".join(sql.split())
            assert "ubr.row_status IN ('ACCEPTED', 'OVERRIDDEN')" in sql_norm
            target = args[0]
            org_id = args[1] if len(args) > 1 else None
            filtered = []
            for row in rows:
                if row.get("date_clean") != target:
                    continue
                if org_id is not None and int(row.get("organization_id") or 0) != int(org_id):
                    continue
                if row.get("row_status") not in ("ACCEPTED", "OVERRIDDEN"):
                    continue
                tid = str(row.get("ticket_id") or "").strip()
                if not tid:
                    continue
                filtered.append(
                    {
                        "date_clean": row["date_clean"],
                        "name_clean": row["name_clean"],
                        "service_type": row.get("service_type"),
                        "ticket_id": row["ticket_id"],
                        "special_instructions_raw": row.get("special_instructions_raw"),
                        "supply_interpretation": row.get("supply_interpretation"),
                        "special_instruction_review": row.get("special_instruction_review"),
                    }
                )
            result.clear()
            result.extend(filtered)

        cursor.execute = capture_execute
        cursor.fetchall = lambda: list(result)
        cursor.fetchone = MagicMock(return_value=None)
        cursor._executed = executed
        return cursor

    def _report_from_upload_rows(self, rows, organization_id=3, target=None):
        from backend import supply_usage as su

        target = target or self.TARGET
        cursor = self._cursor_for_upload_rows(rows)
        original_te, original_thc = self._patch_schema(su)
        original_staging = su._load_staging_orders
        original_split = su._load_split_load_bag_ids
        su._load_staging_orders = lambda *a, **k: []
        su._load_split_load_bag_ids = lambda *a, **k: set()
        try:
            return build_supply_usage_report(cursor, organization_id, target)
        finally:
            su.table_exists = original_te
            su.table_has_column = original_thc
            su._load_staging_orders = original_staging
            su._load_split_load_bag_ids = original_split

    def _row(
        self,
        *,
        ticket_id,
        row_status,
        special_instructions_raw=None,
        name_clean="Customer",
        organization_id=3,
        date_clean=None,
    ):
        return {
            "ticket_id": ticket_id,
            "row_status": row_status,
            "special_instructions_raw": special_instructions_raw,
            "name_clean": name_clean,
            "organization_id": organization_id,
            "date_clean": date_clean or self.TARGET,
            "service_type": "Wash & Fold",
        }

    def test_accepted_row_contributes_tide_downy_oxiclean(self):
        report = self._report_from_upload_rows(
            [
                self._row(
                    ticket_id="ACC001",
                    row_status="ACCEPTED",
                    special_instructions_raw=self.FAB_OXIC,
                    name_clean="Accepted Customer",
                )
            ]
        )
        assert report["summary"]["orders_analyzed"] == 1
        assert report["usage_by_supply"]["Tide"]["orders"] == 1
        assert report["usage_by_supply"]["Tide"]["doses"] == 1
        assert report["usage_by_supply"]["Tide"]["ounces"] == 2.0
        assert report["usage_by_supply"]["Downy"]["doses"] == 1
        assert report["usage_by_supply"]["Downy"]["ounces"] == 1.0
        assert report["usage_by_supply"]["OxiClean"]["doses"] == 1
        assert report["usage_by_supply"]["OxiClean"]["ounces"] == 1.0
        assert report["orders"][0]["supplies_used"] == ["Tide", "Downy", "OxiClean"]

    def test_overridden_row_contributes_all_free_clear(self):
        report = self._report_from_upload_rows(
            [
                self._row(
                    ticket_id="OVR001",
                    row_status="OVERRIDDEN",
                    special_instructions_raw=self.HYPO,
                    name_clean="Overridden Customer",
                )
            ]
        )
        assert report["summary"]["orders_analyzed"] == 1
        assert report["summary"]["hypo_orders"] == 1
        assert report["usage_by_supply"]["All Free & Clear"]["orders"] == 1
        assert report["usage_by_supply"]["All Free & Clear"]["doses"] == 1
        assert report["usage_by_supply"]["All Free & Clear"]["ounces"] == 2.0
        assert report["usage_by_supply"]["Tide"]["doses"] == 0
        assert report["orders"][0]["supplies_used"] == ["All Free & Clear"]

    def test_rejected_duplicate_contributes_zero_usage(self):
        report = self._report_from_upload_rows(
            [
                self._row(
                    ticket_id="REJ001",
                    row_status="REJECTED_DUPLICATE",
                    special_instructions_raw=self.FAB_OXIC,
                )
            ]
        )
        assert report["summary"]["orders_analyzed"] == 0
        assert report["orders"] == []
        assert report["usage_by_supply"]["Tide"]["doses"] == 0
        assert report["usage_by_supply"]["Downy"]["doses"] == 0
        assert report["usage_by_supply"]["OxiClean"]["doses"] == 0

    def test_deleted_row_contributes_zero_usage(self):
        report = self._report_from_upload_rows(
            [
                self._row(
                    ticket_id="DEL001",
                    row_status="DELETED",
                    special_instructions_raw=self.HYPO,
                )
            ]
        )
        assert report["summary"]["orders_analyzed"] == 0
        assert report["usage_by_supply"]["All Free & Clear"]["doses"] == 0
        assert report["usage_by_supply"]["All Free & Clear"]["ounces"] == 0.0

    def test_needs_attention_row_contributes_zero_usage(self):
        report = self._report_from_upload_rows(
            [
                self._row(
                    ticket_id="ATT001",
                    row_status="NEEDS_ATTENTION",
                    special_instructions_raw=self.FAB_OXIC,
                )
            ]
        )
        assert report["summary"]["orders_analyzed"] == 0
        assert report["usage_by_supply"]["Tide"]["doses"] == 0
        assert report["usage_by_supply"]["Downy"]["doses"] == 0
        assert report["usage_by_supply"]["OxiClean"]["doses"] == 0

    def test_accepted_plus_rejected_duplicate_counts_once(self):
        report = self._report_from_upload_rows(
            [
                self._row(
                    ticket_id="SAMEBAG01",
                    row_status="ACCEPTED",
                    special_instructions_raw=self.FAB_OXIC,
                    name_clean="Bella Lavarre",
                ),
                self._row(
                    ticket_id="SAMEBAG01",
                    row_status="REJECTED_DUPLICATE",
                    special_instructions_raw=self.FAB_OXIC,
                    name_clean="Bella Lavarre",
                ),
            ]
        )
        assert report["summary"]["orders_analyzed"] == 1
        assert report["usage_by_supply"]["Tide"]["orders"] == 1
        assert report["usage_by_supply"]["Tide"]["doses"] == 1
        assert report["usage_by_supply"]["Tide"]["ounces"] == 2.0
        assert report["usage_by_supply"]["Downy"]["doses"] == 1
        assert report["usage_by_supply"]["OxiClean"]["doses"] == 1
        assert len(report["orders"]) == 1
        assert report["orders"][0]["order_id"] == "SAMEBAG01"

    def test_organization_scoping_excludes_other_org_rows(self):
        report = self._report_from_upload_rows(
            [
                self._row(
                    ticket_id="ORG3OK",
                    row_status="ACCEPTED",
                    special_instructions_raw=self.HYPO,
                    organization_id=3,
                ),
                self._row(
                    ticket_id="ORG9NO",
                    row_status="ACCEPTED",
                    special_instructions_raw=self.FAB_OXIC,
                    organization_id=9,
                ),
            ],
            organization_id=3,
        )
        assert report["summary"]["orders_analyzed"] == 1
        assert report["orders"][0]["order_id"] == "ORG3OK"
        assert report["usage_by_supply"]["All Free & Clear"]["doses"] == 1
        assert report["usage_by_supply"]["Tide"]["doses"] == 0
        assert report["usage_by_supply"]["Downy"]["doses"] == 0

    def test_date_and_ticket_filtering_still_apply(self):
        from backend import supply_usage as su

        rows = [
            self._row(
                ticket_id="TODAY1",
                row_status="ACCEPTED",
                special_instructions_raw="USE FABRIC SOFTENER",
                date_clean=self.TARGET,
            ),
            self._row(
                ticket_id="YDAY1",
                row_status="ACCEPTED",
                special_instructions_raw=self.FAB_OXIC,
                date_clean=date(2026, 7, 13),
            ),
            self._row(
                ticket_id="",
                row_status="ACCEPTED",
                special_instructions_raw=self.HYPO,
                date_clean=self.TARGET,
            ),
            self._row(
                ticket_id=None,
                row_status="OVERRIDDEN",
                special_instructions_raw=self.FAB_OXIC,
                date_clean=self.TARGET,
            ),
        ]
        cursor = self._cursor_for_upload_rows(rows)
        original_te, original_thc = self._patch_schema(su)
        try:
            loaded = su._load_upload_batch_orders(cursor, 3, self.TARGET)
        finally:
            su.table_exists = original_te
            su.table_has_column = original_thc

        assert len(loaded) == 1
        assert loaded[0]["ticket_id"] == "TODAY1"
        sql, args = cursor._executed[0]
        assert args == (self.TARGET, 3)
        assert "ubr.date_clean = %s" in sql
        assert "ub.organization_id = %s" in sql
        assert "ubr.ticket_id IS NOT NULL" in sql
        assert "ubr.row_status IN ('ACCEPTED', 'OVERRIDDEN')" in sql

        report = self._report_from_upload_rows(rows)
        assert report["summary"]["orders_analyzed"] == 1
        assert report["usage_by_supply"]["Tide"]["doses"] == 1
        assert report["usage_by_supply"]["Downy"]["doses"] == 1
        assert report["usage_by_supply"]["Downy"]["ounces"] == 1.0
        assert report["usage_by_supply"]["OxiClean"]["doses"] == 0


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
