"""Tests for tenant_scope helpers."""

from backend.tenant_scope import (
    bulk_action_entity_guard,
    combined_view_is_admin_only,
    normalize_active_entity_tab,
    require_organization_id,
    resolve_entity_scope,
    scoped_organization_filter,
)


def test_require_organization_id():
    assert require_organization_id(3) == 3


def test_scoped_organization_filter():
    clause, params = scoped_organization_filter(5)
    assert clause == "organization_id = %s"
    assert params == (5,)


def test_resolve_entity_scope_washpro():
    scope = resolve_entity_scope(1, "washpro", ["ADMIN"])
    assert scope["organization_slug"] == "washpro"
    assert "washpro" in scope["entity_tabs"]
    assert "combined" in scope["entity_tabs"]


def test_normalize_active_entity_tab_fallback():
    assert normalize_active_entity_tab("invalid", organization_slug="washmate") == "washmate"


def test_bulk_action_entity_guard_blocks_none_worker():
    allowed, reason = bulk_action_entity_guard(
        {"can_work_rinse": False, "can_work_drop_off": False, "can_work_both": False},
        source_entity="washpro",
        target_entity="rinse_exclusive",
        organization_slug="washpro",
    )
    assert allowed is False
    assert reason


def test_combined_view_is_admin_only():
    assert combined_view_is_admin_only("combined") is True
    assert combined_view_is_admin_only("washpro") is False
