"""Tests for Rinse Special Instructions parsing and mapping."""

import pytest

from backend.rinse_special_instructions import (
    build_special_instructions_raw,
    extract_labeled_special_instructions,
    format_special_instructions_display,
    interpret_special_instructions,
)

CHRISTIAN_POLLUTED_RAW = (
    "Vendor Notes Vendor Price Collateral Dry Clean Hang Dry Launder & Press Leather Cleaning "
    "Press Only Repair Shine Special Services Specialty Items Wash and Fold Apron Baby Clothing "
    "Bag Bathing Suit Bathing Suit (Bottom) Bathing Suit (Top) Bath Mat Bath Rug Belt Blanket "
    "Blanket (Large) Blanket (Small) Blouse Boots Boxers Bra Button (Repair) Cloth Mask "
    "Cloth Mask (Kids) Coat Coat (Down) Comforter Comforter (Down) Couch Cover Cover Cummerbund "
    "Curtain Door Hanger Dress (Casual) Dress (Formal) Duvet D; USE FABRIC SOFTENER; USE OXICLEAN; "
    "Use Hypoallergenic Soap"
)

CHRISTIAN_CATALOG_ONLY = CHRISTIAN_POLLUTED_RAW.split(";")[0]

RYAN_TIFFANY_POLLUTED_RAW = (
    "Vendor Notes Vendor Price Collateral Dry Clean Hang Dry Launder & Press Leather Cleaning "
    "Press Only Repair Shine Special Services Specialty Items Wash and Fold Apron Baby Clothing "
    "Bag Bathing Suit Bathing Suit (Bottom) Bathing Suit (Top) Bath Mat Bath Rug Belt Blanket "
    "Blanket (Large) Blanket (Small) Blouse Boots Boxers Bra Button (Repair) Cloth Mask "
    "Cloth Mask (Kids) Coat Coat (Down) Comforter Comforter (Down) Couch Cover Cover Cummerbund "
    "Curtain Door Hanger Dress (Casual) Dress (Formal) Duvet D; USE FABRIC SOFTENER; USE OXICLEAN; "
    "Use Hypoallergenic Soap"
)

CURTIS_POLLUTED_RAW = (
    "Vendor Notes Vendor Price Collateral Dry Clean Hang Dry Launder & Press Leather Cleaning "
    "Press Only Repair Shine Special Services Specialty Items Wash and Fold Apron Baby Clothing "
    "Bag Bathing Suit Bathing Suit (Bottom) Bathing Suit (Top) Bath Mat Bath Rug Belt Blanket "
    "Blanket (Large) Blanket (Small) Blouse Boots Boxers Bra Button (Repair) Cloth Mask "
    "Cloth Mask (Kids) Coat Coat (Down) Comforter Comforter (Down) Couch Cover Cover Cummerbund "
    "Curtain Door Hanger Dress (Casual) Dress (Formal) Duvet D; USE OXICLEAN"
)

CURTIS_EMPTY_SI_PORTAL = """Special Instructions: 
Service Type: Wash and Fold
Vendor Notes Vendor Price Collateral Dry Clean Hang Dry"""

RYAN_TIFFANY_LABELED_SI = (
    "Special Instructions: Use Hypoallergenic Soap; USE OXICLEAN\nService Type: Wash and Fold"
)


class TestBuildSpecialInstructionsRaw:
    def test_blank_is_none(self):
        assert build_special_instructions_raw() is None

    def test_explicit_column(self):
        raw = build_special_instructions_raw(special_instructions_col="USE OXICLEAN")
        assert raw == "USE OXICLEAN"

    def test_flags_combined(self):
        raw = build_special_instructions_raw(
            special_instructions_col="USE OXICLEAN",
            use_fab="X",
            use_oxic="X",
        )
        assert "USE FABRIC SOFTENER" in raw
        assert "USE OXICLEAN" in raw

    def test_flags_without_si_column_are_ignored(self):
        assert build_special_instructions_raw(use_fab="X", use_oxic="X") is None

    def test_flags_from_unusable_si_column_catalog_pollution(self):
        raw = build_special_instructions_raw(
            special_instructions_col=CHRISTIAN_CATALOG_ONLY,
            use_fab="X",
            use_oxic="X",
            use_hypo="X",
        )
        assert "USE FABRIC SOFTENER" in raw
        assert "USE OXICLEAN" in raw
        assert "Hypoallergenic" in raw

    def test_catalog_pollution_without_flags_stays_none(self):
        assert build_special_instructions_raw(special_instructions_col=CHRISTIAN_CATALOG_ONLY) is None

    def test_hypo_flag(self):
        raw = build_special_instructions_raw(
            special_instructions_col="Use Hypoallergenic Soap",
            use_hypo="X",
        )
        assert "Hypoallergenic" in raw

    def test_vendor_catalog_notes_skipped(self):
        raw = build_special_instructions_raw(
            notes=CHRISTIAN_POLLUTED_RAW.split(";")[0],
            use_hypo="X",
        )
        assert raw is None

    def test_vendor_catalog_notes_do_not_merge_with_si(self):
        raw = build_special_instructions_raw(
            special_instructions_col="Use Hypoallergenic Soap",
            notes=CHRISTIAN_POLLUTED_RAW.split(";")[0],
            use_hypo="X",
        )
        assert raw == "Use Hypoallergenic Soap"

    def test_notes_not_merged_into_raw(self):
        raw = build_special_instructions_raw(
            notes="USE OXICLEAN",
            special_instructions_col="Use Hypoallergenic Soap",
        )
        assert raw == "Use Hypoallergenic Soap"


