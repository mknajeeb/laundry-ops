"""Tests for Rinse Special Instructions parsing and mapping."""

import pytest

from backend.rinse_special_instructions import (
    build_special_instructions_raw,
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


class TestBuildSpecialInstructionsRaw:
    def test_blank_is_none(self):
        assert build_special_instructions_raw() is None

    def test_explicit_column(self):
        raw = build_special_instructions_raw(special_instructions_col="USE OXICLEAN")
        assert raw == "USE OXICLEAN"

    def test_flags_combined(self):
        raw = build_special_instructions_raw(use_fab="X", use_oxic="X")
        assert "USE FABRIC SOFTENER" in raw
        assert "USE OXICLEAN" in raw

    def test_hypo_flag(self):
        raw = build_special_instructions_raw(use_hypo="X")
        assert "Hypoallergenic" in raw

    def test_vendor_catalog_notes_skipped(self):
        raw = build_special_instructions_raw(
            notes=CHRISTIAN_POLLUTED_RAW.split(";")[0],
            use_hypo="X",
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
        out = interpret_special_instructions(CHRISTIAN_POLLUTED_RAW)
        assert out["supply_interpretation"] == "Standard soap"
        assert out["supplies_used"] == ["Tide"]
        assert out["special_instructions_raw"] is None
        assert out["special_instruction_review"] is False

    def test_real_hypo_still_maps(self):
        out = interpret_special_instructions("Use Hypoallergenic Soap")
        assert out["supplies_used"] == ["Hypoallergenic detergent"]
