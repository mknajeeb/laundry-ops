"""Tests for supply usage mapping, first-weight ET day population, and scan splits."""

from datetime import date, datetime, timezone
from unittest.mock import MagicMock

from backend.supply_usage import (
    build_supply_usage_report,
    detect_split_order,
    first_weight_on_et_day,
    load_orders_for_supply_usage,
    processing_units_from_split_confirmation,
    split_order_multiplier,
    supplies_for_usage,
    _display_special_instructions,
    _load_approved_upload_orders_by_tickets,
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


def _ev(
    purpose: str,
    ts: datetime,
    *,
    scan_index: int = 1,
    eid: int = 1,
    user: str = "Op",
    rack: str | None = None,
    bag_id: str = "BAG00001",
) -> dict:
    return {
        "id": eid,
        "bag_id": bag_id,
        "purpose": purpose,
        "scanned_at_parsed": ts,
        "scan_index": scan_index,
        "user_name": user,
        "rack": rack,
    }


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
            mapping_rules=DEFAULT_MAPPING_RULES,
        )
        assert row["special_instructions"] == "Hypoallergenic + OxiClean"
        assert row["supplies_used"] == ["All Free & Clear", "OxiClean"]
        assert "Downy" not in row["supplies_used"]


class TestPortalSplitTextHelper:
    """Portal split text remains detectable, but Supply Usage dosing ignores it."""

    def test_split_order_label(self):
        assert detect_split_order("Customer requested Split Order") is True
        assert split_order_multiplier("Split-Order tag") == 2

    def test_split_ticket_portal_noise_not_split(self):
        assert detect_split_order(
            "Vendor Notes Vendor Price Add New Item Split Ticket Processed Save"
        ) is False

    def test_portal_split_text_does_not_set_processing_units_on_order_row(self):
        row = _order_row_from_staging(
            {
                "ticket_id": "SPLITTXT1",
                "name_clean": "Split Text Customer",
                "special_instructions_raw": "Split Order; USE OXICLEAN",
            },
            mapping_rules=DEFAULT_MAPPING_RULES,
            processing_units=1,
            split_confirmed=False,
        )
        assert row["processing_units"] == 1
        assert row["multiplier"] == 1
        assert row["split_order"] is False
        assert row["split_pending"] is True
        assert row["split_status"] == "pending"
        assert row["doses_by_supply"]["Tide"] == 1
        assert row["doses_by_supply"]["OxiClean"] == 1