class TestInterpretSpecialInstructions:
    def test_standard_blank(self):
        out = interpret_special_instructions(None)
        assert out["supply_interpretation"] == "Standard soap"
        assert out["supplies_used"] == ["Tide"]
        assert out["special_instruction_review"] is False

    def test_fabric_softener(self):
        out = interpret_special_instructions("USE FABRIC SOFTENER")
        assert out["supply_interpretation"] == "Soap + softener"
        assert out["supplies_used"] == ["Tide", "Downy"]

    def test_oxiclean(self):
        out = interpret_special_instructions("use oxiclean")
        assert out["supply_interpretation"] == "Soap + OxiClean"
        assert "OxiClean" in out["supplies_used"]

    def test_fab_and_oxic(self):
        out = interpret_special_instructions("USE FABRIC SOFTENER; USE OXICLEAN")
        assert out["supply_interpretation"] == "Soap + softener + OxiClean"
        assert out["supplies_used"] == ["Tide", "Downy", "OxiClean"]

    def test_hypo(self):
        out = interpret_special_instructions("Use Hypoallergenic Soap")
        assert out["supply_interpretation"] == "Hypoallergenic soap"
        assert out["supplies_used"] == ["Hypoallergenic detergent"]

    def test_hypo_fab(self):
        out = interpret_special_instructions("Use Hypoallergenic Soap; USE FABRIC SOFTENER")
        assert "Hypoallergenic" in out["supply_interpretation"]
        assert "Downy" in out["supplies_used"]

    def test_hypo_oxic(self):
        out = interpret_special_instructions("Use Hypoallergenic Soap; USE OXICLEAN")
        assert "OxiClean" in out["supplies_used"]

    def test_unknown_flags_review(self):
        out = interpret_special_instructions("CALL CUSTOMER BEFORE WASH")
        assert out["special_instruction_review"] is True
        assert out["supply_interpretation"] == "Needs review"

    def test_case_insensitive_multi(self):
        out = interpret_special_instructions("use fabric softener\nuse oxiclean")
        assert out["supply_interpretation"] == "Soap + softener + OxiClean"

    def test_bare_hypo_in_unrelated_word_does_not_match(self):
        out = interpret_special_instructions("Customer requested hypothetic sizing chart")
        assert "Hypoallergenic" not in out["supplies_used"]
        assert out["special_instruction_review"] is True
        assert out["supply_interpretation"] == "Needs review"

    def test_christian_portal_vendor_catalog_defaults_tide(self):
        out = interpret_special_instructions(CHRISTIAN_CATALOG_ONLY)
        assert out["supply_interpretation"] == "Standard soap"
        assert out["supplies_used"] == ["Tide"]
        assert out["special_instructions_raw"] is None
        assert out["special_instruction_review"] is False

    def test_polluted_catalog_trailing_tokens_default_standard(self):
        out = interpret_special_instructions(CHRISTIAN_POLLUTED_RAW)
        assert out["supply_interpretation"] == "Standard soap"
        assert out["supplies_used"] == ["Tide"]
        assert out["special_instructions_raw"] is None
        assert out["special_instruction_review"] is False

    def test_ryan_tiffany_polluted_row_defaults_standard(self):
        out = interpret_special_instructions(RYAN_TIFFANY_POLLUTED_RAW)
        assert out["supply_interpretation"] == "Standard soap"
        assert out["supplies_used"] == ["Tide"]
        assert format_special_instructions_display(RYAN_TIFFANY_POLLUTED_RAW) is None

    def test_ryan_tiffany_labeled_si_hypo_oxic_only(self):
        out = interpret_special_instructions(RYAN_TIFFANY_LABELED_SI)
        assert out["supplies_used"] == ["Hypoallergenic detergent", "OxiClean"]
        assert format_special_instructions_display(RYAN_TIFFANY_LABELED_SI) == (
            "Hypoallergenic + OxiClean"
        )
        assert "softener" not in (out["supply_interpretation"] or "").lower()

    def test_curtis_teegardin_empty_si_defaults_standard(self):
        out = interpret_special_instructions(CURTIS_POLLUTED_RAW)
        assert out["supply_interpretation"] == "Standard soap"
        assert out["supplies_used"] == ["Tide"]
        assert format_special_instructions_display(CURTIS_POLLUTED_RAW) is None

    def test_curtis_empty_labeled_si_ignores_stale_flags(self):
        raw = build_special_instructions_raw(
            special_instructions_col=CURTIS_EMPTY_SI_PORTAL,
            use_fab="X",
            use_oxic="X",
            use_hypo="X",
        )
        assert raw is None
        assert format_special_instructions_display(CURTIS_EMPTY_SI_PORTAL) is None

    def test_labeled_special_instructions_with_fabric_softener(self):
        raw = "Special Instructions: USE FABRIC SOFTENER; USE OXICLEAN"
        out = interpret_special_instructions(raw)
        assert out["supplies_used"] == ["Tide", "Downy", "OxiClean"]

    def test_portal_menu_pollution_without_selection_defaults_standard(self):
        out = interpret_special_instructions(CHRISTIAN_CATALOG_ONLY)
        assert out["supply_interpretation"] == "Standard soap"
        assert out["supplies_used"] == ["Tide"]

    def test_extract_labeled_special_instructions(self):
        raw = (
            "Vendor Notes Vendor Price Wash and Fold "
            "Special Instructions: Use Hypoallergenic Soap; USE OXICLEAN"
        )
        assert extract_labeled_special_instructions(raw) == (
            "Use Hypoallergenic Soap; USE OXICLEAN"
        )

    def test_real_hypo_still_maps(self):
        out = interpret_special_instructions("Use Hypoallergenic Soap")
        assert out["supplies_used"] == ["Hypoallergenic detergent"]


