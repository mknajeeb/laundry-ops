"""Tests for Pub 15-T and withholding profile defaults."""

from decimal import Decimal

from backend.employee_withholding_profile import (
    apply_withholding_profile_defaults,
    is_married_filing,
    step2_checkbox_checked,
)
from backend.pub_15t_withholding import federal_withholding_pub_15t


def test_profile_defaults_single_nyc():
    profile = apply_withholding_profile_defaults({}, "Jane Doe")
    assert profile["nyc_resident"] is True
    assert profile["filing_status"] == "single_or_mfs"
    assert profile["step2_multiple_jobs"] == "no"
    assert not step2_checkbox_checked(profile)


def test_profile_override_alec_dependents():
    profile = apply_withholding_profile_defaults({}, "Alec Coaxum")
    assert int(profile["w4_qualifying_children_under_17_count"]) == 2
    assert float(profile["dependents_amount"]) == 4000.0


def test_profile_override_alec_display_name_alias():
    profile = apply_withholding_profile_defaults({}, "Alec W Coaxum")
    assert float(profile["dependents_amount"]) == 4000.0


def test_profile_override_tarannum_mithala_alias():
    profile = apply_withholding_profile_defaults({}, "Tarannum Mithala")
    assert is_married_filing(profile)


def test_profile_override_tarannum_mithila_display_alias():
    profile = apply_withholding_profile_defaults({}, "Mithila")
    assert is_married_filing(profile)


def test_profile_override_paola_multiple_jobs():
    profile = apply_withholding_profile_defaults({}, "Paola Almiron")
    assert profile["two_jobs_only"] is True
    assert step2_checkbox_checked(profile)


def test_profile_override_tarannum_married():
    profile = apply_withholding_profile_defaults({}, "Tarannum Mithila")
    assert is_married_filing(profile)


def test_federal_minimum_matches_pub_15t_no_annual_gate():
    from backend.pub_15t_withholding import federal_minimum_withholding_pub_15t

    wages = Decimal("120")
    pub = federal_withholding_pub_15t(
        wages,
        periods_per_year=52,
        filing_status="single_or_mfs",
    )
    minimum = federal_minimum_withholding_pub_15t(
        wages,
        periods_per_year=52,
        filing_status="single_or_mfs",
    )
    assert minimum == pub


def test_federal_step2_higher_than_standard():
    standard = federal_withholding_pub_15t(
        Decimal("800"),
        periods_per_year=26,
        step2_checkbox=False,
    )
    step2 = federal_withholding_pub_15t(
        Decimal("800"),
        periods_per_year=26,
        step2_checkbox=True,
    )
    assert step2 >= standard
