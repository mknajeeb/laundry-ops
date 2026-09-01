"""Safety tests for scoped org Rinse ops baseline reset."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.rinse_ops_baseline_reset import (
    ALLOWED_ORGANIZATION_IDS,
    TARGETS,
    _require_allowed_org,
    _validate_target,
    inventory_org_rinse_ops,
)


def test_only_org_3_allowed():
    assert 3 in ALLOWED_ORGANIZATION_IDS
    assert _require_allowed_org(3) == 3
    with pytest.raises(ValueError):
        _require_allowed_org(1)
    with pytest.raises(ValueError):
        _require_allowed_org(99)


def test_targets_never_include_preserved_business_tables():
    names = {t.table for t in TARGETS}
    forbidden = {
        "employees",
        "users",
        "auth_sessions",
        "payroll_cycles",
        "payroll_payments",
        "system_settings",
        "rinse_bag_registry",
        "rinse_folding_user_map",
        "rinse_bulk_workitems",
        "orders_staging",
        "checkout_log",
        "orders_final",
    }
    assert names.isdisjoint(forbidden)


def test_validate_stops_when_upload_batches_lack_org(monkeypatch):
    cur = MagicMock()

    def fake_exists(_c, table):
        return table in ("upload_batch_rows", "upload_batches")

    def fake_has(_c, table, col):
        if table == "upload_batches" and col == "organization_id":
            return False
        if table == "upload_batch_rows" and col == "upload_batch_id":
            return True
        return False

    monkeypatch.setattr(
        "backend.rinse_ops_baseline_reset.table_exists", fake_exists
    )
    monkeypatch.setattr(
        "backend.rinse_ops_baseline_reset.table_has_column", fake_has
    )
    from backend.rinse_ops_baseline_reset import TargetSpec

    spec = TargetSpec("upload_batch_rows", "via_upload_batches")
    reason = _validate_target(cur, spec)
    assert reason and "organization_id" in reason
