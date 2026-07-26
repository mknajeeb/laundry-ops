"""Legacy HD EDD membership gate — disabled.

HD day membership is append-only same-day scrape evidence (service_type=HD),
not estimated_delivery_date. This module remains only as a no-op passthrough
for older call sites / tests that still import the gate name.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping


def apply_hd_edd_day_membership_gate(
    cursor,
    organization_id: int,
    selected_date_et: date,
    membership_result: Mapping[str, Any],
) -> dict[str, Any]:
    """No-op: EDD must not include or exclude HD membership."""
    del cursor, organization_id  # unused — kept for call-signature compatibility
    out = dict(membership_result or {})
    out["hd_edd_gate"] = {
        "selected_date_et": selected_date_et.isoformat(),
        "enabled": False,
        "authoritative_field": None,
        "disabled_reason": "hd_membership_uses_same_day_scrape_evidence_not_edd",
        "removed_future_edd_bag_ids": [],
        "removed_past_edd_bag_ids": [],
        "removed_inactive_bag_ids": [],
        "removed_completed_bag_ids": [],
        "removed_missing_edd_bag_ids": [],
        "added_edd_day_bag_ids": [],
        "removed_future_edd_count": 0,
        "removed_inactive_count": 0,
        "removed_completed_count": 0,
        "added_edd_day_count": 0,
    }
    return out


def load_active_hd_presence_edd_map(cursor, organization_id: int) -> dict[str, dict[str, Any]]:
    """Deprecated helper — returns empty (EDD gate disabled)."""
    del cursor, organization_id
    return {}


def load_hd_presence_edd_lookup(
    cursor,
    organization_id: int,
    bag_ids: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Deprecated helper — returns empty (EDD gate disabled)."""
    del cursor, organization_id, bag_ids
    return {}
