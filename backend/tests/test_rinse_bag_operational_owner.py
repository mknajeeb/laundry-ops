"""Tests for canonical operational owner isolation."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest

from backend.rinse_bag_operational_owner import (
    CanonicalOwner,
    REJECT_REASON_NOT_OWNER,
    SOURCE_CREDENTIAL,
    assert_operational_write_allowed,
    assign_owner_from_credential,
    filter_bag_ids_for_operational_write,
    resolve_canonical_owner,
    SOURCE_REGISTRY,
    _pick_canonical_from_candidates,
)


class TestCanonicalOwnerResolution:
    def test_pick_earliest_registry(self):
        owner = _pick_canonical_from_candidates(
            "BAG1",
            [
                (3, datetime(2026, 6, 16, 9, 0, 0), SOURCE_REGISTRY),
                (1, datetime(2026, 6, 10, 7, 0, 0), SOURCE_REGISTRY),
            ],
        )
        assert owner is not None
        assert owner.owner_organization_id == 1

    def test_resolve_from_table(self):
        row = {
            "bag_id": "BAG1",
            "owner_organization_id": 1,
            "owner_rinse_vendor": "washpro",
            "assigned_at": datetime(2026, 6, 1),
            "assignment_source": SOURCE_REGISTRY,
            "locked": 1,
        }
        with patch(
            "backend.rinse_bag_operational_owner._fetch_owner_row",
            return_value=row,
        ):
            owner = resolve_canonical_owner(object(), "BAG1")
        assert owner is not None
        assert owner.owner_organization_id == 1
        assert owner.from_table is True


class TestOperationalWriteGate:
    def test_rejects_non_owner_when_canonical_exists(self):
        canonical = CanonicalOwner(
            bag_id="BAG1",
            owner_organization_id=1,
            owner_rinse_vendor="washpro",
            assigned_at=datetime(2026, 6, 1),
            assignment_source=SOURCE_REGISTRY,
        )
        with patch(
            "backend.rinse_bag_operational_owner.resolve_canonical_owner",
            return_value=canonical,
        ), patch(
            "backend.rinse_bag_operational_owner.operational_owner_gate_enabled",
            return_value=True,
        ):
            ok, reason, owner = assert_operational_write_allowed(object(), 3, "BAG1")
        assert ok is False
        assert reason == REJECT_REASON_NOT_OWNER
        assert owner.owner_organization_id == 1

    def test_allows_and_assigns_on_first_write(self):
        with patch(
            "backend.rinse_bag_operational_owner.resolve_canonical_owner",
            return_value=None,
        ), patch(
            "backend.rinse_bag_operational_owner.operational_owner_gate_enabled",
            return_value=True,
        ), patch(
            "backend.rinse_bag_operational_owner.assign_owner_on_first_write",
            return_value=CanonicalOwner(
                bag_id="NEW1",
                owner_organization_id=3,
                owner_rinse_vendor="veewash",
                assigned_at=datetime(2026, 6, 16),
                assignment_source="gate_first_write",
            ),
        ):
            ok, reason, owner = assert_operational_write_allowed(object(), 3, "NEW1")
        assert ok is True
        assert reason is None
        assert owner is not None
        assert owner.owner_organization_id == 3

    def test_filter_batch_splits_allowed_and_rejected(self):
        canonical = CanonicalOwner(
            bag_id="WP1",
            owner_organization_id=1,
            owner_rinse_vendor="washpro",
            assigned_at=datetime(2026, 6, 1),
            assignment_source=SOURCE_REGISTRY,
        )
        with patch(
            "backend.rinse_bag_operational_owner.assert_operational_write_allowed",
            side_effect=lambda _c, org, bid, **kw: (
                (False, REJECT_REASON_NOT_OWNER, canonical) if bid == "WP1"
                else (True, None, None)
            ),
        ):
            allowed, rejected = filter_bag_ids_for_operational_write(object(), 3, {"WP1", "VEE1"})
        assert allowed == {"VEE1"}
        assert len(rejected) == 1
        assert rejected[0]["bag_id"] == "WP1"

    def test_credential_sourced_allows_despite_historical_washpro_owner(self):
        canonical = CanonicalOwner(
            bag_id="BAG1",
            owner_organization_id=1,
            owner_rinse_vendor="washpro",
            assigned_at=datetime(2026, 6, 1),
            assignment_source=SOURCE_REGISTRY,
        )
        with patch(
            "backend.rinse_bag_operational_owner.resolve_canonical_owner",
            return_value=canonical,
        ), patch(
            "backend.rinse_bag_operational_owner.operational_owner_gate_enabled",
            return_value=True,
        ), patch(
            "backend.rinse_bag_operational_owner.assign_owner_from_credential",
            return_value=CanonicalOwner(
                bag_id="BAG1",
                owner_organization_id=3,
                owner_rinse_vendor="veewash",
                assigned_at=datetime(2026, 6, 16),
                assignment_source=SOURCE_CREDENTIAL,
            ),
        ) as assign_cred:
            ok, reason, owner = assert_operational_write_allowed(
                object(), 3, "BAG1", credential_sourced=True
            )
        assert ok is True
        assert reason is None
        assert owner.owner_organization_id == 3
        assign_cred.assert_called_once()