class TestFirstWeightEtDayMembership:
    DAY = date(2026, 7, 14)

    def test_upload_today_first_weight_yesterday_excluded(self):
        events = [
            _ev("sent-to-vendor", datetime(2026, 7, 13, 8, 0, 0), eid=1),
            _ev("weight-entry", datetime(2026, 7, 13, 9, 0, 0), eid=2),
        ]
        assert first_weight_on_et_day(events, self.DAY) is None

    def test_upload_yesterday_first_weight_today_included(self):
        events = [
            _ev("sent-to-vendor", datetime(2026, 7, 13, 18, 0, 0), eid=1),
            _ev("weight-entry", datetime(2026, 7, 14, 10, 15, 0), eid=2),
        ]
        out = first_weight_on_et_day(events, self.DAY)
        assert out is not None
        assert out["first_weight_et"] == datetime(2026, 7, 14, 10, 15, 0)
        assert out["processing_units"] == 1
        assert out["split_confirmed"] is False

    def test_first_weight_at_14_235959_et_included(self):
        events = [
            _ev("sent-to-vendor", datetime(2026, 7, 14, 8, 0, 0), eid=1),
            _ev("weight-entry", datetime(2026, 7, 14, 23, 59, 59), eid=2),
        ]
        out = first_weight_on_et_day(events, self.DAY)
        assert out is not None
        assert out["first_weight_et"] == datetime(2026, 7, 14, 23, 59, 59)

    def test_first_weight_at_15_000000_et_belongs_to_next_day(self):
        events = [
            _ev("sent-to-vendor", datetime(2026, 7, 14, 8, 0, 0), eid=1),
            _ev("weight-entry", datetime(2026, 7, 15, 0, 0, 0), eid=2),
        ]
        assert first_weight_on_et_day(events, self.DAY) is None
        out_next = first_weight_on_et_day(events, date(2026, 7, 15))
        assert out_next is not None
        assert out_next["first_weight_et"] == datetime(2026, 7, 15, 0, 0, 0)

    def test_utc_aware_timestamp_around_et_midnight_stripped_to_wall(self):
        # Production stores naive ET wall time. Aware inputs are coerced to naive
        # wall clock before lifecycle comparison (00:00 ET belongs to that ET day).
        events = [
            _ev("sent-to-vendor", datetime(2026, 7, 13, 20, 0, 0), eid=1),
            _ev(
                "weight-entry",
                datetime(2026, 7, 14, 0, 0, 0, tzinfo=timezone.utc),
                eid=2,
            ),
        ]
        out = first_weight_on_et_day(events, self.DAY)
        assert out is not None
        assert out["first_weight_et"] == datetime(2026, 7, 14, 0, 0, 0)

        # 04:00 UTC wall-stripped would be treated as 04:00 ET under Rinse naive-ET
        # convention; true zone conversion is not applied to scan DATETIME values.
        aware_four = [
            _ev("sent-to-vendor", datetime(2026, 7, 13, 20, 0, 0), eid=1),
            _ev(
                "weight-entry",
                datetime(2026, 7, 14, 4, 0, 0, tzinfo=timezone.utc),
                eid=2,
            ),
        ]
        out_four = first_weight_on_et_day(aware_four, self.DAY)
        assert out_four is not None
        assert out_four["first_weight_et"] == datetime(2026, 7, 14, 4, 0, 0)

    def test_approved_row_without_first_weight_excluded(self):
        events = [
            _ev("sent-to-vendor", datetime(2026, 7, 14, 8, 0, 0), eid=1),
            _ev("add-photos", datetime(2026, 7, 14, 9, 0, 0), eid=2),
        ]
        assert first_weight_on_et_day(events, self.DAY) is None

    def test_repeat_trip_uses_current_lifecycle_first_weight_only(self):
        events = [
            _ev("sent-to-vendor", datetime(2026, 7, 1, 8, 0, 0), eid=1),
            _ev("weight-entry", datetime(2026, 7, 1, 9, 0, 0), eid=2),
            _ev("start-cleaning", datetime(2026, 7, 1, 10, 0, 0), eid=3, rack="W25-30-VW"),
            _ev("start-cleaning", datetime(2026, 7, 1, 10, 0, 0), eid=4, rack="W26-30-VW"),
            _ev("sent-to-vendor", datetime(2026, 7, 14, 7, 0, 0), eid=5),
            _ev("weight-entry", datetime(2026, 7, 14, 11, 0, 0), eid=6),
        ]
        out = first_weight_on_et_day(events, self.DAY)
        assert out is not None
        assert out["first_weight_et"] == datetime(2026, 7, 14, 11, 0, 0)
        assert out["lifecycle_anchor_et"] == datetime(2026, 7, 14, 7, 0, 0)
        assert out["processing_units"] == 1
        assert out["split_confirmed"] is False

    def test_old_lifecycle_split_does_not_affect_current(self):
        events = [
            _ev("sent-to-vendor", datetime(2026, 6, 1, 8, 0, 0), eid=1),
            _ev("weight-entry", datetime(2026, 6, 1, 9, 0, 0), eid=2),
            _ev("start-cleaning", datetime(2026, 6, 1, 10, 0, 0), eid=3, rack="W25-30-VW"),
            _ev("start-cleaning", datetime(2026, 6, 1, 10, 0, 0), eid=4, rack="W26-30-VW"),
            _ev("sent-to-vendor", datetime(2026, 7, 14, 8, 0, 0), eid=5),
            _ev("weight-entry", datetime(2026, 7, 14, 9, 30, 0), eid=6),
            _ev("start-cleaning", datetime(2026, 7, 14, 10, 0, 0), eid=7, rack="W31-40-VW"),
        ]
        out = first_weight_on_et_day(events, self.DAY)
        assert out["processing_units"] == 1
        assert out["split_confirmed"] is False
        assert out["washer_racks"] == ["W31-40-VW"]

    def test_split_capable_before_confirmation_is_one_unit(self):
        events = [
            _ev("sent-to-vendor", datetime(2026, 7, 14, 8, 0, 0), eid=1),
            _ev("weight-entry", datetime(2026, 7, 14, 9, 0, 0), eid=2),
            _ev("split-load", datetime(2026, 7, 14, 9, 20, 0), eid=3),
            _ev("add-photos", datetime(2026, 7, 14, 9, 20, 0), eid=4),
        ]
        out = first_weight_on_et_day(events, self.DAY)
        assert out["processing_units"] == 1
        assert out["split_confirmed"] is False
        assert out["has_split_load_scan"] is True
        assert processing_units_from_split_confirmation(split_confirmed=False) == 1

    def test_split_load_purpose_alone_does_not_confirm_two_units(self):
        events = [
            _ev("sent-to-vendor", datetime(2026, 7, 14, 8, 0, 0), eid=1),
            _ev("weight-entry", datetime(2026, 7, 14, 9, 0, 0), eid=2),
            _ev("split-load", datetime(2026, 7, 14, 9, 2, 0), eid=3),
            _ev("add-photos", datetime(2026, 7, 14, 9, 2, 0), eid=4),
        ]
        out = first_weight_on_et_day(events, self.DAY)
        assert out["processing_units"] == 1
        assert out["split_confirmed"] is False
        assert out["has_split_load_scan"] is True

    def test_si_split_order_marks_pending_without_changing_units(self):
        row = _order_row_from_staging(
            {
                "ticket_id": "PEND0001",
                "name_clean": "Pending Split",
                "special_instructions_raw": "Split Order; USE OXICLEAN",
            },
            mapping_rules=DEFAULT_MAPPING_RULES,
            processing_units=1,
            split_confirmed=False,
        )
        assert row["processing_units"] == 1
        assert row["split_pending"] is True
        assert row["split_status"] == "pending"
        assert row["doses_by_supply"]["Tide"] == 1

    def test_no_si_split_is_unresolved_not_pending(self):
        row = _order_row_from_staging(
            {
                "ticket_id": "UNRESOL1",
                "name_clean": "No Split Hint",
                "special_instructions_raw": "USE OXICLEAN",
            },
            mapping_rules=DEFAULT_MAPPING_RULES,
            processing_units=1,
            split_confirmed=False,
            has_split_load_scan=True,
        )
        assert row["processing_units"] == 1
        assert row["split_pending"] is False
        assert row["split_status"] == "unresolved"
        assert row["split_load_scan"] is True

    def test_dual_washer_start_cleaning_confirms_two_units(self):
        events = [
            _ev("sent-to-vendor", datetime(2026, 7, 14, 8, 0, 0), eid=1),
            _ev("weight-entry", datetime(2026, 7, 14, 9, 28, 0), eid=2),
            _ev("split-load", datetime(2026, 7, 14, 9, 30, 0), eid=3),
            _ev("add-photos", datetime(2026, 7, 14, 9, 30, 0), eid=4),
            _ev(
                "start-cleaning",
                datetime(2026, 7, 14, 9, 46, 0),
                eid=5,
                rack="W28-20-VW",
            ),
            _ev(
                "start-cleaning",
                datetime(2026, 7, 14, 9, 46, 0),
                eid=6,
                rack="W27-20-VW",
            ),
        ]
        out = first_weight_on_et_day(events, self.DAY)
        assert out["processing_units"] == 2
        assert out["split_confirmed"] is True
        assert set(out["washer_racks"]) == {"W27-20-VW", "W28-20-VW"}
        assert out["washer_load_count"] == 2
        assert processing_units_from_split_confirmation(split_confirmed=True) == 2

    def test_single_washer_start_cleaning_is_one_unit(self):
        events = [
            _ev("sent-to-vendor", datetime(2026, 7, 14, 8, 0, 0), eid=1),
            _ev("weight-entry", datetime(2026, 7, 14, 9, 0, 0), eid=2),
            _ev("add-photos", datetime(2026, 7, 14, 9, 20, 0), eid=3),
            _ev(
                "start-cleaning",
                datetime(2026, 7, 14, 9, 40, 0),
                eid=4,
                rack="W30-40-VW",
            ),
        ]
        out = first_weight_on_et_day(events, self.DAY)
        assert out["processing_units"] == 1
        assert out["split_confirmed"] is False
        assert out["washer_racks"] == ["W30-40-VW"]


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
                "processing_units": 1,
                "split_order": False,
            }
        ]
        report = self._report_from_orders(orders)
        assert report["usage_by_supply"]["Tide"]["doses"] == 1
        assert report["usage_by_supply"]["Tide"]["ounces"] == 2.0
        assert report["usage_by_supply"]["Downy"]["doses"] == 1
        assert report["usage_by_supply"]["Downy"]["ounces"] == 1.0

    def test_confirmed_split_doubles_doses(self):
        orders = [
            {
                "supplies_used": ["Tide"],
                "doses_by_supply": {"Tide": 2},
                "multiplier": 2,
                "processing_units": 2,
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


class TestApprovedUploadRowStatusSql:
    def test_approved_upload_query_filters_row_status_and_org(self):
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
            _load_approved_upload_orders_by_tickets(cursor, 3, ["ABC12345"])
        finally:
            su.table_exists = original_te
            su.table_has_column = original_thc

        assert executed
        sql = executed[0][0]
        assert "ub.batch_id = ubr.upload_batch_id" in sql
        assert "ubr.row_status IN ('ACCEPTED', 'OVERRIDDEN')" in sql
        assert "UPPER(TRIM(ubr.ticket_id)) IN" in sql
        assert "date_clean = %s" not in sql
        assert executed[0][1][0] == "ABC12345"
        assert executed[0][1][-1] == 3


class TestLoadOrdersFirstWeightPopulation:
    DAY = date(2026, 7, 14)
    FAB_OXIC = "USE FABRIC SOFTENER; USE OXICLEAN"

    def _membership(self, bag_id="BAG00001", *, units=1, split=False):
        return {
            bag_id: {
                "lifecycle_anchor_et": datetime(2026, 7, 14, 8, 0, 0),
                "first_weight_et": datetime(2026, 7, 14, 10, 0, 0),
                "split_confirmed": split,
                "split_pending": not split,
                "latest_split_scan_et": datetime(2026, 7, 14, 10, 30, 0) if split else None,
                "processing_units": units,
                "split_load_scan_count": 1 if split else 0,
            }
        }

    def _meta(self, ticket_id, *, row_status="ACCEPTED", si=None, source="upload_batch_rows"):
        return {
            ticket_id: {
                "ticket_id": ticket_id,
                "name_clean": "Customer",
                "date_clean": date(2026, 7, 13),
                "special_instructions_raw": si if si is not None else self.FAB_OXIC,
                "row_status": row_status,
                "_source": source,
            }
        }

    def _load(self, membership, meta):
        from backend import supply_usage as su

        cursor = MagicMock()
        cursor.fetchone.return_value = None
        original_fw = su._bags_with_first_weight_on_et_day
        original_meta = su._load_approved_order_metadata
        su._bags_with_first_weight_on_et_day = lambda *a, **k: membership
        su._load_approved_order_metadata = lambda *a, **k: meta
        try:
            return load_orders_for_supply_usage(cursor, 3, self.DAY)
        finally:
            su._bags_with_first_weight_on_et_day = original_fw
            su._load_approved_order_metadata = original_meta

    def test_accepted_counts_with_first_weight(self):
        orders = self._load(self._membership("ACC00001"), self._meta("ACC00001"))
        assert len(orders) == 1
        assert orders[0]["supplies_used"] == ["Tide", "Downy", "OxiClean"]
        assert orders[0]["processing_units"] == 1
        assert orders[0]["doses_by_supply"]["Tide"] == 1
        assert orders[0]["doses_by_supply"]["Downy"] == 1
        assert orders[0]["doses_by_supply"]["OxiClean"] == 1

    def test_overridden_counts(self):
        meta = self._meta(
            "OVR00001",
            row_status="OVERRIDDEN",
            si="Use Hypoallergenic Soap",
        )
        orders = self._load(self._membership("OVR00001"), meta)
        assert len(orders) == 1
        assert orders[0]["supplies_used"] == ["All Free & Clear"]
        assert orders[0]["doses_by_supply"]["All Free & Clear"] == 1

    def test_no_metadata_means_excluded_even_with_first_weight(self):
        # REJECTED / DELETED / NEEDS_ATTENTION never appear in approved metadata loader.
        orders = self._load(self._membership("REJ00001"), {})
        assert orders == []

    def test_rejected_deleted_needs_attention_not_in_metadata(self):
        from backend import supply_usage as su

        executed: list[str] = []

        def fake_table_exists(cursor, table):
            return table in ("upload_batch_rows", "upload_batches")

        def fake_table_has_column(cursor, table, col):
            if table == "upload_batches" and col in ("id", "organization_id"):
                return True
            if table == "upload_batch_rows" and col in (
                "ticket_id",
                "special_instructions_raw",
                "row_status",
            ):
                return True
            return False

        cursor = MagicMock()
        cursor.fetchall.return_value = []

        def capture(sql, args=()):
            executed.append(sql)

        cursor.execute = capture
        original_te = su.table_exists
        original_thc = su.table_has_column
        su.table_exists = fake_table_exists
        su.table_has_column = fake_table_has_column
        try:
            _load_approved_upload_orders_by_tickets(
                cursor, 3, ["REJ1", "DEL1", "ATT1", "ACC1"]
            )
        finally:
            su.table_exists = original_te
            su.table_has_column = original_thc

        assert any("row_status IN ('ACCEPTED', 'OVERRIDDEN')" in s for s in executed)
        assert all("REJECTED_DUPLICATE" not in s for s in executed)

    def test_confirmed_split_doubles_supply_doses(self):
        orders = self._load(
            self._membership("SPL00001", units=2, split=True),
            self._meta("SPL00001"),
        )
        assert orders[0]["processing_units"] == 2
        assert orders[0]["split_confirmed"] is True
        assert orders[0]["doses_by_supply"]["Tide"] == 2
        assert orders[0]["doses_by_supply"]["Downy"] == 2
        assert orders[0]["estimated_doses"] == 6

    def test_report_excludes_other_day_first_weights(self):
        from backend import supply_usage as su

        cursor = MagicMock()
        cursor.fetchone.return_value = None
        original_fw = su._bags_with_first_weight_on_et_day
        su._bags_with_first_weight_on_et_day = lambda *a, **k: {}
        try:
            report = build_supply_usage_report(cursor, 3, self.DAY)
        finally:
            su._bags_with_first_weight_on_et_day = original_fw
        assert report["summary"]["orders_analyzed"] == 0
        assert "first_weight_et day" in report["data_source"]


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
