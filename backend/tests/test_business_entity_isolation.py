"""Tests for WashPro / WashMate / VeeWash entity isolation."""

from backend.business_entity import (
    ENTITY_NONE,
    ENTITY_RINSE_EXCLUSIVE,
    ENTITY_SHARED,
    ENTITY_VEEWASH,
    ENTITY_WASHMATE,
    ENTITY_WASHPRO,
    default_entity_for_org,
    entities_for_organization,
    normalize_shift_entity,
    normalize_worker_entity,
    shift_matches_entity_tab,
    worker_allows_shift_entity,
    worker_matches_entity_tab,
)
from backend.payroll_employer_affiliation import (
    EMPLOYER_AFFILIATION_VEEWASH,
    bulk_shift_entity_allowed,
    employer_affiliation_from_flags,
    flags_from_employer_affiliation,
)


def test_default_entity_per_org_slug():
    assert default_entity_for_org("washpro") == ENTITY_WASHPRO
    assert default_entity_for_org("washmate") == ENTITY_WASHMATE
    assert default_entity_for_org("veewash") == ENTITY_VEEWASH


def test_legacy_veewash_shift_on_washpro_org_maps_to_washpro():
    assert normalize_shift_entity("veewash", organization_slug="washpro") == ENTITY_WASHPRO


def test_legacy_veewash_shift_on_veewash_org_stays_veewash():
    assert normalize_shift_entity("veewash", organization_slug="veewash") == ENTITY_VEEWASH


def test_none_worker_hidden_from_entity_tabs():
    worker = {"employer_affiliation": ENTITY_NONE}
    assert worker_matches_entity_tab(ENTITY_NONE, ENTITY_WASHPRO, organization_slug="washpro") is False
    assert worker_matches_entity_tab(worker["employer_affiliation"], ENTITY_RINSE_EXCLUSIVE, organization_slug="washpro") is False
    assert worker_matches_entity_tab(worker["employer_affiliation"], "combined", organization_slug="washpro") is False


def test_washpro_tab_does_not_show_veewash_worker():
    worker = {"employer_affiliation": ENTITY_VEEWASH}
    assert worker_matches_entity_tab(worker["employer_affiliation"], ENTITY_WASHPRO, organization_slug="washpro") is False
    assert worker_matches_entity_tab(worker["employer_affiliation"], ENTITY_VEEWASH, organization_slug="veewash") is True


def test_washmate_tab_does_not_show_washpro_worker():
    worker = {"employer_affiliation": ENTITY_WASHPRO}
    assert worker_matches_entity_tab(worker["employer_affiliation"], ENTITY_WASHMATE, organization_slug="washmate") is False
    washmate_worker = {"employer_affiliation": ENTITY_WASHMATE}
    assert worker_matches_entity_tab(washmate_worker["employer_affiliation"], ENTITY_WASHMATE, organization_slug="washmate") is True


def test_shared_worker_visible_on_washpro_and_rinse_tabs_for_washpro_org():
    worker = {"employer_affiliation": ENTITY_SHARED}
    assert worker_matches_entity_tab(worker["employer_affiliation"], ENTITY_WASHPRO, organization_slug="washpro") is True
    assert worker_matches_entity_tab(worker["employer_affiliation"], ENTITY_RINSE_EXCLUSIVE, organization_slug="washpro") is True
    assert worker_matches_entity_tab(worker["employer_affiliation"], ENTITY_VEEWASH, organization_slug="washpro") is False


def test_bulk_move_blocks_cross_entity_worker():
    worker = {"employer_affiliation": ENTITY_WASHPRO}
    allowed, reason = bulk_shift_entity_allowed(worker, ENTITY_RINSE_EXCLUSIVE, organization_slug="washpro")
    assert allowed is False
    assert reason


def test_bulk_move_allows_matching_entity_worker():
    worker = {"employer_affiliation": ENTITY_RINSE_EXCLUSIVE}
    allowed, _ = bulk_shift_entity_allowed(worker, ENTITY_RINSE_EXCLUSIVE, organization_slug="washpro")
    assert allowed is True


def test_shift_tab_match_is_entity_scoped():
    assert shift_matches_entity_tab(ENTITY_WASHPRO, ENTITY_WASHPRO, organization_slug="washpro") is True
    assert shift_matches_entity_tab(ENTITY_WASHPRO, ENTITY_VEEWASH, organization_slug="washpro") is False


def test_entities_for_org_slug():
    assert entities_for_organization("washpro", is_privileged=True) == [
        ENTITY_WASHPRO,
        ENTITY_RINSE_EXCLUSIVE,
        "combined",
    ]
    assert entities_for_organization("veewash", is_privileged=False) == [ENTITY_VEEWASH]


def test_legacy_veewash_affiliation_flag_maps_to_washpro_on_washpro_org():
    flags = flags_from_employer_affiliation(EMPLOYER_AFFILIATION_VEEWASH)
    assert employer_affiliation_from_flags(flags, organization_slug="washpro") == ENTITY_WASHPRO


def test_worker_allows_shift_entity_shared():
    assert worker_allows_shift_entity(ENTITY_SHARED, ENTITY_RINSE_EXCLUSIVE, organization_slug="washpro")
    assert not worker_allows_shift_entity(ENTITY_WASHMATE, ENTITY_WASHPRO, organization_slug="washmate")
