"""Tests for Rinse Special Instructions parsing and mapping."""

import pytest

from backend.rinse_special_instructions import (
    build_special_instructions_raw,
    interpret_special_instructions,
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