class TestFormatSpecialInstructionsDisplay:
    def test_blank_is_none(self):
        assert format_special_instructions_display(None) is None
        assert format_special_instructions_display("") is None

    def test_polluted_catalog_only_is_none(self):
        assert format_special_instructions_display(CHRISTIAN_CATALOG_ONLY) is None

    def test_polluted_row_shows_none_not_template_tokens(self):
        assert format_special_instructions_display(CHRISTIAN_POLLUTED_RAW) is None

    def test_hypo_only(self):
        assert format_special_instructions_display("Use Hypoallergenic Soap") == "Hypoallergenic"

    def test_fab_oxic(self):
        assert (
            format_special_instructions_display("USE FABRIC SOFTENER; USE OXICLEAN")
            == "Fabric Softener + OxiClean"
        )

    def test_oxic_only(self):
        assert format_special_instructions_display("USE OXICLEAN") == "OxiClean"

    def test_embedded_hypo_in_catalog_blob_ignored_without_labeled_si(self):
        raw = (
            "Vendor Notes Vendor Price Collateral Dry Clean Hang Dry Launder & Press Leather Cleaning "
            "Press Only Repair Shine Special Services Specialty Items Wash and Fold Apron Baby Clothing "
            "Bag Bathing Suit Bathing Suit (Bottom) Bathing Suit (Top) Bath Mat Bath Rug Belt Blanket "
            "Blanket (Large) Blanket (Small) Blouse Boots Boxers Bra Button (Repair) Cloth Mask "
            "Cloth Mask (Kids) Coat Coat (Down) Comforter Comforter (Down) Couch Cover Cover Cummerbund "
            "Curtain Door Hanger Dress (Casual) Dress (Formal) Duvet D Use Hypoallergenic Soap"
        )
        assert format_special_instructions_display(raw) is None

    def test_unknown_notes_appended(self):
        out = format_special_instructions_display("USE OXICLEAN; CALL CUSTOMER BEFORE WASH")
        assert out == "OxiClean; CALL CUSTOMER BEFORE WASH"
