"""Tests for near-complete WF post-processing weight backfill."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from backend.rinse_near_complete_wf_backfill import (
    plan_near_complete_wf_backfill_for_bag,
)


def _ev(purpose: str, ts: datetime, user: str = "Jennifer (VeeWash)", **extra):
    row = {
        "purpose": purpose,
        "scanned_at_parsed": ts,
        "user_name": user,
        "bag_id": "BAG1",
    }
    row.update(extra)
    return row


def test_plan_eligible_when_cc_and_registry_weight_without_post_weight():
    events = [
        _ev("sent-to-vendor", datetime(2026, 7, 16, 7, 0), user="Driver"),
        _ev("weight-entry", datetime(2026, 7, 16, 8, 0), user="Singh (VeeWash)"),
        _ev("start-cleaning", datetime(2026, 7, 16, 9, 0), user="Singh (VeeWash)"),
        _ev("complete-cleaning", datetime(2026, 7, 16, 13, 54), user="Jennifer (VeeWash)"),
    ]
    cursor = MagicMock()
    cursor.fetchone.return_value = {"weight_num": 27.2, "completion_status": "REJECTED"}

    with patch(
        "backend.rinse_at_vendor_module._load_at_vendor_scan_events_for_bags",
        return_value={"BAG1": events},
    ):
        plan = plan_near_complete_wf_backfill_for_bag(
            cursor,
            3,
            "BAG1",
            selected_date_et=date(2026, 7, 16),
            events=events,
        )

    assert plan["eligible"] is True
    assert plan["credited_employee"] == "Jennifer (VeeWash)"
    assert plan["registry_weight_lbs"] == 27.2
    assert plan["has_post_processing_weight"] is False


def test_plan_skips_when_post_processing_weight_already_present():
    events = [
        _ev("sent-to-vendor", datetime(2026, 7, 16, 7, 0), user="Driver"),
        _ev("weight-entry", datetime(2026, 7, 16, 8, 0), user="Singh (VeeWash)"),
        _ev("start-cleaning", datetime(2026, 7, 16, 9, 0), user="Singh (VeeWash)"),
        _ev("complete-cleaning", datetime(2026, 7, 16, 13, 54), user="Jennifer (VeeWash)"),
        _ev(
            "weight-entry",
            datetime(2026, 7, 16, 13, 55),
            user="Jennifer (VeeWash)",
            weight_lbs=27.2,
        ),
    ]
    cursor = MagicMock()
    cursor.fetchone.return_value = {"weight_num": 27.2}

    plan = plan_near_complete_wf_backfill_for_bag(
        cursor,
        3,
        "BAG1",
        selected_date_et=date(2026, 7, 16),
        events=events,
    )
    assert plan["eligible"] is False
    assert plan["skip_reason"] == "already_has_post_processing_weight"


def test_plan_skips_without_registry_weight():
    events = [
        _ev("sent-to-vendor", datetime(2026, 7, 16, 7, 0), user="Driver"),
        _ev("complete-cleaning", datetime(2026, 7, 16, 13, 54), user="Jennifer (VeeWash)"),
    ]
    cursor = MagicMock()
    cursor.fetchone.return_value = {"weight_num": None}

    plan = plan_near_complete_wf_backfill_for_bag(
        cursor,
        3,
        "BAG1",
        selected_date_et=date(2026, 7, 16),
        events=events,
    )
    assert plan["eligible"] is False
    assert plan["skip_reason"] == "no_registry_weight"
